from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from app.business.rag.chunking.registry import get_chunking_strategy
from app.pkgs.vector import QdrantClient
from app.utils.module_logger import _tagged, get_module_logger

logger = get_module_logger("rag")


def build_embedding_client() -> EmbeddingClient | None:
    """从顶层 embedding 配置构建真实 EmbeddingClient（OpenAI 兼容）。

    缺失 api_key 时返回 None（调用方据此跳过向量化或报错）。
    embedding 配置位于 config/llm_config.{env}.yml 的顶层 `embedding` 段
    （与 `rag` 同级，不由前端管理）：
        model / api_key
    base_url 复用 config/llm_config.{env}.yml 的 `llm.base_url`。
    稠密向量维度由 qdrant.vector_size 决定（须与嵌入模型实际输出维度一致）。
    """
    from app.config import load_llm_config
    from app.config.rag_config import load_embedding_config_raw

    emb_cfg = load_embedding_config_raw()
    if not isinstance(emb_cfg, dict) or not emb_cfg.get("api_key"):
        return None

    llm_cfg = load_llm_config()
    return EmbeddingClient(
        model=emb_cfg.get("model", "text-embedding-v4"),
        api_key=emb_cfg["api_key"],
        base_url=getattr(llm_cfg, "base_url", "") or "",
    )


class EmbeddingClient:
    """OpenAI 兼容的 Embedding 封装（可对接 DashScope / OpenAI 等网关）。

    使用前需在 config/llm_config.{env}.yml 的顶层 `embedding` 段配置：
        embedding.model / embedding.api_key
        llm.base_url（网关地址）
    稠密向量维度由 qdrant.vector_size 确定，须与嵌入模型实际输出维度一致。
    """

    def __init__(
        self,
        model: str,
        api_key: str,
        base_url: str,
    ) -> None:
        self.model = model
        try:
            from openai import OpenAI

            self._client = OpenAI(api_key=api_key, base_url=base_url)
        except ImportError:  # pragma: no cover
            self._client = None
            logger.warning("openai SDK 未安装，EmbeddingClient 不可用")

    def embed(self, texts: list[str]) -> list[list[float]]:
        """批量生成向量。"""
        if self._client is None:
            raise RuntimeError("OpenAI SDK 未安装，无法调用 embedding")
        resp = self._client.embeddings.create(model=self.model, input=texts)
        # 按输入顺序返回向量
        ordered = sorted(resp.data, key=lambda x: x.index)
        return [item.embedding for item in ordered]

    def embed_one(self, text: str) -> list[float]:
        return self.embed([text])[0]


