# myagent

客服 Agent MVP 骨架，提供基于 `FastAPI` 的对话接口，以及 `FAQ / 订单查询 / 物流查询 / 转人工` 四条最小闭环能力。当前仓库已拆分为 `FastAPI` 后端和 `Vue 3 + Vite + TypeScript` 前端。

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
- 多轮槽位补齐

当前版本使用本地 mock 数据，不依赖真实数据库、Redis 或外部业务系统。

## Frontend Notes

- `frontend/` 使用 `Vue 3 + Vite + TypeScript + Pinia + Vue Router`
- Vite 开发服务通过 `/api` 和 `/ws` 代理到 `http://127.0.0.1:8000`
- 后端已开放 `http://127.0.0.1:5173` 和 `http://localhost:5173` 的 CORS
- 前端控制台包含消息流、会话状态面板、轮次 Trace 历史，以及订单/物流/转人工的结构化详情卡片
- `/chat` 返回除了文本回复外，还包含 `tool_result`、`session_state` 和 `turn_trace`，便于前端直接渲染调试信息
- Web 端对话默认优先使用 `WebSocket /ws/chat`，由 Vite 转发到后端，实时接收 `status / intent / state / trace / tool_result / final` 事件
- `POST /chat` 仍然保留，作为 WebSocket 不可用时的回退通道
