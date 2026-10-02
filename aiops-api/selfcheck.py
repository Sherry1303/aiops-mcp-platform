# -*- coding: utf-8 -*-
"""aiops-api 自检脚本：验证 4 个核心接口 + CORS 预检 + 完整 AI 链路。

用法：
    python selfcheck.py                     # 快速检查（不触发 SSH 采样与 LLM）
    python selfcheck.py --full              # 含流量采样 + /api/chat 全链路（真实 DeepSeek + SSH）
    python selfcheck.py --base http://localhost:8000
"""
from __future__ import annotations

import argparse
import json
import sys
import time

import requests

# Windows 控制台默认 GBK，强制 UTF-8 输出，避免中文/符号打印时抛 UnicodeEncodeError
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

PASS, FAIL = 0, 0
FAILED_ITEMS: list[str] = []


def check(name: str, ok: bool, extra: str = "") -> bool:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  [PASS] {name}" + (f" —— {extra}" if extra else ""))
    else:
        FAIL += 1
        FAILED_ITEMS.append(name)
        print(f"  [FAIL] {name}" + (f" —— {extra}" if extra else ""))
    return ok


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://localhost:8000")
    parser.add_argument("--full", action="store_true", help="包含流量采样与 AI 对话全链路")
    parser.add_argument("--device", default="R1")
    parser.add_argument("--interface", default="eth0")
    args = parser.parse_args()
    base = args.base.rstrip("/")
    print(f"=== aiops-api 自检 · {base} · 全链路={args.full} · "
          f"{time.strftime('%Y-%m-%d %H:%M:%S')} ===")

    # ---------- 1. 健康检查 ----------
    print("\n== 1. 健康检查 /health ==")
    try:
        resp = requests.get(f"{base}/health", timeout=20)
        data = resp.json()
        check("HTTP 200", resp.status_code == 200, f"status={resp.status_code}")
        check("服务状态 ok", data.get("status") == "ok")
        check("MCP 长连接已建立", bool(data.get("mcp", {}).get("connected")),
              f"tools={data.get('mcp', {}).get('tools')}")
        check("DeepSeek 密钥已配置", bool(data.get("deepseek_key")))
        check("资产清单已加载", len(data.get("devices") or []) > 0,
              f"devices={data.get('devices')}")
    except Exception as exc:  # noqa: BLE001
        check("后端可访问", False, f"{type(exc).__name__}: {exc}")
        print("\n后端未启动？请先执行：uvicorn main:app --reload --port 8000")
        return 1

    # ---------- 2. CORS 预检 ----------
    print("\n== 2. CORS 预检（模拟浏览器从 5173 发起）==")
    origin = "http://localhost:5173"
    resp = requests.options(f"{base}/api/devices", headers={
        "Origin": origin,
        "Access-Control-Request-Method": "GET",
        "Access-Control-Request-Headers": "content-type",
    }, timeout=10)
    acao = resp.headers.get("access-control-allow-origin")
    check("预检返回 2xx", 200 <= resp.status_code < 300, f"status={resp.status_code}")
    check("Access-Control-Allow-Origin 存在", bool(acao), f"值={acao}")
    resp = requests.get(f"{base}/api/devices", headers={"Origin": origin}, timeout=60)
    check("实际请求带 CORS 头",
          resp.headers.get("access-control-allow-origin") == "*",
          f"值={resp.headers.get('access-control-allow-origin')}")
    print("  （浏览器侧请确认 axios 没有同时开启 withCredentials）")

    # ---------- 3. 设备清单 ----------
    print("\n== 3. 设备清单 /api/devices ==")
    data = resp.json()
    check("返回设备列表", isinstance(data.get("devices"), list) and data["total"] > 0,
          f"total={data.get('total')} online={data.get('online')}")
    for device in data.get("devices", []):
        print(f"    - {device['name']:>4} | {device['ip']:>15} | {device['role']:<8} | "
              f"{'● 在线' if device['online'] else '○ 离线'} | {device['version']}"
              + (f" | {device['error'][:60]}" if device.get("error") else ""))
    check("存在在线设备（否则后续链路无法验证）", data.get("online", 0) > 0,
          f"online={data.get('online')}")

    # ---------- 4. 审计日志 ----------
    print("\n== 4. 审计日志 /api/audit-logs ==")
    resp = requests.get(f"{base}/api/audit-logs", params={"limit": 5}, timeout=20)
    data = resp.json()
    check("HTTP 200 且结构正确",
          resp.status_code == 200 and isinstance(data.get("items"), list),
          f"total={data.get('total')} returned={data.get('returned')}")
    if data.get("items"):
        top = data["items"][0]
        print(f"    最新一条：{top['timestamp']} | {top['device_name']} | "
              f"{top['action']} | {top['status']}")


    # ---------- 5. 聚合统计 ----------
    print("\n== 5. 控制台统计 /api/stats ==")
    stats = requests.get(f"{base}/api/stats", timeout=60).json()
    check("四个数据卡片字段齐全",
          all(key in stats for key in ("devices_total", "devices_online",
                                       "alerts_active", "audit_total")),
          json.dumps(stats, ensure_ascii=False))

    # ---------- 6. 流量采样（可选）----------
    if args.full:
        print(f"\n== 6. 流量采样 /api/traffic/{args.device}/{args.interface} ==")
        resp = requests.get(f"{base}/api/traffic/{args.device}/{args.interface}",
                            params={"gap": 1.0}, timeout=90)
        data = resp.json()
        check("HTTP 200", resp.status_code == 200, f"status={resp.status_code}")
        check("返回真实计数" if data.get("online") else "设备离线时给出原因",
              (data.get("rx_bytes", 0) > 0) or bool(data.get("message")),
              f"RX={data.get('rx_bytes')}B TX={data.get('tx_bytes')}B "
              f"RX速率={data.get('rx_mbps')}Mbps state={data.get('state')}")

        # ---------- 7. AI 全链路 ----------
        print("\n== 7. AI 全链路 POST /api/chat ==")
        question = f"帮我查一下 {args.device} 的 {args.interface} 流量"
        print(f"    提问：{question}")
        started = time.time()
        resp = requests.post(f"{base}/api/chat", json={"message": question}, timeout=180)
        cost = time.time() - started
        data = resp.json()
        check("HTTP 200", resp.status_code == 200, f"status={resp.status_code}")
        tools = data.get("tool_calls") or []
        check("DeepSeek 发起了 MCP 工具调用", len(tools) > 0,
              f"tools={[t['name'] for t in tools]} 耗时={cost:.1f}s")
        check("工具确实经 MCP 返回了内容",
              any(len(t.get("result", "")) > 0 for t in tools),
              f"status={[t['status'] for t in tools]}")
        reply = data.get("reply", "")
        check("最终回复非空", len(reply) > 10, f"{len(reply)} 字")
        check("回复提及目标设备或端口",
              args.device.lower() in reply.lower()
              or args.interface.lower() in reply.lower())
        print("\n    ---- AI 回复 ----")
        print("    " + reply.replace("\n", "\n    "))
        if tools:
            print("\n    ---- MCP 工具原始返回（截断）----")
            print("    " + tools[0].get("result", "")[:600].replace("\n", "\n    "))

    print(f"\n=== 结果：通过 {PASS} 项 · 失败 {FAIL} 项 ===")
    if FAILED_ITEMS:
        print("失败项：" + "、".join(FAILED_ITEMS))
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
