# RAG 模块落地实现说明

`app/business/rag` 是客服 Agent 的知识检索模块。本文档按 **分块 → 向量化 → 入库 → 检索 → 召回 → 重排序** 六个阶段梳理当前**已实际落地**的实现。

模块定位：仅负责知识检索链路，不负责对话编排（见 `app/business/customer_service.py`）。

## 全链路概览

```
┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐
│  1.分块  │ →  │ 2.向量化 │ →  │  3.入库  │ →  │  4.检索  │ →  │  5.召回  │ →  │  6.融合  │ →  │ 7.重排序 │
└──────────┘    └──────────┘    └──────────┘    └──────────┘    └──────────┘    └──────────┘    └──────────┘
  Chunker       Embedding        Qdrant.upsert   Strategy        multi-strategy   RRF fusion      Rerank /
                + sparse_                          .retrieve       (BM25/Semantic)                  credibility
                bm25
```

> 各阶段对应参数（chunk_size/top_k/rrf_k/...）来源详见末尾"参数来源对照表"。

---

## 文档上传链路（POST /knowledge/upload）

入口在 `app/api/rag.py:knowledge_upload`，把前端上传的文件驱动走完 1→3 阶段，并维护 `knowledge_files` 元信息状态（`app/dao/knowledge_file.py`）。链路：

1. **落元信息（PROCESSING）**：`file_dao.create(user_id, filename, file_size, doc_type, status=PROCESSING)`；返回 `record["id"]` 作为 `doc_id`，透传后续入库，用于按文档删向量。
2. **构建入库服务**：`_build_ingestion_service()` 按 `rag` 段构造 `Chunker`、按顶层配置构造 `EmbeddingClient` 与 `QdrantClient`。
3. **向量化前置校验**：`embedding_client is None`（缺 `embedding.api_key`）→ 立即 `update_status(doc_id, ERROR, ...)` 并返回 400，**不再往下走**。避免「成功但 0 向量」的假状态。
4. **分块 + 向量化 + 批量入库**：`.json` → `ingest_json_records`；`.md/.markdown` → `ingest_markdown_text`；二者汇聚到 `_ingest_chunks`：批量算 dense、逐块算 BM25 sparse，一次性 upsert 命名向量 `{dense, bm25}`（payload 含 `user_id` / `doc_id`）。
5. **状态变更**：
   - 成功 → `update_status(doc_id, SUCCESS, chunk_count=实际写入块数)`；
   - 异常 → `update_status(doc_id, ERROR, error_message=str(exc))` 并重抛。
6. **返回结果**：序列化的文件记录（含 `status` / `chunk_count` / 文件名等）。

> 文件名与后缀合法性、后缀与 `doc_type` 一致性由前端校验（仅支持 `.md/.markdown/.json`），后端不再做这两类校验。

---

## 1. 分块（chunker.py）

**职责**：把原始文档切成结构化 `Chunk` 列表。

- `Chunk`：`chunk_no / content / heading_path / doc_type / metadata`。
- `Chunker.chunk_markdown()`：按 `#`~`######` 标题切分逻辑块，每个块继承其上层 `heading_path`；超长块用递归字符切块继续切。
- `Chunker.chunk_text()`：无 Markdown 结构时的通用文本切块。
- 递归分隔符优先级：`\n\n` > `\n` > `。` > `；` > `，` > ` ` > 硬切（保留 `chunk_overlap`）。
- **参数全部配置化**（`chunk_size` / `chunk_overlap` / `min_chunk_size`），由 `api/rag.py:_build_ingestion_service` 在构造时从 `rag` 段读入并注入 Chunker，**不硬编码**。

---

## 2. 向量化（ingestion.py + sparse_bm25.py）

**职责**：把每个 `Chunk` 转换成稠密向量（语义）和稀疏向量（BM25 关键词），用于后续双路检索。

