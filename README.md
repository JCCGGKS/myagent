# myagent

客服 Agent MVP：基于 `FastAPI` 的对话后端 + `Vue 3 + Vite + TypeScript` 前端。提供 `订单查询/改地址/开票 / 物流查询 / 退款与售后 / 投诉处理 / 转人工 / 问候闲聊` 六条最小闭环能力，采用「主意图 + 子意图」结构 + 多轮槽位补齐，由 LangGraph 编排单轮 Agent 节点；并支持规则+LLM 双路情绪识别与「先安抚后作答」。运行链全异步（`async` SSE → `AsyncOpenAI` → LangGraph `astream`/`ainvoke` → DAO 原生 `AsyncSession`）。

## Quick Start

后端：

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.api.app:app --reload
```

前端：

```bash
cd frontend
npm install
npm run dev
```

默认开发地址：
- 前端：`http://127.0.0.1:5173`
- 后端：`http://127.0.0.1:8000`
- 指标：`http://127.0.0.1:8000/metrics`（Prometheus）

> 后端除注册/登录/找回密码/重置密码与 `/docs`、`/openapi.json`、`/redoc`、`/metrics` 外，其余接口（`/chat`、`/knowledge`、`/rag/config`）均需 `Authorization: Bearer <TOKEN>`。先 `POST /auth/register` 或 `/auth/login` 取 token。

基础设施（可选，未启动则后端自动回退内存实现）：

```bash
docker compose up -d mysql redis qdrant
```

## Current Scope
- 订单状态查询、改地址、开票；物流状态查询；退款/售后（咨询与办理）；投诉处理；转人工；问候闲聊
- 规则+LLM 双路情绪识别（意图路由内并行识别，合并写入 `state.emotion`；negative 时确定性「先安抚后作答」）；**情绪仅作回复/澄清的语气信号，不参与意图路由、策略仲裁或转人工等任何决策分支**（详见 `app/schema/stage.md` 与 `app/business/intent/README.md`）
- 多轮槽位补齐；主意图切换后状态冻结与槽位继承
- 结构化上下文压缩（`running_summary`）与工具调用
- **R1 二次确认**：退款等高风险的 `request_refund` 动作在工具执行前挂起，待用户下一轮自然语言「确认/取消」再放行（确定性信号识别，不依赖 LLM 回忆）
- 知识库上传 + 混合向量检索（Qdrant：dense 语义 + bm25 稀疏双向量，RRF 融合；可选 DashScope rerank 重排，配置齐全时生效）
- 用户认证（JWT：注册/登录/找回/重置/改密）
- 可观测：Prometheus 指标（`/metrics`）、TraceId 全链路日志、事件日志、`monitoring/`（Prometheus + Grafana）
- 图态持久化：LangGraph checkpointer（Redis 优先，未配回退内存），多轮断点续跑

后端意图结构（「主意图 + 子意图」，来自 `config/intent_schemas.yml` / `intent_rules.yml`，权威枚举见 `app/schema/intent.py`）：

- `order_query` → `order_query.query_status` / `order_query.modify_address` / `order_query.apply_invoice`
- `logistics` → `logistics.not_received` / `logistics.lost_package` / `logistics.delayed`
- `after_sale_refund` → `after_sale_refund.consult_policy` / `after_sale_refund.request_refund` / `after_sale_refund.no_reason_return` / `after_sale_refund.wrong_goods` / `after_sale_refund.damage_refund`
- `complaint` → `complaint.compensate` / `complaint.service_complaint`（纯投诉，落 handoff）
- `handoff_service` → `handoff_service.request_human`
- `unrecognize` → `unrecognize.unknown`
- `unsupported_biz` → `unsupported_biz.out_of_scope`

## API Endpoints

认证（公开）：
- `POST /auth/register` / `POST /auth/login` / `POST /auth/forgot-password` / `POST /auth/reset-password` / `POST /auth/change-password`

对话（需 Token）：
- `POST /chat` — 非流式 `ChatResponse`
- `POST /chat/stream` — SSE 流式（Web 首选）
- `GET /chat/sessions`、`GET /chat/session/{id}/messages`、`GET /chat/session/{id}/events`（回放可观测事件流）、`PUT /chat/session/{id}`、`DELETE /chat/session/{id}`

