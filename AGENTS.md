# Repository Guidelines

## Project Overview
This is a customer service Agent MVP with a FastAPI backend and Vue 3 frontend. The agent provides five core capabilities: order query, logistics query, refund consultation, human handoff, and greetings. The backend uses a main intent + sub-intent structure with multi-turn slot filling.

## Project Structure & Module Organization

```text
myagent/
├── app/
│   ├── api/         # FastAPI HTTP / SSE 入口，仅做请求处理与应用装配
│   ├── business/    # 业务逻辑层（含 auth / rag / tools / prompts 子模块）
│   ├── config/      # 配置加载
│   ├── dao/         # 数据访问层（session / user / knowledge / data）
│   ├── data/        # 独立资源层（orders.json / logistics.json）
│   ├── model/       # SQLAlchemy ORM 表模型
│   ├── pkgs/        # 第三方调用封装（auth / llm / vector）
│   ├── schema/      # Pydantic 请求/响应数据结构
│   └── utils/       # 文本与状态辅助函数
├── config/          # test / prod / local yml 配置文件
├── eval/            # 单点评估脚本、样本、评估报告
├── frontend/        # Vue 3 前端
├── tests/           # 后端单元测试
├── wiki/            # 设计文档
├── template/        # 调研与草稿材料
├── main.py          # 后端启动入口（转发到 app/api/app.py）
└── README.md
```

分层依赖方向严格向下、无环：`api → business → dao → model`，`pkgs / utils / schema / data` 为叶子层，不被反向依赖。

Core backend modules:

- `app/api`: 仅暴露 HTTP / SSE 接口与组装应用；按模块拆分为 `chat.py` / `auth.py` / `rag.py`
- `app/business`: 业务逻辑层，串联意图识别、状态更新、策略分发、工具路由、澄清与回复生成
  - `routing.py`: 意图路由、状态跟踪
  - `dialog.py`: 澄清回复、最终回复、memory 持久化
  - `execution.py`: 业务工具调用、转人工执行
  - `context.py`: 最近消息窗口与 `running_summary` 压缩
  - `domain.py`: 订单查询、物流查询、转人工等领域服务
  - `intent_schema.py`: 主意图 `slot schema` 与规则关键词 registry，默认从 YAML 加载
  - `llm_fallback.py`: LLM 兜底意图识别
  - `state_summary.py`: 共享的状态摘要构建（打破 context ↔ routing 循环依赖）
  - `agent_node.py`: 单轮 Agent 节点执行
  - `customer_service.py`: 客服主 Agent，编排各节点
  - `app/business/rag`: 知识检索（chunker / ingestion / sparse_bm25 / retrieval_strategy / rerank）
  - `app/business/tools`: 工具层，封装供 LLM 调用的业务工具（如 `rag_tool.py` 的 `RagRetrieveTool` 检索工具）；依赖 `rag` 子包
  - `app/business/prompts`: LLM prompt 定义（intent 等）
  - `app/business/auth`: 认证业务（service / router / models / deps），依赖 `UserDAO` 依赖注入
- `app/dao`: 数据访问层，对外提供 `SessionStore` / `UserDAO` 抽象接口与 `Memory*` / `Sql*` 双实现
  - `session.py`: `SessionStore`（ABC）、`MemorySessionStore`、`SqlSessionStore`
  - `user.py`: `UserDAO`（ABC）、`MemoryUserDAO`、`SqlUserDAO`
  - `knowledge.py`: `KnowledgeStore`，包装 `app.pkgs.vector`
  - `data.py`: 加载 `app/data` 下的 JSON 资源（容错）
- `app/model`: SQLAlchemy ORM 表模型
  - `user.py`: `User` 表（`id` 为 `Integer` 自增主键）
  - `session.py`: `Session / Message / StateSnapshot / ToolCall / HandoffRecord` 表
- `app/schema`: Pydantic 数据结构（`ChatRequest` / `ChatResponse` / `ConversationState` 等）
- `app/pkgs`: 第三方调用封装
  - `auth`: `jwt`（token 签发/校验）、`password`（bcrypt）、`email`（smtp）
  - `llm`: `client`（OpenAI 客户端构建）
  - `vector`: `qdrant`（向量库客户端）
- `app/config`: 读取 `APP_ENV` 对应配置并叠加 local 覆盖
- `app/data`: 独立资源层（`orders.json` / `logistics.json`），由 `app/dao/data.py` 容错加载
- `app/utils`: `config_paths`（统一 ROOT/CONFIG 目录解析）、`state`（`action_history` 等状态辅助）

## Build, Test, and Development Commands

### Backend Setup
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Running the Backend
```bash
# Development with auto-reload
uvicorn app.api.app:app --reload

# Or use main.py (redirects to app/api/app.py)
python main.py
```

Default backend address: `http://127.0.0.1:8000`

### Frontend Setup
```bash
cd frontend
npm install
npm run dev
```

Default frontend address: `http://127.0.0.1:5173`

### Running Tests
```bash
# Run all tests
pytest tests/

# Run a single test file
pytest tests/test_routing_services.py

# Run a specific test
pytest tests/test_routing_services.py::test_intent_router

# Run with verbose output
pytest tests/ -v
```

### Evaluation Scripts
```bash
# Run intent single-step evaluation
python eval/run_intent_single_step_eval.py

# Run intent comparison evaluation
python eval/run_intent_compare_eval.py
```

