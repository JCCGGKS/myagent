from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from app.schema import ConversationState, ToolExecutionResult
from app.business.tools.domain import (
    HandoffService,
    LogisticsService,
    OrderService,
    RefundService,
)
from app.business.tools.rag_tool import RagRetrieveTool
from app.utils import build_action_record, observe_handoff, observe_tool

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 工具单点注册表
# 新增工具 = 在此加一项 + 实现对应 handler 方法（签名统一为 (args, state)）。
# - schema：走 LLM function calling 的 tools 参数
# - handler：ToolExecutor 上的方法名，统一签名 (args: dict, state) -> ToolExecutionResult
# ---------------------------------------------------------------------------
_ORDER_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "query_order",
        "description": (
            "查询【订单本身】的状态与信息：是否已下单/已发货、是否待付款、商品名称、金额等。"
            "当用户询问「订单状态/订单详情/发货了吗(是否已发货)/金额/商品」时调用。"
            "注意：仅查订单维度信息用本工具；已发货之后的运输过程"
            "（快递到哪了/运输中/派送中/是否签收）请用 query_logistics。"
        ),
        "parameters": {
            "type": "object",
            "properties": {"order_id": {"type": "string", "description": "订单号"}},
            "required": ["order_id"],
        },
    },
}
_LOGISTICS_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "query_logistics",
        "description": (
            "查询【已发货后的运输过程】：快递到哪了、运输中/派送中、最新物流节点、是否签收。"
            "当用户询问「物流/快递/配送进度/货到没到」时调用。"
            "注意：仅查运输过程用本工具；订单是否已发货、待付款、商品、金额等订单维度信息"
            "请用 query_order。"
        ),
        "parameters": {
            "type": "object",
            "properties": {"order_id": {"type": "string", "description": "订单号"}},
            "required": ["order_id"],
        },
    },
}
_HANDOFF_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "create_handoff",
        "description": (
            "转接人工客服：创建人工服务单，由人工基于当前会话上下文继续处理。"
            "仅当以下情况之一才调用：(1)用户明确要求人工客服/转人工；(2)投诉情绪升级、需人工介入；"
            "(3)多次澄清仍无法解决（达到澄清上限）。"
            "注意：不要因缺少订单号或信息不全而转人工——先用对应的业务工具"
            "（query_order/query_logistics/request_refund），由工具提示用户补全信息。"
        ),
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
}
_REFUND_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "request_refund",
        "description": (
            "发起售后【实际办理】退款/退货/换货/维修。仅当用户明确表示要办理退款、退货、换货、维修"
            "（即要真正发起售后操作）时调用；若用户只是咨询退款政策、七天无理由、退换货规则等"
            "（并不要求实际办理），请用 rag_retrieve 检索知识库。需提供订单号；"
            "refund_type 可选 refund(退款)/return(无理由退货)/exchange(换货)/warranty(质量问题维修)。\n"
            "【二次确认（R1）】本工具涉及动钱，必须两步：①首次调用 confirm 默认为 false，"
            "工具只返回确认提示、不真正办理；②用户明确回复“确认”后，由模型在下一轮以 confirm=true "
            "再次调用，方可真正发起退款。切勿在未确认时直接以 confirm=true 调用。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "order_id": {"type": "string", "description": "订单号"},
                "refund_type": {
                    "type": "string",
                    "description": "退款类型",
                    "enum": ["refund", "return", "exchange", "warranty"],
                },
                "reason": {"type": "string", "description": "退款/退货原因（可选）"},
                "confirm": {
                    "type": "boolean",
                    "description": (
                        "是否已在上一轮向用户确认。首次调用必须为 false（默认），"
                        "工具仅返回确认提示；用户确认后，由模型在下一轮以 confirm=true 再次调用，"
                        "方可真正发起退款。幂等保护下重复确认不会生成新受理单。"
                    ),
                },
            },
            "required": ["order_id"],
        },
    },
}
_MODIFY_ADDRESS_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "modify_address",
        "description": "修改订单收货地址。当用户要改地址、修改地址、换收货地址时调用。需提供订单号与新地址。",
        "parameters": {
            "type": "object",
            "properties": {
                "order_id": {"type": "string", "description": "订单号"},
                "new_address": {"type": "string", "description": "新的收货地址"},
            },
            "required": ["order_id", "new_address"],
        },
    },
}
_INVOICE_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "apply_invoice",
        "description": "开具电子发票。当用户要开发票、开票、要发票时调用。需提供订单号与发票抬头（可选）。",
        "parameters": {
            "type": "object",
            "properties": {
                "order_id": {"type": "string", "description": "订单号"},
                "invoice_title": {"type": "string", "description": "发票抬头（可选）"},
            },
            "required": ["order_id"],
        },
    },
}