知识库 / RAG（需 Token）：
- `POST /knowledge/upload`（支持 `.md`/`.markdown`/`.json`/`.word`/`.excel`/`.csv`/`.pdf`/`.ppt`）、`GET /knowledge/files`、`PUT /knowledge/files/{id}`（更新元信息）、`DELETE /knowledge/files/{id}`
- `GET /rag/config` / `PUT /rag/config`

可观测（公开）：
- `GET /metrics` — Prometheus 指标

示例：

```bash
curl -X POST http://127.0.0.1:8000/chat \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <TOKEN>" \
  -d '{"session_id":"demo-session","user_id":"user-001","channel":"web","message":"帮我查一下订单 A1001"}'
```

## Execution Chain (LangGraph)

`CustomerServiceAgent`（`app/business/agent/graph.py`）用 `StateGraph` 编译：

`input_normalizer → confirmation_guard →（条件：pending_confirmation 非空则拦截确认/取消信号）→ intent_router → state_tracker → policy_layer →（条件）→ clarification_node | agent_node | handoff_node | response_generator → context_compressor → END`

- `confirmation_guard` 仅在 `state.pending_confirmation` 非空时介入，用确定性 `classify_confirm_signal` 识别用户回复为「确认/取消/无关」，放行或取消上一轮挂起的高风险操作（如退款），否则回退正常意图路由。
- `policy_layer` 产出 `current_action`，由 `route_after_policy` 分发到澄清/工具/转人工/回复节点。
- **边界落库**：图内不写库；`chat()` 用 `ainvoke` 跑完后由 `MessageService.persist` 批量落库，`chat_events()` 用 `astream` 边跑边推事件，但 `final` 事件在落库之后下发（先持久化再回包，避免崩溃丢上下文）。
- **图态持久化**：图带 checkpointer（优先 Redis，未配回退内存），支持多轮断点续跑（TTL 由 `checkpoint_config` 控制，默认 7 天）。
- `ChatResponse` 仅含 `reply` + `session_id` + `session_state`（快照字段，含 `pending_confirmation` 挂起标志）。

SSE 事件：`intent` / `state` / `tool_result` / `final`（异常时 `error`）。

## Project Structure

```text
myagent/
├── app/
│   ├── api/         # app.py / chat.py / auth.py / rag.py（仅装配路由）
│   ├── business/    # agent / intent / dialog / tools / context / rag / prompts / auth / memory
│   ├── config/      # settings / llm / rag_config / context_config / checkpoint_config / logging_config
│   ├── dao/         # session / user / knowledge / knowledge_file / data / event_log（Memory* / Sql* 双实现）
│   ├── data/        # orders.json / logistics.json
│   ├── model/       # user / session(含 EventLog) / knowledge（SQLAlchemy ORM）
│   ├── middleware/  # auth（JWT）/ cors / trace（TraceId）
│   ├── pkgs/        # auth(jwt/password/email) / llm / vector(qdrant)
│   ├── schema/      # chat / auth / intent / state / session / business
│   └── utils/       # config_paths / state / text / llm / files / module_logger / metrics / trace
├── config/          # llm_config.*.yml + 意图/澄清/回复 prompt 模板
├── eval/            # 评估套件：intent / rag / answer / trajectory
├── frontend/        # Vue 3 前端
├── tests/           # 后端单元测试（aiosqlite 内存库隔离）
├── monitoring/      # Prometheus + Grafana 配置
├── docker-compose.yml  # mysql / redis / qdrant
├── main.py          # 转发 app.api.app:app
└── AGENTS.md
```

> `docs/`、`plans/`、`interview/`、`logs/` 为 `.gitignore` 忽略的本地目录，不纳入版本库。

分层依赖严格向下、无环：`api → business → dao → model`；`pkgs / utils / schema / data` 为叶子层。

