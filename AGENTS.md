# Repository Guidelines

## Project Overview
This is a customer service Agent MVP with a FastAPI backend and Vue 3 frontend. The agent provides six core capabilities: FAQ, order query, logistics query, refund consultation, human handoff, and greetings. The backend uses a main intent + sub-intent structure with multi-turn slot filling.

## Project Structure & Module Organization

```text
myagent/
├── app/
│   ├── agents/      # Customer service main agent, orchestrates nodes
│   ├── api/         # FastAPI / WebSocket entry points
│   ├── config/      # Configuration loading
│   ├── mock_data/   # FAQ, order, logistics mock data
│   ├── models/      # Request, response, session, domain models
│   ├── prompts/     # LLM prompt definitions
│   ├── rag/         # Knowledge retrieval and FAQ/RAG modules
│   ├── services/    # Routing / state / policy / dialog / execution / context services
│   ├── store/       # Session state storage, tool audit, handoff records
│   └── utils/       # File and text utility functions
├── config/          # test / prod / local yml configuration files
├── eval/            # Single-point evaluation scripts, samples, evaluation reports
├── frontend/        # Vue 3 frontend
├── tests/           # Backend unit tests
├── wiki/            # Design documentation
├── template/        # Research and draft materials
├── main.py          # Backend entry point (redirects to app/api/app.py)
└── README.md
```

Core backend modules:

- `app/api`: Exposes HTTP and WebSocket interfaces, handles app assembly
- `app/agents`: Chains intent recognition, state updates, policy distribution, FAQ/tool routing, clarification and response generation
- `app/models`: Unified maintenance of `ChatRequest`, `ChatResponse`, `ConversationState` and other data structures
- `app/rag`: Hosts FAQ retrieval and subsequent RAG evolution entry points, currently contains `KnowledgeBaseService` and `RagRetrievalService`
- `app/services/domain`: Order query, logistics query, human handoff and other domain services
- `app/services/routing`: Intent routing, state tracking, policy layer
- `app/services/dialog`: Clarification replies, final replies, memory persistence
- `app/services/execution`: Business tool calls, human handoff execution
- `app/services/context`: Recent message window and `running_summary` compression
- `app/services/intent_schema`: Main intent `slot schema` and rule keyword registry, loaded from YAML by default
- `app/config`: Reads `APP_ENV` corresponding configuration and overlays local overrides
- `app/prompts`: Independently manages LLM-related prompts for easy viewing and iteration
- `app/store`: Currently uses in-memory `sessions / messages / state_snapshots / tool_calls / handoff_records`
- `app/utils/state`: State auxiliary functions like `action_history`

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

- `GET /health` - Health check
- `POST /chat` - Chat endpoint (fallback when WebSocket unavailable)
- `WS /ws/chat` - WebSocket chat endpoint (preferred for web)
- `GET /session/{session_id}` - Get session state

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

`input_normalizer -> intent_router -> state_tracker -> policy_layer -> clarification / knowledge / tool / handoff -> response_generator -> context_compressor -> memory_writer`

## Intent Structure

Current backend intent structure uses "main intent + sub-intent", loaded from `config/intent_schemas.yml` and `config/intent_rules.yml`:

- `faq` -> `faq.general`
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

WebSocket `/ws/chat` continuously outputs:
- `status` - Processing status
- `intent` - Recognized intent
- `state` - Current state snapshot
- `trace` - Execution trace
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

Run tests with `pytest tests/` before committing changes. When adding new functionality, add corresponding test cases in the appropriate test file.

## Commit & Pull Request Guidelines
Recent history uses Conventional Commits, for example `docs(template): 补充多轮意图识别调研`. Follow `type(scope): summary` and keep scopes specific, such as `template`, `rag`, `agent`, `api`, `services`, `frontend`.

Pull requests should include:

- a short description of what changed and why
- impacted paths, such as `app/services/routing.py`
- screenshots only when UI or formatting changes materially

Stage only intended files and review `git diff --cached` before committing.

## Frontend Notes

- `frontend/` uses `Vue 3 + Vite + TypeScript + Pinia + Vue Router`
- Vite dev server proxies `/api` and `/ws` to `http://127.0.0.1:8000`
- Backend has CORS enabled for `http://127.0.0.1:5173` and `http://localhost:5173`
- Frontend console includes message flow, session state panel, turn trace history, and structured detail cards for orders/logistics/handoff
- WebSocket `/ws/chat` is preferred for real-time communication, with `POST /chat` as fallback
