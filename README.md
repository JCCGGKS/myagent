# myagent

客服 Agent MVP：基于 `FastAPI` 的对话后端 + `Vue 3 + Vite + TypeScript` 前端。提供 `订单查询 / 物流查询 / 退款咨询 / 转人工 / 问候闲聊` 五条最小闭环能力，采用「主意图 + 子意图」结构 + 多轮槽位补齐，由 LangGraph 编排单轮 Agent 节点。运行链全异步（`async` SSE → `AsyncOpenAI` → LangGraph `astream`/`ainvoke` → DAO 原生 `AsyncSession`）。

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

> 后端除注册/登录/找回密码/重置密码与 `/docs`、`/openapi.json`、`/redoc` 外，其余接口（`/chat`、`/knowledge`、`/rag/config`）均需 `Authorization: Bearer <TOKEN>`。先 `POST /auth/register` 或 `/auth/login` 取 token。

基础设施（可选，未启动则后端自动回退内存实现）：

```bash
docker compose up -d mysql redis qdrant
```

## Current Scope
- 订单状态查询、物流状态查询、退款规则咨询、转人工、问候闲聊
- 多轮槽位补齐；主意图切换后状态冻结与槽位继承
- 结构化上下文压缩（`running_summary`）与工具调用
- 知识库上传 + 向量检索（Qdrant + embedding，配置齐全时生效）
- 用户认证（JWT：注册/登录/找回/重置/改密）

后端意图结构（「主意图 + 子意图」，来自 `config/intent_schemas.yml` / `intent_rules.yml`）：

- `order_service` → `order_service.query_status`
- `logistics_service` → `logistics_service.query_status`
- `refund_service` → `refund_service.consult_policy` / `refund_service.request_refund`
- `handoff_service` → `handoff_service.request_human`
- `unsupported` → `unsupported.unknown`

## API Endpoints

认证（公开）：
- `POST /auth/register` / `POST /auth/login` / `POST /auth/forgot-password` / `POST /auth/reset-password` / `POST /auth/change-password`

对话（需 Token）：
- `POST /chat` — 非流式 `ChatResponse`
- `POST /chat/stream` — SSE 流式（Web 首选）
- `GET /chat/sessions`、`GET /chat/session/{id}/messages`、`PUT /chat/session/{id}`、`DELETE /chat/session/{id}`

知识库 / RAG（需 Token）：
- `POST /knowledge/upload`、`GET /knowledge/files`、`DELETE /knowledge/files/{id}`
- `GET /rag/config` / `PUT /rag/config`

示例：

```bash
curl -X POST http://127.0.0.1:8000/chat \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <TOKEN>" \
  -d '{"session_id":"demo-session","user_id":"user-001","channel":"web","message":"帮我查一下订单 A1001"}'
```

## Execution Chain (LangGraph)

`CustomerServiceAgent`（`app/business/agent/graph.py`）用 `StateGraph` 编译：

`input_normalizer → intent_router → state_tracker → policy_layer →（条件）→ clarification_node | agent_node | handoff_node | response_generator → context_compressor → END`

- `policy_layer` 产出 `current_action`，由 `route_after_policy` 分发到澄清/工具/转人工/回复节点。
- **边界落库**：图内不写库；`chat()` 用 `ainvoke` 跑完后由 `MessageService.persist` 批量落库，`chat_events()` 用 `astream` 边跑边推事件，但 `final` 事件在落库之后下发（先持久化再回包，避免崩溃丢上下文）。
- `ChatResponse` 仅含 `reply` + `session_id` + `session_state`（快照字段）。

SSE 事件：`intent` / `state` / `tool_result` / `final`（异常时 `error`）。

## Project Structure

```text
myagent/
├── app/
│   ├── api/         # chat.py / auth.py / rag.py（仅装配路由）
│   ├── business/    # agent / intent / dialog / tools / context / rag / prompts / auth / memory
│   ├── config/      # settings / llm / rag_config / context_config / logging_config
│   ├── dao/         # session / user / knowledge / knowledge_file / data（Memory* / Sql* 双实现）
│   ├── data/        # orders.json / logistics.json
│   ├── model/       # user / session / knowledge（SQLAlchemy ORM）
│   ├── middleware/  # auth（JWT）/ cors
│   ├── pkgs/        # auth(jwt/password/email) / llm / vector(qdrant)
│   ├── schema/      # chat / auth / intent / state / session / business
│   └── utils/       # config_paths / state / text / llm / files / module_logger
├── config/          # llm_config.*.yml + 意图/澄清/回复 prompt 模板
├── eval/            # 意图 / RAG 评估脚本与样本
├── frontend/        # Vue 3 前端
├── tests/           # 后端单元测试（aiosqlite 内存库隔离）
├── docker-compose.yml  # mysql / redis / qdrant
├── main.py          # 转发 app.api.app:app
└── AGENTS.md
```

分层依赖严格向下、无环：`api → business → dao → model`；`pkgs / utils / schema / data` 为叶子层。

### 数据存储切换
`app/dao` 的 `get_session_store()` / `get_user_dao()` / `get_knowledge_file_dao()` 按 `AsyncSessionLocal` 是否为空选择 `Sql*`（已配 mysql + aiomysql，原生异步）或 `Memory*`（进程内，本地/测试）。`app/model/session.py` 仅 `Session` / `Message` 两张表（早期审计表已移除）。

## Configuration

### 意图 / 文案模板（YAML）
- `config/intent_schemas.yml` — 主意图 slot schema
- `config/intent_rules.yml` — 主/子意图规则关键词与情绪规则
- `config/clarification_prompts.yml` — 缺槽追问 / fallback 文案
- `config/response_prompts.yml` — 客服话术 / 退款确认 / 订单物流转人工模板

### LLM 兜底配置
按环境拆分：`config/llm_config.local.yml`（gitignore，本机 key/中转站）、`llm_config.test.yml`、`llm_config.prod.yml`。`get_app_env()` 默认 `local`；`llm_config.local.yml` 存在时覆盖基线。关键字段：`enabled` / `api_key` / `model` / `base_url` / `timeout_seconds` / `confidence_threshold`。RAG 段另含 `embedding`（api_key 等）与 `qdrant`（host/port/collection/vector_size）配置。

## Testing & Evaluation

```bash
pytest tests/                                   # 全部
pytest tests/test_routing_services.py           # 单文件
pytest tests/test_routing_services.py::test_intent_router   # 单用例

python eval/run_intent_single_step_eval.py      # 意图单步评估
python eval/run_intent_compare_eval.py          # 意图对比评估
```

测试用 `tests/conftest.py` 的 `aiosqlite` 内存 SQLite（`StaticPool`）异步引擎隔离，DAO 走 `Sql*` 实现。

## Frontend Notes
- `Vue 3 + Vite + TypeScript + Pinia + Vue Router`
- Vite 代理 `/api`（`/chat`、`/auth`、`/knowledge`、`/rag`）到 `http://127.0.0.1:8000`
- 视图：`ConsoleView`（消息流 + 状态面板 + 轮次 Trace）、`KnowledgeBuildPanel`、`LoginView` / `RegisterView` / `ForgotPasswordView`
- 组件：`OrderDetailCard` / `LogisticsTimelineCard` / `HandoffCard` / `TurnTracePanel` / `LiveStatsBar` / `StatsPanel`
- 库：`lib/sse.ts`（`ChatSSEClient` + `AbortController` 支持中途打断）、`lib/api.ts`、`lib/session.ts`；状态：`stores/chat.ts`、`stores/auth.ts`
- Web 端优先 SSE `POST /chat/stream`，`POST /chat` 为回退通道
