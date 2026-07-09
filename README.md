# myagent

客服 Agent MVP 骨架，提供基于 `FastAPI` 的对话接口，以及 `订单查询 / 物流查询 / 退款咨询 / 转人工 / 问候` 五条最小闭环能力。当前仓库已拆分为 `FastAPI` 后端和 `Vue 3 + Vite + TypeScript` 前端。

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

后端接口：

- `POST /chat`
- `POST /chat/init` - 创建会话
- `POST /chat/stream` - SSE 流式对话（Web 端首选）
- `POST /auth/register` / `POST /auth/login` / `POST /auth/forgot-password` / `POST /auth/reset-password` / `POST /auth/change-password`
- `POST /knowledge/upload` - 知识库上传
- `GET /rag/config` / `PUT /rag/config`

示例请求：

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

## Current Scope

- 订单状态查询
- 物流状态查询
- 退款规则咨询
- 转人工
- 问候闲聊
- 多轮槽位补齐
- 主意图切换后的状态冻结与槽位继承
- 结构化上下文压缩与工具审计日志

当前后端意图结构已升级为“主意图 + 子意图”，例如：

- `order_service` -> `order_service.query_status`
- `logistics_service` -> `logistics_service.query_status`
- `refund_service` -> `refund_service.consult_policy`
- `refund_service` -> `refund_service.request_refund`
- `handoff_service` -> `handoff_service.request_human`
- `chitchat` -> `chitchat.greeting`
- `chitchat` -> `chitchat.thanks`
- `unsupported` -> `unsupported.unknown`

当前版本默认使用内存实现（`MemorySessionStore` / `MemoryUserDAO`），配置了 `mysql` 段即自动切换到 `SqlSessionStore` / `SqlUserDAO` 落 MySQL；向量库走 `app.pkgs.vector` 的 qdrant 客户端。测试通过依赖注入用 sqlite 内存库隔离。

当前后端执行链与 `template/06.1-06.4`、`template/07` 对齐为：

`input_normalizer -> intent_router -> state_tracker -> policy_layer -> clarification / tool / handoff -> response_generator -> context_compressor -> memory_writer`

## Project Structure

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

后端模块职责：

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
  - `business/rag`: 知识检索（chunker / ingestion / sparse_bm25 / retrieval_strategy / rerank）
  - `business/tools`: 工具层，封装供 LLM 调用的业务工具（如 `rag_tool.py` 的 `RagRetrieveTool` 检索工具）；依赖 `rag` 子包
  - `business/prompts`: LLM prompt 定义（intent 等）
  - `business/auth`: 认证业务（service / router / models / deps），依赖 `UserDAO` 依赖注入
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

## State Model

当前 `ConversationState` 已覆盖两层上下文：

- 业务状态：`current_main_intent / current_sub_intent / stage / slots / missing_slots / confirmed_slots`
- 执行状态：`current_action / latest_action_result / action_history / running_summary / archived_states`

当前 `POST /chat/stream` 会持续输出 SSE 事件：

- `intent`
- `state`
- `tool_result`
- `final`

## Intent Schema Config

主意图对应的 `slot schema` 已外置到：

- `config/intent_schemas.yml`
- `config/intent_rules.yml`
- `config/clarification_prompts.yml`
- `config/response_prompts.yml`

当前 `StateTrackerService` 会通过 `IntentSchemaRegistry` 读取 `intent_schemas.yml`，用于：

- 计算 `required_slots`
- 控制 `inheritable` 槽位继承
- 统一 `clarification_order` 等配置入口

当前 `IntentRouterService` 会通过 `IntentRuleRegistry` 读取 `intent_rules.yml`，用于：

- 主意图规则关键词命中
- `refund_action / refund_rule / greeting / thanks` 等子分支规则
- 情绪规则关键词命中

当前 `ClarificationService` 会通过 `ClarificationPromptRegistry` 读取 `clarification_prompts.yml`，用于：

- 意图澄清统一文案
- 不同主意图的缺槽追问文案
- 通用 fallback 澄清文案

当前 `ResponseService` 会通过 `ResponsePromptRegistry` 读取 `response_prompts.yml`，用于：

- 闲聊和兜底客服话术
- 退款确认文案
- 订单 / 物流 / 转人工模板化回复

## LLM Fallback Config

LLM 兜底配置按环境拆分：

- `config/llm_config.test.yml`
- `config/llm_config.prod.yml`
- `config/llm_config.local.yml`

加载顺序：

1. 读取 `APP_ENV` 对应的基线配置，默认 `test`
2. 如果存在 `config/llm_config.local.yml`，再用本地配置覆盖

`llm_config.local.yml` 已加入 `.gitignore`，适合放本机 key 和中转站地址。

示例字段：

- `enabled`
- `api_key`
- `model`
- `base_url`
- `timeout_seconds`
- `confidence_threshold`

## Frontend Notes

- `frontend/` 使用 `Vue 3 + Vite + TypeScript + Pinia + Vue Router`
- Vite 开发服务通过 `/api` 和 `/chat/stream` 代理到 `http://127.0.0.1:8000`
- 后端已开放 `http://127.0.0.1:5173` 和 `http://localhost:5173` 的 CORS
- 前端控制台包含消息流、会话状态面板、轮次 Trace 历史，以及订单/物流/转人工的结构化详情卡片
- `/chat` 返回除了文本回复外，还包含 `tool_result`、`session_state` 和 `turn_trace`，便于前端直接渲染调试信息
- Web 端对话默认优先使用 SSE `POST /chat/stream`，由 Vite 转发到后端，实时接收 `intent / state / tool_result / final` 事件
- `POST /chat` 仍然保留，作为 SSE 不可用时的回退通道
- 前端使用 `ChatSSEClient`（`frontend/src/lib/sse.ts`）配合 `AbortController` 支持用户中途打断
