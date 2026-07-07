# myagent

客服 Agent MVP 骨架，提供基于 `FastAPI` 的对话接口，以及 `FAQ / 订单查询 / 物流查询 / 退款咨询 / 转人工 / 问候` 六条最小闭环能力。当前仓库已拆分为 `FastAPI` 后端和 `Vue 3 + Vite + TypeScript` 前端。

## Quick Start

后端：

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload
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

- `GET /health`
- `POST /chat`
- `WS /ws/chat`
- `GET /session/{session_id}`

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

- FAQ 问答
- 订单状态查询
- 物流状态查询
- 退款规则咨询
- 转人工
- 问候闲聊
- 多轮槽位补齐
- 主意图切换后的状态冻结与槽位继承
- 结构化上下文压缩与工具审计日志

当前后端意图结构已升级为“主意图 + 子意图”，例如：

- `faq` -> `faq.general`
- `order_service` -> `order_service.query_status`
- `logistics_service` -> `logistics_service.query_status`
- `refund_service` -> `refund_service.consult_policy`
- `refund_service` -> `refund_service.request_refund`
- `handoff_service` -> `handoff_service.request_human`
- `chitchat` -> `chitchat.greeting`
- `chitchat` -> `chitchat.thanks`
- `unsupported` -> `unsupported.unknown`

当前版本使用本地 mock 数据，不依赖真实数据库、Redis 或外部业务系统。

当前后端执行链与 `template/06.1-06.4`、`template/07` 对齐为：

`input_normalizer -> intent_router -> state_tracker -> policy_layer -> clarification / knowledge / tool / handoff -> response_generator -> context_compressor -> memory_writer`

## Project Structure

```text
myagent/
├── app/
│   ├── agents/      # 客服主 Agent，仅负责编排节点
│   ├── api/         # FastAPI / WebSocket 入口
│   ├── config/      # 配置加载
│   ├── mock_data/   # FAQ、订单、物流 mock 数据
│   ├── models/      # 请求、响应、会话、领域模型
│   ├── prompts/     # LLM prompt 定义
│   ├── services/    # FAQ / 路由 / 状态 / 策略 / 对话 / 执行 / 上下文服务
│   ├── store/       # 会话状态存储、工具审计、handoff 记录
│   └── utils/       # 文件与文本工具函数
├── config/          # test / prod / local yml 配置文件
├── eval/            # 单点评估脚本、样本、评估报告
├── frontend/        # Vue 3 前端
├── tests/           # 后端单元测试
├── wiki/            # 设计文档
├── template/        # 调研与草稿材料
├── main.py          # 后端启动入口
└── README.md
```

后端模块职责：

- `app/api`: 对外暴露 HTTP 和 WebSocket 接口，负责应用装配
- `app/agents`: 串联意图识别、状态更新、策略分发、FAQ/工具路由、澄清与回复生成
- `app/models`: 统一维护 `ChatRequest`、`ChatResponse`、`ConversationState` 等数据结构
- `app/services/domain`: FAQ 检索、订单查询、物流查询、转人工能力
- `app/services/routing`: 意图路由、状态跟踪、策略层
- `app/services/dialog`: 澄清回复、最终回复、memory 持久化
- `app/services/execution`: 知识检索、业务工具调用、转人工执行
- `app/services/context`: 最近消息窗口和 `running_summary` 压缩
- `app/services/intent_schema`: 主意图 `slot schema` 和规则关键词 registry，默认从 YAML 加载
- `app/config`: 负责读取 `APP_ENV` 对应配置并叠加本地覆盖
- `app/prompts`: 独立管理 LLM 相关 prompt，便于查看和迭代
- `app/store`: 当前使用内存版 `sessions / messages / state_snapshots / tool_calls / handoff_records`
- `app/utils/state`: `action_history` 等状态辅助函数

## State Model

当前 `ConversationState` 已覆盖两层上下文：

- 业务状态：`current_main_intent / current_sub_intent / stage / slots / missing_slots / confirmed_slots`
- 执行状态：`current_action / latest_action_result / action_history / running_summary / archived_states`

当前 `ws/chat` 会持续输出：

- `status`
- `intent`
- `state`
- `trace`
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
- Vite 开发服务通过 `/api` 和 `/ws` 代理到 `http://127.0.0.1:8000`
- 后端已开放 `http://127.0.0.1:5173` 和 `http://localhost:5173` 的 CORS
- 前端控制台包含消息流、会话状态面板、轮次 Trace 历史，以及订单/物流/转人工的结构化详情卡片
- `/chat` 返回除了文本回复外，还包含 `tool_result`、`session_state` 和 `turn_trace`，便于前端直接渲染调试信息
- Web 端对话默认优先使用 `WebSocket /ws/chat`，由 Vite 转发到后端，实时接收 `status / intent / state / trace / tool_result / final` 事件
- `POST /chat` 仍然保留，作为 WebSocket 不可用时的回退通道
