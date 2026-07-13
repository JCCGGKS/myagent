from __future__ import annotations

import re

from app.schema import (
    HandoffResult,
    LogisticsEvent,
    LogisticsInfo,
    OrderInfo,
    RefundResult,
)
from app.dao.data import load_orders, load_logistics


# 不依赖 \b：Python3 默认 unicode 模式下中文也算「单词字符」，
# 中文与订单号之间没有 \b 边界，会导致「订单A1001」抽取失败。
# 改用显式「非字母数字」前后断言，让中文/标点/空格/字符串边界都成为合法边界。
ORDER_ID_PATTERN = re.compile(r"(?<![A-Za-z0-9])[A-Z]\d{4}(?![A-Za-z0-9])")


def load_mock_json_file(filename: str) -> list[dict]:
    if filename == "orders.json":
        return load_orders()
    if filename == "logistics.json":
        return load_logistics()
    return []


class OrderService:
    def __init__(self) -> None:
        raw_orders = load_mock_json_file("orders.json")
        self._orders = {item["order_id"]: OrderInfo(**item) for item in raw_orders}

    def get_order_status(self, order_id: str) -> OrderInfo | None:
        return self._orders.get(order_id)

    def modify_address(self, order_id: str, new_address: str) -> dict[str, object]:
        """修改订单收货地址（mock：无真实订单后端，返回受理结果）。"""
        if order_id not in self._orders:
            return {"ok": False, "order_id": order_id, "message": "没有查到这个订单号"}
        return {
            "ok": True,
            "order_id": order_id,
            "new_address": new_address,
            "message": "地址修改申请已提交，待仓库确认",
        }

    def apply_invoice(self, order_id: str, invoice_title: str = "") -> dict[str, object]:
        """开具电子发票（mock：无真实发票后端，返回受理结果）。"""
        if order_id not in self._orders:
            return {"ok": False, "order_id": order_id, "message": "没有查到这个订单号"}
        return {
            "ok": True,
            "order_id": order_id,
            "invoice_title": invoice_title,
            "message": "电子发票已开具",
        }


class LogisticsService:
    def __init__(self) -> None:
        raw_items = load_mock_json_file("logistics.json")
        self._records = {}
        for item in raw_items:
            timeline = [LogisticsEvent(**event) for event in item["timeline"]]
            self._records[item["order_id"]] = LogisticsInfo(
                order_id=item["order_id"],
                tracking_status=item["tracking_status"],
                timeline=timeline,
            )

    def get_logistics(self, order_id: str) -> LogisticsInfo | None:
        return self._records.get(order_id)


class HandoffService:
    def __init__(self) -> None:
        self._counter = 1000
        # R2 幂等：同一会话已建过人工单则直接返回原单，避免重复建单。
        self._by_session: dict[str, HandoffResult] = {}

    def create_handoff(self, session_id: str, summary: str) -> HandoffResult:
        if session_id in self._by_session:
            return self._by_session[session_id]
        self._counter += 1
        result = HandoffResult(ticket_id=f"H{self._counter}", summary=summary)
        self._by_session[session_id] = result
        return result


def extract_order_id(text: str) -> str | None:
    match = ORDER_ID_PATTERN.search(text.upper())
    return match.group(0) if match else None


class RefundService:
    """售后退款/退货/换货/维修受理服务（mock：无真实订单后端）。

    设计 §2.1 明确要求 ``RefundTool``；此前缺失导致 after_sale_refund 类意图
    在 agent_node 无工具可调用，退化为 ``create_handoff`` 转人工。
    """

    def __init__(self) -> None:
        self._counter = 2000
        # R2 幂等：同一 (订单号, 退款类型) 只生成一次受理单，重复请求返回原单号，
        # 防止重试/二次确认/并行调用导致重复退款。
        self._by_key: dict[tuple[str, str], RefundResult] = {}

    def request_refund(self, order_id: str, refund_type: str = "refund", reason: str = "") -> RefundResult:
        key = (order_id, refund_type)
        if key in self._by_key:
            return self._by_key[key]
        self._counter += 1
        result = RefundResult(
            refund_id=f"R{self._counter}",
            order_id=order_id,
            refund_type=refund_type,
            status="已受理",
        )
        self._by_key[key] = result
        return result
