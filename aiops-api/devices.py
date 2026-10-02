# -*- coding: utf-8 -*-
"""设备资产层：读取 inventory.json、SSH 探测在线状态、解析设备原始输出。

链路：FastAPI → server.py(MCP/stdio) → paramiko SSH → 真实设备
本模块只做「资产 + 探测 + 解析」，不含任何 LLM 逻辑。
"""
from __future__ import annotations

import json
import re
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import paramiko

from config import (DEFAULT_INTERFACE, ERROR_MARKS, INVENTORY_FILE,
                    PROBE_CACHE_TTL, PROBE_TIMEOUT)

# ================= 资产清单（与 server.py 的加载逻辑保持一致）=================
DEFAULT_DEVICE = {
    "host": "192.168.56.10",
    "role": "核心路由器",
    "port": 22,
    "user": "vyos",
    "pass": "123456",
}


def load_inventory() -> dict:
    """读取 inventory.json；文件缺失/损坏时回落到默认单机拓扑。"""
    default = {"R1": dict(DEFAULT_DEVICE)}
    if not INVENTORY_FILE.exists():
        return default
    try:
        data = json.loads(INVENTORY_FILE.read_text(encoding="utf-8"))
        parsed = {}
        for name, info in (data.get("devices") or {}).items():
            parsed[name] = {
                "host": info.get("ip") or info.get("host"),
                "port": int(info.get("port", 22)),
                "user": info.get("user", "vyos"),
                "pass": info.get("pass", "123456"),
                "role": info.get("role", "未知设备"),
            }
        return parsed or default
    except Exception:  # noqa: BLE001 —— 资产文件异常不应拖垮后端
        return default


TOPOLOGY = load_inventory()
DEVICES = list(TOPOLOGY)


def device_meta(name: str) -> dict | None:
    """返回设备的连接元数据（含管理 IP / 端口 / 角色）。"""
    info = TOPOLOGY.get(name)
    if not info:
        return None
    return {
        "name": name,
        "ip": info["host"],
        "role": info["role"],
        "port": info["port"],
        "user": info["user"],
    }


# ================= 原始输出解析（正则与旧控制台完全一致，实测可用）=================
def is_error_output(raw: str) -> bool:
    """判断 MCP/SSH 返回是否为失败信息（离线、超时、异常、安全拒绝）。"""
    return any(mark in (raw or "") for mark in ERROR_MARKS)


def parse_version(raw: str) -> str:
    """show version → 版本号；Linux 容器的 /etc/os-release → PRETTY_NAME。"""
    text = raw or ""
    match = re.search(r"PRETTY_NAME=\"?([^\"\n]+)", text)
    if match:
        return match.group(1).strip()
    match = re.search(r"Version:\s*(.+)", text)
    if match:
        return match.group(1).strip()
    match = re.search(r"^VERSION=\"?([^\"\n]+)", text, re.MULTILINE)
    return match.group(1).strip() if match else "-"


def parse_uptime(raw: str) -> dict:
    """show system uptime → 运行时长 + 1/5/15 分钟负载百分比（VyOS 用负载表达 CPU 压力）。"""
    info = {"uptime": "-", "load1": None, "load5": None, "load15": None}
    match = re.search(r"Uptime:\s*(.+)", raw or "")
    if match:
        info["uptime"] = match.group(1).strip()
    for key, pattern in (("load1", r"1\s+minute:\s*([\d.]+)%"),
                         ("load5", r"5\s+minutes:\s*([\d.]+)%"),
                         ("load15", r"15\s+minutes:\s*([\d.]+)%")):
        match = re.search(pattern, raw or "")
        if match:
            try:
                info[key] = float(match.group(1))
            except ValueError:
                info[key] = None
    if info["uptime"] == "-":
        match = re.search(r"up\s+([^,]+),\s+(\d+)\s+user", raw or "")
        if match:
            info["uptime"] = match.group(1).strip()
    return info


UNIT_TO_MB = {"b": 1 / 1024 / 1024, "kb": 1 / 1024, "mb": 1.0,
              "gb": 1024.0, "tb": 1024.0 * 1024}


def _to_mb(number: str, unit: str):
    try:
        return float(number) * UNIT_TO_MB.get((unit or "mb").lower(), 1.0)
    except (TypeError, ValueError):
        return None


def parse_memory(raw: str) -> dict:
    """show system memory → 总量 / 空闲 / 使用（MB）+ 使用率。"""
    info = {"total_mb": None, "free_mb": None, "used_mb": None, "percent": None}
    for key in ("total", "free", "used"):
        match = re.search(rf"{key}:\s*([\d.]+)\s*(B|KB|MB|GB|TB)", raw or "", re.IGNORECASE)
        if match:
            info[f"{key}_mb"] = _to_mb(match.group(1), match.group(2))
    if info["total_mb"] and info["used_mb"]:
        info["percent"] = round(info["used_mb"] / info["total_mb"] * 100, 1)
    return info


