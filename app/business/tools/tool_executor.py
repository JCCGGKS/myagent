from __future__ import annotations

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
            "refund_type 可选 refund(退款)/return(无理由退货)/exchange(换货)/warranty(质量问题维修)。"
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

TOOLS: dict[str, dict[str, Any]] = {
    "rag_retrieve": {"schema": RagRetrieveTool().to_tool_schema(), "handler": "_rag_retrieve"},
    "query_order": {"schema": _ORDER_SCHEMA, "handler": "_query_order"},
    "query_logistics": {"schema": _LOGISTICS_SCHEMA, "handler": "_query_logistics"},
    "create_handoff": {"schema": _HANDOFF_SCHEMA, "handler": "_handle_handoff"},
    "request_refund": {"schema": _REFUND_SCHEMA, "handler": "_request_refund"},
    "modify_address": {"schema": _MODIFY_ADDRESS_SCHEMA, "handler": "_modify_address"},
    "apply_invoice": {"schema": _INVOICE_SCHEMA, "handler": "_apply_invoice"},
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
    ) -> None:
        self.order_service = order_service
        self.logistics_service = logistics_service
        self.handoff_service = handoff_service
        self.refund_service = refund_service or RefundService()
        self.rag_tool = rag_tool or RagRetrieveTool()
        # 从单点注册表构建 名称 -> handler 方法 的映射
        self._handlers = {name: getattr(self, spec["handler"]) for name, spec in TOOLS.items()}

    def run(
        self, tool_calls: list[dict[str, Any]], state: ConversationState
    ) -> list[dict[str, Any]]:
        tool_messages: list[dict[str, Any]] = []
        last_result: ToolExecutionResult | None = None
        for tc in tool_calls:
            name = tc["function"]["name"]
            canonical = TOOL_ALIASES.get(name, name)
            start = time.perf_counter()
            status = "ok"
            try:
                try:
                    args = json.loads(tc["function"].get("arguments") or "{}")
                except (json.JSONDecodeError, ValueError):
                    logger.warning("[tool] invalid JSON args for %s raw=%r", name, tc["function"].get("arguments"))
                    result = ToolExecutionResult(
                        kind="error",
                        user_facing_summary=f"工具 {name} 的参数格式错误，无法执行。",
                    )
                else:
                    result = self._execute_one(name, args, state)
                if isinstance(result, ToolExecutionResult) and result.kind == "error":
                    status = "error"
            except Exception:
                # 处理器异常：保留原行为（向上抛出），但先记指标，避免该工具指标丢失。
                observe_tool(canonical, "error", time.perf_counter() - start)
                raise
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

    def _execute_one(
        self, name: str, args: dict[str, Any], state: ConversationState
    ) -> ToolExecutionResult:
        logger.info("[tool] executing %s args=%s", name, args)
        canonical = TOOL_ALIASES.get(name, name)
        handler = self._handlers.get(canonical)
        if handler is None:
            return ToolExecutionResult(kind="error", user_facing_summary=f"未知工具: {name}")
        return handler(args, state)

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
        result = self.refund_service.request_refund(order_id, refund_type=refund_type, reason=reason)
        return ToolExecutionResult(
            kind="aftersale_refund",
            raw_result=result.model_dump(),
            sanitized_result=result.model_dump(),
            user_facing_summary=f"已为订单 {order_id} 提交{refund_type}申请，受理单号 {result.refund_id}",
        )

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
