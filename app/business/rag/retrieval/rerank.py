from __future__ import annotations

import requests

from app.utils.module_logger import _tagged, get_module_logger


logger = get_module_logger("rag")


class RerankClient:
    """文本重排客户端（OpenAI 兼容 rerank 协议，根据配置开关启用）。

    依赖 config/llm_config.{env}.yml 的 `rag.rerank` 段（独立配置，不再复用
    embedding 的 api_key / base_url）：
      - rag.rerank.enabled  是否启用（rag 段由前端管理）
      - rag.rerank.model    重排模型（由配置提供，无默认值）
      - rag.rerank.api_key  重排服务 API Key
      - rag.rerank.base_url 重排网关基址（OpenAI 兼容 /v1，由配置提供，无默认值）

    协议（OpenAI 兼容 rerank，与 Cohere/Jina 风格一致）：
      POST <base_url>/rerank
      body  : {"model": <m>, "query": <q>, "documents": [d0, d1, ...], "top_n": <n>}
      resp  : {"results": [{"index": <i>, "relevance_score": <s>}, ...]}  // 按分数降序
    若 base_url 已含 `/rerank` 后缀则直接作为端点，否则自动补 `/rerank`。
    """

    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str,
        timeout: float = 10.0,
    ) -> None:
        if not api_key:
            raise ValueError("RerankClient 需要 api_key（配置 rag.rerank.api_key）")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        # 推导实际 rerank 端点：base_url 已含 rerank 路径（/rerank 或 /reranks）则直接用，
        # 否则在其后补 /rerank（兼容“仅给基址”的配置写法）。
        base = (base_url or "").rstrip("/")
        if base.endswith("/rerank") or base.endswith("/reranks"):
            self.endpoint = base
        else:
            self.endpoint = base + "/rerank"

    def rerank(self, query: str, documents: list[str]) -> list[tuple[int, float]]:
        """对文档按与 query 的相关性重排，返回 [(原索引, 相关性分数)]，降序。

        调用失败时不抛异常，返回原始顺序，保证检索链路不中断。
        """
        if not documents:
            return []
        logger.info(_tagged("rag", "rerank start query=%r docs=%d model=%s endpoint=%s"),
                    query, len(documents), self.model, self.endpoint)
        payload = {
            "model": self.model,
            "query": query,
            "documents": documents,
            "top_n": len(documents),
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        try:
            resp = requests.post(
                self.endpoint, json=payload, headers=headers, timeout=self.timeout
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:  # 重排为增强项，失败降级为原始顺序
            logger.warning(_tagged("rag", "rerank 调用失败，降级为原始顺序: %s"), e)
            return list(enumerate([1.0 - i * 1e-6 for i in range(len(documents))]))

        # OpenAI 兼容 rerank 响应：results 内含 index / relevance_score（容纳 id / score 别名）
        results = data.get("results") or data.get("data") or data.get("rankings") or []
        scored: list[tuple[int, float]] = []
        for r in results:
            idx = r.get("index", r.get("id"))
            score = r.get("relevance_score", r.get("score"))
            if idx is None or score is None:
                continue
            scored.append((int(idx), float(score)))
        scored.sort(key=lambda x: x[1], reverse=True)
        logger.info(_tagged("rag", "rerank end scored=%d"), len(scored))
        return scored


def build_rerank_client() -> RerankClient | None:
    """从配置构建 RerankClient；未开启或配置缺失时返回 None。

    读取 `rag.rerank`（enabled / base_url / api_key / model），不再借用
    embedding 的 api_key，也不再用代码内硬编码的默认网关 / 模型。
    model 与 base_url 必须由配置显式提供；缺失任一则视为未就绪，跳过重排。
    """
    from app.config.rag_config import load_rag_config_raw

    rag_cfg = load_rag_config_raw()
    rerank_cfg = rag_cfg.get("rerank", {})
    if not isinstance(rerank_cfg, dict) or not rerank_cfg.get("enabled"):
        return None
    api_key = rerank_cfg.get("api_key") or ""
    if not api_key:
        logger.warning(_tagged("rag", "rerank 已开启但未配置 rag.rerank.api_key，跳过重排"))
        return None
    model = rerank_cfg.get("model")
    base_url = rerank_cfg.get("base_url")
    if not model or not base_url:
        logger.warning(
            _tagged("rag", "rerank 已开启但缺少 rag.rerank.model / base_url 配置，跳过重排")
        )
        return None
    return RerankClient(api_key=api_key, model=model, base_url=base_url)
