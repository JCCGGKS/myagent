# 异步 I/O 与「pending 级联」问题梳理

本文梳理本项目的 I/O 异步化演进，重点还原「聊天接口 pending 导致后续接口都 pending」这一问题的
**发现过程、修复方案与底层原理**。文中另含一节说明它与「先落库再下发」是**两件不同的事**，避免混淆。

相关文档：`plans/full-async-plan.md`、`template/07_系统架构.md`。

---

## 1. 问题是怎么发现的

### 1.1 现象

用户反馈：发完一次聊天后，前端的 `pending` 标志一直为 `true`，导致**后续所有聊天请求都被拦住**——
表现为「聊天接口的 pending 导致后续接口都是 pending」。

### 1.2 前端的并发保护机制

`frontend/src/stores/chat.ts` 里 `pending` 是典型的单飞行（single-inflight）保护：

- `sendMessage` 入口用 `if (!message || pending.value) return;` 拦截（`chat.ts:469`），
  `pending.value = true` 在请求发出前置位（`chat.ts:479`）；
- 只有收到 `final`（`chat.ts` 约 452 行 `pending.value = false`）或 `error`（`chat.ts:409` `pending.value = false`）
  事件后，`pending` 才复位为 `false`。

也就是说：**只要 `final`/`error` 事件迟迟不到，`pending` 就一直是 `true`，后续点击发送全部被 guard 挡掉。**

### 1.3 诊断：事件循环被长调用阻塞

`/chat/stream` 后端是 `graph.astream` 异步生成器（`app/business/agent/graph.py:187`），本应边跑边把
`intent / state / tool_result / final` 事件逐一下发。但如果请求链路里存在**一个长耗时的同步调用直接跑在事件循环线程上**
（例如同步 LLM 客户端 `sync_client.create(...)`、或同步 DB 提交 `SessionLocal()` `commit()` 写在 `async def` 处理函数里，
没有 `await` 也没有 `to_thread` 卸载），它就会**一直占据事件循环线程**，期间：

- 其它协程（含把 `final` 回传、把 `pending` 置 `false` 的代码）全部暂停；
- 于是 `final` 迟迟不下发 → `pending` 不复位 → 后续发送被前端 guard 拦截；
- 同时后端新到的请求也得不到调度，表现为「都卡在 pending」。

结论：**根因不是前端逻辑错，而是后端某处「长同步调用阻塞了事件循环」，导致 final 永远迟到、pending 永远复位不了。**

---

## 2. 如何修复

修复目标是让请求链路里**没有任何调用长时间占据事件循环线程**，使 `final` 能按时下发、`pending` 及时复位。

### 2.1 M1：把阻塞调用移出事件循环线程 + LLM 异步化

- LLM 调用改用 `AsyncOpenAI`（原生异步，`chat.completions.create` 在 I/O 等待时让出循环，不占线程）；
- 同步 DAO / 同步第三方调用用 `asyncio.to_thread(...)` 丢到工作线程池执行，
  主事件循环线程在等待期间继续驱动其它协程。

这一步已经能消除「一次聊天卡住后续」的级联：长调用不再占住循环，循环始终能把 `final` 回传、把 `pending` 复位。

### 2.2 M2：DAO 换成原生异步会话，去掉 to_thread

M2 进一步把 DAO 层（`SessionStore` / `UserDAO` / `KnowledgeFileDAO`）整体换成 `AsyncSession`（aiomysql），
业务层直接 `await`，**不再需要 M1 的 `asyncio.to_thread` 线程桥接**（`app/business/dialog/session.py:7` 注释）。

- `app/model/__init__.py:78`：`AsyncSessionLocal = async_sessionmaker(bind=_async_engine, ...)`（有异步 engine 时非 `None`）；
- `app/dao/__init__.py:14`：注入 `AsyncSessionLocal`；为 `None` 时回退 `Memory*` 实现（进程内，本地/测试用）；
- `SqlSessionStore` 等用 `async with self._db() as db:` + `await db.commit()`，提交也真正让出循环。

至此，从 HTTP SSE 入口 → `AsyncOpenAI` → LangGraph `graph.astream` → 原生 `AsyncSession`，**全链路 I/O 都在等
待时让出事件循环**，没有任何一处会长时间占住循环线程。

### 2.3 效果

- LLM 生成与 DB 提交期间，循环照常服务其它协程；
- `final` 正常下发 → 前端 `pending.value = false`（`chat.ts` 约 452 行）→ 后续发送不再被 guard 挡掉；
- 不再出现「一次聊天卡住后续」的级联。

