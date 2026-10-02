# -*- coding: utf-8 -*-
"""aiops-api 全局配置。

本后端不复制任何数据，直接对接现有的 MCP 生态（默认目录 D:\\mcp-vyos）：
    server.py       MCP Server（stdio 传输）
    inventory.json  设备资产
    audit.db        SQLite 审计库 / 告警库

所有路径都可以用环境变量覆盖，便于部署到别的机器：
    AIOPS_LEGACY_DIR  MCP 生态根目录（默认 D:\\mcp-vyos）
    AIOPS_MCP_SERVER  MCP Server 脚本路径
    AIOPS_INVENTORY   设备清单 JSON
    AIOPS_AUDIT_DB    审计 SQLite 路径
    AIOPS_PYTHON      拉起 MCP Server 的 Python 解释器（默认当前解释器）
    DEEPSEEK_API_KEY  DeepSeek 密钥
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


def _load_dotenv() -> None:
    """极简 .env 加载器（零依赖）：只写入尚未存在的环境变量。"""
    path = BASE_DIR / ".env"
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv()

# ================= 路径 =================
LEGACY_DIR = Path(os.getenv("AIOPS_LEGACY_DIR", r"D:\mcp-vyos"))
MCP_SERVER_SCRIPT = Path(os.getenv("AIOPS_MCP_SERVER", str(LEGACY_DIR / "server.py")))
INVENTORY_FILE = Path(os.getenv("AIOPS_INVENTORY", str(LEGACY_DIR / "inventory.json")))
AUDIT_DB = Path(os.getenv("AIOPS_AUDIT_DB", str(LEGACY_DIR / "audit.db")))
SECRETS_FILE = LEGACY_DIR / ".streamlit" / "secrets.toml"
PYTHON_EXE = os.getenv("AIOPS_PYTHON", sys.executable or "python")

# ================= 服务 =================
API_HOST = os.getenv("AIOPS_HOST", "0.0.0.0")
API_PORT = int(os.getenv("AIOPS_PORT", "8000"))
CORS_ORIGINS = [o.strip() for o in os.getenv("AIOPS_CORS_ORIGINS", "*").split(",") if o.strip()]

# ================= DeepSeek =================
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
LLM_TIMEOUT = float(os.getenv("AIOPS_LLM_TIMEOUT", "60"))
MAX_TOOL_ROUNDS = int(os.getenv("AIOPS_MAX_TOOL_ROUNDS", "3"))
MAX_HISTORY = int(os.getenv("AIOPS_MAX_HISTORY", "12"))

# ================= 采集 =================
DEFAULT_INTERFACE = os.getenv("AIOPS_DEFAULT_IFACE", "eth0")
PROBE_TIMEOUT = float(os.getenv("AIOPS_PROBE_TIMEOUT", "4"))
PROBE_CACHE_TTL = float(os.getenv("AIOPS_PROBE_TTL", "15"))
DETAIL_CACHE_TTL = float(os.getenv("AIOPS_DETAIL_TTL", "10"))
MCP_CALL_TIMEOUT = float(os.getenv("AIOPS_MCP_TIMEOUT", "45"))

# 探测失败特征串（与 Streamlit 控制台保持一致，可兜住编码异常场景）
ERROR_MARKS = (
    "SSH执行出错", "SSH失败", "TimeoutError", "timed out", "timeout",
    "MCP调用失败", "执行失败", "Traceback", "不存在", "安全拒绝",
)


def load_api_key() -> str:
    """密钥顺序：环境变量 DEEPSEEK_API_KEY → .env → 旧控制台的 secrets.toml。"""
    key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if key:
        return key
    if SECRETS_FILE.exists():
        match = re.search(r'DEEPSEEK_API_KEY\s*=\s*["\']([^"\']+)["\']',
                          SECRETS_FILE.read_text(encoding="utf-8", errors="ignore"))
        if match:
            return match.group(1).strip()
    return ""
