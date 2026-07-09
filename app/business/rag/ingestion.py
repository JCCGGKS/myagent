from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path
from typing import Any

from app.business.rag.chunker import Chunker
from app.pkgs.vector import QdrantClient

logger = logging.getLogger(__name__)


class EmbeddingClient:
    """text-embedding-v4 封装（OpenAI 兼容接口）。

    使用前需在 config/llm_config.local.yml 的 rag.embedding 配置：
        model / api_key / dimensions
    base_url 复用 llm.base_url（阿里云 DashScope 兼容网关）。
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

        contents = [c.content for c in chunks]
        vectors = self.embedding_client.embed(contents)

        points: list[dict[str, Any]] = []
        for chunk, vector in zip(chunks, vectors):
            pid = str(uuid.uuid4())
            payload = {
                "content": chunk.content,
                "doc_type": chunk.doc_type,
                "heading_path": chunk.heading_path,
                "metadata": chunk.metadata,
            }
            points.append({"id": pid, "vector": vector, "payload": payload})

        self.qdrant_client.upsert(points)
        logger.info("已入库 %d 个块", len(points))
        return len(points)