### 稠密向量（EmbeddingClient）
- 封装 `openai.OpenAI`（OpenAI 兼容协议），可对接 DashScope / OpenAI 等网关。
- `embed()` 批量 / `embed_one()` 单条。
- `build_embedding_client()`：从顶层 `embedding` 段（model / api_key）+ `llm.base_url` 构建，缺 `api_key` 返回 `None`。
- 向量维度由 `qdrant.vector_size` 决定（与嵌入模型输出维度对齐）。

### 稀疏向量（BM25）
- `tokenize()`：小写 ASCII 词 + 单个汉字（`[a-z0-9]+|[一-鿿]`），MVP 简化分词。
- `build_sparse_vector(text)`：把文本转成 `SparseVector(indices, values)`，**仅存词频 TF**；IDF 由 Qdrant 在查询时按全局统计计算（`Modifier.IDF`）。
- 词→索引用 md5 稳定映射到 `VOCAB_SIZE = 1<<20` 的哈希空间，无需维护真实词表。
- 本仓库采用此 BM25 方案（非 full-text 索引，qdrant-client 1.18 无文本查询类型）。

---

## 3. 入库（ingestion.py + QdrantClient.upsert）

**职责**：把 `dense` + `bm25` 双向量连同 payload 写入 Qdrant。

### KnowledgeIngestionService
- 三种入口：
  - `ingest_markdown_file(path, ...)` — 从文件读 Markdown
  - `ingest_markdown_text(text, ...)` — 直接传文本
  - `ingest_json_records(records, ...)` — JSON 数组
- 三者均支持 `user_id: int | None` 参数；**`user_id` 写入每块 payload**（`payload["user_id"]`），检索结果通过 `_hit_to_dict` 回到 `metadata.user_id`。
- `_ingest_chunks()`：对每个块同时构建 `dense` 与 `bm25` 向量，写入命名向量 `{"dense": ..., "bm25": SparseVector(...)}`，payload 含 `content / doc_type / heading_path / metadata / user_id`。
- `embedding_client` 为 `None` 时跳过向量化（仅记日志），作为安全网；但上传接口已在更前置拦截（`embedding_client is None` 直接判 ERROR，见「文档上传链路」第 3 步），正常不会走到这里。

### QdrantClient
- 真实 `qdrant_client.QdrantClient`，命名向量 `dense`（稠密）+ `bm25`（稀疏，`Modifier.IDF`）。
- `_ensure_collection()`：懒建集合；若已存在但缺稀疏向量（旧 schema），本地开发环境重建，避免静默失败。
- `upsert(points)`：接受命名向量 dict。
- `get_qdrant_client()`：读取顶层 `qdrant` 段（host/port/collection_name/api_key/distance/vector_size）。
- 默认 `host=localhost`、`port=6333`、`collection_name=customer_service_knowledge`、无鉴权。
- `qdrant.distance`（默认 Cosine）在集合创建时固定，**查询时不可更改**（更改 = 整库重建）。

### Point ID
- 选用 UUID（`str(uuid.uuid4())`），不维护自增序列。
- 原因：分布式友好、避免并发冲突、append-only 设计下无自然主键。

---

## 4. 检索（retrieval_strategy.py）

**职责**：根据配置选择具体策略，从 Qdrant 召回候选文档。

### 抽象与具体策略
- `Document`：统一结果结构 `id / content / metadata / score`；`metadata` 包含 `doc_type`、`heading_path`、`source`、入库时传入的 `user_id`（如有）。
- `RetrievalStrategy`（ABC）：统一接口 `retrieve(query) -> list[Document]`。
- `BM25Strategy`：调用 `search_bm25`，按单一 `min_score_threshold` 过滤。
- `SemanticStrategy`：调用 `EmbeddingClient.embed_one()` 生成查询向量后 `search_semantic`；未配置 embedding 时抛 `RuntimeError`。

### HybridStrategy — 泛型依赖注入
- **构造**：`strategies: list[RetrievalStrategy]` — 通过构造注入任意数量的子策略，不再硬编码 BM25 / Semantic 命名参数。
- **职责单一**：只负责调度注入的子策略各路召回并 RRF 融合，自身不 `new` 任何子策略。
- 支持未来扩展 N 路检索，只需改工厂函数。

