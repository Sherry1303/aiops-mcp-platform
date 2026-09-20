import asyncio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def call_mcp_tool(tool_name: str, arguments: dict):
    """调用本地 MCP Server 的工具"""
    server_params = StdioServerParameters(
        command="python",
        args=["D:\\mcp-vyos\\server.py"],
        env=None
    )
    
    try:
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(tool_name, arguments=arguments)
                if result.content:
                    return result.content[0].text
                return "执行成功，无返回值。"
    except BaseException as e:  # 核心修复：捕获 Python 3.11 的 ExceptionGroup
        return f"执行失败: {str(e)}"