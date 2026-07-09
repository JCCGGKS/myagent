from __future__ import annotations

import logging
from typing import Any

import requests

from app.config.rag_config import load_rag_config_raw


logger = logging.getLogger(__name__)

# DashScope 重排服务地址（文本重排 / rerank）
DASHSCOPE_RERANK_URL = "https://dashscope.aliyuncs.com/api/v1/services/rerank"
DEFAULT_RERANK_MODEL = "gated-rerank"


class RerankClient:
    """DashScope 文本重排客户端（根据配置开关启用）。

    依赖 config/llm_config.{env}.yml 的：
      - rag.rerank.model  重排模型（缺省 gated-rerank）
      - rag.rerank.enabled 是否启用（rag 段由前端管理）
      - embedding.api_key  DashScope API Key（顶层 embedding 段，与 embedding 复用）
    """

    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_RERANK_MODEL,
        base_url: str = DASHSCOPE_RERANK_URL,
        timeout: float = 10.0,
    ) -> None:
        if not api_key:
            raise ValueError("RerankClient 需要 DashScope api_key（配置 embedding.api_key）")
        self.api_key = api_key
        self.model = model
        self.base_url = base_url
        self.timeout = timeout

    def rerank(self, query: str, documents: list[str]) -> list[tuple[int, float]]:
        """对文档按与 query 的相关性重排，返回 [(原索引, 相关性分数)]，降序。

        调用失败时不抛异常，返回原始顺序，保证检索链路不中断。
        """
        if not documents:
            return []
        payload = {
            "model": self.model,
            "input": {"query": query, "documents": documents},
            "parameters": {"return_documents": False},
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        try:
            resp = requests.post(
                self.base_url, json=payload, headers=headers, timeout=self.timeout
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:  # 重排为增强项，失败降级为原始顺序
            logger.warning("rerank 调用失败，降级为原始顺序: %s", e)
            return list(enumerate([1.0 - i * 1e-6 for i in range(len(documents))]))

        results = data.get("output", {}).get("results", [])
        # results 含 index 与 relevance_score，按分数降序
        scored = [(r["index"], float(r["relevance_score"])) for r in results]
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored


def build_rerank_client() -> RerankClient | None:
    """从配置构建 RerankClient；未开启或缺少 key 时返回 None。"""
    from app.config.rag_config import load_embedding_config_raw, load_rag_config_raw

    rag_cfg = load_rag_config_raw()
    rerank_cfg = rag_cfg.get("rerank", {})
    if not isinstance(rerank_cfg, dict) or not rerank_cfg.get("enabled"):
        return None
    emb_cfg = load_embedding_config_raw()
    api_key = emb_cfg.get("api_key") if isinstance(emb_cfg, dict) else None
    if not api_key:
        logger.warning("rerank 已开启但未配置 embedding.api_key，跳过重排")
        return None
    model = rerank_cfg.get("model") or DEFAULT_RERANK_MODEL
    return RerankClient(api_key=api_key, model=model)
