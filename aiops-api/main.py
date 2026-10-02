# -*- coding: utf-8 -*-
"""aiops-api —— 对接现有 MCP Server（D:\\mcp-vyos\\server.py）的 FastAPI 后端。

启动：
    cd D:\\aiops-api
    uvicorn main:app --reload --port 8000

接口一览：
    GET  /health                                健康检查（含 MCP 连接状态）
    GET  /api/devices                           设备清单 + SSH 实时在线状态
    GET  /api/devices/{name}                    单台设备只读详情（经 MCP → SSH）
    POST /api/chat                              AI 对话（DeepSeek 意图识别 → MCP 工具 → 总结）
    GET  /api/audit-logs                        审计日志（SQLite，分页/筛选）
    GET  /api/alerts                            告警列表 + 分级统计
    POST /api/alerts/{id}/ack                   确认告警（可带处置备注）
    GET  /api/stats                             控制台数据卡聚合数据
    GET  /api/traffic/{device}/{interface}       端口流量（两次采样算 Mbps）
    GET  /api/mcp/health                        MCP 客户端状态
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import Body, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

import audit
from agent import run_agent
from config import (API_HOST, API_PORT, AUDIT_DB, CORS_ORIGINS, DEFAULT_INTERFACE,
                    INVENTORY_FILE, MCP_SERVER_SCRIPT, load_api_key)
from devices import DEVICES, collect_device_detail, probe_snapshot, sample_traffic
from mcp_client import mcp_client
from schemas import (AckRequest, AuditListResponse, ChatRequest, ChatResponse,
                     DeviceListResponse, StatsResponse, TrafficResponse)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动时建立 MCP 长连接 + 初始化审计库；退出时优雅关闭。"""
    audit.init_db()
    ok = await mcp_client.start()
    print(f"[aiops-api] MCP Server {'已连接' if ok else '连接失败'}：{MCP_SERVER_SCRIPT}")
    if not ok:
        print(f"[aiops-api] MCP 错误：{mcp_client.last_error}（单次调用时会自动重连并兜底）")
    print(f"[aiops-api] 资产清单 {INVENTORY_FILE}（{len(DEVICES)} 台设备）· 审计库 {AUDIT_DB}")
    yield
    await mcp_client.stop()


app = FastAPI(title="AIOps API", version="1.0.0",
              description="MCP + VyOS + DeepSeek 的 AIOps 控制台后端",
              lifespan=lifespan)

# ================= CORS =================
# 开发阶段放开所有来源。注意：allow_origins=["*"] 时必须 allow_credentials=False，
# 否则浏览器会直接判定响应非法（这是最常见的 CORS 报错原因）。
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
    max_age=600,
)


@app.middleware("http")
async def cors_safety_net(request, call_next):
    """兜底：即使未被 CORSMiddleware 覆盖的响应（如异常路径）也补上 CORS 头。"""
    try:
        response = await call_next(request)
    except Exception as exc:  # noqa: BLE001 —— 任何未捕获异常都返回 JSON + CORS 头
        response = JSONResponse(
            {"detail": f"内部错误：{type(exc).__name__} - {exc}"}, status_code=500)
    if "access-control-allow-origin" not in response.headers:
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Headers"] = "*"
        response.headers["Access-Control-Allow-Methods"] = "*"
    return response


# ================= 系统健康 =================
@app.get("/health", tags=["system"])
async def health():
    """健康检查：MCP 连接状态 + 密钥是否就绪 + 关键路径。"""
    return {
        "status": "ok",
        "service": "aiops-api",
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "mcp": mcp_client.health(),
        "deepseek_key": bool(load_api_key()),
        "inventory": str(INVENTORY_FILE),
        "audit_db": str(AUDIT_DB),
        "devices": DEVICES,
    }


@app.get("/api/mcp/health", tags=["system"])
async def mcp_health():
    """MCP 客户端单独状态（前端顶部指示灯会轮询它）。"""
    return mcp_client.health()


# ================= 设备 =================
@app.get("/api/devices", response_model=DeviceListResponse, tags=["device"])
async def list_devices(refresh: bool = Query(False, description="true = 跳过缓存强制重新探测")):
    """设备清单（读 inventory.json）+ SSH 实时在线状态（带 TTL 缓存 + 并发探测）。"""
    rows, cached, checked_at = await run_in_threadpool(probe_snapshot, refresh)
    devices = [{
        "name": row["name"],
        "ip": row.get("ip", "-"),
        "role": row.get("role", "未知设备"),
        "port": int(row.get("port", 22)),
        "online": bool(row.get("online")),
        "version": row.get("version", "-"),
        "latency_ms": row.get("latency_ms"),
        "error": row.get("error", ""),
    } for row in rows]
    online = sum(1 for item in devices if item["online"])
    return {
        "total": len(devices),
        "online": online,
        "offline": len(devices) - online,
        "cached": cached,
        "checked_at": checked_at,
        "devices": devices,
    }