### 数据存储切换
`app/dao` 的 `get_session_store()` / `get_user_dao()` / `get_knowledge_file_dao()` / `get_event_log_store()` 按 `AsyncSessionLocal` 是否为空选择 `Sql*`（已配 mysql + aiomysql，原生异步）或 `Memory*`（进程内，本地/测试）。`app/model/session.py` 含 `Session` / `Message` / `EventLog` 三张表（早期审计表已移除，`EventLog` 为可观测事件日志表）。

## Configuration

### 意图 / 文案模板（YAML）
- `config/intent_schemas.yml` — 主意图 slot schema
- `config/intent_rules.yml` — 主/子意图规则关键词与情绪规则
- `config/clarification_prompts.yml` — 缺槽追问 / fallback 文案
- `config/response_prompts.yml` — 客服话术 / 退款确认 / 订单物流转人工模板

### LLM 兜底配置
按环境拆分：`config/llm_config.local.yml`（gitignore，本机 key/中转站）、`llm_config.local.example.yml`（示例可复制为 local）、`llm_config.test.yml`、`llm_config.prod.yml`。`get_app_env()` 默认 `local`；`llm_config.local.yml` 存在时覆盖基线。关键字段：`enabled` / `api_key` / `model` / `base_url` / `timeout_seconds` / `confidence_threshold`。RAG 段另含 `embedding`（api_key 等）与 `qdrant`（host/port/collection/vector_size）配置。

### RAG 检索配置（写入 `llm_config.{env}.yml` 的 `rag` 段，前端 `PUT /rag/config` 可调）
`retrieval_strategy`（`bm25` | `semantic` | `hybrid`，默认 hybrid，RRF 融合）/ `top_k` / `min_score_threshold`（单一字段，按策略量纲由前端限幅）/ `chunk_size` / `chunk_overlap` / `rrf_k` / `rerank`（`enabled`/`base_url`/`api_key`/`model`，DashScope 重排，失败降级）。详见 `app/business/rag/README.md`。

### 图态持久化配置
`app/config/checkpoint_config.py`：checkpointer TTL（`CHECKPOINT_TTL_SECONDS` 或 `llm_config.{env}.yml` 的 `checkpoint` 段，默认 7 天）。Redis 优先（`langgraph-checkpoint-redis`+`redis`+`REDIS_URL`），未配回退进程内 `MemorySaver`。

## Testing & Evaluation

```bash
pytest tests/                                   # 全部
pytest tests/test_routing_services.py           # 单文件
pytest tests/test_routing_services.py::test_intent_router   # 单用例
```

测试用 `tests/conftest.py` 的 `aiosqlite` 内存 SQLite（`StaticPool`）异步引擎隔离，DAO 走 `Sql*` 实现。

评估套件按维度拆分到 `eval/` 子目录，统一入口 `run_eval.py`：
```bash
python eval/intent/run_eval.py [--no-llm | --with-llm | --compare-only | --sweep-threshold]   # 意图单步评估
eval/rag/.venv/bin/python eval/rag/run_ragas_eval.py [...]    # RAGAS 端到端评测（独立 venv 运行）
python eval/answer/run_eval.py [--limit N | --no-llm-judge]   # 最终回复质量评估
python eval/trajectory/run_eval.py                            # 决策轨迹评估
```

## Frontend Notes
- `Vue 3 + Vite + TypeScript + Pinia + Vue Router`
- Vite 代理 `/api`（`/chat`、`/auth`、`/knowledge`、`/rag`）到 `http://127.0.0.1:8000`
- 视图：`ConsoleView`（消息流 + 状态面板 + 轮次 Trace）、`KnowledgeBuildPanel`、`LoginView` / `RegisterView` / `ForgotPasswordView`
- 组件：`OrderDetailCard` / `LogisticsTimelineCard` / `HandoffCard` / `TurnTracePanel` / `LiveStatsBar` / `StatsPanel`
- 库：`lib/sse.ts`（`ChatSSEClient` + `AbortController` 支持中途打断）、`lib/api.ts`、`lib/session.ts`；状态：`stores/chat.ts`、`stores/auth.ts`
- Web 端优先 SSE `POST /chat/stream`，`POST /chat` 为回退通道
