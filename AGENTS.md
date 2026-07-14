# Repository Guidelines

## Project Overview
客服 Agent MVP：`FastAPI` 后端 + `Vue 3 + Vite + TypeScript` 前端。后端提供五条最小闭环能力——订单查询、物流查询、退款咨询、转人工、问候闲聊——采用「主意图 + 子意图」结构 + 多轮槽位补齐，由 LangGraph 编排单轮 Agent 节点。运行链为**全异步**（`async` SSE → `AsyncOpenAI` → LangGraph `astream`/`ainvoke` → DAO 原生 `AsyncSession`）。

## Project Structure & Module Organization

```text
myagent/
├── app/
│   ├── api/         # FastAPI 入口：chat.py / auth.py / rag.py，仅装配路由
│   ├── business/    # 业务逻辑层（见下，含 agent / intent / dialog / tools / rag / context / auth / prompts / memory 子包）
│   ├── config/      # 配置加载（settings / llm / rag_config / context_config / logging_config）
│   ├── dao/         # 数据访问层（session / user / knowledge / knowledge_file / data）
│   ├── data/        # 独立资源层（orders.json / logistics.json）
│   ├── model/       # SQLAlchemy ORM 表模型（user / session / knowledge）
│   ├── middleware/  # auth（JWT） + cors 中间件，统一在 app 装配
│   ├── pkgs/        # 第三方封装（auth: jwt/password/email；llm: client；vector: qdrant）
│   ├── schema/      # Pydantic（chat / auth / intent / state / session / business）
│   └── utils/       # config_paths / state / text / llm / files / module_logger
├── config/          # 各环境 yml（llm_config.*.yml + 意图/澄清/回复 prompt 模板）
├── eval/            # 意图 / RAG 评估脚本与样本
├── frontend/        # Vue 3 前端
├── tests/           # 后端单元测试
├── wiki/ / template/ / plans/   # 设计文档、调研草稿、实施计划
├── docker-compose.yml  # mysql / redis / qdrant 基础设施
├── main.py          # 转发到 app.api.app:app
└── README.md
```

分层依赖严格向下、无环：`api → business → dao → model`；`pkgs / utils / schema / data` 为叶子层，不被反向依赖。

### `app/business` 子包职责
- `agent/`：`graph.py`（`CustomerServiceAgent`，LangGraph 编排）、`agent_node.py`（`AgentNodeService`，LLM function-calling 工具节点）。
- `intent/`：`routing.py`（`IntentRouterService` 意图路由、`StateTrackerService` 槽位状态、`HandoffClarificationPolicy` 策略）、`schema.py`（`IntentSchemaRegistry`/`IntentRuleRegistry`，从 YAML 加载）、`llm_fallback.py`（`LLMIntentFallbackService` 兜底）。
- `dialog/`：`clarification.py`（`ClarificationService` + `ClarificationPromptRegistry`）、`response.py`（`ResponseService` + `ResponsePromptRegistry`）、`message.py`（`MessageService` 边界批量落库）、`session.py`（`SessionService` 会话/消息读写 + `get_session_service` 工厂）。
- `tools/`：`domain.py`（`OrderService` / `LogisticsService` / `HandoffService` / `extract_order_id`）、`tool_executor.py`（`ToolExecutor`）、`registry.py`（`build_tool_schemas`）、`rag_tool.py`（`RagRetrieveTool`）。
- `context/`：`context.py`（`ContextService` 最近消息窗口 + `running_summary` 压缩）、`state_summary.py`（共享状态摘要，打破 context ↔ intent 循环依赖）。
- `rag/`：`chunking/`（策略模式分块：`models` / `base` / `recursive_splitter` / `structure_chunk` / 7 个策略文件 / `registry`）+ `retrieval/`（独立检索目录：`models` / `base` / `bm25` / `semantic` / `hybrid` / `registry` / `rerank`，每个策略一个文件）+ `ingestion` / `sparse_bm25`（知识检索，`chunking` 与 `retrieval` 互不 import）。
- `prompts/`：`intent.py` / `system.py`（LLM prompt 定义）。
- `auth/`：`service.py`（register/login/forgot/reset/change 业务）、`router.py`（前缀 `/auth`）。
- `memory/`：记忆持久化（当前占位）。

`app/business/__init__.py` 聚合导出上述服务，供 `graph.py` 与 `api/chat.py` 直接 `from app.business import ...`。

### `app/dao`
对外提供 `SessionStore` / `UserDAO` / `KnowledgeFileDAO` 抽象接口与 `Memory*` / `Sql*` 双实现，通过 `get_session_store()` / `get_user_dao()` / `get_knowledge_file_dao()` 选择：
- `AsyncSessionLocal` 非空（已配 mysql + aiomysql）→ 用 `Sql*` 异步实现；
- 为空（未配 mysql）→ 回退 `Memory*` 进程内实现，适合本地/测试。

`knowledge.py`（`KnowledgeStore`）包装 `app.pkgs.vector`；`data.py` 容错加载 `app/data` 的 JSON。