### 工厂函数
- `get_strategy_from_config(rag_config=None)`：从运行时 `RagConfigService` 读最新配置。
- `_build_strategy(client, rag_config)`：按 `RagConfig.retrieval_strategy` 分支构造。
  - `bm25` → `BM25Strategy`
  - `semantic` → `SemanticStrategy`
  - `hybrid` → `HybridStrategy(strategies=[BM25Strategy, SemanticStrategy], ...)`
- 语义/混合缺 embedding 配置时**直接抛错**（fail-fast），不静默回退到 mock。
- 单一 `min_score_threshold` 由 `rag` 顶层读出即用于三路过滤，不做归一化；前端按 `retrieval_strategy` 控制可输入范围，避免量纲误配。

---

## 5. 召回（各子策略并发拉取候选）

**职责**：在 hybrid 策略下，分别调用注入的各子策略拉取候选文档，每路独立打分排序。

### 召回缓冲
- 每路调用 `limit = max(top_k * 2, 20)`，多召回一些再做过滤/融合，避免单一阈值过滤后结果不足。
- 例：`top_k=5` → 每路召回 20 条；后续融合 + top_k 截断得到最终 5 条。

### 单路打分
- **BM25**：Qdrant 内部按 IDF 计算（`Modifier.IDF`），输出 0~10 量级分数。
- **Semantic**：Qdrant 按集合创建时的 `qdrant.distance`（默认 Cosine）计算，输出 0~1 余弦相似度。
- 两条路**量纲不同**，分数不可直接比较或线性相加。

### 子策略独立过滤
- 每路在召回后立即按 `min_score_threshold` 过滤低分文档。
- 过滤后剩下的进入下一步融合。

---

## 6. 融合（HybridStrategy._rrf_fusion）

**职责**：把多路结果合并为统一排序，**消除量纲差异**。

### 选型：RRF（Reciprocal Rank Fusion）
- **量纲无关**：只看排名，不看分数本身；BM25（0~10）与余弦（0~1）可平等融合。
- **无需归一化**：避免跨量纲线性混合的不确定性。
- **加权重排**：未来若需要，可叠加权重（当前未启用，保持简单）。

### 融合公式
```
对每一路 docs:
    对每个 doc，按其在该路的排名 rank (从 1 开始):
        score[doc.id] += 1 / (rrf_k + rank)
```
- `rrf_k` 由 `rag.rrf_k` 配置（默认 60），是控制"高排名优势"的常数。
- `k` 越大 → 排名靠前的优势越平滑；`k` 越小 → 头部结果主导越强。

### 实现
- **支持任意路数**：`for docs in results_by_strategy: for rank, doc in enumerate(docs, start=1): ...`
- 同一 `doc.id` 在多路出现时分数累加（doc 必出至少两路时分数更高）。
- 首次出现的 `doc` 写入 `doc_map`，供后续构造 `Document` 时取 `content` / `metadata`。
- 融合后按分数降序排序输出。

### 为什么不走 Qdrant 原生 FusionQuery
- `QdrantClient.search_hybrid()` 提供 `Prefetch + FusionQuery(RRF)`，**目前是死代码**，未在 `HybridStrategy` 中调用。
- 当前实现选择**客户端 RRF**：更易调试、配置可控、与现有 `min_score_threshold` 过滤逻辑对齐。
- 后续若性能成为瓶颈，可切到服务端 RRF（去除 `top_k * 2` 召回缓冲）。

### 融合后处理
- 按 `min_score_threshold` 再过滤一次（兜底，hybrid 场景下阈值应接近 0）。
- 返回前 `top_k * 2` 个（中间截断，最终 `top_k` 在 `RagRetrieveTool` 生效）。

---

## 7. 重排序（tools/rag_tool.py + rerank.py）

**职责**：在召回结果上做精排，可选启用 DashScope rerank。

### RagRetrieveTool.run()
流水线：`retrieve → _dedup → (rerank | credibility) → top_k`

