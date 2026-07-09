# RAG 模块落地实现说明

`app/business/rag` 是客服 Agent 的知识检索模块。本文档梳理该模块当前**已实际落地**的实现，区分「真实接入」与「占位/未做」。

模块定位：仅负责知识检索链路（切块 → 入库 → 召回 → 融合 → 重排 → 去重/可信度排序），不负责对话编排（见 `app/business/customer_service.py`）。

## 整体检索链路

```
文档/文本
  └─ Chunker            按 Markdown 结构切块，长块递归字符切块兜底
       └─ EmbeddingClient   生成稠密向量（语义）
       └─ build_sparse_vector  生成稀疏向量（BM25 关键词，仅存 TF）
            └─ QdrantClient.upsert   双向量写入 Qdrant（dense + bm25/IDF）

查询 query
  └─ RetrievalStrategy   bm25 / semantic / hybrid(rrf)
       └─ RagRetrieveTool
            ├─ _dedup        按内容去重
            ├─ _rerank        DashScope 重排（配置开关，失败降级）
            │   或 _apply_credibility   doc_type 可信度微调
            └─ top_k 截断
```

## 各文件落地实现

### chunker.py — 文档切块（已落地）
- `Chunk`：`chunk_no / content / heading_path / doc_type / metadata`。
- `Chunker.chunk_markdown()`：按 `#`~`######` 标题切分逻辑块，每个块继承其上层 `heading_path`；超长块用递归字符切块继续切。
- `Chunker.chunk_text()`：无 Markdown 结构时的通用文本切块。
- 递归分隔符优先级：`\n\n` > `\n` > `。` > `；` > `，` > ` ` > 硬切（保留 `chunk_overlap`）。
- 默认 `chunk_size=800`、`chunk_overlap=100`、`min_chunk_size=50`，均在构造参数中可调。

### sparse_bm25.py — 稀疏向量 BM25（已落地，参考 template/rag.md）
- `tokenize()`：小写 ASCII 词 + 单个汉字（`[a-z0-9]+|[一-鿿]`），MVP 简化分词。
- `build_sparse_vector(text)`：把文本转成 `SparseVector(indices, values)`，**仅存词频 TF**；IDF 由 Qdrant 在查询时按全局统计计算（`Modifier.IDF`）。
- 词→索引用 md5 稳定映射到 `VOCAB_SIZE = 1<<20` 的哈希空间，无需维护真实词表。
- 这是本仓库采用的 BM25 方案（非 full-text 索引，qdrant-client 1.18 无文本查询类型）。

### ingestion.py — 入库服务（已落地）
- `EmbeddingClient`（OpenAI 兼容）：封装 `openai.OpenAI`，`embed()` / `embed_one()` 批量与单条向量化；可对接 DashScope / OpenAI 等网关。
- `build_embedding_client()`：从 `rag.embedding`（model / api_key / dimensions）+ `llm.base_url` 构建，缺 `api_key` 返回 `None`。
- `KnowledgeIngestionService`：
  - `ingest_markdown_file()` / `ingest_markdown_text()` / `ingest_json_records()` 三种入口。
  - `_ingest_chunks()`：对每个块同时构建 `dense`（语义）与 `bm25`（稀疏）向量，写入命名向量 `{"dense": ..., "bm25": SparseVector(...)}`，payload 含 `content / doc_type / heading_path / metadata`。
  - `embedding_client` 为 `None` 时跳过向量化（仅记日志），不会崩溃。

### 向量层 — app/pkgs/vector/qdrant.py（已落地，真实 Qdrant）
- 真实 `qdrant_client.QdrantClient`，命名向量 `dense`（稠密）+ `bm25`（稀疏，`Modifier.IDF`）。
- `_ensure_collection()`：懒建集合；若已存在但缺稀疏向量（旧 schema），本地开发环境重建，避免静默失败（生产应改显式迁移）。
- `upsert(points)`：接受命名向量 dict。
- `search_semantic()`：`using=dense`，余弦/BOT/欧氏按配置。
- `search_bm25()`：查询文本转稀疏向量，`using=bm25`。
- `search_hybrid()`：Qdrant 原生 `Prefetch`（两个向量分别召回）+ `FusionQuery(RRF)` 融合。
- `get_qdrant_client()`：读取 `rag.qdrant`（host/port/collection_name/api_key）与 `rag.embedding.dimensions`。
- 默认 `host=localhost`、`port=6333`、`collection_name=customer_service_knowledge`、无鉴权。