### `app/model`
SQLAlchemy 2.0 ORM：`user.py`（`User`，`id` 为 `Integer` 自增主键）、`session.py`（`Session` / `Message` 两张表，**早期审计表 `StateSnapshot`/`ToolCall`/`HandoffRecord` 已移除**）、`knowledge.py`（知识库文件元数据）。

### `app/middleware`
`setup_middlewares(app)` 安装：
- `auth.py`：`AuthMiddleware` 解析 `Authorization: Bearer` JWT，写入 `request.state.user`；非公开路径缺/失效 token 返回 401。`PUBLIC_PATHS` = 注册/登录/找回密码/重置密码/`/docs`/`/openapi.json`/`/redoc`。
- `cors.py`：开放 `http://127.0.0.1:5173` 与 `http://localhost:5173`。

> 所有 `/chat`、`/knowledge`、`/rag/config` 接口均需在 `Authorization` 头携带有效 token（由中间件鉴权）。

## Build, Test, and Development Commands

### Backend Setup
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Running the Backend
```bash
# 开发（热重载）
uvicorn app.api.app:app --reload
# 等价入口：python main.py
# 生产多 worker（CPU 密集与 I/O 等待分离，详见 plans/full-async-plan.md）
uvicorn app.api.app:app --workers 4
# 或 gunicorn -k uvicorn.workers.UvicornWorker -w 4
```

默认地址：`http://127.0.0.1:8000`（文档 `/docs` 需登录白名单内 Token，见 middleware）。

`LangGraph` 为**硬依赖**：`CustomerServiceAgent._build_graph` 在 `langgraph` 不可用时显式抛 `RuntimeError`。

### Infrastructure (可选)
```bash
docker compose up -d mysql redis qdrant   # 三者相互独立，后端依赖其 healthy
```
未启动 mysql 时后端自动回退内存实现；RAG 的 qdrant + embedding 仅在配置齐全时生效。

### Frontend Setup
```bash
cd frontend
npm install
npm run dev   # http://127.0.0.1:5173
```

### Running Tests
```bash
pytest tests/                                   # 全部
pytest tests/test_routing_services.py           # 单文件
pytest tests/test_routing_services.py::test_intent_router   # 单用例
pytest tests/ -v                                # 详细
```
测试夹具（`tests/conftest.py`）用 `aiosqlite` 内存 SQLite + `StaticPool` 异步引擎隔离，DAO 测试经 `Sql*` 实现；结束统一 `dispose` 回收 worker 线程。`Auth` 测试同理基于异步 sqlite。

### Evaluation Scripts
```bash
python eval/run_intent_single_step_eval.py   # 意图单步评估
python eval/run_intent_compare_eval.py       # 意图对比评估
```

## Backend API Endpoints

认证（公开路径，无需 Token）：
- `POST /auth/register` / `POST /auth/login` / `POST /auth/forgot-password` / `POST /auth/reset-password` / `POST /auth/change-password`

对话（需 Token）：
- `POST /chat` — 非流式，返回 `ChatResponse`
- `POST /chat/stream` — SSE 流式（Web 首选，`text/event-stream`）
- `GET /chat/sessions` — 当前用户会话列表
- `GET /chat/session/{session_id}/messages` — 会话消息（须归属当前用户）
- `PUT /chat/session/{session_id}` — 重命名会话
- `DELETE /chat/session/{session_id}` — 软删除会话

知识库 / RAG（需 Token）：
- `POST /knowledge/upload` — 上传 `.md`/`.json`（先落元信息记录，再向量化）
- `GET /knowledge/files` — 当前用户文件列表
- `DELETE /knowledge/files/{file_id}` — 软删元信息 + 清理 Qdrant 向量
- `GET /rag/config` / `PUT /rag/config` — 检索配置读写

示例（需先 `POST /auth/login` 取 token）：
```bash
curl -X POST http://127.0.0.1:8000/chat \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <TOKEN>" \
  -d '{"session_id":"demo-session","user_id":"user-001","channel":"web","message":"帮我查一下订单 A1001"}'
```

## Execution Chain (LangGraph)

`CustomerServiceAgent`（`app/business/agent/graph.py`）用 `StateGraph(dict)` 编译，节点顺序：

`input_normalizer → intent_router → state_tracker → policy_layer →（条件分支）→ clarification_node | agent_node | handoff_node | response_generator → context_compressor → END`

- `policy_layer`（`HandoffClarificationPolicy.decide`）产出 `current_action`，由 `route_after_policy` 分发：`ask_intent_clarification`/`ask_slot_clarification` → `clarification_node`；`agent_process` → `agent_node`（工具调用）；`handoff_human` → `handoff_node`；其余 → `response_generator`。
- **边界落库**：图内节点只收集数据、不写库；`chat()` 用 `graph.ainvoke` 跑完后由 `MessageService.persist` 批量落库。`chat_events()` 用 `graph.astream` 边跑边下推 `intent/state/tool_result` 事件，但 **`final` 事件在 `persist` 之后才下发**——先持久化（用户消息 + 助手回复 + 状态快照）再 yield `final`，避免「客户端已收回复但 DB 未落库」的崩溃窗口（详见 `plans/full-async-plan.md`）。
- 全链路 `async def`，I/O 等待让出事件循环。

