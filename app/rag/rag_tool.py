from __future__ import annotations

from typing import Any

from app.rag.retrieval_strategy import get_strategy_from_config

# 后端默认重排模型（前端开启重排但未指定模型时使用）
DEFAULT_RERANK_MODEL = "bge-reranker-v2-m3"


class RagRetrieveTool:
    """RAG 检索工具封装（供 LLM 调用）。"""

    def __init__(
        self,
        strategy: RetrievalStrategy | None = None,
        top_k: int = 5,
        rerank_enabled: bool = False,
        rerank_model: str = "",
    ) -> None:
        self.strategy = strategy or get_strategy_from_config()
        self.top_k = top_k
        self.rerank_enabled = rerank_enabled
        # 未指定模型时使用后端默认重排模型
        self.rerank_model = rerank_model or DEFAULT_RERANK_MODEL

    def run(self, query: str) -> list[dict[str, Any]]:
        """执行检索，返回结构化结果。

        Args:
            query: 用户问题或改写后的查询。

        Returns:
            包含 `content`、`metadata`、`score` 的文档列表。
        """
        # 1. 执行检索
        docs = self.strategy.retrieve(query)

        # 2. Rerank（如果启用）
        if self.rerank_enabled:
            docs = self._rerank(docs, query)

        # 3. 返回 top_k
        return [doc.to_dict() for doc in docs[: self.top_k]]

    def _rerank(self, docs: list[Document], query: str) -> list[Document]:
        """Rerank 结果（TODO: 接入真实 Rerank 模型）。"""
        # TODO: 接入真实 Rerank 模型（如 bge-reranker）
        # 当前为模拟实现，随机打乱后返回
        import random

        random.shuffle(docs)
        return docs

    @property
    def name(self) -> str:
        return "rag_retrieve"

    @property
    def description(self) -> str:
        return (
            "从知识库中检索与用户问题相关的文档片段。"
            "当用户问题可能涉及产品信息、政策条款、FAQ 时，调用此工具。"
            "参数 query 应为用户问题的简洁表述或关键词。"
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
    """从配置文件读取配置，创建 RAG 工具实例。"""
    from pathlib import Path

    import yaml

    config_path = Path(__file__).resolve().parents[2] / "config" / "llm_config.local.yml"
    if not config_path.exists():
        return RagRetrieveTool()

    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    rag_config = config.get("rag", {})
    return RagRetrieveTool(
        strategy=get_strategy_from_config(),
        top_k=rag_config.get("top_k", 5),
        rerank_enabled=rag_config.get("rerank", {}).get("enabled", False),
        rerank_model=rag_config.get("rerank", {}).get("model", ""),
    )