# side_effect=True 的工具带不可逆副作用（动钱/转人工/改地址/开票），
# 自动重试可能导致重复触发，故不参与自动重试（仅由模型软重试 + R2 幂等兜底）。
TOOLS: dict[str, dict[str, Any]] = {
    "rag_retrieve": {"schema": RagRetrieveTool().to_tool_schema(), "handler": "_rag_retrieve", "side_effect": False},
    "query_order": {"schema": _ORDER_SCHEMA, "handler": "_query_order", "side_effect": False},
    "query_logistics": {"schema": _LOGISTICS_SCHEMA, "handler": "_query_logistics", "side_effect": False},
    "create_handoff": {"schema": _HANDOFF_SCHEMA, "handler": "_handle_handoff", "side_effect": True},
    "request_refund": {"schema": _REFUND_SCHEMA, "handler": "_request_refund", "side_effect": True},
    "modify_address": {"schema": _MODIFY_ADDRESS_SCHEMA, "handler": "_modify_address", "side_effect": True},
    "apply_invoice": {"schema": _INVOICE_SCHEMA, "handler": "_apply_invoice", "side_effect": True},
}
# LLM 可能返回的历史别名，统一归并到规范名
TOOL_ALIASES: dict[str, str] = {
    "order_query": "query_order",
    "logistics": "query_logistics",
    "handoff_service": "create_handoff",
    "request_human": "create_handoff",
    "refund": "request_refund",
    "return": "request_refund",
    "exchange": "request_refund",
    "warranty": "request_refund",
}
# 供 registry.build_tool_schemas() 读取
TOOL_SCHEMAS: dict[str, dict[str, Any]] = {name: spec["schema"] for name, spec in TOOLS.items()}