#### 去重（_dedup）
- 按 `content` 去重，保留同内容中分数最高的一份。

#### Rerank（_rerank）
- `RerankClient`：调用 DashScope rerank 接口（`DASHSCOPE_RERANK_URL`，默认模型 `gated-rerank`）。
- `rerank(query, documents)`：返回 `[(原索引, 相关性分数)]` 降序。
- **调用失败不抛异常，降级为原始顺序**，保证链路不中断。
- `build_rerank_client()`：`rag.rerank.enabled=false` 或缺 `embedding.api_key` 时返回 `None`。

#### 可信度微调（_apply_credibility）
- 未启用 rerank 时，按 `score + DOC_TYPE_CREDIBILITY[doc_type]` 微调排序：
  - `policy 0.05 > faq 0.03 > product 0.02 > help 0.01`
- 用于在分数相同时提升权威来源的优先级。

#### 工具调用接口
- 提供 `name / description / to_tool_schema()` 供 LLM 工具调用。
- `get_rag_tool()` 从运行时 `RagConfig` 读 `top_k` / `rerank` 配置，不再硬编码。

---

## 配置总览（config/llm_config.{env}.yml）

### `rag` 段（前端 `PUT /rag/config` 可控）

```yaml
rag:
  retrieval_strategy: hybrid        # bm25 | semantic | hybrid
  top_k: 5
  min_score_threshold: 0.0          # 单一字段，读出即用
  chunk_size: 800
  chunk_overlap: 100
  min_chunk_size: 50
  rrf_k: 60                         # RRF 常数 k
  rerank:
    enabled: false
    model: gated-rerank
```

### 顶层基础设施段（前端不可控）

```yaml
embedding:                          # 与 rag 同级
  model: text-embedding-v4
  api_key: sk-xxx
qdrant:                             # 与 rag 同级
  host: localhost
  port: 6333
  collection_name: customer_service_knowledge
  vector_size: 1536
  distance: Cosine
```

### 参数来源对照表

| 参数 | 来源 | 生效阶段 |
|---|---|---|
| `chunk_size` / `chunk_overlap` / `min_chunk_size` | `rag` 段 | 1.分块 |
| `embedding.model` / `api_key` | 顶层 `embedding` | 2.向量化 |
| `qdrant.vector_size` / `distance` / `collection_name` | 顶层 `qdrant` | 2.向量化 / 3.入库 |
| `top_k` | `rag.top_k` | 4.检索 / 5.召回 / 7.重排序 |
| `min_score_threshold` | `rag.min_score_threshold` | 4.检索 / 5.召回 / 6.融合 |
| `rrf_k` | `rag.rrf_k` | 6.融合 |
| `rerank.enabled` / `model` | `rag.rerank` | 7.重排序 |

修改 `rag` 段参数后，下次检索/入库即生效（运行时通过 `RagConfigService` 读最新值）。

---

## 阈值校准要点

- **混合检索（RRF）分数极小**：融合后分数约 `1/(k+rank)`，`k=60` 时最大约 `0.016`。`min_score_threshold` 在 hybrid 策略下**必须接近 0**，否则会过滤掉全部结果（默认 `0.0` = 仅按 top_k 截断）。
- BM25（IDF）分数在 0~10 量级，强命中约 4~6。
- Semantic 余弦相似度 0~1。
- 三者共用同一个 `min_score_threshold` 字段，读到什么值就直接用什么值过滤。
  前端按当前 `retrieval_strategy` 限制可输入范围，避免量纲误配。

---

## user_id 元数据

- `KnowledgeIngestionService.ingest_*` 方法支持 `user_id` 入参；不为 None 时写入每块 Qdrant payload。
- `QdrantClient._hit_to_dict` 从 payload 读出 `user_id` 并回填到结果 `metadata`。
- 前端上传接口（`POST /knowledge/upload`）已接入 `AuthMiddleware`，从 token 中解析当前 user 后传递 `user_id=current_user.id`。
- 检索结果可携带 `user_id` 用于上层做按用户过滤 / 权限隔离（当前未消费该字段，预留位）。

