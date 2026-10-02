# -*- coding: utf-8 -*-
"""MCPClient —— 把现有 MCP Server（server.py，stdio 传输）封装成一个 Python 类。

设计要点：
1. 正常情况下保持一条【长连接会话】：FastAPI lifespan 启动时握手，进程退出时优雅关闭，
   避免每次请求都重新拉起 python 子进程（旧版 mcp_client.py 就是每次调一次，慢）。
2. 任何一次调用失败都会自动重连；重连仍失败则退化为【一次性 stdio 会话】兜底，
   保证「连接异常」不会变成「功能不可用」。
3. 全程不伪造数据：MCP 调用失败一律把错误原文返回给上层与前端。
"""
from __future__ import annotations

import asyncio
import os
from contextlib import AsyncExitStack
from datetime import datetime, timezone

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from config import MCP_CALL_TIMEOUT, MCP_SERVER_SCRIPT, PYTHON_EXE

# ================= 工具声明（与 server.py 的 @mcp.tool 完全对齐）=================
# 供 DeepSeek function calling 使用；WRITE_TOOLS 里的工具属于写操作，会被安全门拦截。
TOOL_SCHEMAS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "get_topology",
            "description": "获取全部纳管设备的清单（设备名、管理 IP、角色）",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_device",
            "description": "查询网络设备的只读状态，支持 show 命令（如 show version、show interfaces）",
            "parameters": {
                "type": "object",
                "properties": {
                    "device_name": {"type": "string", "description": "设备名，例如 R1、SW1"},
                    "command_name": {"type": "string",
                                     "description": "查询命令，必须以 show 开头，例如 show version"},
                },
                "required": ["device_name", "command_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "configure_interface",
            "description": "开启或关闭某个端口。危险写操作，需管理员审批（后端会拦截，不会直接下发）",
            "parameters": {
                "type": "object",
                "properties": {
                    "device_name": {"type": "string", "description": "设备名，例如 R1"},
                    "interface": {"type": "string", "description": "端口名，例如 eth1"},
                    "action": {"type": "string", "enum": ["enable", "disable"],
                               "description": "开启还是关闭"},
                },
                "required": ["device_name", "interface", "action"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "monitor_traffic",
            "description": "监控指定端口的流量统计（RX/TX 字节与错误包）",
            "parameters": {
                "type": "object",
                "properties": {
                    "device_name": {"type": "string", "description": "设备名，例如 R1"},
                    "interface": {"type": "string", "description": "端口名，例如 eth0"},
                },
                "required": ["device_name", "interface"],
            },
        },
    },
]

WRITE_TOOLS = {"configure_interface"}


class MCPClient:
    """stdio 传输的 MCP 客户端（长连接 + 自动重连 + 一次性会话兜底）。"""

    def __init__(self, script_path=None, python_exe: str | None = None,
                 timeout: float = MCP_CALL_TIMEOUT) -> None:
        self.script_path = script_path or MCP_SERVER_SCRIPT
        self.python_exe = python_exe or PYTHON_EXE
        self.timeout = float(timeout)
        self._stack: AsyncExitStack | None = None
        self._session: ClientSession | None = None
        self._lock = asyncio.Lock()
        self._tools: list[str] = []
        self.started_at: str = ""
        self.last_error: str = ""
        self.call_count = 0
        self.reconnect_count = 0

    # ---------- 生命周期 ----------
    @property
    def connected(self) -> bool:
        return self._session is not None

    def _params(self) -> StdioServerParameters:
        """子进程参数：继承当前环境（保证能 import paramiko / mcp）+ UTF-8 输出。"""
        env = dict(os.environ)
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUNBUFFERED"] = "1"
        return StdioServerParameters(command=self.python_exe,
                                     args=[str(self.script_path)], env=env)

    async def start(self) -> bool:
        """建立长连接会话并握手；成功返回 True。"""
        if self._session is not None:
            return True
        if not self.script_path.exists():
            self.last_error = f"MCP Server 脚本不存在：{self.script_path}"
            return False
        try:
            self._stack = AsyncExitStack()
            read, write = await self._stack.enter_async_context(stdio_client(self._params()))
            self._session = await self._stack.enter_async_context(ClientSession(read, write))
            await asyncio.wait_for(self._session.initialize(), timeout=self.timeout)
            listed = await asyncio.wait_for(self._session.list_tools(), timeout=self.timeout)
            self._tools = [tool.name for tool in listed.tools]
            self.started_at = datetime.now(timezone.utc).astimezone().strftime(
                "%Y-%m-%d %H:%M:%S")
            self.last_error = ""
            return True
        except BaseException as exc:  # noqa: BLE001 —— Python 3.11+ 可能是 ExceptionGroup
            self.last_error = f"{type(exc).__name__}: {exc}"
            await self.stop()
            return False

    async def stop(self) -> None:
        """关闭会话（关闭失败不影响进程退出）。"""
        self._session = None
        stack, self._stack = self._stack, None
        if stack is not None:
            try:
                await stack.aclose()
            except BaseException as exc:  # noqa: BLE001
                self.last_error = f"关闭 MCP 会话时出错：{type(exc).__name__}: {exc}"

    async def _reconnect(self) -> bool:
        await self.stop()
        self.reconnect_count += 1
        return await self.start()

    # ---------- 工具调用 ----------
    @staticmethod
    async def _read_result(session: ClientSession, name: str, args: dict) -> str:
        """发起一次 call_tool 并把 content 拼成纯文本。"""
        result = await session.call_tool(name, arguments=args or {})
        texts = [item.text for item in (getattr(result, "content", None) or [])
                 if getattr(item, "text", None)]
        if texts:
            return "\n".join(texts)
        if getattr(result, "isError", False):
            return f"工具 {name} 返回错误，但无文本内容。"
        return "执行成功，无返回值。"

    async def _ephemeral_call(self, name: str, args: dict, timeout: float) -> str:
        """兜底方案：每次调用都新起一个 MCP Server 子进程（与旧 mcp_client.py 等价）。"""
        async with stdio_client(self._params()) as (read, write):
            async with ClientSession(read, write) as session:
                await asyncio.wait_for(session.initialize(), timeout=timeout)
                return await asyncio.wait_for(self._read_result(session, name, args), timeout)

    async def call_tool(self, name: str, args: dict | None = None,
                        timeout: float | None = None) -> str:
        """调用 MCP 工具，返回文本结果；失败时返回以「MCP调用失败」开头的说明。"""
        args = args or {}
        wait = float(timeout or self.timeout)
        async with self._lock:                      # 单会话串行，避免 stdio 消息错帧
            self.call_count += 1
            if self._session is None:
                await self._reconnect()
            if self._session is not None:
                for attempt in (1, 2):              # 第一次失败 → 重连后再试一次
                    try:
                        return await asyncio.wait_for(
                            self._read_result(self._session, name, args), timeout=wait)
                    except BaseException as exc:    # noqa: BLE001
                        self.last_error = f"{name} 调用异常：{type(exc).__name__}: {exc}"
                        if attempt == 2:
                            break
                        await self._reconnect()
            # 长连接不可用 → 走一次性会话兜底
            try:
                return await self._ephemeral_call(name, args, wait)
            except BaseException as exc:            # noqa: BLE001
                self.last_error = f"{type(exc).__name__}: {exc}"
                return f"MCP调用失败: {self.last_error}"

    # ---------- 元信息 ----------
    async def list_tools(self) -> list[str]:
        if self._session is None:
            await self._reconnect()
        return list(self._tools)

    def tool_schemas(self) -> list[dict]:
        """返回给 DeepSeek 的工具声明（与 server.py 对齐，可在运行时校验）。"""
        return TOOL_SCHEMAS

    def health(self) -> dict:
        return {
            "connected": self.connected,
            "server_script": str(self.script_path),
            "python": self.python_exe,
            "tools": self._tools,
            "transport": "stdio",
            "started_at": self.started_at,
            "calls": self.call_count,
            "reconnects": self.reconnect_count,
            "last_error": self.last_error,
        }


# 全局单例：main.py 在 lifespan 里 start/stop，agent.py 直接复用
mcp_client = MCPClient()