### retrieval_strategy.py — 检索策略（已落地）
- `Document`：统一结果结构 `id / content / metadata / score`。
- `BM25Strategy`：调用 `search_bm25`，按 `bm25.min_score_threshold` 过滤。
- `SemanticStrategy`：调用 `EmbeddingClient.embed_one()` 生成查询向量后 `search_semantic`；未配置 embedding 时抛 `RuntimeError`（不再用 mock 随机分）。
- `HybridStrategy`：`_rrf_fusion()`（倒数排序融合，`k=60`）或 `_weighted_fusion()`（需归一化），按 `hybrid.min_score_threshold` 过滤后取前 20。
- `get_strategy_from_config()` / `_build_strategy()`：按 `RagConfig.retrieval_strategy` 装配；语义/混合缺 embedding 配置时抛错。

### rerank.py — 重排（已落地，DashScope，配置开关）
- `RerankClient`：调用 DashScope rerank 接口（`DASHSCOPE_RERANK_URL`，默认模型 `gated-rerank`）。
- `rerank(query, documents)`：返回 `[(原索引, 相关性分数)]` 降序；**调用失败不抛异常，降级为原始顺序**，保证链路不中断。
- `build_rerank_client()`：`rag.rerank.enabled=false` 或缺 `api_key` 时返回 `None`。

### rag_tool.py — 检索工具封装（已落地）
- `RagRetrieveTool.run()`：`retrieve → _dedup → (rerank | credibility) → top_k`。
- `_dedup()`：按 `content` 去重，保留同内容中分数最高的一份。
- `_apply_credibility()`：未启用 rerank 时，按 `score + DOC_TYPE_CREDIBILITY[doc_type]` 微调排序（`policy 0.05 > faq 0.03 > product 0.02 > help 0.01`）。
- `_rerank()`：用 `build_rerank_client()` 重排，`None` 或失败则回退原序。
- `rerank_enabled=None` 时运行时由 `RagConfig` 决定，支持 `/rag/config` 动态开关。
- 提供 `name / description / to_tool_schema()` 供 LLM 工具调用；`get_rag_tool()` 从 `llm_config.local.yml` 读配置。

### __init__.py — 统一导出
导出 `QdrantClient / BM25Strategy / SemanticStrategy / HybridStrategy / RagRetrieveTool / Chunker / Chunk / KnowledgeIngestionService / EmbeddingClient / build_embedding_client / build_sparse_vector / tokenize / RerankClient / build_rerank_client`。

## 配置说明（config/llm_config.{env}.yml 的 `rag` 段）

```yaml
rag:
  retrieval_strategy: hybrid        # bm25 | semantic | hybrid
  top_k: 5
  embedding:                        # 语义/混合检索必需
    model: text-embedding-v4
    api_key: <DashScope API Key>
    dimensions: 1024
  qdrant:                          # 可选，缺省 localhost:6333
    host: localhost
    port: 6333
    collection_name: customer_service_knowledge
    # api_key: ...                 # 可选
  rerank:
    enabled: false                 # true 时启用 DashScope 重排
    model: gated-rerank
  bm25:
    min_score_threshold: 1.0       # IDF 分数 0~10 量级，强命中 4~6
  semantic:
    metric: cosine
    min_score_threshold: 0.5
  hybrid:
    fusion_method: rrf             # rrf | weighted
    weighted_alpha: 0.5
    min_score_threshold: 0.0       # 必接近 0，见下
```

## 阈值校准要点

- **混合检索（RRF）分数极小**：融合后分数约 `1/(k+rank)`，`k=60` 时最大约 `0.016`。`hybrid.min_score_threshold` **必须为 0.0（或接近 0）**，否则会过滤掉全部结果（默认为 `0.0` = 仅按 top_k 截断，不过滤）。
- BM25（IDF）分数在 0~10 量级，强命中约 4~6，故 `bm25.min_score_threshold` 默认 `1.0`。
- Semantic 余弦相似度 0~1，默认 `0.5`。

## 已接入 vs 未实现

已落地：
- 真实 Qdrant（dense + bm25/IDF 双向量、RRF 原生融合）
- 真实 OpenAI 兼容 Embedding
- 真实 DashScope Rerank（配置开关、失败降级）
- 检索结果去重 + doc_type 可信度排序
- Markdown 结构切块

按需求**未实现**（用户「5 暂时不实现」）：
- 文档管理接口（知识文档的 list / get / delete / version）。此缺席为有意，非缺陷。

## 端到端调用示例

```python
from app.business.rag import get_rag_tool, KnowledgeIngestionService, get_qdrant_client
from app.business.rag import build_embedding_client

# 入库
qdrant = get_qdrant_client()
emb = build_embedding_client()
svc = KnowledgeIngestionService(qdrant_client=qdrant, embedding_client=emb)
svc.ingest_markdown_text("# 退款政策\n...\n# 物流时效\n...", doc_type="policy")

# 检索
tool = get_rag_tool()
results = tool.run("怎么申请退款？")
for r in results:
    print(r["score"], r["content"])
```
