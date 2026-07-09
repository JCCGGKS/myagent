from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path
from typing import Any

from app.business.rag.chunker import Chunker
from app.pkgs.vector import QdrantClient

logger = logging.getLogger(__name__)


def build_embedding_client() -> EmbeddingClient | None:
    """从 rag.embedding 配置构建真实 EmbeddingClient（OpenAI 兼容）。

    缺失 api_key 时返回 None（调用方据此跳过向量化或报错）。
    embedding 配置位于 config/llm_config.{env}.yml 的 `rag.embedding` 段：
        model / api_key / dimensions
    base_url 复用 config/llm_config.{env}.yml 的 `llm.base_url`。
    """
    from app.config import load_llm_config
    from app.config.rag_config import load_rag_config_raw

    rag_cfg = load_rag_config_raw()
    emb_cfg = rag_cfg.get("embedding", {})
    if not isinstance(emb_cfg, dict) or not emb_cfg.get("api_key"):
        return None

    llm_cfg = load_llm_config()
    return EmbeddingClient(
        model=emb_cfg.get("model", "text-embedding-v4"),
        api_key=emb_cfg["api_key"],
        base_url=getattr(llm_cfg, "base_url", "") or "",
        dimensions=emb_cfg.get("dimensions", 1024),
    )


class EmbeddingClient:
    """OpenAI 兼容的 Embedding 封装（可对接 DashScope / OpenAI 等网关）。

    使用前需在 config/llm_config.{env}.yml 配置：
        rag.embedding.model / rag.embedding.api_key / rag.embedding.dimensions
        llm.base_url（网关地址）
    """

    def __init__(
        self,
        model: str,
        api_key: str,
        base_url: str,
        dimensions: int = 1024,
    ) -> None:
        self.model = model
        self.dimensions = dimensions
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
        chunker: Chunker | None = None,
        embedding_client: EmbeddingClient | None = None,
        collection_name: str = "customer_service_knowledge",
        vector_size: int = 1024,
    ) -> None:
        self.qdrant_client = qdrant_client
        self.chunker = chunker or Chunker()
        self.embedding_client = embedding_client
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
    ) -> int:
        """入库单个 Markdown 文档。返回写入的块数量。"""
        path = Path(file_path)
        text = path.read_text(encoding="utf-8")
        source = source or path.name
        return self.ingest_markdown_text(text, doc_type=doc_type, source=source)

    def ingest_markdown_text(
        self,
        text: str,
        doc_type: str = "faq",
        source: str = "",
    ) -> int:
        """入库 Markdown 文本。"""
        chunks = self.chunker.chunk_markdown(text, doc_type=doc_type, source=source)
        return self._ingest_chunks(chunks)

    def ingest_json_records(
        self,
        records: list[dict[str, Any]],
        doc_type: str = "faq",
        text_field: str = "content",
    ) -> int:
        """入库 JSON 记录列表（如 FAQ 数据）。"""
        total = 0
        for rec in records:
            content = rec.get(text_field, "")
            if not content:
                continue
            meta = {k: v for k, v in rec.items() if k != text_field}
            chunks = self.chunker.chunk_text(content, doc_type=doc_type, source=json.dumps(meta, ensure_ascii=False))
            total += self._ingest_chunks(chunks)
        return total

    def _ingest_chunks(self, chunks: list) -> int:
        if not chunks:
            return 0
        if self.embedding_client is None:
            logger.warning("未配置 embedding_client，跳过向量化（仅记录分块数=%d）", len(chunks))
            return 0

        from app.business.rag.sparse_bm25 import build_sparse_vector

        contents = [c.content for c in chunks]
        dense_vectors = self.embedding_client.embed(contents)

        points: list[dict[str, Any]] = []
        for chunk, dense in zip(chunks, dense_vectors):
            pid = str(uuid.uuid4())
            payload = {
                "content": chunk.content,
                "doc_type": chunk.doc_type,
                "heading_path": chunk.heading_path,
                "metadata": chunk.metadata,
            }
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
        logger.info("已入库 %d 个块", len(points))
        return len(points)