def parse_interface(raw: str, ifname: str = DEFAULT_INTERFACE) -> dict:
    """show interfaces / ip -s link 输出 → 链路状态、地址、RX/TX 字节与错误包。"""
    info = {"state": "-", "address": "-", "rx_bytes": None, "tx_bytes": None,
            "rx_errors": None, "tx_errors": None, "rx_packets": None, "tx_packets": None}
    text = raw or ""
    match = re.search(rf"^{re.escape(ifname)}:.*?state\s+(\w+)", text, re.MULTILINE)
    if match:
        info["state"] = match.group(1).upper()
    else:
        match = re.search(rf"{re.escape(ifname)}\s+is\s+(\w+)", text)
        if match:
            info["state"] = match.group(1).upper()
    match = re.search(r"\binet\s+([\d.]+/\d+)", text)
    if match:
        info["address"] = match.group(1)
    for key, pattern in (("rx", r"RX:\s*bytes.*?\n\s*([\d.]+)\s+([\d.]+)\s+([\d.]+)"),
                         ("tx", r"TX:\s*bytes.*?\n\s*([\d.]+)\s+([\d.]+)\s+([\d.]+)")):
        match = re.search(pattern, text, re.DOTALL)
        if match:
            try:
                info[f"{key}_bytes"] = int(float(match.group(1)))
                info[f"{key}_packets"] = int(float(match.group(2)))
                info[f"{key}_errors"] = int(float(match.group(3)))
            except ValueError:
                pass
    if info["state"] == "-":
        match = re.search(rf"{re.escape(ifname)}.*?(\bUP\b|\bDOWN\b|state\s+(\w+))", text)
        if match:
            info["state"] = (match.group(2) or match.group(1)).upper()
    return info


def parse_traffic(output: str, ifname: str = DEFAULT_INTERFACE) -> tuple[int, int]:
    """取 (RX 字节, TX 字节)。"""
    info = parse_interface(output, ifname)
    return info["rx_bytes"] or 0, info["tx_bytes"] or 0


# ================= SSH 在线探测（并发 + TTL 缓存）=================
def _probe_over_ssh(name: str) -> dict:
    """直连 SSH 探测单台设备：TCP 预检 → 登录 → 取系统版本。"""
    meta = device_meta(name)
    if not meta:
        return {"name": name, "ip": "-", "role": "-", "port": 22, "online": False,
                "version": "-", "latency_ms": None,
                "error": f"设备不在资产清单中（可用：{DEVICES}）"}

    # ① TCP 预检：离线设备 2 秒内失败，不必白等 SSH 超时
    try:
        with socket.create_connection((meta["ip"], meta["port"]),
                                     timeout=min(2.0, PROBE_TIMEOUT)):
            pass
    except OSError as exc:
        return {**meta, "online": False, "version": "-", "latency_ms": None,
                "error": f"TCP {meta['ip']}:{meta['port']} 不可达（{type(exc).__name__}）"}

    started = time.perf_counter()
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        ssh.connect(meta["ip"], meta["port"], meta["user"], TOPOLOGY[name]["pass"],
                    look_for_keys=False, allow_agent=False, timeout=PROBE_TIMEOUT,
                    banner_timeout=PROBE_TIMEOUT, auth_timeout=PROBE_TIMEOUT)
        detect = "test -f /opt/vyatta/bin/vyatta-op-cmd-wrapper && echo vyos || echo linux"
        _, stdout, _ = ssh.exec_command(detect, timeout=PROBE_TIMEOUT)
        os_type = stdout.read().decode(errors="ignore").strip()
        cmd = ("cat /etc/os-release" if os_type == "linux"
               else "/opt/vyatta/bin/vyatta-op-cmd-wrapper show version")
        _, stdout, _ = ssh.exec_command(cmd, timeout=PROBE_TIMEOUT)
        raw = stdout.read().decode("utf-8", errors="ignore")
    except Exception as exc:  # noqa: BLE001 —— 探测失败只记录，不抛给调用方
        return {**meta, "online": False, "version": "-", "latency_ms": None,
                "error": f"SSH 失败：{type(exc).__name__} - {exc}"}
    finally:
        ssh.close()

    online = bool((raw or "").strip()) and not is_error_output(raw)
    return {**meta, "online": online, "version": parse_version(raw) if online else "-",
            "latency_ms": int((time.perf_counter() - started) * 1000) if online else None,
            "error": "" if online else ((raw or "").strip()[:200] or "SSH 无输出")}


_probe_cache: dict = {"ts": 0.0, "devices": {}, "checked_at": ""}
_probe_lock = threading.Lock()


