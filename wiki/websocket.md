# WebSocket 简述

## 为什么用 WebSocket

这个项目的前端需要实时收到对话处理过程中的中间事件，例如：

- 消息已接收
- 意图识别结果
- 槽位状态
- 路由结果
- 工具调用结果
- 最终回复

`HTTP` 只能方便地拿最终结果，`SSE` 更适合单向流式输出，`WebSocket` 更适合这种持续双向对话。

## 底层原理

`WebSocket` 仍然建立在 `TCP` 之上。

建立连接时，浏览器会先发起一次带 `Upgrade: websocket` 的 HTTP 请求。服务端如果接受，会返回 `101 Switching Protocols`。从这一刻开始，连接从 HTTP 切换为 WebSocket 长连接。

后续双方不再按“请求一次、响应一次”的方式工作，而是在同一个连接上双向发送数据帧。

## 当前项目的连接链路

当前链路是：

1. 浏览器打开前端页面 `http://127.0.0.1:5173`
2. 前端连接 `ws://127.0.0.1:5173/ws/chat`
3. Vite 将 `/ws/chat` 代理到 `ws://127.0.0.1:8000/ws/chat`
4. FastAPI 在 `/ws/chat` 上执行 `accept()`
5. 前后端在同一个长连接上持续通信

所以前端看起来连的是 `5173`，真正处理业务的是 `8000`。

## 项目中的实现位置

- 前端建连：`frontend/src/lib/websocket.ts`
- 前端触发连接：`frontend/src/stores/chat.ts`
- Vite 代理：`frontend/vite.config.ts`
- 后端入口：`app/api.py`
- 事件生成：`app/agent.py`

## 当前消息流

前端发送：

```json
{
  "session_id": "web-xxx",
  "user_id": "user-001",
  "channel": "web",
  "message": "帮我查一下订单 A1001"
}
```

后端按阶段返回：

- `status`
- `intent`
- `state`
- `trace`
- `tool_result`
- `final`

这样前端不仅能显示最终回复，还能显示处理过程。

## 和 HTTP、SSE 的区别

- `HTTP`：一问一答，适合普通接口
- `SSE`：服务端单向推送，适合流式文本输出
- `WebSocket`：双向长连接，适合多轮实时对话

## 当前方案的优点

- 一条连接支持多轮消息
- 可以实时展示 Agent 中间状态
- 适合后续扩展取消、心跳、人工接管等事件
- 保留了 `/chat` 作为回退接口

## 常见排查点

- 后端是否启动：`uvicorn main:app --reload`
- 前端是否通过 Vite 启动：`cd frontend && npm run dev`
- `vite.config.ts` 中 `/ws` 代理是否存在且开启 `ws: true`
- 浏览器当前访问的 host 是否和预期一致

## 一句话总结

这个项目里的 `WebSocket`，本质上是先通过 HTTP Upgrade 建立长连接，再在同一个 TCP 连接上双向发送对话事件流。