class KnowledgeIngestionService:
    """知识库入库服务：读取文档 → 分块 → 向量化 → 写入 Qdrant。"""

    def __init__(
        self,
        qdrant_client: QdrantClient,
        embedding_client: EmbeddingClient | None = None,
        collection_name: str = "customer_service_knowledge",
        vector_size: int = 1024,
        chunk_size: int = 800,
        chunk_overlap: int = 100,
        min_chunk_size: int = 50,
    ) -> None:
        self.qdrant_client = qdrant_client
        self.embedding_client = embedding_client
        # 切块参数（来自 rag 段，前端可控）：下发给各分块策略。
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.min_chunk_size = min_chunk_size
        self.collection_name = collection_name
        self.vector_size = vector_size
        # 同步集合名与向量维度，便于首次 upsert 时建表
        self.qdrant_client.collection_name = collection_name
        self.qdrant_client.vector_size = vector_size

    def ingest_markdown_file(
        self,
        file_path: str | Path,
        doc_type: str = "faq",
        source: str | None = None,
        user_id: int | None = None,
        doc_id: int | None = None,
    ) -> int:
        """入库单个 Markdown 文档。返回写入的块数量。"""
        path = Path(file_path)
        text = path.read_text(encoding="utf-8")
        source = source or path.name
        return self.ingest_markdown_text(
            text, doc_type=doc_type, source=source, user_id=user_id, doc_id=doc_id
        )

    def ingest_markdown_text(
        self,
        text: str,
        doc_type: str = "faq",
        source: str = "",
        user_id: int | None = None,
        doc_id: int | None = None,
    ) -> int:
        """入库 Markdown 文本：按 doc_type / markdown 格式取策略切块。"""
        strategy = get_chunking_strategy(doc_type, "markdown")
        chunks = strategy.chunk(
            text,
            doc_type=doc_type,
            source=source,
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
            min_chunk_size=self.min_chunk_size,
        )
        return self._ingest_chunks(chunks, user_id=user_id, doc_id=doc_id)

    def ingest_json_records(
        self,
        records: list[dict[str, Any]],
        doc_type: str = "faq",
        text_field: str = "content",
        user_id: int | None = None,
        doc_id: int | None = None,
    ) -> int:
        """入库 JSON 记录列表（如 FAQ 数据）：按 doc_type / json 格式取策略切块。"""
        strategy = get_chunking_strategy(doc_type, "json")
        total = 0
        for rec in records:
            content = rec.get(text_field, "")
            if not content:
                continue
            meta = {k: v for k, v in rec.items() if k != text_field}
            chunks = strategy.chunk(
                content,
                doc_type=doc_type,
                source=json.dumps(meta, ensure_ascii=False),
                chunk_size=self.chunk_size,
                chunk_overlap=self.chunk_overlap,
                min_chunk_size=self.min_chunk_size,
            )
            total += self._ingest_chunks(chunks, user_id=user_id, doc_id=doc_id)
        return total

    def _ingest_chunks(
        self, chunks: list, user_id: int | None = None, doc_id: int | None = None
    ) -> int:
        if not chunks:
            return 0
        if self.embedding_client is None:
            # BM25 仅依赖本地稀疏向量，无需 embedding：写入稀疏向量即可（前端选 bm25
            # 且未配向量模型时的合法路径）。semantic/hybrid 已在 /knowledge/upload 预检拦截。
            from app.business.rag.sparse_bm25 import build_sparse_vector

            points = []
            for chunk in chunks:
                pid = str(uuid.uuid4())
                payload: dict[str, Any] = {
                    "content": chunk.content,
                    "doc_type": chunk.doc_type,
                    "chunk_type": chunk.chunk_type,
                    "heading_path": chunk.heading_path,
                    "metadata": chunk.metadata,
                }
                if user_id is not None:
                    payload["user_id"] = user_id
                if doc_id is not None:
                    payload["doc_id"] = doc_id
                points.append(
                    {
                        "id": pid,
                        "vector": {"bm25": build_sparse_vector(chunk.content)},
                        "payload": payload,
                    }
                )
            self.qdrant_client.upsert(points)
            logger.info(
                _tagged("rag", "已入库 %d 个块（仅 BM25 稀疏向量，未配 embedding） user_id=%s doc_id=%s"),
                len(points), user_id, doc_id,
            )
            return len(points)

        from app.business.rag.sparse_bm25 import build_sparse_vector

        contents = [c.content for c in chunks]
        dense_vectors = self.embedding_client.embed(contents)

        points: list[dict[str, Any]] = []
        for chunk, dense in zip(chunks, dense_vectors):
            pid = str(uuid.uuid4())
            payload: dict[str, Any] = {
                "content": chunk.content,
                "doc_type": chunk.doc_type,
                "chunk_type": chunk.chunk_type,
                "heading_path": chunk.heading_path,
                "metadata": chunk.metadata,
            }
            if user_id is not None:
                payload["user_id"] = user_id
            # doc_id：文件级标识（knowledge_files.id），同文件 chunk 共享，用于按文档删向量
            if doc_id is not None:
                payload["doc_id"] = doc_id
            # 命名向量：稠密（语义）+ 稀疏（BM25，仅存词频，IDF 由 Qdrant 计算）
            points.append(
                {
                    "id": pid,
                    "vector": {
                        "dense": dense,
                        "bm25": build_sparse_vector(chunk.content),
                    },
                    "payload": payload,
                }
            )

        self.qdrant_client.upsert(points)
        logger.info(_tagged("rag", "已入库 %d 个块 user_id=%s doc_id=%s"), len(points), user_id, doc_id)
        return len(points)