---

## 索引概览（向量库索引）

Qdrant 集合 `customer_service_knowledge` 当前建立的索引如下。

### 向量索引（vector indexes）
| 名称 | 类型 | 底层索引 | 配置 |
|---|---|---|---|
| `dense` | 稠密命名向量 | **HNSW**（Qdrant 自动维护，未自定义 `hnsw_config`，用默认参数） | `VectorParams(size=qdrant.vector_size, distance=Cosine)` |
| `bm25` | 稀疏命名向量 | **倒排索引**（Qdrant 自动维护） | `SparseVectorParams(modifier=IDF)`，IDF 由 Qdrant 全局统计 |

两个向量索引在 `_ensure_collection()` 建集合时声明，索引由 Qdrant 自动构建，无需手动 `create_index`。

### 标量索引（payload / scalar indexes）
均为 **keyword** 类型，在 `_ensure_payload_indexes()` 中建立（新建集合与已有集合分支都会补建，已存在时忽略报错）：

| 字段 | 是否建索引 | 用途 |
|---|---|---|
| `doc_id` | ✅ keyword | 按文档批量删向量（`delete_by_doc_id`）时过滤加速 |
| `user_id` | ✅ keyword | 检索按用户隔离（`query_filter` 过滤）时加速 |
| `doc_type` | ❌ 未建 | payload 中有存，目前无需按它做标量过滤 |
| `content` | ❌ 未建 | 正文全文，通常不建索引 |

### 多租户隔离（user_id 过滤）
- 三个检索方法（`search_semantic` / `search_bm25` / `search_hybrid`）均接受 `user_id` 参数；非空时构造 `Filter(must=[FieldCondition(key="user_id", match=MatchValue(value=user_id))])` 透传给 `query_points`。
- 调用链：`agent_node._execute_tool` → `RagRetrieveTool.run(query, user_id=state.user_id)` → `strategy.retrieve(query, user_id=...)` → Qdrant `query_filter`。
- `user_id` 为 `None` 时不过滤（全库召回，用于未登录/内部场景），向后兼容。
- 入库时 `user_id` 写入每块 payload（见 §3），与检索过滤类型一致（均为 `int`）。

---

## 已落地 vs 未实现

已落地：
- 真实 Qdrant（dense + bm25/IDF 双向量、客户端 RRF 融合）
- 真实 OpenAI 兼容 Embedding
- 真实 DashScope Rerank（配置开关、失败降级）
- 检索结果去重 + doc_type 可信度排序
- Markdown 结构切块
- 全链路参数配置化（`top_k` / `min_score_threshold` / `chunk_*` / `rrf_k`）
- `user_id` 元数据写入与回传
- 检索策略泛型依赖注入（HybridStrategy 接收 `list[RetrievalStrategy]`）
- 多租户隔离：`user_id` 写入 payload 且检索按 `user_id` 过滤（keyword 索引加速）
- 文档管理接口：`GET /knowledge/files`（按用户列出）、`DELETE /knowledge/files/{id}`（软删除元信息 + 清向量）、`POST /knowledge/upload` 落 `knowledge_files` 元信息记录
- 标量索引：`doc_id` / `user_id` keyword 索引

---

## 端到端调用示例

```python
from app.business.rag import KnowledgeIngestionService, get_qdrant_client, build_embedding_client
from app.business.tools import get_rag_tool

# 1.分块 → 2.向量化 → 3.入库
qdrant = get_qdrant_client()
emb = build_embedding_client()
svc = KnowledgeIngestionService(qdrant_client=qdrant, embedding_client=emb)
svc.ingest_markdown_text("# 退款政策\n...\n# 物流时效\n...", doc_type="policy", user_id=1)

# 4.检索 → 5.召回 → 6.融合 → 7.重排序
tool = get_rag_tool()
results = tool.run("怎么申请退款？")
for r in results:
    print(r["score"], r["content"])
```