---

## 3. 底层原理

### 3.1 单线程事件循环 + 协作式多任务（底层是 I/O 多路复用）

Python `asyncio` 是**单线程 + 协作式多任务**：同一时刻只有一个协程在跑，遇到 I/O 时主动让出控制权。
而「一个线程如何同时盯着成百上千个连接而不阻塞」的底层引擎，正是 **I/O 多路复用**
（Linux 的 `epoll`、macOS 的 `kqueue`、Windows 的 IOCP，Python 经 `selectors` 模块封装）。

- **底层 = I/O 多路复用 (epoll/kqueue/select)**：当 `await sock.read()` 时，事件循环把该 socket 的 fd 注册进
  epoll 并挂起协程；OS 仅在 fd **就绪**时才唤醒循环——没有任何线程傻等在一个阻塞的 `recv()` 上。
  这正是「单线程撑多连接」的根本机制。
- **上层 = 协作式协程 (`await` 让出)**：开发者面对的模型。`await` 在 I/O 点把控制权交还循环，
  循环借此去驱动其它协程或轮询 epoll；I/O 完成后把结果交回，协程从 `await` 之后继续。
  → 循环始终可响应，`final` 能按时下发，`pending` 能按时复位。
- **阻塞同步调用（直接跑在循环线程）**：一个不 `await` 的长调用（如同步 LLM、同步 DB commit）会**占住循环线程整段时长**，
  绕过了多路复用路径——循环根本没机会走到 epoll 的就绪回调，所有其它协程暂停
  → 表现为 `final` 迟到、`pending` 不复位、新请求排队（即本文的级联现象）。
- **`asyncio.to_thread`（M1 方案）**：把阻塞工作丢到工作线程，循环线程继续跑其它协程（仍能走 epoll）。
  它解决了「占住循环」的问题，但本质仍是「借线程跑同步代码」。
- **原生异步驱动（M2，aiomysql / AsyncOpenAI）**：驱动本身支持 `await`，I/O 等待时直接让出循环、**无需线程切换**，
  是最干净的单循环并发模型。

> ⚠️ **epoll 只覆盖 I/O 等待，不覆盖 CPU 工作**：CPU 密集的长调用（重 JSON / 加密 / 解析）即便有 epoll 也会
> 独占单循环线程。因此真正阻塞 / CPU 重的步骤仍要 `to_thread` 或进程卸载；原生异步只救 I/O 等待。

### 3.2 为什么「长同步调用」会级联成 pending

`pending` 的复位依赖 `final` 事件到达前端；`final` 到达依赖后端把事件 yield 回 SSE 连接；这件事又依赖事件循环
能继续推进 `chat_events` 协程。一旦某处长同步调用占住循环，这条「yield → 下发 → 复位」的链条全断，于是：

```
长同步调用占住事件循环  →  final 迟迟 yield 不出来  →  前端 pending 不复位
→  sendMessage 的 guard 拦截后续所有发送  →  表现为「后续接口都 pending」
```

异步化把「占住循环」的调用变成「挂起并让出循环」，链条恢复，`pending` 及时复位，级联消失。

### 3.3 一句话总结

根因是请求链路里一处**长同步调用阻塞了事件循环**，使 `final` 迟到、前端 `pending` 永远复位不了，后续请求全被拦。
修复 = 让整条链路异步化（M1：`AsyncOpenAI` + `to_thread`；M2：原生 `AsyncSession`，去掉 `to_thread`），
使长 I/O 在等待时让出循环，`final` 按时下发、`pending` 及时复位，级联消失。

---

## 4. 与「先落库再下发」的区别（避免混淆）

「先落库再下发 final」（`graph.py:213` 先 `await message_service.persist(...)` 再 yield `final`）是**另一件独立的事**，
不是本次 pending 级联问题的源头：

- **本文问题（pending 级联）**：关注的是「长调用阻塞事件循环 → `pending` 不复位 → 后续请求被拦」，
  属于**并发/响应性**问题，靠全链路异步化解决。
- **先落库再下发**：关注的是「客户端已收到回复、但 DB 尚未落库」的**崩溃窗口 / 数据持久性**问题，
  靠把 `persist` 的 `await` 排在 `final` yield 之前解决。

两者都建立在「`await` 即顺序保证」这一共同基础上，但动机不同：**一个为了不被卡住，一个为了不丢数据。**
