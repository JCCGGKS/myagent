from __future__ import annotations

from typing import Any

from app.business.rag.retrieval_strategy import (
    Document,
    RetrievalStrategy,
    get_strategy_from_config,
)
from app.config.rag_config import get_rag_config_service
from app.business.rag.rerank import build_rerank_client
from app.utils.module_logger import _tagged, get_module_logger

logger = get_module_logger("tool")


def _config_top_k() -> int:
    """从环境相关的 RagConfig 读取 top_k（默认 5）。"""
    return get_rag_config_service().get_config().top_k

# 后端默认重排模型（前端开启重排但未指定模型时使用）
DEFAULT_RERANK_MODEL = "gated-rerank"

# doc_type 可信度权重（设计 §7.3：优先保留高可信来源文档）。
# 仅在不启用 Rerank 时作为相关性分数的微调，作为同分/近分时的来源偏好。
DOC_TYPE_CREDIBILITY: dict[str, float] = {
    "policy": 0.05,
    "faq": 0.03,
    "product": 0.02,
    "help": 0.01,
}


class RagRetrieveTool:
    """RAG 检索工具封装（供 LLM 调用）。"""

    def __init__(
        self,
        strategy: RetrievalStrategy | None = None,
        top_k: int | None = None,
        rerank_enabled: bool | None = None,
        rerank_model: str = "",
        credibility_weights: dict[str, float] | None = None,
    ) -> None:
        self.strategy = strategy or get_strategy_from_config()
        # top_k 未显式传入时，从环境相关的 RagConfig 读取（不再写死为 5）
        self.top_k = top_k if top_k is not None else _config_top_k()
        # None 表示运行时由 RagConfig 决定（支持 /rag/config 动态开关）
        self._rerank_enabled_override = rerank_enabled
        # 未指定模型时使用后端默认重排模型
        self.rerank_model = rerank_model or DEFAULT_RERANK_MODEL
        self.credibility_weights = credibility_weights if credibility_weights is not None else DOC_TYPE_CREDIBILITY

    def _is_rerank_enabled(self) -> bool:
        if self._rerank_enabled_override is not None:
            return self._rerank_enabled_override
        return get_rag_config_service().get_config().rerank.enabled

    def run(self, query: str, user_id: int | None = None) -> list[dict[str, Any]]:
        """执行检索，返回结构化结果。

        Args:
            query: 用户问题或改写后的查询。
            user_id: 限定检索归属用户（None 表示全库召回，用于未登录/内部场景）。

        Returns:
            包含 `content`、`metadata`、`score` 的文档列表。
        """
        # 1. 执行检索
        logger.info(_tagged("tool", "rag_retrieve start query=%r user_id=%s top_k=%d"), query, user_id, self.top_k)
        docs = self.strategy.retrieve(query, user_id=user_id)

        # 2. 去重（设计 §7.3）：按内容去重，保留分数更高者
        docs = self._dedup(docs)

        # 3. Rerank（如果启用）或按可信度微调排序
        if self._is_rerank_enabled():
            docs = self._rerank(docs, query)
        else:
            docs = self._apply_credibility(docs)

        # 4. 返回 top_k
        results = [doc.to_dict() for doc in docs[: self.top_k]]
        logger.info(_tagged("tool", "rag_retrieve end hits=%d user_id=%s"), len(results), user_id)
        return results

    def _dedup(self, docs: list[Document]) -> list[Document]:
        """按内容去重，保留同内容中分数最高的一份。"""
        best: dict[str, Document] = {}
        for d in docs:
            key = (d.content or "").strip()
            if not key:
                continue
            if key not in best or d.score > best[key].score:
                best[key] = d
        return list(best.values())

    def _apply_credibility(self, docs: list[Document]) -> list[Document]:
        """按相关性 + doc_type 可信度微调排序（不开 Rerank 时使用）。"""
        if not self.credibility_weights:
            return docs

        def _key(d: Document) -> float:
            dt = (d.metadata or {}).get("doc_type", "")
            boost = self.credibility_weights.get(dt, 0.0)
            return (d.score or 0.0) + boost

        return sorted(docs, key=_key, reverse=True)

    def _rerank(self, docs: list[Document], query: str) -> list[Document]:
        """使用 DashScope 重排模型对检索结果重排（按配置开关启用）。

        未配置或调用失败时降级为原始顺序，不中断检索链路。
        """
        client = build_rerank_client()
        if client is None:
            return docs
        scored = client.rerank(query, [d.content for d in docs])
        ordered: list[Document] = []
        for idx, _score in scored:
            if 0 <= idx < len(docs):
                ordered.append(docs[idx])
        return ordered or docs

    @property
    def name(self) -> str:
        return "rag_retrieve"

    @property
    def description(self) -> str:
        return (
            "从企业知识库（FAQ / 政策 / 商品 / 帮助文档）检索事实性答案，"
            "用于与具体订单无关的通用政策或常识问题。"
            "典型适用：退换货政策、七天无理由、售后规则等【仅咨询】场景"
            "（用户问政策但不要求实际办理退款时，优先用本工具而非 request_refund）。"
            "不适用：查询特定订单状态或物流进度（请用 query_order / query_logistics 业务工具，需 order_id）、"
            "发起退款等写操作（用 request_refund）、以及打招呼 / 致谢 / 闲聊（直接回复即可）。"
        )

    def to_tool_schema(self) -> dict[str, Any]:
        """返回 OpenAI tools 参数格式的 schema。"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "用户问题或检索查询（简洁表述或关键词）",
                        }
                    },
                    "required": ["query"],
                },
            },
        }


def get_rag_tool() -> RagRetrieveTool:
    """从环境相关的 RagConfig 读取配置，创建 RAG 工具实例。

    不再硬编码读取 llm_config.local.yml：top_k / rerank 开关均来自
    get_rag_config_service()（按 APP_ENV 解析的目标文件，与 PUT /rag/config 同源）。
    """
    cfg = get_rag_config_service().get_config()
    return RagRetrieveTool(
        strategy=get_strategy_from_config(),
        top_k=cfg.top_k,
        rerank_enabled=cfg.rerank.enabled,
        rerank_model=cfg.rerank.model,
    )