class ToolExecutor:
    """统一的工具执行服务：覆盖 LLM 函数调用工具与业务工具。

    业务工具（订单/物流/转人工）由 domain 服务直接驱动；知识检索
    （``rag_retrieve``）由 ``rag_tool`` 驱动。``agent_node`` 调用 ``run``
    执行一批 tool_calls，返回 tool 结果消息（追加到 ReAct 线程），并把
    最后一次结果写入 ``state.tool_result``。
    """

    def __init__(
        self,
        order_service: OrderService | None = None,
        logistics_service: LogisticsService | None = None,
        handoff_service: HandoffService | None = None,
        refund_service: RefundService | None = None,
        rag_tool: RagRetrieveTool | None = None,
        max_retries: int = 2,
        retry_base_delay: float = 0.1,
        retry_max_delay: float = 1.0,
    ) -> None:
        self.order_service = order_service
        self.logistics_service = logistics_service
        self.handoff_service = handoff_service
        self.refund_service = refund_service or RefundService()
        self.rag_tool = rag_tool or RagRetrieveTool()
        # 失败重试：非副作用工具在基础设施故障（异常）时按退避重试；副作用工具不重试。
        self.max_retries = max_retries
        self.retry_base_delay = retry_base_delay
        self.retry_max_delay = retry_max_delay
        # 从单点注册表构建 名称 -> handler 方法 的映射
        self._handlers = {name: getattr(self, spec["handler"]) for name, spec in TOOLS.items()}

    async def run(
        self, tool_calls: list[dict[str, Any]], state: ConversationState
    ) -> list[dict[str, Any]]:
        tool_messages: list[dict[str, Any]] = []
        last_result: ToolExecutionResult | None = None
        for tc in tool_calls:
            name = tc["function"]["name"]
            canonical = TOOL_ALIASES.get(name, name)
            spec = TOOLS.get(canonical, {})
            side_effect = spec.get("side_effect", False)
            start = time.perf_counter()
            # 失败隔离 + 失败重试（副作用工具不重试，防重复；业务错误不重试）。
            result = await self._execute_with_retry(name, tc, state, side_effect)
            status = "error" if (isinstance(result, ToolExecutionResult) and result.kind == "error") else "ok"
            observe_tool(canonical, status, time.perf_counter() - start)
            tool_messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.get("id"),
                    "name": name,
                    "content": json.dumps(
                        result.model_dump() if isinstance(result, ToolExecutionResult) else result,
                        ensure_ascii=False,
                    ),
                }
            )
            if isinstance(result, ToolExecutionResult):
                last_result = result
        if last_result is not None:
            state.tool_result = last_result
        return tool_messages

    async def _execute_with_retry(
        self, name: str, tc: dict[str, Any], state: ConversationState, side_effect: bool
    ) -> ToolExecutionResult:
        """执行单个工具：失败重试 + 失败隔离。

        - 参数 JSON 非法 / handler 主动返回 error（业务/校验错误）→ **不重试**，直接返回 error。
        - handler 抛异常（多为基础设施故障）→ 对**非副作用**工具按指数退避重试最多
          ``max_retries`` 次；**副作用工具（退款/转人工/改地址/开票）不重试**，避免重复触发
          不可逆动作（在 R2 幂等补齐前，这是更安全的默认）。
        - 重试耗尽仍失败 → 转 error 型 ``ToolExecutionResult``（失败隔离），让 LLM 收到
          observation 自行决定下一步，而非中止整批。
        """
        try:
            args = json.loads(tc["function"].get("arguments") or "{}")
        except (json.JSONDecodeError, ValueError):
            logger.warning("[tool] invalid JSON args for %s raw=%r", name, tc["function"].get("arguments"))
            return ToolExecutionResult(kind="error", user_facing_summary=f"工具 {name} 的参数格式错误，无法执行。")

        # R5 统一参数 schema 校验：缺必填 / 类型错 / 枚举非法 提前拦截，
        # 返回干净 error 且不进 handler、不重试（属调用方错误，非基础设施故障）。
        validation_err = self._validate_tool_args(name, args, state)
        if validation_err:
            logger.warning("[tool] validation failed for %s: %s", name, validation_err)
            return ToolExecutionResult(kind="error", user_facing_summary=validation_err)

        max_attempts = 1 if side_effect else self.max_retries + 1
        last_exc: Exception | None = None
        for attempt in range(max_attempts):
            try:
                result = await self._execute_one(name, args, state)
            except Exception as exc:
                last_exc = exc
                if attempt < max_attempts - 1:
                    delay = min(self.retry_base_delay * (2 ** attempt), self.retry_max_delay)
                    logger.warning(
                        "[tool] %s failed (attempt %d/%d), retry after %.2fs: %r",
                        name, attempt + 1, max_attempts, delay, exc,
                    )
                    await asyncio.sleep(delay)
                    continue
                break  # 最后一次仍失败 → 下方转 error
            # handler 主动返回 error = 业务/校验错误，不重试
            if isinstance(result, ToolExecutionResult) and result.kind == "error":
                return result
            return result

        logger.error("[tool] %s execution failed after %d attempt(s): %r", name, max_attempts, last_exc)
        return ToolExecutionResult(
            kind="error",
            user_facing_summary=f"工具 {name} 执行出错，请稍后重试或联系人工客服。",
        )

    async def _execute_one(
        self, name: str, args: dict[str, Any], state: ConversationState
    ) -> ToolExecutionResult:
        logger.info("[tool] executing %s args=%s", name, args)
        canonical = TOOL_ALIASES.get(name, name)
        handler = self._handlers.get(canonical)
        if handler is None:
            return ToolExecutionResult(kind="error", user_facing_summary=f"未知工具: {name}")
        # 业务处理器为同步实现（mock/同步 DAO），放到线程执行避免阻塞事件循环。
        return await asyncio.to_thread(handler, args, state)

    def _validate_tool_args(
        self, name: str, args: dict[str, Any], state: ConversationState
    ) -> str | None:
        """按工具 schema 统一校验参数（R5）。

        校验项：① 必填字段存在且非空（缺省时回退 ``state.slots``，与 handler 取值逻辑一致）；
        ② 显式传入参数的类型 / 枚举合法。返回 error 摘要串表示校验失败，``None`` 表示通过。

        设计要点：
        - 仅校验「显式传入的参数」的类型/枚举，``state.slots`` 为可信内部状态、不再重复校验；
        - 未知工具（无 schema）返回 ``None``，交由 ``_execute_one`` 统一报「未知工具」；
        - 校验失败属于调用方错误，调用方（``_execute_with_retry``）直接返回 error、**不重试**。
        """
        canonical = TOOL_ALIASES.get(name, name)
        spec = TOOLS.get(canonical)
        if spec is None:
            return None  # 未知工具由 _execute_one 处理
        params = spec["schema"]["function"].get("parameters", {})
        properties = params.get("properties", {})
        required = params.get("required", [])

        # 有效取值 = 显式参数优先，缺失时回退 state.slots（与 handler 内的 or state.slots.get 一致）
        def _value(field: str) -> Any:
            v = args.get(field, None)
            if v in (None, ""):
                v = state.slots.get(field)
            return v

        # ① 必填校验（含 slots 回退）
        missing = [f for f in required if _value(f) in (None, "")]
        if missing:
            return f"缺少必填参数：{', '.join(missing)}，请补充后再试。"

        # ② 类型 / 枚举校验（仅对显式传入、非 None 的参数）
        for field, value in args.items():
            if value is None or field not in properties:
                continue
            prop = properties[field]
            expected = prop.get("type")
            if expected == "string" and not isinstance(value, str):
                return f"参数「{field}」应为文本。"
            if expected == "boolean" and not isinstance(value, bool):
                return f"参数「{field}」应为布尔值（true/false）。"
            if expected in ("integer", "number") and not isinstance(value, (int, float)):
                return f"参数「{field}」应为数字。"
            if expected == "array" and not isinstance(value, list):
                return f"参数「{field}」应为列表。"
            if expected == "object" and not isinstance(value, dict):
                return f"参数「{field}」应为对象。"
            enum = prop.get("enum")
            if enum is not None and value not in enum:
                return f"参数「{field}」取值无效：{value}；可选值为 {enum}。"

        return None

    def _rag_retrieve(self, args: dict[str, Any], state: ConversationState) -> ToolExecutionResult:
        docs = self.rag_tool.run(args.get("query", ""), user_id=state.user_id)
        return ToolExecutionResult(
            kind="knowledge",
            raw_result={"retrieved_docs": docs},
            sanitized_result={"retrieved_docs": docs},
            user_facing_summary=f"检索到 {len(docs)} 条相关文档",
        )

    def _query_order(self, args: dict[str, Any], state: ConversationState) -> ToolExecutionResult:
        order_id = args.get("order_id") or state.slots.get("order_id")
        if not order_id:
            return ToolExecutionResult(
                kind="error",
                user_facing_summary="请提供订单号，以便我为您查询。",
            )
        if self.order_service is None:
            return ToolExecutionResult(
                kind="error",
                user_facing_summary=f"订单服务未配置，无法查询: {order_id}",
            )
        order = self.order_service.get_order_status(order_id)
        raw = order.model_dump() if order else None
        summary = f"订单 {order_id} 当前状态为 {order.status}" if order else "没有查到这个订单号"
        return ToolExecutionResult(
            kind="order_query",
            raw_result=raw,
            sanitized_result=raw,
            user_facing_summary=summary,
        )

    def _query_logistics(self, args: dict[str, Any], state: ConversationState) -> ToolExecutionResult:
        order_id = args.get("order_id") or state.slots.get("order_id")
        if not order_id:
            return ToolExecutionResult(
                kind="error",
                user_facing_summary="请提供订单号，以便我为您查询物流。",
            )
        if self.logistics_service is None:
            return ToolExecutionResult(
                kind="error",
                user_facing_summary=f"物流服务未配置，无法查询: {order_id}",
            )
        logistics = self.logistics_service.get_logistics(order_id)
        raw = logistics.model_dump() if logistics else None
        latest_status = (
            logistics.timeline[-1].status
            if logistics and logistics.timeline
            else "无"
        )
        summary = (
            f"订单 {order_id} 当前物流状态为 {logistics.tracking_status}，最近节点 {latest_status}"
            if logistics
            else "没有查到物流信息"
        )
        return ToolExecutionResult(
            kind="logistics",
            raw_result=raw,
            sanitized_result=raw,
            user_facing_summary=summary,
        )

    def _handle_handoff(self, args: dict[str, Any], state: ConversationState) -> ToolExecutionResult:
        # create_handoff 会就地把 tool_result 写入 state，并返回 state；
        # 作为工具处理器需返回 ToolExecutionResult 供 run() 序列化 tool 消息，
        # 否则会把整个 ConversationState 交给 json.dumps 而报
        # "Object of type ConversationState is not JSON serializable"。
        self.create_handoff(state)
        return state.tool_result

    def create_handoff(self, state: ConversationState) -> ConversationState:
        observe_handoff()  # 业务 KPI：转人工率
        if self.handoff_service is None:
            state.tool_result = ToolExecutionResult(
                kind="error",
                user_facing_summary="转人工服务未配置，无法创建服务单。",
            )
            # 直接落地回复，避免 response_generator 再调一次 LLM（去冗余）。
            state.reply = state.tool_result.user_facing_summary
            return state
        handoff = self.handoff_service.create_handoff(state.session_id, state.summary)
        state.tool_result = ToolExecutionResult(
            kind="handoff",
            raw_result=handoff.model_dump(),
            sanitized_result=handoff.model_dump(),
            user_facing_summary=f"已创建人工服务单 {handoff.ticket_id}",
        )
        # 直接落地面向用户的最终回复，使下游 response_generator 命中早返回、
        # 不再多调一次 LLM 把 tool_result 改写成话术（去冗余，与 agent 直答同思路）。
        state.reply = (
            f"已为你转人工客服，服务单号 {handoff.ticket_id}。"
            "人工客服会基于当前会话上下文继续处理。"
        )
        state.handoff = True
        state.action_history.append(
            build_action_record("handoff_node", state.tool_result.user_facing_summary)
        )
        return state

    def _request_refund(self, args: dict[str, Any], state: ConversationState) -> ToolExecutionResult:
        order_id = args.get("order_id") or state.slots.get("order_id")
        if not order_id:
            return ToolExecutionResult(kind="error", user_facing_summary="请提供订单号，以便为您发起退款。")
        if self.refund_service is None:
            return ToolExecutionResult(kind="error", user_facing_summary=f"退款服务未配置，无法处理: {order_id}")
        refund_type = args.get("refund_type", "refund")
        reason = args.get("reason", "")
        # R1 二次确认：未确认前绝不执行任何退款副作用，仅返回确认提示让用户拍板。
        # 确认信号来自模型在用户确认后以 confirm=true 二次调用（幂等保护见 R2）。
        confirmed = args.get("confirm") is True or self._refund_confirmed(state, order_id, refund_type)
        if not confirmed:
            prompt = (
                f"⚠️ 即将为订单 {order_id} 发起【{refund_type}】申请"
                + (f"（原因：{reason}）" if reason else "")
                + "，该操作不可撤销。请确认是否继续？确认请直接回复「确认」。"
            )
            # 直接落地面向用户的最终回复，使 response_generator 命中早返回、
            # 不再多调一次 LLM 把确认提示改写成话术（与 handoff 同思路，保证提示必达）。
            state.reply = prompt
            return ToolExecutionResult(
                kind="confirmation",
                raw_result={"order_id": order_id, "refund_type": refund_type, "confirmed": False},
                sanitized_result={"order_id": order_id, "refund_type": refund_type, "confirmed": False},
                user_facing_summary=prompt,
            )
        # 已确认 → 执行（R2 幂等兜底：重复确认不会生成新受理单）。
        result = self.refund_service.request_refund(order_id, refund_type=refund_type, reason=reason)
        # 记录确认痕迹，便于审计与跨轮去重。
        marker = f"refund:{order_id}:{refund_type}"
        if marker not in state.confirmed_slots:
            state.confirmed_slots.append(marker)
        return ToolExecutionResult(
            kind="aftersale_refund",
            raw_result=result.model_dump(),
            sanitized_result=result.model_dump(),
            user_facing_summary=f"已为订单 {order_id} 提交{refund_type}申请，受理单号 {result.refund_id}",
        )

    @staticmethod
    def _refund_confirmed(state: ConversationState, order_id: str, refund_type: str) -> bool:
        """该 (订单, 类型) 是否已在历史轮次被确认过（审计/跨轮去重用）。"""
        return f"refund:{order_id}:{refund_type}" in state.confirmed_slots

    def _modify_address(self, args: dict[str, Any], state: ConversationState) -> ToolExecutionResult:
        order_id = args.get("order_id") or state.slots.get("order_id")
        new_address = args.get("new_address", "")
        if not order_id or not new_address:
            return ToolExecutionResult(kind="error", user_facing_summary="请提供订单号与新收货地址。")
        if self.order_service is None:
            return ToolExecutionResult(kind="error", user_facing_summary=f"订单服务未配置，无法修改地址: {order_id}")
        result = self.order_service.modify_address(order_id, new_address)
        if not result.get("ok"):
            return ToolExecutionResult(kind="error", user_facing_summary=result.get("message", "地址修改失败。"))
        return ToolExecutionResult(
            kind="order_query",
            raw_result=result,
            sanitized_result=result,
            user_facing_summary=f"订单 {order_id} 的收货地址已提交修改为：{new_address}",
        )

    def _apply_invoice(self, args: dict[str, Any], state: ConversationState) -> ToolExecutionResult:
        order_id = args.get("order_id") or state.slots.get("order_id")
        invoice_title = args.get("invoice_title", "")
        if not order_id:
            return ToolExecutionResult(kind="error", user_facing_summary="请提供订单号，以便开具发票。")
        if self.order_service is None:
            return ToolExecutionResult(kind="error", user_facing_summary=f"订单服务未配置，无法开票: {order_id}")
        result = self.order_service.apply_invoice(order_id, invoice_title=invoice_title)
        if not result.get("ok"):
            return ToolExecutionResult(kind="error", user_facing_summary=result.get("message", "开票失败。"))
        suffix = f"（抬头：{invoice_title}）" if invoice_title else ""
        return ToolExecutionResult(
            kind="order_query",
            raw_result=result,
            sanitized_result=result,
            user_facing_summary=f"订单 {order_id} 的电子发票已开具{suffix}",
        )
