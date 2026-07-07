# myagent

客服 Agent MVP 骨架，提供基于 `FastAPI` 的对话接口，以及 `FAQ / 订单查询 / 物流查询 / 转人工 / 问候` 五条最小闭环能力。当前仓库已拆分为 `FastAPI` 后端和 `Vue 3 + Vite + TypeScript` 前端。

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
- 转人工
- 问候闲聊
- 多轮槽位补齐

当前后端意图结构已升级为“主意图 + 子意图”，例如：

- `faq` -> `faq.general`
- `order_service` -> `order_service.query_status`
- `logistics_service` -> `logistics_service.query_status`
- `handoff_service` -> `handoff_service.request_human`
- `chitchat` -> `chitchat.greeting`
- `unsupported` -> `unsupported.unknown`

当前版本使用本地 mock 数据，不依赖真实数据库、Redis 或外部业务系统。

## Project Structure

```text
myagent/
├── app/
│   ├── agents/      # 客服主 Agent、状态流转、路由编排
│   ├── api/         # FastAPI / WebSocket 入口
│   ├── config/      # 配置加载
│   ├── mock_data/   # FAQ、订单、物流 mock 数据
│   ├── models/      # 请求、响应、会话、领域模型
│   ├── prompts/     # LLM prompt 定义
│   ├── services/    # FAQ / 订单 / 物流 / 转人工 / LLM 兜底服务
│   └── store/       # 会话状态存储
├── config/          # test / prod / local yml 配置文件
├── eval/            # 单点评估脚本、样本、评估报告
├── frontend/        # Vue 3 前端
├── wiki/            # 设计文档
├── template/        # 调研与草稿材料
├── main.py          # 后端启动入口
└── README.md
```

后端模块职责：

- `app/api`: 对外暴露 HTTP 和 WebSocket 接口，负责应用装配
- `app/agents`: 串联意图识别、状态更新、FAQ/工具路由、澄清与回复生成
- `app/models`: 统一维护 `ChatRequest`、`ChatResponse`、`ConversationState` 等数据结构
- `app/services`: 承载 FAQ 检索、订单查询、物流查询、转人工、LLM fallback 等能力
- `app/config`: 负责读取 `APP_ENV` 对应配置并叠加本地覆盖
- `app/prompts`: 独立管理 LLM 相关 prompt，便于查看和迭代
- `app/store`: 当前使用内存会话存储，后续可替换为 Redis 或数据库

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
