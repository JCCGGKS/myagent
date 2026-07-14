from __future__ import annotations

import asyncio
import inspect
import json
import logging
import os
import uuid
from collections.abc import AsyncGenerator, Awaitable
from typing import Any, Callable

from app.schema import ChatRequest, ChatResponse, ConversationState
from app.utils.module_logger import _tagged, get_module_logger

# 分模块 logger：落入 logs/graph-*.log（同时冒泡控制台），阶段标签经 _tag 注入 [stage] 前缀。
logger = get_module_logger("graph")


def _tag(stage: str, msg: str) -> str:
    """给日志加 pipeline 阶段标签，形如 `[intent] ...`，便于按阶段检索/归类。

    阶段取值：input / intent / state / policy / clarification / agent / handoff /
    response / compressor / tool / persist / agent。
    """
    return _tagged(stage, msg)
from app.business.agent.agent_node import AgentNodeService
from app.business.tools.tool_executor import ToolExecutor
from app.business.tools.registry import build_tool_schemas
from app.business.tools.confirmation import classify_confirm_signal
from app.business import (
    ClarificationService,
    ContextService,
    HandoffClarificationPolicy,
    HandoffService,
    IntentRouterService,
    IntentSchemaRegistry,
    LLMIntentFallbackService,
    LogisticsService,
    MessageService,
    OrderService,
    RefundService,
    ResponseService,
    StateTrackerService,
)
from app.business.dialog import SessionService
from app.config.context_config import get_context_config_service
from app.config.checkpoint_config import get_checkpoint_config_service
from app.utils import normalize_whitespace, observe_low_confidence

try:
    from langgraph.graph import END, START, StateGraph
except ImportError:  # pragma: no cover
    END = "END"
    START = "START"
    StateGraph = None

from langgraph.checkpoint.memory import MemorySaver


def _make_summary_fold_fn(
    llm_client: Any | None,
    llm_model: str | None,
    llm_config: Any | None = None,
) -> Callable[[str, list[dict]], Awaitable[str]] | None:
    """构造摘要折叠器（异步）：把已有摘要与新增溢出消息合并为一段连贯摘要。

    无 LLM 客户端时返回 None，由 ContextService 退化为拼接截断。
    生成参数（thinking 等）沿用 LLMConfig，避免压缩步骤触发思维链推理。
    """
    extra_body = None
    if llm_config is not None and getattr(llm_config, "enable_thinking", None) is not None:
        extra_body = {"enable_thinking": llm_config.enable_thinking}

    async def fold(old_summary: str, overflow: list[dict]) -> str:
        new_text = "\n".join(
            f"{m.get('role', '')}: {m.get('content', '')}"
            for m in overflow
            if m.get("content")
        )
        messages = [
            {
                "role": "system",
                "content": "你负责压缩客服对话，输出简洁中文摘要，保留关键实体与未决问题。",
            },
            {
                "role": "user",
                "content": (
                    "请把「已有摘要」与「新增对话片段」合并为一段连贯摘要，"
                    "保留用户意图、订单号/物流单号等关键实体、已解决与未解决的问题；"
                    "不要逐条罗列，不要编造新信息。\n\n"
                    f"已有摘要：\n{old_summary or '(无)'}\n\n"
                    f"新增对话片段：\n{new_text}"
                ),
            },
        ]
        try:
            resp = await llm_client.chat.completions.create(
                model=llm_model, messages=messages, **(extra_body or {})
            )
            summary = resp.choices[0].message.content or ""
            return summary.strip()
        except Exception as exc:  # noqa: BLE001
            logger.warning(_tag("infra", "summary fold LLM call failed err=%r"), exc)
            return ""

    if llm_client is None or not llm_model:
        return None
    return fold