### Useful Git Commands
```bash
git diff --stat          # Review change scope before committing
git status --short      # Verify staged and unstaged files
git diff --cached       # Review staged changes before committing
```

## Backend API Endpoints

- `POST /chat` - Chat endpoint (non-streaming)
- `POST /chat/init` - Create a new session
- `POST /chat/stream` - SSE chat endpoint (preferred for web, returns `text/event-stream`)
- `GET /session/{session_id}` - Get session state
- `POST /auth/register` / `POST /auth/login` / `POST /auth/forgot-password` / `POST /auth/reset-password` / `POST /auth/change-password` - 认证
- `POST /knowledge/upload` - 知识库上传
- `GET /rag/config` / `PUT /rag/config` - RAG 配置

Example curl request:
```bash
curl -X POST http://127.0.0.1:8000/chat \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "demo-session",
    "user_id": "user-001",
    "channel": "web",
    "message": "帮我查一下订单 A1001"
  }'
```

## Execution Chain

The backend execution chain aligns with `template/06.1-06.4` and `template/07`:

`input_normalizer -> intent_router -> state_tracker -> policy_layer -> clarification / tool / handoff -> response_generator -> context_compressor -> memory_writer`

## Intent Structure

Current backend intent structure uses "main intent + sub-intent", loaded from `config/intent_schemas.yml` and `config/intent_rules.yml`:

- `order_service` -> `order_service.query_status`
- `logistics_service` -> `logistics_service.query_status`
- `refund_service` -> `refund_service.consult_policy`
- `refund_service` -> `refund_service.request_refund`
- `handoff_service` -> `handoff_service.request_human`
- `chitchat` -> `chitchat.greeting`
- `chitchat` -> `chitchat.thanks`
- `unsupported` -> `unsupported.unknown`

Intent codes in design docs (`template/`) have been aligned to this list.

## Configuration Files

### Intent Schema Config
Main intent slot schemas are externalized to:
- `config/intent_schemas.yml` - Slot schemas for main intents
- `config/intent_rules.yml` - Rule keywords for intent routing
- `config/clarification_prompts.yml` - Clarification prompt templates
- `config/response_prompts.yml` - Response prompt templates

### LLM Fallback Config
LLM fallback configuration is split by environment:
- `config/llm_config.test.yml`
- `config/llm_config.prod.yml`
- `config/llm_config.local.yml` (gitignored, for local overrides)

Loading order:
1. Read baseline config corresponding to `APP_ENV` (default: `test`)
2. If `config/llm_config.local.yml` exists, overlay with local config

`llm_config.local.yml` is in `.gitignore`, suitable for local keys and proxy addresses.

## State Model

Current `ConversationState` covers two layers of context:

- Business state: `current_main_intent / current_sub_intent / stage / slots / missing_slots / confirmed_slots`
- Execution state: `current_action / latest_action_result / action_history / running_summary / archived_states`

SSE `/chat/stream` continuously outputs events:
- `intent` - Recognized intent
- `state` - Current state snapshot
- `tool_result` - Tool execution results
- `final` - Final response

## Coding Style & Naming Conventions
Use 4 spaces for Python indentation and follow PEP 8 naming:

- `snake_case` for variables, functions, and file names
- `UPPER_SNAKE_CASE` for constants such as `COLLECTION_NAME`
- Use Type Hints for all function signatures and model definitions

For Markdown, prefer short sections, flat bullet lists, and topic-based filenames like `02_RAG.md`. Keep examples practical and written in concise Chinese when extending the existing research docs.

## Testing Guidelines

Tests are located in `tests/` directory with `test_*.py` files. Current test coverage includes:
- `test_customer_service_agent.py` - End-to-end agent tests
- `test_routing_services.py` - Intent routing tests
- `test_dialog_services.py` - Dialog services tests
- `test_execution_services.py` - Execution services tests
- `test_context_services.py` - Context services tests
- `test_rag_module.py` - RAG module tests
- `test_auth_services.py` - Auth services tests（基于 sqlite 内存库 + `SqlUserDAO` 依赖注入）

Run tests with `pytest tests/` before committing changes. When adding new functionality, add corresponding test cases in the appropriate test file.

## Commit & Pull Request Guidelines
Recent history uses Conventional Commits, for example `docs(template): 补充多轮意图识别调研`. Follow `type(scope): summary` and keep scopes specific, such as `template`, `rag`, `agent`, `api`, `business`, `dao`, `frontend`.

Pull requests should include:

- a short description of what changed and why
- impacted paths, such as `app/business/routing.py`
- screenshots only when UI or formatting changes materially

Stage only intended files and review `git diff --cached` before committing.

## Frontend Notes

- `frontend/` uses `Vue 3 + Vite + TypeScript + Pinia + Vue Router`
- Vite dev server proxies `/api` and `/chat/stream` to `http://127.0.0.1:8000`
- Backend has CORS enabled for `http://127.0.0.1:5173` and `http://localhost:5173`
- Frontend console includes message flow, session state panel, turn trace history, and structured detail cards for orders/logistics/handoff
- SSE `POST /chat/stream` is preferred for real-time communication, with `POST /chat` as fallback
- Frontend uses `ChatSSEClient` (`frontend/src/lib/sse.ts`) with `AbortController` for user interrupt
