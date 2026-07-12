"""业务领域结构：订单、物流、转人工。"""

from __future__ import annotations

from pydantic import BaseModel


class OrderInfo(BaseModel):
    order_id: str
    status: str
    product_name: str
    amount: float


class LogisticsEvent(BaseModel):
    time: str
    status: str


class LogisticsInfo(BaseModel):
    order_id: str
    tracking_status: str
    timeline: list[LogisticsEvent]


class HandoffResult(BaseModel):
    ticket_id: str
    summary: str


class RefundResult(BaseModel):
    """售后退款/退货/换货/维修的受理结果（mock 实现，无真实订单后端）。"""

    refund_id: str
    order_id: str
    refund_type: str = "refund"
    status: str = "已受理"