class CustomerServiceAgent:
    def __init__(
        self,
        store: SessionService,
        order_service: OrderService,
        logistics_service: LogisticsService,
        handoff_service: HandoffService,
        refund_service: RefundService | None = None,
        llm_fallback_service: LLMIntentFallbackService | None = None,
        llm_client: Any | None = None,
        llm_model: str | None = None,
        llm_config: Any | None = None,
        event_store: Any | None = None,
    ) -> None:
        self.store = store
        self.order_service = order_service
        self.logistics_service = logistics_service
        self.handoff_service = handoff_service
        self.intent_schema_registry = IntentSchemaRegistry()
        self.intent_router_service = IntentRouterService(llm_fallback_service=llm_fallback_service)
        self.state_tracker_service = StateTrackerService(schema_registry=self.intent_schema_registry)
        self.policy_service = HandoffClarificationPolicy()
        self.clarification_service = ClarificationService(
            llm_client=llm_client,
            llm_model=llm_model,
            llm_config=llm_config,
        )
        context_config = get_context_config_service().get_config()
        self.context_service = ContextService(
            state_tracker=self.state_tracker_service,
            max_recent_messages=context_config.max_recent_messages,
            max_summary_chars=context_config.max_summary_chars,
            summarizer=_make_summary_fold_fn(llm_client, llm_model, llm_config),
        )
        self.response_service = ResponseService(
            llm_client=llm_client,
            llm_model=llm_model,
            llm_config=llm_config,
        )
        self.message_service = MessageService(store, event_store=event_store)
        # 统一工具执行服务（覆盖 LLM 函数调用工具与业务工具）
        self.tool_executor = ToolExecutor(
            order_service=order_service,
            logistics_service=logistics_service,
            handoff_service=handoff_service,
            refund_service=refund_service,
        )
        # agent_node 初始化（工具编排节点）
        self.agent_node_service = AgentNodeService(
            llm_client=llm_client,
            llm_model=llm_model,
            tool_executor=self.tool_executor,
            tools=build_tool_schemas(),  # 注册全部工具 schema 到 LLM function calling
            llm_config=llm_config,
        )
        # langgraph 为硬依赖：不可用时显式报错
        if StateGraph is None:
            raise RuntimeError(
                "LangGraph is required for agent orchestration; please install langgraph."
            )
        # 图态持久化层（checkpointer）：优先 Redis，未配置时回退进程内 MemorySaver。
        # 具体 choice 见 _build_checkpointer；Redis 路径需 langgraph-checkpoint-redis
        # + redis 已安装且 REDIS_URL 已配置。
        #
        # 关键：AsyncRedisSaver 构造依赖运行中的事件循环（其内部调用
        # asyncio.get_running_loop），而本服务在模块导入期（无事件循环）就构造
        # CustomerServiceAgent（见 app/api/chat.py 模块级 agent），故 checkpointer
        # 不能在此同步构建，改为首次异步请求时惰性构建（_ensure_checkpointer），
        # 此处先以无 checkpointer 占位编译图，惰性构建完成后再重编译。
        self.checkpointer = None
        self._cp_ready = False
        self._cp_lock = asyncio.Lock()
        self.graph = self._build_graph()

    def _build_graph(self) -> Any:
        if StateGraph is None:
            return None

        builder = StateGraph(dict)
        builder.add_node("input_normalizer", self.input_normalizer)
        builder.add_node("confirmation_guard", self.confirmation_guard)
        builder.add_node("intent_router", self.intent_router)
        builder.add_node("state_tracker", self.state_tracker)
        builder.add_node("policy_layer", self.policy_layer)
        builder.add_node("clarification_node", self.clarification_node)
        builder.add_node("agent_node", self.agent_node)
        builder.add_node("handoff_node", self.handoff_node)
        builder.add_node("response_generator", self.response_generator)
        builder.add_node("context_compressor", self.context_compressor)

        builder.add_edge(START, "input_normalizer")
        # confirmation_guard 优先于意图路由：若上一轮挂起了 R1 二次确认，
        # 本轮「确认/取消」需被确定性拦截，不能当新意图交 LLM 自由函数调用（见 06_工具调用）。
        builder.add_edge("input_normalizer", "confirmation_guard")
        builder.add_conditional_edges(
            "confirmation_guard",
            self.route_after_confirmation_guard,
            {
                "normal": "intent_router",
                "handled": "response_generator",
            },
        )
        builder.add_edge("intent_router", "state_tracker")
        builder.add_edge("state_tracker", "policy_layer")
        builder.add_conditional_edges(
            "policy_layer",
            self.route_after_policy,
            {
                "clarification_node": "clarification_node",
                "agent_node": "agent_node",
                "handoff_node": "handoff_node",
                "response_generator": "response_generator",
            },
        )
        builder.add_edge("clarification_node", "context_compressor")
        # agent_node 执行完后，路由到 response_generator
        builder.add_edge("agent_node", "response_generator")
        builder.add_edge("handoff_node", "response_generator")
        builder.add_edge("response_generator", "context_compressor")
        builder.add_edge("context_compressor", END)
        return builder.compile(checkpointer=self.checkpointer)

    def _build_checkpointer(self) -> Any:
        """构造图态持久化层（checkpointer）。

        优先级：配置了 ``REDIS_URL`` 且 ``langgraph-checkpoint-redis`` + ``redis`` 可用
        → ``AsyncRedisSaver``（跨重启 / 跨 worker 真持久化）；否则回退进程内
        ``MemorySaver``（dev / 测试 / 无 Redis 环境，行为等价于原内存态，但不跨重启）。

        Redis 路径为**显式 opt-in**（需设置环境变量），避免无服务器时连接阻塞。
        """
        redis_url = os.getenv("REDIS_URL") or os.getenv("AGENT_REDIS_URL")
        if not redis_url:
            return MemorySaver()
        try:
            from langgraph.checkpoint.redis.aio import AsyncRedisSaver
        except ImportError:
            logger.warning(
                "REDIS_URL set but langgraph-checkpoint-redis/redis not installed; "
                "falling back to MemorySaver."
            )
            return MemorySaver()
        try:
            # 直接传 redis_url 字符串（让 AsyncRedisSaver 内部惰性建 client）；
            # 不要预先构造 redis.asyncio.Redis，否则其 __init__ 也会要求运行中的事件循环。
            # TTL：0 / 不配置 → None（不过期）；>0 → 传给 saver，活跃会话每轮落库刷新过期时间。
            ttl = get_checkpoint_config_service().get_config().ttl_seconds
            redis_ttl = ttl if ttl and ttl > 0 else None
            return AsyncRedisSaver(
                redis_url=redis_url,
                ttl=redis_ttl,
                connection_args={"socket_connect_timeout": 3, "socket_timeout": 3},
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(_tag("infra", "Redis saver init failed, fallback MemorySaver: %r"), exc)
            return MemorySaver()

    async def _ensure_checkpointer(self) -> None:
        """惰性构建 checkpointer 并（重）编译图。

        AsyncRedisSaver 构造依赖运行中的事件循环，而 agent 在导入期（无循环）创建，
        故延到首次异步请求时在此（已有事件循环）构建，并据此重编译图。

        若 Redis setup 失败（如服务器不可用），回退 MemorySaver 并重新编译图。
        用锁保证并发首请求只构建一次。
        """
        if self._cp_ready:
            return
        async with self._cp_lock:
            if self._cp_ready:
                return
            self.checkpointer = self._build_checkpointer()
            self.graph = self._build_graph()
            setup_fn = getattr(self.checkpointer, "setup", None)
            if setup_fn is not None and inspect.iscoroutinefunction(setup_fn):
                try:
                    await self.checkpointer.setup()
                except Exception as exc:  # noqa: BLE001
                    logger.warning(_tag("infra", "checkpointer setup failed, fallback MemorySaver: %r"), exc)
                    self.checkpointer = MemorySaver()
                    self.graph = self._build_graph()
            self._cp_ready = True

    async def clear_checkpoint(self, thread_id: str) -> None:
        """删除某会话在 checkpointer 中的图态快照（会话删除时清理 Redis key）。

        - Redis（AsyncRedisSaver）：``adelete_thread`` 清掉该 ``thread_id`` 的全部 checkpoint，
          避免软删会话后 Redis key 成为孤儿、或被复用同 ``session_id`` 时复活旧图态。
        - MemorySaver：进程内 dict 删除；若 checkpointer 尚未惰性构建则先构建。
        - 未配置 Redis（回退 MemorySaver）或清理失败：仅记日志，不阻断删除主流程。
        """
        await self._ensure_checkpointer()
        checkpointer = self.checkpointer
        if checkpointer is None:
            return
        delete_fn = getattr(checkpointer, "adelete_thread", None)
        if delete_fn is not None and inspect.iscoroutinefunction(delete_fn):
            try:
                await delete_fn(thread_id)
                logger.info(_tag("infra", "checkpoint cleared thread=%s"), thread_id)
            except Exception as exc:  # noqa: BLE001
                logger.warning(_tag("infra", "checkpoint clear failed thread=%s err=%r"), thread_id, exc)
            return
        sync_delete = getattr(checkpointer, "delete_thread", None)
        if sync_delete is not None:
            try:
                sync_delete(thread_id)
                logger.info(_tag("infra", "checkpoint cleared thread=%s"), thread_id)
            except Exception as exc:  # noqa: BLE001
                logger.warning(_tag("infra", "checkpoint clear failed thread=%s err=%r"), thread_id, exc)

    async def chat(self, request: ChatRequest, user_id: int, trace_id: str | None = None) -> ChatResponse:
        trace_id = trace_id or uuid.uuid4().hex
        logger.info(_tag("agent", "chat start session=%s user=%s trace_id=%s message=%r"), request.session_id, user_id, trace_id, request.message[:80])
        state = await self._execute_request(request, user_id)
        # 边界落库：图运行期间只收集数据，结束后批量写入会话存储。
        # 落库失败绝不影响回复返回——避免「LLM 已生成答案但用户收不到」的 UX 事故。
        try:
            state = await self.message_service.persist(state, request)
        except Exception as exc:
            logger.error(
                _tag("persist", "failed session=%s user=%s err=%r"),
                request.session_id, user_id, exc,
            )
        # 事件流落库（best-effort）：非流式仅落 final 事件；完整决策链由 SSE 路径记录。
        final_event = {"type": "final", "trace_id": trace_id, "response": self._build_chat_response(state).model_dump()}
        await self.message_service.persist_events(request.session_id, trace_id, [final_event])
        logger.info(
            _tag("agent", "chat done session=%s user=%s trace_id=%s intent=%s.%s action=%s"),
            request.session_id, user_id, trace_id,
            state.current_main_intent, state.current_sub_intent, state.current_action,
        )
        return self._build_chat_response(state)

    async def chat_events(
        self, request: ChatRequest, user_id: int, trace_id: str | None = None
    ) -> "AsyncGenerator[dict[str, Any], None]":
        """LangGraph 图驱动的事件生成（与 chat() 行为一致，异步生成器）。

        使用 ``graph.astream`` 按节点分块产出事件，I/O 等待时让出事件循环，
        避免单请求阻塞整个事件循环（详见 plans/full-async-plan.md）。

        落库顺序：图运行期间实时下发 intent/state/tool_result 等事件；
        **final 事件在落库之后才下发**——先 ``persist``（用户消息 + 助手回复 +
        状态快照）再 yield ``final``，避免「客户端已收到回复但 DB 尚未落库」的
        窗口（进程在二者间崩溃会导致上下文丢失）。若图未走到 response_generator
        （如澄清分支）则不产生 final 事件，落库仍照常进行。

        落库与回复解耦：``persist`` 用 ``try/except`` 隔离，**失败仅记服务端日志，
        绝不阻塞 ``final`` 下发**。客服场景下「LLM 已答出但用户收不到」比
        「回复展示了但没存进库」严重得多，故存储故障只应造成审计/上下文丢失，
        不应阻断回复。

        事件流（event_log）落库：本轮所有事件收集后随 final 一起批量落库，
        best-effort，失败仅记日志，不阻断回复。回放时按 trace_id 还原决策链。
        """
        trace_id = trace_id or uuid.uuid4().hex
        payload = await self._build_payload(request, user_id)
        config = {"configurable": {"thread_id": request.session_id}}
        final_state: ConversationState | None = None
        collected: list[dict[str, Any]] = []
        async for chunk in self.graph.astream(payload, config=config):
            for node_name, node_payload in chunk.items():
                # node_payload is the full payload dict: {"state": ..., "request": ...}
                state = node_payload.get("state") if isinstance(node_payload, dict) else node_payload
                if state:
                    final_state = state
                    for ev in self._node_state_to_events(node_name, state, trace_id):
                        # final 需先落库再下发，故此处暂不下发，留待落库后统一 yield
                        if ev.get("type") == "final":
                            continue
                        collected.append(ev)
                        yield ev
        # 边界落库：先持久化（用户消息 + 助手回复 + 状态快照），再下发 final 事件。
        # 落库失败绝不影响回复下发——异常被隔离，final 始终必达（见方法 docstring）。
        if final_state is not None:
            final_event = {
                "type": "final",
                "trace_id": trace_id,
                "response": self._build_chat_response(final_state).model_dump(),
            }
            try:
                await self.message_service.persist(final_state, request)
            except Exception as exc:  # 落库异常隔离，保证 final 必达
                logger.error(
                    _tag("persist", "failed session=%s user=%s err=%r"),
                    request.session_id, user_id, exc,
                )
            # 事件流落库（best-effort）：含已下发的 intent/state/tool_result + final
            await self.message_service.persist_events(request.session_id, trace_id, collected + [final_event])
            yield final_event

    def _node_state_to_events(
        self, node_name: str, state: ConversationState, trace_id: str | None = None
    ) -> list[dict[str, Any]]:
        """将节点执行后的状态转为事件列表（供 chat_events 和 graph.stream 共用）。"""
        events: list[dict[str, Any]] = []
        if node_name == "intent_router":
            intent = state.intent_result
            main_intent = intent.main_intent if intent else "unrecognize"
            confidence = intent.confidence if intent else 0.0
            needs_clarification = intent.needs_clarification if intent else False
            # 业务 KPI：低置信度 / 需澄清计数
            if needs_clarification or confidence < 0.5:
                observe_low_confidence()
            events.append(
                {
                    "type": "intent",
                    "trace_id": trace_id,
                    "main_intent": main_intent,
                    "sub_intent": intent.sub_intent if intent else "unrecognize.unknown",
                    "confidence": confidence,
                    "slots": intent.slots if intent else {},
                    "needs_clarification": needs_clarification,
                }
            )
        elif node_name == "state_tracker":
            events.append(
                {
                    "type": "state",
                    "trace_id": trace_id,
                    "stage": state.stage,
                    "current_main_intent": state.current_main_intent,
                    "current_sub_intent": state.current_sub_intent,
                    "slots": state.slots,
                    "missing_slots": state.missing_slots,
                    "needs_clarification": state.needs_clarification,
                }
            )
        elif node_name in {"handoff_node", "agent_node"}:
            if state.tool_result:
                events.append(
                    {"type": "tool_result", "trace_id": trace_id, "tool_result": self._serialize_tool_result(state)}
                )
        elif node_name == "response_generator":
            events.append({"type": "final", "trace_id": trace_id, "response": self._build_chat_response(state).model_dump()})
        # 其他节点不推事件（或推通用 trace）
        return events

    async def _execute_request(self, request: ChatRequest, user_id: int) -> ConversationState:
        payload = await self._build_payload(request, user_id)
        config = {"configurable": {"thread_id": request.session_id}}
        payload = await self.graph.ainvoke(payload, config=config)
        return payload["state"]

    async def _build_payload(self, request: ChatRequest, user_id: int) -> dict[str, Any]:
        # 图态从 checkpointer 按 thread_id（= session_id）恢复，替代原 store.get 读内存态。
        # 无历史（新会话 / 老会话 / Redis 清空）→ get_state/aget_state 返回 None → 新建空 state。
        await self._ensure_checkpointer()
        config = {"configurable": {"thread_id": request.session_id}}
        # 两套 saver 接口相反：MemorySaver 仅实现同步 get_tuple（用 graph.get_state）；
        # AsyncRedisSaver 仅实现异步 aget_tuple（用 graph.aget_state，同步会报
        # InvalidStateError）。按 checkpointer 是否具备 aget_tuple 分发。
        # 注意：aget_state/get_state 是 graph 的方法，能力判断要看 checkpointer 的
        # aget_tuple/get_tuple。
        if self.checkpointer is not None and hasattr(self.checkpointer, "aget_tuple"):
            snap = await self.graph.aget_state(config)
        else:
            snap = self.graph.get_state(config)
        state: ConversationState | None = None
        if snap is not None and getattr(snap, "values", None):
            candidate = snap.values.get("state")
            if isinstance(candidate, ConversationState):
                state = candidate
            else:
                # 陈旧/损坏的检查点（如旧代码版本写入的不同结构，或 state 为 None）
                # 会让节点拿到 None.state，进而报
                # 'NoneType' object has no attribute 'session_id'。直接清掉该
                # thread 的检查点，让本轮以全新 state 启动（会话消息存于 SessionStore，
                # 与图态解耦，清图态不丢用户可见的历史）。
                logger.warning(
                    _tag("infra", "invalid checkpoint state thread=%s, clearing"),
                    request.session_id,
                )
                await self.clear_checkpoint(request.session_id)
        if state is None:
            state = ConversationState(
                session_id=request.session_id,
                user_id=user_id,
                channel=request.channel,
            )
        return {"state": state, "request": request}

    async def input_normalizer(self, payload: dict[str, Any]) -> dict[str, Any]:
        state: ConversationState = payload["state"]
        request: ChatRequest = payload["request"]
        message = normalize_whitespace(request.message)
        logger.debug(_tag("input", "session=%s message=%r"), state.session_id, message[:80])

        state.reply = ""
        state.intent_result = None
        state.tool_result = None
        state.handoff = False
        state.handoff_reason = ""
        state.current_action = ""

        state.channel = request.channel
        # state.user_id 已在 _build_payload 初始化时设置
        state.recent_messages.append({"role": "user", "content": message})
        payload["state"] = state
        return payload

    async def confirmation_guard(self, payload: dict[str, Any]) -> dict[str, Any]:
        """R1 二次确认确定性拦截（位于意图路由之前）。

        上一轮若挂起了待确认操作（``state.pending_confirmation`` 非空），本轮用户回复需被
        **确定性**判定为确认/取消，而不是当新意图重新走 LLM 函数调用——后者会丢失「上轮
        问过确认」的上下文而失效（见 06_工具调用 回归）。

        - 取消信号：清空挂起态，直接给取消话术（``response_generator`` 早返回）。
        - 确认信号：用挂起负载以 ``confirm=true`` 重放对应工具（绕过 LLM），执行真退款。
        - 既非确认也非取消：视为用户转移话题，清空挂起态，走正常路由。
        """
        state: ConversationState = payload["state"]
        pending = state.pending_confirmation
        if not pending:
            return payload

        message = state.recent_messages[-1]["content"] if state.recent_messages else ""
        signal = classify_confirm_signal(message)

        if signal == "cancel":
            state.pending_confirmation = None
            state.reply = self._cancel_template()
            logger.info(_tag("confirm", "user cancelled pending refund session=%s"), state.session_id)
            return payload

        if signal == "confirm":
            state.pending_confirmation = None
            # 用挂起负载重放工具调用（confirm=true），绕过 LLM 自由函数调用，
            # 保证 R1 闭环确定性：用户回「确认」即执行，绝不依赖模型回忆。
            replay_args = {k: v for k, v in pending.items() if k != "tool"}
            replay_args["confirm"] = True
            tool_call = {
                "id": "confirm_replay",
                "function": {
                    "name": pending.get("tool", "request_refund"),
                    "arguments": json.dumps(replay_args, ensure_ascii=False),
                },
            }
            await self.tool_executor.run([tool_call], state)
            logger.info(_tag("confirm", "user confirmed pending refund session=%s"), state.session_id)
            return payload

        # 既非确认也非取消：用户已转移话题，清空挂起态避免 stale（如隔轮才回「确认」）。
        state.pending_confirmation = None
        logger.info(_tag("confirm", "pending confirmation cleared (topic shift) session=%s"), state.session_id)
        return payload

    def route_after_confirmation_guard(self, payload: dict[str, Any]) -> str:
        state: ConversationState = payload["state"]
        if state.reply or state.tool_result is not None:
            return "handled"
        return "normal"

    def _cancel_template(self) -> str:
        tpl = self.response_service.prompt_registry.get_tool_template("request_refund", "cancelled")
        return tpl or "已取消本次操作。"

    async def intent_router(self, payload: dict[str, Any]) -> dict[str, Any]:
        state: ConversationState = payload["state"]
        logger.debug(_tag("intent", "session=%s"), state.session_id)
        state.intent_result = await self.intent_router_service.route(
            state, state.recent_messages[-1]["content"]
        )
        logger.debug(
            _tag("intent", "result intent=%s.%s source=%s"),
            state.intent_result.main_intent if state.intent_result else None,
            state.intent_result.sub_intent if state.intent_result else None,
            state.intent_result.route_source if state.intent_result else None,
        )
        payload["state"] = state
        return payload

    async def state_tracker(self, payload: dict[str, Any]) -> dict[str, Any]:
        state: ConversationState = payload["state"]
        intent = state.intent_result
        if intent is None:
            logger.warning(_tag("state", "no intent_result session=%s"), state.session_id)
            return payload
        logger.debug(_tag("state", "session=%s intent=%s"), state.session_id, intent.main_intent)
        payload["state"] = self.state_tracker_service.apply(state, intent)
        return payload

    async def policy_layer(self, payload: dict[str, Any]) -> dict[str, Any]:
        state: ConversationState = payload["state"]
        logger.debug(_tag("policy", "session=%s"), state.session_id)
        payload["state"] = self.policy_service.decide(state)
        logger.debug(_tag("policy", "decision action=%s"), state.current_action)
        return payload

    def route_after_policy(self, payload: dict[str, Any]) -> str:
        state: ConversationState = payload["state"]
        action = state.current_action
        if action in {"ask_intent_clarification", "ask_slot_clarification"}:
            logger.debug(_tag("policy", "route -> clarification_node session=%s"), state.session_id)
            return "clarification_node"
        # agent_process 路由到 agent_node（工具调用）
        if action == "agent_process":
            logger.debug(_tag("policy", "route -> agent_node session=%s"), state.session_id)
            return "agent_node"
        if action == "handoff_human":
            logger.debug(_tag("policy", "route -> handoff_node session=%s"), state.session_id)
            return "handoff_node"
        # 其他情况（如 answer_directly）路由到 response_generator
        logger.debug(_tag("policy", "route -> response_generator session=%s"), state.session_id)
        return "response_generator"

    async def clarification_node(self, payload: dict[str, Any]) -> dict[str, Any]:
        state: ConversationState = payload["state"]
        logger.debug(_tag("clarification", "session=%s"), state.session_id)
        payload["state"] = await self.clarification_service.generate(state)
        return payload

    async def agent_node(self, payload: dict[str, Any]) -> dict[str, Any]:
        state: ConversationState = payload["state"]
        logger.debug(_tag("agent", "session=%s"), state.session_id)
        payload["state"] = await self.agent_node_service.run(state)
        return payload

    async def handoff_node(self, payload: dict[str, Any]) -> dict[str, Any]:
        state: ConversationState = payload["state"]
        logger.info(_tag("handoff", "session=%s reason=%s"), state.session_id, state.handoff_reason)
        payload["state"] = self.tool_executor.create_handoff(state)
        return payload

    async def response_generator(self, payload: dict[str, Any]) -> dict[str, Any]:
        state: ConversationState = payload["state"]
        logger.debug(_tag("response", "session=%s"), state.session_id)
        payload["state"] = await self.response_service.generate(state)
        # 多意图续办提示：有待处理意图时，在回复末尾提示用户可继续（Phase 3）
        if state.pending_intents and not state.handoff:
            names = "、".join(p.main_intent for p in state.pending_intents)
            state.reply = f"{state.reply}\n\n（还有「{names}」待处理，需要的话我可以继续处理。）"
        logger.debug(_tag("response", "reply=%r session=%s"), state.reply[:80] if state.reply else "", state.session_id)
        return payload

    async def context_compressor(self, payload: dict[str, Any]) -> dict[str, Any]:
        state: ConversationState = payload["state"]
        logger.debug(_tag("compressor", "session=%s"), state.session_id)
        payload["state"] = await self.context_service.compress(state)
        return payload

    def _build_chat_response(self, state: ConversationState) -> ChatResponse:
        # 简化后只下发前端真正渲染的字段：reply（消息气泡）+ session_state（StatsPanel）。
        # session_id 回传前端，使前端能按会话 id 将消息渲染到对应的聊天框（而非仅依赖当前激活会话）。
        # 其余意图/槽位/阶段等均在 session_state 内部，无需在顶层重复。
        return ChatResponse(
            reply=state.reply,
            session_id=state.session_id,
            session_state=self._build_session_snapshot(state),
        )

    def _build_session_snapshot(self, state: ConversationState) -> dict[str, Any]:
        # 仅下发 StatsPanel（经 sessionSnapshot）实际消费的字段，其余内部状态不进响应，
        # 避免冗余 payload（详见前端 ConsoleView / StatsPanel）。
        return {
            "current_main_intent": state.current_main_intent,
            "current_sub_intent": state.current_sub_intent,
            "stage": state.stage,
            "slots": state.slots,
            "missing_slots": state.missing_slots,
            "needs_clarification": state.needs_clarification,
            "pending_intents": [
                {"main_intent": p.main_intent, "sub_intent": p.sub_intent, "slots": p.slots}
                for p in state.pending_intents
            ],
            "summary": state.summary,
        }

    def _serialize_tool_result(self, state: ConversationState) -> dict[str, Any] | None:
        return state.tool_result.model_dump() if state.tool_result else None