def probe_snapshot(force: bool = False) -> tuple[list[dict], bool, str]:
    """并发探测全部设备；PROBE_CACHE_TTL 内直接复用缓存。

    返回 (设备列表, 是否命中缓存, 探测时间)。
    """
    now = time.time()
    with _probe_lock:
        fresh = _probe_cache["devices"] and now - _probe_cache["ts"] < PROBE_CACHE_TTL
        if fresh and not force:
            return list(_probe_cache["devices"].values()), True, _probe_cache["checked_at"]

    if not DEVICES:
        return [], False, datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 并发探测：离线设备互不阻塞
    with ThreadPoolExecutor(max_workers=min(8, max(1, len(DEVICES)))) as pool:
        rows = list(pool.map(_probe_over_ssh, DEVICES))
    data = {row["name"]: row for row in rows}
    checked_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with _probe_lock:
        _probe_cache.update({"ts": time.time(), "devices": data, "checked_at": checked_at})
    return list(data.values()), False, checked_at


# ================= 只读采集（经 MCP → SSH，与对话链路复用同一条通道）=================
DETAIL_CMDS = (
    ("version", "show version"),
    ("interface", f"show interfaces ethernet {DEFAULT_INTERFACE}"),
    ("cpu", "show system uptime"),        # VyOS 用负载百分比表达 CPU 压力
    ("memory", "show system memory"),
)


async def collect_device_detail(name: str, mcp) -> dict:
    """经 MCP Server 采集一台设备的只读详情（4 条 show 命令，全部只读）。

    首条命令失败即中断，避免离线设备连续 4 次 SSH 超时。
    """
    meta = device_meta(name)
    if not meta:
        return {"name": name, "online": False, "error": f"设备 {name} 不存在，可用：{DEVICES}"}

    detail: dict = {"name": name, "ip": meta["ip"], "role": meta["role"], "port": meta["port"],
                    "online": True, "error": "", "raw": {},
                    "collected_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    for key, cmd in DETAIL_CMDS:
        raw = await mcp.call_tool("query_device", {"device_name": name, "command_name": cmd})
        detail["raw"][key] = raw
        if is_error_output(raw):
            detail.update({"online": False, "error": raw.strip()[:200]})
            break

    iface = parse_interface(detail["raw"].get("interface", ""), DEFAULT_INTERFACE)
    uptime = parse_uptime(detail["raw"].get("cpu", ""))
    memory = parse_memory(detail["raw"].get("memory", ""))
    version_raw = detail["raw"].get("version", "")
    detail.update({
        "version": parse_version(version_raw) if version_raw else "-",
        "state": iface["state"],
        "address": iface["address"],
        "rx_bytes": iface["rx_bytes"] or 0,
        "tx_bytes": iface["tx_bytes"] or 0,
        "rx_errors": iface["rx_errors"] or 0,
        "tx_errors": iface["tx_errors"] or 0,
        "uptime": uptime["uptime"],
        "cpu_percent": uptime["load1"],
        "memory_percent": memory["percent"],
        "memory_used_mb": memory["used_mb"],
        "memory_total_mb": memory["total_mb"],
    })
    return detail


async def sample_traffic(name: str, interface: str, mcp, gap: float = 1.0) -> dict:
    """两次采样 RX/TX 计数增量，换算成 Mbps（走 MCP 的 monitor_traffic 工具）。"""
    import asyncio

    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    first = await mcp.call_tool("monitor_traffic",
                                {"device_name": name, "interface": interface})
    if is_error_output(first):
        return {"device": name, "interface": interface, "online": False, "state": "-",
                "rx_bytes": 0, "tx_bytes": 0, "rx_delta": 0, "tx_delta": 0,
                "rx_mbps": 0.0, "tx_mbps": 0.0, "rx_errors": 0, "tx_errors": 0,
                "sample_gap": 0.0, "timestamp": stamp,
                "message": first.strip()[:200], "raw_preview": (first or "")[:600]}

    started = time.perf_counter()
    await asyncio.sleep(max(0.2, float(gap)))
    second = await mcp.call_tool("monitor_traffic",
                                 {"device_name": name, "interface": interface})
    elapsed = max(time.perf_counter() - started, 0.001)

    first_info = parse_interface(first, interface)
    info = parse_interface(second, interface)
    rx1, tx1 = first_info["rx_bytes"] or 0, first_info["tx_bytes"] or 0
    rx2, tx2 = info["rx_bytes"] or 0, info["tx_bytes"] or 0
    return {
        "device": name,
        "interface": interface,
        "online": True,
        "state": info["state"],
        "address": info["address"],
        "rx_bytes": rx2,
        "tx_bytes": tx2,
        "rx_delta": max(rx2 - rx1, 0),
        "tx_delta": max(tx2 - tx1, 0),
        "rx_mbps": round(max(rx2 - rx1, 0) * 8 / 1_000_000 / elapsed, 4),
        "tx_mbps": round(max(tx2 - tx1, 0) * 8 / 1_000_000 / elapsed, 4),
        "rx_errors": info["rx_errors"] or 0,
        "tx_errors": info["tx_errors"] or 0,
        "sample_gap": round(elapsed, 3),
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "message": "",
        "raw_preview": (second or "")[:600],
    }