@app.get("/api/devices/{name}", tags=["device"])
async def device_detail(name: str,
                        audit_it: bool = Query(True, description="是否写入审计日志")):
    """单台设备只读详情：版本 / 接口状态与计数 / CPU 负载 / 内存（经 MCP → SSH）。"""
    if name not in DEVICES:
        raise HTTPException(status_code=404,
                            detail=f"设备 {name} 不存在，可用设备：{DEVICES}")
    detail = await collect_device_detail(name, mcp_client)
    if audit_it:
        audit.log_action(name, "inspect_detail",
                         f"经 MCP 采集只读详情（接口 {DEFAULT_INTERFACE}）",
                         "SUCCESS" if detail.get("online") else "FAILED")
    return detail


# ================= AI 对话（核心链路）=================
@app.post("/api/chat", response_model=ChatResponse, tags=["ai"])
async def chat(payload: ChatRequest = Body(...)):
    """自然语言 → DeepSeek 意图识别 → MCP 工具（stdio → SSH）→ 中文总结。

    示例：{"message": "帮我查一下 R1 的 eth0 流量"}
    """
    text = (payload.message or "").strip()
    if not text:
        raise HTTPException(status_code=422, detail="message 不能为空")
    return await run_agent(text, payload.history, payload.session_id)


# ================= 审计日志 =================
@app.get("/api/audit-logs", response_model=AuditListResponse, tags=["audit"])
async def audit_logs(
    status: str | None = Query(None, description="SUCCESS / FAILED / PENDING"),
    device: str | None = Query(None, description="按设备名过滤"),
    keyword: str | None = Query(None, description="按动作/详情关键字模糊搜索"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    """从 SQLite 读取审计日志（时间倒序，带总数便于前端分页）。"""
    total, items = await run_in_threadpool(audit.query_logs, status, device, keyword,
                                           limit, offset)
    return {"total": int(total), "returned": len(items), "items": items}


# ================= 告警 =================
@app.get("/api/alerts", tags=["alert"])
async def list_alerts(
    level: str | None = Query(None, pattern="^(?i)(P0|P1|P2)$"),
    status: str | None = Query(None, pattern="^(?i)(ACTIVE|ACKED)$"),
    limit: int = Query(50, ge=1, le=500),
):
    """历史告警 + 分级统计（P0 不可达 / P1 严重 / P2 提示）。"""
    items = await run_in_threadpool(audit.list_alerts, level, status, limit)
    stats = await run_in_threadpool(audit.alert_stats)
    return {"items": items, "stats": stats}


@app.post("/api/alerts/{alert_id}/ack", tags=["alert"])
async def ack_alert(alert_id: int, payload: AckRequest | None = Body(default=None)):
    """确认单条告警，可附处置备注（与 Streamlit 控制台共用同一张 alerts 表）。"""
    note = (payload.note if payload else "") or ""
    ok = await run_in_threadpool(audit.ack_alert, alert_id, note)
    if not ok:
        raise HTTPException(status_code=404, detail="告警不存在或已被确认")
    return {"ok": True, "alert_id": alert_id, "message": "已确认"}


# ================= 控制台聚合统计 =================
@app.get("/api/stats", response_model=StatsResponse, tags=["system"])
async def stats():
    """控制台顶部数据卡：纳管设备 / 在线设备 / 未确认告警 / 审计记录。"""
    rows, _, _ = await run_in_threadpool(probe_snapshot, False)
    return {
        "devices_total": len(rows),
        "devices_online": sum(1 for row in rows if row.get("online")),
        "alerts_active": await run_in_threadpool(audit.count_alerts, "ACTIVE"),
        "alerts_total": await run_in_threadpool(audit.count_alerts, None),
        "audit_total": await run_in_threadpool(audit.count_logs),
        "audit_failed": await run_in_threadpool(audit.count_logs, "FAILED"),
    }


# ================= 流量 =================
@app.get("/api/traffic/{device}/{interface}", response_model=TrafficResponse,
         tags=["traffic"])
async def traffic(
    device: str,
    interface: str = DEFAULT_INTERFACE,
    gap: float = Query(1.0, ge=0.2, le=5.0, description="两次采样的间隔秒数"),
):
    """指定设备端口的流量统计：两次采样计数增量 → Mbps（经 MCP → SSH）。"""
    if device not in DEVICES:
        raise HTTPException(status_code=404,
                            detail=f"设备 {device} 不存在，可用设备：{DEVICES}")
    return await sample_traffic(device, interface, mcp_client, gap)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host=API_HOST, port=API_PORT, reload=False)
