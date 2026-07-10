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
