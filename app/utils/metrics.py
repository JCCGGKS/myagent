from __future__ import annotations

"""自托管可观测指标（Prometheus 客户端，零外部依赖）。

仅定义**低基数 label** 的指标（见 observability-trace-plan.md §4.2 基数铁律），
`user_id` / `session_id` / 原始 prompt 等高频维度**绝不**进 label，
它们归 event_log / 日志，靠 `trace_id` 关联。

指标清单（与计划 Phase 7 对齐，仅含可干净埋点的核心信号）：
- 工具：调用量（按 tool_name + status）、延迟
- 请求：调用量（按 intent + channel）、端到端延迟
- 业务 KPI：转人工率、低置信度率

LLM token 用量、节点级延迟需从 LLM 层透出 usage / 图回调，留作后续演进。
"""

from prometheus_client import Counter, Histogram, CONTENT_TYPE_LATEST, generate_latest

# --- 工具 ---
TOOL_CALLS = Counter(
    "myagent_tool_calls_total",
    "Tool invocations by tool name and status.",
    ["tool_name", "status"],  # status: ok / error
)
TOOL_LATENCY = Histogram(
    "myagent_tool_latency_seconds",
    "Tool execution latency in seconds.",
    ["tool_name"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0),
)

# --- 请求 ---
REQUESTS = Counter(
    "myagent_requests_total",
    "Chat requests by main intent and channel.",
    ["intent", "channel"],
)
REQUEST_LATENCY = Histogram(
    "myagent_request_latency_seconds",
    "End-to-end chat request latency in seconds.",
    buckets=(0.5, 1.0, 2.5, 5.0, 10.0, 20.0, 40.0, 60.0),
)

# --- 业务 KPI ---
HANDOFF_TOTAL = Counter(
    "myagent_handoff_total",
    "Total handoff-to-human requests (key business KPI).",
)
LOW_CONFIDENCE_TOTAL = Counter(
    "myagent_low_confidence_total",
    "Total requests where intent recognition was low confidence / needs clarification.",
)


def observe_tool(name: str, status: str, latency_seconds: float) -> None:
    TOOL_CALLS.labels(tool_name=name, status=status).inc()
    TOOL_LATENCY.labels(tool_name=name).observe(latency_seconds)


def observe_request(intent: str, channel: str, latency_seconds: float) -> None:
    REQUESTS.labels(intent=intent, channel=channel).inc()
    REQUEST_LATENCY.observe(latency_seconds)


def observe_handoff() -> None:
    HANDOFF_TOTAL.inc()


def observe_low_confidence() -> None:
    LOW_CONFIDENCE_TOTAL.inc()


def render_metrics() -> tuple[bytes, str]:
    """供 `/metrics` 端点返回最新指标文本。"""
    return generate_latest(), CONTENT_TYPE_LATEST