`ChatResponse` 经 `_build_chat_response` 简化，仅下发前端渲染所需字段：`reply` + `session_id` + `session_state`（快照：`current_main_intent`/`current_sub_intent`/`stage`/`slots`/`missing_slots`/`needs_clarification`/`summary`）。

## SSE Events
`/chat/stream` 持续输出：
- `intent` — 识别意图（main/sub/confidence/slots/needs_clarification）
- `state` — 状态快照
- `tool_result` — 工具执行结果
- `final` — 最终响应（落库后下发）
- `error` — 异常兜底

## Intent Structure
「主意图 + 子意图」，由 `config/intent_schemas.yml` 与 `config/intent_rules.yml` 加载：
- `order_service` → `order_service.query_status`
- `logistics_service` → `logistics_service.query_status`
- `refund_service` → `refund_service.consult_policy` / `refund_service.request_refund`
- `handoff_service` → `handoff_service.request_human`
- `unsupported` → `unsupported.unknown`

## State Model
`ConversationState`（`app/schema/state.py`）覆盖两层上下文：
- 业务状态：`current_main_intent / current_sub_intent / stage / slots / missing_slots / confirmed_slots`
- 执行状态：`current_action / latest_action_result / action_history / running_summary / archived_states`

## Configuration Files

### 意图 / 文案模板（YAML）
- `config/intent_schemas.yml` — 主意图 slot schema（`required_slots` / `inheritable` / `clarification_order`）
- `config/intent_rules.yml` — 主/子意图规则关键词与情绪规则
- `config/clarification_prompts.yml` — 缺槽追问 / fallback 澄清文案
- `config/response_prompts.yml` — 客服话术 / 退款确认 / 订单物流转人工模板

### LLM 兜底配置（按环境拆分）
- `config/llm_config.local.yml`（gitignore，本机 key/中转站）、`config/llm_config.test.yml`、`config/llm_config.prod.yml`
- `get_app_env()` 默认 `local`（**非** test）；优先读 `llm_config.{env}.yml`。
- `app/config/settings.py`：`get_mysql_config` / `get_jwt_config` / `get_smtp_config`；`app/config/llm.py`：`load_llm_config`；`app/config/rag_config.py`：`RagConfig` + `get_rag_config_service`；`app/config/context_config.py`：`get_context_config_service`（控制 `max_recent_messages` / `max_summary_chars`）；`app/config/logging_config.py`：日志。

## Coding Style & Naming Conventions
4 空格缩进，PEP 8：
- `snake_case`：变量/函数/文件名；`UPPER_SNAKE_CASE`：常量（`COLLECTION_NAME` 等）
- 所有函数签名与模型定义加 Type Hints
- Markdown 偏好短节、扁平列表、`02_RAG.md` 式主题命名；扩展调研文档用简洁中文

## Testing Guidelines
`tests/` 下 `test_*.py`，当前覆盖：
- `test_customer_service_agent.py` — 端到端 Agent
- `test_routing_services.py` — 意图路由
- `test_dialog_services.py` — 澄清/回复
- `test_full_async.py` — 全异步执行链
- `test_session_store_persistence.py` — 会话持久化
- `test_knowledge_file_dao.py` — 知识文件 DAO
- `test_rag_module.py` — RAG 模块
- `test_tool_executor.py` — 工具执行
- `test_auth_services.py` — 认证（异步 sqlite 内存库 + `SqlUserDAO`）

提交前跑 `pytest tests/`；新增能力在对应文件补用例。

## Commit & Pull Request Guidelines
采用 Conventional Commits，如 `docs(template): 补充多轮意图识别调研`。scope 用 `template` / `rag` / `agent` / `api` / `business` / `dao` / `frontend` 等。PR 含：变更说明 + 影响路径（如 `app/business/agent/graph.py`）+ 仅在 UI/格式显著变化时附截图。提交前 `git diff --cached` 复核，仅 stage 目标文件。

## Frontend Notes
- `Vue 3 + Vite + TypeScript + Pinia + Vue Router`
- Vite 代理 `/api`（`/chat`、`/auth`、`/knowledge`、`/rag`）到 `http://127.0.0.1:8000`
- 视图：`ConsoleView`（消息流 + 状态面板 + 轮次 Trace）、`KnowledgeBuildPanel`、`LoginView` / `RegisterView` / `ForgotPasswordView`
- 组件：`OrderDetailCard` / `LogisticsTimelineCard` / `HandoffCard` / `TurnTracePanel` / `LiveStatsBar` / `StatsPanel`
- 库：`lib/sse.ts`（`ChatSSEClient` + `AbortController` 支持中途打断）、`lib/api.ts`、`lib/session.ts`；状态：`stores/chat.ts`、`stores/auth.ts`
- Web 端优先 SSE `POST /chat/stream`，`POST /chat` 为回退通道
