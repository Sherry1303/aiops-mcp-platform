# -*- coding: utf-8 -*-
"""FastAPI 请求 / 响应数据模型（pydantic v2）。"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    """对话历史中的一条消息。"""

    role: Literal["user", "assistant"] = "user"
    content: str = ""


class ChatRequest(BaseModel):
    """POST /api/chat 入参。

    message  自然语言指令，例如「帮我查一下 R1 的 eth0 流量」
    history  可选的历史上下文，前端把最近几轮回传即可（服务端只保留最近 MAX_HISTORY 条）
    """

    message: str = Field(..., min_length=1, max_length=2000,
                         description="自然语言运维指令")
    history: list[ChatMessage] = Field(default_factory=list)
    session_id: str = Field(default="web", max_length=64)


class ToolCallRecord(BaseModel):
    """一次 MCP 工具调用的完整留痕。"""

    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    result: str = ""
    status: Literal["SUCCESS", "FAILED", "PENDING_APPROVAL"] = "SUCCESS"
    elapsed_ms: int = 0
    transport: str = "mcp:stdio"


class PendingApproval(BaseModel):
    """写操作被安全门拦截后产生的待审批任务。"""

    tool: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    reason: str = "写操作需管理员审批，已拦截，未下发到设备"


class ChatResponse(BaseModel):
    """POST /api/chat 返回。"""

    reply: str
    model: str
    rounds: int = 1
    elapsed_ms: int = 0
    tool_calls: list[ToolCallRecord] = Field(default_factory=list)
    pending_approval: PendingApproval | None = None


class DeviceInfo(BaseModel):
    """设备（含 SSH 探测结果）。"""

    name: str
    ip: str
    role: str
    port: int = 22
    online: bool = False
    version: str = "-"
    latency_ms: int | None = None
    error: str = ""


class DeviceListResponse(BaseModel):
    total: int
    online: int
    offline: int
    cached: bool = False
    checked_at: str
    devices: list[DeviceInfo] = Field(default_factory=list)


class TrafficResponse(BaseModel):
    device: str
    interface: str
    online: bool
    state: str = "-"
    address: str = "-"
    rx_bytes: int = 0
    tx_bytes: int = 0
    rx_delta: int = 0
    tx_delta: int = 0
    rx_mbps: float = 0.0
    tx_mbps: float = 0.0
    rx_errors: int = 0
    tx_errors: int = 0
    sample_gap: float = 1.0
    timestamp: str = ""
    message: str = ""


class AuditItem(BaseModel):
    id: int
    timestamp: str = ""
    device_name: str = ""
    action: str = ""
    details: str = ""
    status: str = ""


class AuditListResponse(BaseModel):
    total: int
    returned: int
    items: list[AuditItem] = Field(default_factory=list)


class AlertItem(BaseModel):
    id: int
    timestamp: str = ""
    device_name: str = ""
    level: str = "P2"
    message: str = ""
    status: str = "ACTIVE"
    note: str = ""


class StatsResponse(BaseModel):
    """控制台顶部 4 个数据卡（多返回几个便于扩展）。"""

    devices_total: int = 0
    devices_online: int = 0
    alerts_active: int = 0
    alerts_total: int = 0
    audit_total: int = 0
    audit_failed: int = 0


class AckRequest(BaseModel):
    """POST /api/alerts/{id}/ack 入参。"""

    note: str = Field("", max_length=500, description="处置备注（可空）")


class AckResponse(BaseModel):
    ok: bool
    alert_id: int
    message: str

