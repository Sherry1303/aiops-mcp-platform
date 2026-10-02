# -*- coding: utf-8 -*-
"""AI Agent：DeepSeek 意图识别 → MCP 工具调用 → 二次总结，产出最终回复。

完整链路：
    前端 POST /api/chat
      → DeepSeek（deepseek-chat，function calling 判定意图）
      → MCPClient.call_tool（stdio 传输 → server.py 的 @mcp.tool）
      → paramiko SSH → 真实设备
      → 结果回填对话 → DeepSeek 生成中文总结 → 返回前端
"""
from __future__ import annotations

import json
import time

from openai import AsyncOpenAI

from audit import log_action
from config import (DEEPSEEK_BASE_URL, DEEPSEEK_MODEL, LLM_TIMEOUT, MAX_HISTORY,
                    MAX_TOOL_ROUNDS, load_api_key)
from devices import DEVICES, is_error_output
from mcp_client import WRITE_TOOLS, mcp_client

SYSTEM_PROMPT = f"""你是 AIOps 智能运维助手，服务于一个「MCP + VyOS + DeepSeek」的网络自动化平台。

工作方式：
1. 先用一句话说明你打算做什么，再调用工具获取真实数据，禁止凭经验编造设备状态。
2. 只读查询一律使用 query_device（命令必须以 show 开头）或 monitor_traffic；
   需要设备清单时用 get_topology。
3. configure_interface 属于危险写操作，会被安全门拦截并进入管理员审批队列，
   你只需如实告知用户「已提交审批、尚未下发」。
4. 拿到工具结果后，用简洁的中文 Markdown 作答：先给结论，再列关键指标
   （流量用 bytes/Mbps、CPU 用百分比、内存用百分比），最后可给一条运维建议。
5. 若工具返回错误或设备离线，要明确说明是哪台设备不可达，不要隐藏错误。

当前纳管设备：{", ".join(DEVICES) if DEVICES else "（未加载到资产清单）"}。
"""

_client: AsyncOpenAI | None = None
_client_key: str = ""


def get_client() -> AsyncOpenAI:
    """惰性创建 AsyncOpenAI 客户端（密钥变化时自动重建）。"""
    global _client, _client_key
    key = load_api_key()
    if _client is None or key != _client_key:
        _client = AsyncOpenAI(api_key=key or "not-configured",
                              base_url=DEEPSEEK_BASE_URL, timeout=LLM_TIMEOUT)
        _client_key = key
    return _client


def build_messages(message: str, history=None) -> list[dict]:
    """拼装发给 DeepSeek 的消息：system + 最近的对话历史 + 本轮提问。"""
    messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
    for item in (history or [])[-MAX_HISTORY:]:
        role = item.role if hasattr(item, "role") else item.get("role", "user")
        content = item.content if hasattr(item, "content") else item.get("content", "")
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": message})
    return messages


def _dump_tool_calls(tool_calls) -> list[dict]:
    """把 openai 的 tool_calls 对象转成可回填的纯 dict（兼容不同版本字段）。"""
    dumped = []
    for call in tool_calls:
        dumped.append({
            "id": call.id,
            "type": "function",
            "function": {
                "name": call.function.name,
                "arguments": call.function.arguments or "{}",
            },
        })
    return dumped


async def run_agent(message: str, history=None, session_id: str = "web") -> dict:
    """执行一轮完整链路，返回可直接序列化为 ChatResponse 的字典。"""
    started = time.perf_counter()
    records: list[dict] = []
    pending: dict | None = None
    rounds = 0

    def _pack(reply: str) -> dict:
        return {
            "reply": reply,
            "model": DEEPSEEK_MODEL,
            "rounds": rounds,
            "elapsed_ms": int((time.perf_counter() - started) * 1000),
            "tool_calls": records,
            "pending_approval": pending,
        }

    if not load_api_key():
        return _pack("未检测到 DeepSeek 密钥：请在 aiops-api 的 .env 里配置 "
                     "DEEPSEEK_API_KEY（或设置同名环境变量）后重启后端。")

    # 每次 AI 对话都留痕，便于审计页追溯「谁在什么时候问了什么」
    log_action("-", "chat", f"[{session_id}] {message[:180]}", "SUCCESS")
    messages = build_messages(message, history)
    client = get_client()
    reply = ""

    try:
        for round_no in range(1, MAX_TOOL_ROUNDS + 1):
            rounds = round_no
            completion = await client.chat.completions.create(
                model=DEEPSEEK_MODEL,
                messages=messages,
                tools=mcp_client.tool_schemas(),
                tool_choice="auto",
            )
            choice = completion.choices[0].message
            if not choice.tool_calls:
                reply = (choice.content or "").strip() or "(模型未返回内容)"
                break

            messages.append({"role": "assistant", "content": choice.content or "",
                             "tool_calls": _dump_tool_calls(choice.tool_calls)})

            for call in choice.tool_calls:
                name = call.function.name
                try:
                    args = json.loads(call.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}
                stamp = time.perf_counter()

                if name in WRITE_TOOLS:
                    # 安全门：写操作不下发，仅入审批意图
                    result = ("【安全门】该操作属于写操作，已拦截并进入管理员审批队列，"
                              "未下发到设备。")
                    status = "PENDING_APPROVAL"
                    log_action(args.get("device_name", "-"), name,
                               f"{args}（等待管理员审批）", "PENDING")
                    pending = {"tool": name, "arguments": args,
                               "reason": "写操作需管理员审批，已拦截，未下发到设备"}
                else:
                    result = await mcp_client.call_tool(name, args)
                    status = "FAILED" if is_error_output(result) else "SUCCESS"
                    log_action(args.get("device_name") or "-", name,
                               f"{args} → {result[:180]}", status)

                records.append({
                    "name": name,
                    "arguments": args,
                    "result": result[:4000],
                    "status": status,
                    "elapsed_ms": int((time.perf_counter() - stamp) * 1000),
                    "transport": "mcp:stdio",
                })
                messages.append({"role": "tool", "tool_call_id": call.id,
                                 "content": f"执行结果：\n{result}"})

        if not reply:
            # 工具轮次用尽 → 再补一次不带工具的总结，保证用户一定拿到答复
            summary = await client.chat.completions.create(
                model=DEEPSEEK_MODEL, messages=messages)
            reply = (summary.choices[0].message.content or "").strip() \
                or "(已达到最大工具调用轮次，请换个说法再问)"
    except Exception as exc:  # noqa: BLE001 —— LLM 侧异常要回显给前端而不是 500
        reply = f"AI 调用出错：{type(exc).__name__} - {exc}"
        log_action("-", "chat_error", f"{message[:120]} → {exc}", "FAILED")

    return _pack(reply)

