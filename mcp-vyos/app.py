# -*- coding: utf-8 -*-
"""
AIOps 智能网络运维控制台 —— Streamlit 单文件入口

视觉层（Glass / Light 设计系统；CSS 由本文件 inject_css() 注入，令牌与 .streamlit/config.toml 对应）：
    画布   linear-gradient(135deg, #f5f7fa 0%, #e8ecf1 100%)（固定不滚动）
    字体   Inter（Google Fonts 注入；代码块使用等宽字体）
    卡片   .metric-card —— rgba(255,255,255,.8) 玻璃底 / 1px solid rgba(255,255,255,.5) 描边 /
           圆角 16px / padding 24px / 阴影 0 4px 20px rgba(0,0,0,.05) / 悬停 translateY(-4px) 并加深阴影
    图标   Feather 线性图标，全部以 CSS background-image（SVG data URI）内嵌，无图标字体依赖
    拓扑   Plotly 圆角矩形节点，在线 #4ECDC4 / 离线 #FF6B6B，悬停显示设备详情
    隐藏   #MainMenu / footer / header 默认装扮（仅保留侧边栏折叠按钮，避免侧栏无法收起）

功能层：
    01 AI 运维对话   自然语言 → MCP 工具调用 → SSH；写操作强制人工审批
    02 流量监控      真实 RX/TX 计数增量采样
    03 智能巡检      一键遍历设备，检查接口 / CPU / 内存，产出 Markdown 巡检报告
    04 告警中心      SQLite 历史告警，P0/P1/P2 级别筛选，标记已确认并可填写备注
    05 审计日志      全量留痕，支持按状态筛选与 CSV 导出
"""

import asyncio
import html
import json
import math
import os
import random
import re
import time
from contextlib import contextmanager
from datetime import datetime

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from openai import OpenAI

from audit_logger import (
    ack_alert,
    ack_all_alerts,
    get_alert_stats,
    get_alerts,
    get_all_logs,
    init_db,
    log_action,
    log_alert,
)
from mcp_client import call_mcp_tool

# ================= 页面与数据基础 =================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INVENTORY_FILE = os.path.join(BASE_DIR, "inventory.json")

st.set_page_config(
    page_title="AIOps 智能网络运维控制台",
    page_icon="🛰",
    layout="wide",
    initial_sidebar_state="expanded",
)
init_db()


def load_inventory() -> dict:
    """读取 inventory.json 生成设备清单；任何异常都降级为单机默认值，保证页面可用。"""
    default = {"R1": {"host": "192.168.56.10", "role": "核心路由器"}}
    try:
        with open(INVENTORY_FILE, "r", encoding="utf-8") as fp:
            devices = json.load(fp).get("devices", {})
        parsed = {
            name: {"host": info.get("ip", "-"), "role": info.get("role", "未知设备")}
            for name, info in devices.items()
        }
        return parsed or default
    except Exception:  # noqa: BLE001 —— 资产文件缺失/损坏时不影响页面启动
        return default


def load_api_key() -> str:
    """密钥读取顺序：.streamlit/secrets.toml（推荐） → 环境变量 DEEPSEEK_API_KEY。"""
    try:
        if "DEEPSEEK_API_KEY" in st.secrets:
            return str(st.secrets["DEEPSEEK_API_KEY"]).strip()
    except Exception:  # noqa: BLE001 —— 未创建 secrets.toml 时 st.secrets 会抛异常
        pass
    return os.getenv("DEEPSEEK_API_KEY", "").strip()


TOPOLOGY = load_inventory()
DEVICES = list(TOPOLOGY)
DEVICE_IFACE = "eth0"                     # 巡检/采样统一针对的接口
DEEPSEEK_API_KEY = load_api_key()
client = OpenAI(api_key=DEEPSEEK_API_KEY or "not-configured", base_url="https://api.deepseek.com")

# ---- 设计令牌（与 inject_css() 里的 CSS 变量、config.toml 三处保持一致）----
CANVAS_GRADIENT = "linear-gradient(135deg, #f5f7fa 0%, #e8ecf1 100%)"
ACCENT = "#4ECDC4"          # 主色 / 在线节点
ACCENT_DEEP = "#2f9e93"     # 主色加深（线框、文字强调）
DANGER = "#FF6B6B"          # 离线节点 / 致命告警
CHART_RX = "#4ECDC4"        # 流量图 RX
CHART_TX = "#5B8DEF"        # 流量图 TX
NODE_W, NODE_H, NODE_R = 0.46, 0.22, 0.06   # 拓扑圆角矩形节点的宽 / 高 / 圆角（数据坐标）

# 设备探测失败特征字符串（ASCII 特征可兜住极端编码场景）
ERROR_MARKS = (
    "SSH执行出错", "SSH失败", "TimeoutError", "timed out",
    "MCP调用失败", "执行失败", "Traceback", "不存在",
)

# ================= LLM 工具定义 =================
tools = [
    {
        "type": "function",
        "function": {
            "name": "query_device",
            "description": "查询网络设备的只读状态，支持 show 命令",
            "parameters": {
                "type": "object",
                "properties": {
                    "device_name": {"type": "string", "description": "设备名，例如 R1, SW1"},
                    "command_name": {"type": "string", "description": "查询命令，如 show interfaces, show ip route"}
                },
                "required": ["device_name", "command_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "configure_interface",
            "description": "开启或关闭某个端口。该操作属于危险操作，需管理员审批。",
            "parameters": {
                "type": "object",
                "properties": {
                    "device_name": {"type": "string", "description": "设备名，例如 R1"},
                    "interface": {"type": "string", "description": "端口名，例如 eth1"},
                    "action": {"type": "string", "enum": ["enable", "disable"], "description": "开启还是关闭"}
                },
                "required": ["device_name", "interface", "action"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "monitor_traffic",
            "description": "监控指定端口的流量统计",
            "parameters": {
                "type": "object",
                "properties": {
                    "device_name": {"type": "string", "description": "设备名，例如 R1"},
                    "interface": {"type": "string", "description": "端口名，例如 eth0"}
                },
                "required": ["device_name", "interface"]
            }
        }
    }
]

# ================= 视觉层：CSS 注入（st.markdown 注入，Inter + 浅色渐变 + Glass 卡片 + 线性图标） =================
# 卡片壳统一用 st.container(border=True, key="card_xxx") 生成（Streamlit 1.64+ 会把 key 变成 st-key-card_xxx 类），
# 卡片内容凡为 HTML 的，都在内部再套一层 <div class="metric-card">（内层用 .metric-card--inner 抵消重复描边）。
CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

:root{
  --canvas-from:#f5f7fa;      /* 渐变起点 */
  --canvas-to:#e8ecf1;        /* 渐变终点 */
  --glass:rgba(255,255,255,.8);
  --glass-border:rgba(255,255,255,.5);
  --card-radius:16px;
  --card-pad:24px;
  --shadow:0 4px 20px rgba(0,0,0,.05);
  --shadow-hover:0 18px 38px rgba(15,23,42,.14);
  --accent:#4ECDC4;           /* 在线 / 主色 */
  --accent-deep:#2f9e93;
  --danger:#FF6B6B;           /* 离线 / 致命 */
  --warn:#f59e0b;
  --info:#5B8DEF;
  --text:#1f2937;
  --muted:#6b7280;
  --line:#e3e9f0;
  --mono:'JetBrains Mono','Cascadia Code',Consolas,'Courier New',monospace;
}

/* ---------- 基础：Inter 字体 + 线性渐变画布 ---------- */
.stApp, .stApp *, [data-testid="stAppViewContainer"] *{
  font-family:'Inter','Segoe UI','Microsoft YaHei','PingFang SC',-apple-system,sans-serif !important;
}
.stApp code, .stApp pre, .stApp kbd, [data-testid="stCode"] *, .ax-console, .ax-mono{
  font-family:var(--mono) !important;
}
html, body{
  background:linear-gradient(135deg, #f5f7fa 0%, #e8ecf1 100%) !important;
  background-attachment:fixed !important;
  color:var(--text) !important;
}
.stApp, [data-testid="stAppViewContainer"], [data-testid="stMain"], [data-testid="stMainBlockContainer"]{
  background:linear-gradient(135deg, #f5f7fa 0%, #e8ecf1 100%) !important;
  background-attachment:fixed !important;
}
[data-testid="stMainBlockContainer"]{ padding-top:1.3rem; padding-bottom:3rem; max-width:1560px; }
[data-testid="stMarkdownContainer"] p{ line-height:1.75; color:var(--text); }
hr{ border-color:var(--line) !important; }
a{ color:var(--accent-deep) !important; }

/* ---------- 隐藏 Streamlit 默认装扮：主菜单 / 页脚 / 顶栏 ---------- */
#MainMenu, footer, [data-testid="stToolbar"], [data-testid="stDecoration"],
[data-testid="stStatusWidget"], [data-testid="stAppDeployButton"],
[data-testid="stHeaderActionElements"], [data-testid="stToolbarActions"]{
  display:none !important; visibility:hidden !important; height:0 !important;
}
header[data-testid="stHeader"]{
  background:transparent !important; box-shadow:none !important; border:0 !important;
}
/* 顶栏内容整体隐身，但保留侧边栏折叠/展开按钮，避免侧栏收起后无法再打开 */
header[data-testid="stHeader"] *{ visibility:hidden !important; }
[data-testid="stSidebarCollapseButton"], [data-testid="stSidebarCollapseButton"] *,
[data-testid="stExpandSidebarButton"], [data-testid="stExpandSidebarButton"] *{
  visibility:visible !important;
}

/* ---------- 滚动条 ---------- */
::-webkit-scrollbar{ width:9px; height:9px; }
::-webkit-scrollbar-track{ background:rgba(255,255,255,.35); }
::-webkit-scrollbar-thumb{ background:#cfd8e3; border-radius:8px; }
::-webkit-scrollbar-thumb:hover{ background:var(--accent); }

/* ---------- 侧边栏：玻璃面板 ---------- */
[data-testid="stSidebar"]{
  background:rgba(255,255,255,.72) !important;
  border-right:1px solid var(--glass-border);
  backdrop-filter:blur(14px) saturate(150%);
  box-shadow:0 0 24px rgba(15,23,42,.05);
}
[data-testid="stSidebar"] [data-testid="stSidebarUserContent"]{ padding-top:.6rem; }
[data-testid="stSidebar"] hr{ margin:1rem 0; }
[data-testid="stSidebar"] div[class*="st-key-card_"]{ padding:16px !important; border-radius:14px !important; }

/* ---------- 卡片：.metric-card 与 st-key-card_* 容器共用同一套玻璃样式 ---------- */
.metric-card,
div[class*="st-key-card_"]{
  background:rgba(255,255,255,.8) !important;
  border:1px solid rgba(255,255,255,.5) !important;
  border-radius:16px !important;
  padding:24px !important;
  box-shadow:0 4px 20px rgba(0,0,0,.05) !important;
  backdrop-filter:blur(12px) saturate(150%);
  transition:transform .22s ease, box-shadow .22s ease, border-color .22s ease;
}
.metric-card:hover,
div[class*="st-key-card_"]:hover{
  transform:translateY(-4px);
  box-shadow:0 18px 38px rgba(15,23,42,.14) !important;
  border-color:rgba(78,205,196,.55) !important;
}
/* 内层语义类：抵消容器已提供的玻璃底，避免"卡中卡"双描边 */
.metric-card--inner,
.metric-card--inner:hover{
  background:transparent !important; border:0 !important; border-radius:0 !important;
  padding:0 !important; box-shadow:none !important; transform:none !important;
  backdrop-filter:none !important;
}
/* 容器内部的第一层 Streamlit 块不重复描边 */
div[class*="st-key-card_"] > div,
div[class*="st-key-card_"] > div > div[data-testid="stVerticalBlock"]{
  background:transparent !important; border:0 !important; box-shadow:none !important;
}

/* ---------- Feather 线性图标：全部以 background-image（SVG data URI）内嵌，无图标字体依赖 ---------- */
.ax-ico{
  display:inline-block; width:16px; height:16px; flex:0 0 auto; vertical-align:-3px;
  background-repeat:no-repeat; background-position:center; background-size:16px 16px;
}
.ax-ico.activity{background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%236b7280' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpolyline points='22 12 18 12 15 21 9 3 6 12 2 12'/%3E%3C/svg%3E")}
.ax-ico.server{background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%236b7280' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Crect x='2' y='2' width='20' height='8' rx='2'/%3E%3Crect x='2' y='14' width='20' height='8' rx='2'/%3E%3Cline x1='6' y1='6' x2='6.01' y2='6'/%3E%3Cline x1='6' y1='18' x2='6.01' y2='18'/%3E%3C/svg%3E")}
.ax-ico.alert{background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%236b7280' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z'/%3E%3Cline x1='12' y1='9' x2='12' y2='13'/%3E%3Cline x1='12' y1='17' x2='12.01' y2='17'/%3E%3C/svg%3E")}
.ax-ico.bell{background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%236b7280' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M18 8a6 6 0 0 0-12 0c0 7-3 9-3 9h18s-3-2-3-9'/%3E%3Cpath d='M13.73 21a2 2 0 0 1-3.46 0'/%3E%3C/svg%3E")}
.ax-ico.shield{background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%236b7280' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z'/%3E%3C/svg%3E")}
.ax-ico.wifi{background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%236b7280' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M5 12.55a11 11 0 0 1 14.08 0'/%3E%3Cpath d='M1.42 9a16 16 0 0 1 21.16 0'/%3E%3Cpath d='M8.53 16.11a6 6 0 0 1 6.95 0'/%3E%3Cline x1='12' y1='20' x2='12.01' y2='20'/%3E%3C/svg%3E")}
.ax-ico.cpu{background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%236b7280' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Crect x='4' y='4' width='16' height='16' rx='2'/%3E%3Crect x='9' y='9' width='6' height='6'/%3E%3Cline x1='9' y1='1' x2='9' y2='4'/%3E%3Cline x1='15' y1='1' x2='15' y2='4'/%3E%3Cline x1='9' y1='20' x2='9' y2='23'/%3E%3Cline x1='15' y1='20' x2='15' y2='23'/%3E%3Cline x1='20' y1='9' x2='23' y2='9'/%3E%3Cline x1='20' y1='14' x2='23' y2='14'/%3E%3Cline x1='1' y1='9' x2='4' y2='9'/%3E%3Cline x1='1' y1='14' x2='4' y2='14'/%3E%3C/svg%3E")}
.ax-ico.database{background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%236b7280' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cellipse cx='12' cy='5' rx='9' ry='3'/%3E%3Cpath d='M21 12c0 1.66-4 3-9 3s-9-1.34-9-3'/%3E%3Cpath d='M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5'/%3E%3C/svg%3E")}
.ax-ico.memory{background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%236b7280' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cline x1='22' y1='12' x2='2' y2='12'/%3E%3Cpath d='M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z'/%3E%3Cline x1='6' y1='16' x2='6.01' y2='16'/%3E%3Cline x1='10' y1='16' x2='10.01' y2='16'/%3E%3C/svg%3E")}
.ax-ico.terminal{background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%236b7280' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpolyline points='4 17 10 11 4 5'/%3E%3Cline x1='12' y1='19' x2='20' y2='19'/%3E%3C/svg%3E")}
.ax-ico.chat{background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%236b7280' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z'/%3E%3C/svg%3E")}
.ax-ico.share{background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%236b7280' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Ccircle cx='18' cy='5' r='3'/%3E%3Ccircle cx='6' cy='12' r='3'/%3E%3Ccircle cx='18' cy='19' r='3'/%3E%3Cline x1='8.59' y1='13.51' x2='15.42' y2='17.49'/%3E%3Cline x1='15.41' y1='6.51' x2='8.59' y2='10.49'/%3E%3C/svg%3E")}
.ax-ico.traffic{background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%236b7280' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cline x1='18' y1='20' x2='18' y2='10'/%3E%3Cline x1='12' y1='20' x2='12' y2='4'/%3E%3Cline x1='6' y1='20' x2='6' y2='14'/%3E%3C/svg%3E")}
.ax-ico.search{background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%236b7280' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Ccircle cx='11' cy='11' r='8'/%3E%3Cline x1='21' y1='21' x2='16.65' y2='16.65'/%3E%3C/svg%3E")}
.ax-ico.file{background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%236b7280' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z'/%3E%3Cpolyline points='14 2 14 8 20 8'/%3E%3Cline x1='8' y1='13' x2='16' y2='13'/%3E%3Cline x1='8' y1='17' x2='16' y2='17'/%3E%3C/svg%3E")}
.ax-ico.clipboard{background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%236b7280' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2'/%3E%3Crect x='8' y='2' width='8' height='4' rx='1'/%3E%3C/svg%3E")}
.ax-ico.download{background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%236b7280' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4'/%3E%3Cpolyline points='7 10 12 15 17 10'/%3E%3Cline x1='12' y1='15' x2='12' y2='3'/%3E%3C/svg%3E")}
.ax-ico.refresh{background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%236b7280' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpolyline points='23 4 23 10 17 10'/%3E%3Cpolyline points='1 20 1 14 7 14'/%3E%3Cpath d='M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15'/%3E%3C/svg%3E")}
.ax-ico.check{background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%236b7280' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M22 11.08V12a10 10 0 1 1-5.93-9.14'/%3E%3Cpolyline points='22 4 12 14.01 9 11.01'/%3E%3C/svg%3E")}
.ax-ico.reject{background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%236b7280' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Ccircle cx='12' cy='12' r='10'/%3E%3Cline x1='15' y1='9' x2='9' y2='15'/%3E%3Cline x1='9' y1='9' x2='15' y2='15'/%3E%3C/svg%3E")}
.ax-ico.clock{background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%236b7280' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Ccircle cx='12' cy='12' r='10'/%3E%3Cpolyline points='12 6 12 12 16 14'/%3E%3C/svg%3E")}
.ax-ico.filter{background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%236b7280' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpolygon points='22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3'/%3E%3C/svg%3E")}
.ax-ico.bolt{background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%236b7280' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpolygon points='13 2 3 14 12 14 11 22 21 10 12 10 13 2'/%3E%3C/svg%3E")}
.ax-ico.light{background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%23ffffff' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpolyline points='22 12 18 12 15 21 9 3 6 12 2 12'/%3E%3C/svg%3E")}

/* ---------- 按钮上的线性图标（同样是 CSS background-image 内嵌） ---------- */
div[class*="st-key-btn_inspect"] button::before,
div[class*="st-key-btn_sample"] button::before,
div[class*="st-key-btn_export"] button::before,
div[class*="st-key-btn_download"] button::before,
div[class*="st-key-btn_refresh"] button::before,
div[class*="st-key-side_refresh"] button::before,
div[class*="st-key-btn_ack"] button::before,
div[class*="st-key-ack_"] button::before,
div[class*="st-key-btn_approve"] button::before,
div[class*="st-key-btn_reject"] button::before,
div[class*="st-key-btn_clear_chat"] button::before,
div[class*="st-key-quick_"] button::before{
  content:""; width:16px; height:16px; margin-right:8px; flex:0 0 auto;
  background-repeat:no-repeat; background-position:center; background-size:16px 16px;
}
div[class*="st-key-btn_inspect"] button::before{background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%232f9e93' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Ccircle cx='11' cy='11' r='8'/%3E%3Cline x1='21' y1='21' x2='16.65' y2='16.65'/%3E%3C/svg%3E")}
div[class*="st-key-btn_sample"] button::before{background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%232f9e93' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cline x1='18' y1='20' x2='18' y2='10'/%3E%3Cline x1='12' y1='20' x2='12' y2='4'/%3E%3Cline x1='6' y1='20' x2='6' y2='14'/%3E%3C/svg%3E")}
div[class*="st-key-btn_export"] button::before, div[class*="st-key-btn_download"] button::before{background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%236b7280' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4'/%3E%3Cpolyline points='7 10 12 15 17 10'/%3E%3Cline x1='12' y1='15' x2='12' y2='3'/%3E%3C/svg%3E")}
div[class*="st-key-btn_refresh"] button::before, div[class*="st-key-side_refresh"] button::before{background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%236b7280' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpolyline points='23 4 23 10 17 10'/%3E%3Cpolyline points='1 20 1 14 7 14'/%3E%3Cpath d='M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15'/%3E%3C/svg%3E")}
div[class*="st-key-btn_ack"] button::before, div[class*="st-key-ack_"] button::before{background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%232f9e93' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M22 11.08V12a10 10 0 1 1-5.93-9.14'/%3E%3Cpolyline points='22 4 12 14.01 9 11.01'/%3E%3C/svg%3E")}
div[class*="st-key-btn_approve"] button::before{background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%23ffffff' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M22 11.08V12a10 10 0 1 1-5.93-9.14'/%3E%3Cpolyline points='22 4 12 14.01 9 11.01'/%3E%3C/svg%3E")}
div[class*="st-key-btn_reject"] button::before{background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%23c2410c' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Ccircle cx='12' cy='12' r='10'/%3E%3Cline x1='15' y1='9' x2='9' y2='15'/%3E%3Cline x1='9' y1='9' x2='15' y2='15'/%3E%3C/svg%3E")}
div[class*="st-key-btn_clear_chat"] button::before{background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%236b7280' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpolyline points='3 6 5 6 21 6'/%3E%3Cpath d='M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6'/%3E%3Cline x1='10' y1='11' x2='10' y2='17'/%3E%3Cline x1='14' y1='11' x2='14' y2='17'/%3E%3C/svg%3E")}
div[class*="st-key-quick_"] button::before{background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%236b7280' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpolygon points='13 2 3 14 12 14 11 22 21 10 12 10 13 2'/%3E%3C/svg%3E")}

/* ---------- 标签页（只用 testid / ARIA，避开已废弃的 BaseWeb 选择器） ---------- */
[data-testid="stTabs"] [role="tablist"]{
  gap:6px; background:transparent !important; border-bottom:1px solid var(--line);
}
[data-testid="stTab"]{
  border-radius:10px 10px 0 0 !important; padding:9px 16px !important;
  color:var(--muted) !important; font-weight:600 !important; background:transparent !important;
  transition:color .18s ease, background .18s ease;
}
[data-testid="stTab"] p{ font-size:.9rem !important; }
[data-testid="stTab"]:hover{ color:var(--accent-deep) !important; background:rgba(78,205,196,.10) !important; }
[data-testid="stTab"][aria-selected="true"], [data-testid="stTab"][data-selected="true"],
[data-testid="stTab"][data-state="active"]{
  color:var(--accent-deep) !important; background:rgba(78,205,196,.12) !important;
}
[data-testid="stTabHighlight"]{ background-color:var(--accent) !important; height:3px !important; }
[data-testid="stTabPanel"]{ padding-top:1.1rem; }


/* ---------- 按钮 ---------- */
.stButton button, .stDownloadButton button, .stFormSubmitButton button{
  background:rgba(255,255,255,.9) !important; color:var(--text) !important;
  border:1px solid var(--line) !important; border-radius:10px !important;
  font-weight:600 !important; box-shadow:0 1px 2px rgba(15,23,42,.05);
  transition:transform .18s ease, box-shadow .18s ease, border-color .18s ease;
}
.stButton button:hover, .stDownloadButton button:hover, .stFormSubmitButton button:hover{
  transform:translateY(-2px); border-color:rgba(78,205,196,.6) !important;
  box-shadow:0 10px 22px rgba(78,205,196,.22); color:var(--accent-deep) !important;
}
.stButton button[kind="primary"], .stDownloadButton button[kind="primary"]{
  background:linear-gradient(135deg,#4ECDC4 0%,#2f9e93 100%) !important;
  color:#ffffff !important; border-color:transparent !important;
  box-shadow:0 8px 20px rgba(47,158,147,.28);
}
.stButton button[kind="primary"] p, .stDownloadButton button[kind="primary"] p{ color:#ffffff !important; }
.stButton button[kind="primary"]:hover, .stButton button[kind="primary"]:hover p{
  box-shadow:0 14px 28px rgba(47,158,147,.36); color:#ffffff !important;
}

/* ---------- 表单控件与指标 ---------- */
[data-testid="stTextInputRootElement"], [data-testid="stNumberInputContainer"],
[data-testid="stSelectbox"] [role="combobox"], [data-testid="stChatInput"],
[data-testid="stTextArea"] textarea{
  background:rgba(255,255,255,.92) !important; border:1px solid var(--line) !important;
  border-radius:12px !important; transition:border-color .2s ease, box-shadow .2s ease;
}
[data-testid="stTextInputRootElement"]:focus-within, [data-testid="stSelectbox"] [role="combobox"]:focus,
[data-testid="stChatInput"]:focus-within, [data-testid="stTextArea"] textarea:focus{
  border-color:var(--accent) !important; box-shadow:0 0 0 3px rgba(78,205,196,.18) !important;
}
[data-testid="stTextInputRootElement"] input, [data-testid="stTextArea"] textarea,
[data-testid="stChatInput"] textarea{ color:var(--text) !important; }
[data-testid="stWidgetLabel"] p, [data-testid="stWidgetLabel"] label{
  color:var(--muted) !important; font-size:.8rem !important; font-weight:600 !important; letter-spacing:.05em;
}
[data-testid="stRadio"] label p{ color:var(--text) !important; font-size:.85rem !important; }
[data-testid="stMetricValue"]{ color:#0f172a !important; font-weight:700 !important; }
[data-testid="stMetricLabel"] p{ color:var(--muted) !important; }
[data-testid="stMetricDelta"]{ font-weight:600 !important; }
[data-testid="stProgress"] div[role="progressbar"] div{
  background:linear-gradient(90deg,#4ECDC4,#2f9e93) !important;
}
[data-testid="stProgress"] p, [data-testid="stProgress"] div[data-testid="stMarkdownContainer"] p{
  color:var(--muted) !important; font-size:.78rem !important;
}

/* ---------- 代码块 / 表格 / 折叠 / 提示 / 对话气泡 ---------- */
[data-testid="stCode"]{
  background:rgba(255,255,255,.92) !important; border:1px solid var(--line) !important;
  border-radius:12px !important;
}
[data-testid="stCode"] *{ background:transparent !important; color:#0f766e !important; }
.stMarkdown pre{
  background:rgba(255,255,255,.92) !important; border:1px solid var(--line) !important;
  border-radius:12px !important;
}
[data-testid="stDataFrame"], [data-testid="stDataFrameResizable"]{
  border:1px solid var(--line) !important; border-radius:12px !important; overflow:hidden;
  background:rgba(255,255,255,.9) !important;
}
[data-testid="stExpander"]{
  background:rgba(255,255,255,.72) !important; border:1px solid var(--line) !important;
  border-radius:12px !important;
}
[data-testid="stExpander"] details{ background:transparent !important; border:0 !important; }
[data-testid="stExpander"] summary{ color:var(--muted) !important; font-size:.84rem !important; }
[data-testid="stAlert"], [data-testid="stAlertContainer"]{
  background:rgba(255,255,255,.92) !important; border:1px solid var(--line) !important;
  border-radius:12px !important;
}
[data-testid="stChatMessage"]{
  background:rgba(255,255,255,.85) !important; border:1px solid var(--glass-border) !important;
  border-radius:14px !important; padding:10px 14px !important;
  box-shadow:0 2px 10px rgba(15,23,42,.04);
  transition:border-color .2s ease, box-shadow .2s ease;
}
[data-testid="stChatMessage"]:hover{
  border-color:rgba(78,205,196,.55) !important; box-shadow:0 8px 20px rgba(15,23,42,.08);
}
[data-testid="stCaptionContainer"] p{ color:var(--muted) !important; font-size:.76rem !important; }

/* ---------- Markdown 表格 / 标题（巡检报告复用） ---------- */
[data-testid="stMarkdownContainer"] table{
  border-collapse:separate; border-spacing:0; width:100%; margin:10px 0 6px;
  font-size:.85rem; border-radius:12px; overflow:hidden;
}
[data-testid="stMarkdownContainer"] th{
  background:rgba(78,205,196,.14) !important; color:#0f5f59 !important;
  text-align:left; font-weight:700; padding:9px 12px; border-bottom:1px solid var(--line);
}
[data-testid="stMarkdownContainer"] td{
  padding:8px 12px; border-bottom:1px solid var(--line); color:var(--text);
}
[data-testid="stMarkdownContainer"] tbody tr:nth-child(even) td{ background:rgba(255,255,255,.6); }
[data-testid="stMarkdownContainer"] h1{ font-size:1.35rem !important; font-weight:700 !important; color:#0f172a !important; }
[data-testid="stMarkdownContainer"] h2{
  font-size:1.08rem !important; font-weight:700 !important; color:var(--accent-deep) !important;
  margin:1rem 0 .5rem !important;
}
[data-testid="stMarkdownContainer"] h3{ font-size:.95rem !important; font-weight:600 !important; color:#0f172a !important; }

/* ---------- 自定义组件（app.py 内联 HTML 复用） ---------- */
.ax-pill{
  display:inline-flex; align-items:center; gap:6px; padding:3px 10px; border-radius:999px;
  font-size:.74rem; font-weight:600; letter-spacing:.03em; border:1px solid transparent; white-space:nowrap;
}
.ax-pill.ok{ color:#0f766e; background:rgba(78,205,196,.18); border-color:rgba(78,205,196,.45); }
.ax-pill.err{ color:#b91c1c; background:rgba(255,107,107,.16); border-color:rgba(255,107,107,.42); }
.ax-pill.warn{ color:#b45309; background:rgba(245,158,11,.15); border-color:rgba(245,158,11,.4); }
.ax-pill.info{ color:#1d4ed8; background:rgba(91,141,239,.14); border-color:rgba(91,141,239,.38); }
.ax-pill.muted{ color:#4b5563; background:rgba(107,114,128,.12); border-color:rgba(107,114,128,.28); }

.ax-head{
  display:flex; align-items:center; justify-content:space-between; gap:12px;
  padding-bottom:10px; margin-bottom:14px; border-bottom:1px solid var(--line);
}
.ax-head .ax-left{ display:flex; align-items:center; gap:9px; min-width:0; }
.ax-head .ax-title{ font-size:.98rem; font-weight:700; color:#0f172a; letter-spacing:.01em; }
.ax-head .ax-sub{
  font-size:.7rem; color:var(--muted); letter-spacing:.14em; text-transform:uppercase; white-space:nowrap;
}

.ax-note{
  border-left:3px solid var(--accent); background:rgba(78,205,196,.10); padding:10px 12px;
  border-radius:0 10px 10px 0; color:#334155; font-size:.83rem; line-height:1.7;
}
.ax-note.warn{ border-left-color:var(--warn); background:rgba(245,158,11,.10); }
.ax-note.err{ border-left-color:var(--danger); background:rgba(255,107,107,.10); }
.ax-note b{ color:#0f172a; }

.ax-kv{ display:flex; flex-direction:column; gap:9px; }
.ax-kv .row{ display:flex; align-items:center; justify-content:space-between; gap:10px; font-size:.83rem; }
.ax-kv .k{ color:var(--muted); display:flex; align-items:center; gap:8px; }
.ax-kv .v{ color:var(--text); font-weight:600; text-align:right; }

.ax-brand{ display:flex; align-items:center; gap:11px; padding:2px 0 14px; }
.ax-brand .mark{
  width:38px; height:38px; border-radius:12px;
  background:linear-gradient(135deg,#4ECDC4 0%,#2f9e93 100%);
  background-position:center; background-repeat:no-repeat;
  display:flex; align-items:center; justify-content:center;
  box-shadow:0 10px 22px rgba(47,158,147,.32);
}
.ax-brand .name{ font-weight:700; font-size:1rem; color:#0f172a; }
.ax-brand .desc{ font-size:.72rem; color:var(--muted); }

.ax-metric-head{ display:flex; align-items:center; gap:9px; margin-bottom:6px; }
.ax-metric-head .t{ font-size:.72rem; font-weight:700; letter-spacing:.12em; text-transform:uppercase; color:var(--muted); }

.ax-hero{
  background:linear-gradient(120deg,rgba(255,255,255,.86) 0%,rgba(255,255,255,.72) 55%,rgba(78,205,196,.16) 100%);
  border:1px solid var(--glass-border); border-radius:16px; padding:24px 26px;
  box-shadow:0 4px 20px rgba(0,0,0,.05); backdrop-filter:blur(12px) saturate(150%);
  transition:transform .22s ease, box-shadow .22s ease, border-color .22s ease;
}
.ax-hero:hover{
  transform:translateY(-4px); box-shadow:0 18px 38px rgba(15,23,42,.14);
  border-color:rgba(78,205,196,.55);
}
.ax-hero .eyebrow{
  font-size:.7rem; letter-spacing:.24em; text-transform:uppercase; color:var(--accent-deep); font-weight:700;
  display:flex; align-items:center; gap:8px;
}
.ax-hero h1{ margin:10px 0 0; font-size:1.95rem; font-weight:700; letter-spacing:-.02em; color:#0f172a; }
.ax-hero h1 span{
  background:linear-gradient(120deg,#2f9e93,#4ECDC4); -webkit-background-clip:text;
  background-clip:text; color:transparent;
}
.ax-hero p{ margin:10px 0 14px; color:#475569; font-size:.88rem; line-height:1.7; max-width:980px; }
.ax-chips{ display:flex; flex-wrap:wrap; gap:8px; }

.ax-console{
  background:rgba(255,255,255,.92); border:1px solid var(--line); border-radius:12px;
  padding:12px 14px; font-size:.76rem; line-height:1.9; max-height:250px; overflow:auto;
}
.ax-console div{ color:#475569; white-space:pre-wrap; word-break:break-all; }
.ax-console div.ok{ color:#0f9d76; }
.ax-console div.err{ color:#dc2626; }
.ax-console div.warn{ color:#b45309; }
.ax-console div.hi{ color:#0e7490; }

.ax-timeline{ display:flex; flex-direction:column; gap:10px; }
.ax-timeline .item{ display:flex; gap:12px; align-items:flex-start; font-size:.83rem; }
.ax-timeline .dot{
  width:9px; height:9px; border-radius:50%; margin-top:6px; flex:0 0 auto; background:#cbd5e1;
}
.ax-timeline .dot.ok{ background:var(--accent); box-shadow:0 0 8px rgba(78,205,196,.75); }
.ax-timeline .dot.err{ background:var(--danger); box-shadow:0 0 8px rgba(255,107,107,.7); }
.ax-timeline .dot.warn{ background:var(--warn); box-shadow:0 0 8px rgba(245,158,11,.7); }
.ax-timeline .txt{ color:var(--text); font-weight:600; }
.ax-timeline .meta{ color:var(--muted); font-size:.75rem; }

.ax-alert-row{
  display:flex; align-items:center; justify-content:space-between; gap:14px;
  padding:10px 12px; border:1px solid var(--line); border-radius:12px;
  background:rgba(255,255,255,.85); margin-bottom:8px;
}
.ax-alert-row .body{ display:flex; flex-direction:column; gap:4px; min-width:0; }
.ax-alert-row .msg{ color:var(--text); font-size:.85rem; font-weight:600; }
.ax-alert-row .meta{ color:var(--muted); font-size:.74rem; display:flex; align-items:center; gap:8px; }
</style>
"""


def inject_css() -> None:
    """把设计系统 CSS 注入页面（Inter 字体 + 浅色渐变画布 + Glass 卡片 + 线性图标）。"""
    st.markdown(CSS, unsafe_allow_html=True)


# ================= 视觉层小工具（内联 HTML 片段） =================
STATUS_KIND = {
    "SUCCESS": "ok",
    "EXECUTED": "ok",
    "PENDING": "warn",
    "REJECTED": "err",
    "FAILED": "err",
}
LEVEL_KIND = {"P0": "err", "P1": "warn", "P2": "info"}


def esc(value) -> str:
    """HTML 转义；None 统一显示为 -。"""
    return html.escape("-" if value is None else str(value))


def pill(text, kind: str = "info", icon: str = "") -> str:
    """状态药丸，kind ∈ ok / err / warn / info / muted，可选线性图标。"""
    glyph = f'<span class="ax-ico {icon}"></span>' if icon else ""
    return f'<span class="ax-pill {kind}">{glyph}{esc(text)}</span>'


def ico(name: str) -> str:
    """Feather 线性图标（CSS background-image 内嵌 SVG）。"""
    return f'<span class="ax-ico {name}"></span>'


def card_head(title: str, sub: str = "", icon: str = "") -> str:
    """卡片标题栏（左侧线性图标 + 标题，右侧英文副标题）。"""
    glyph = ico(icon) if icon else ""
    return (f'<div class="ax-head"><span class="ax-left">{glyph}'
            f'<span class="ax-title">{esc(title)}</span></span>'
            f'<span class="ax-sub">{esc(sub)}</span></div>')


def metric_head(title: str, icon: str = "") -> str:
    """指标卡顶部小标题（图标 + 全大写标签）。"""
    glyph = ico(icon) if icon else ""
    return f'<div class="ax-metric-head">{glyph}<span class="t">{esc(title)}</span></div>'


def kv_rows(pairs, icons=None) -> str:
    """键值行；value 允许传已拼好的 HTML（如药丸），因此只转义 key。"""
    icons = icons or [None] * len(pairs)
    rows = ""
    for (key, value), icon in zip(pairs, icons):
        glyph = ico(icon) if icon else ""
        rows += (f'<div class="row"><span class="k">{glyph}{esc(key)}</span>'
                 f'<span class="v">{value}</span></div>')
    return f'<div class="ax-kv">{rows}</div>'


def metric_card(content: str, layered: bool = True) -> str:
    """
    卡片内容包装层。

    layered=True 时附加 .metric-card--inner（抵消外层容器已有的玻璃底，避免双描边）；
    layered=False 用于独立 HTML 卡片（如 hero / 控制台），完整使用 .metric-card 规格。
    """
    cls = "metric-card metric-card--inner" if layered else "metric-card"
    return f'<div class="{cls}">{content}</div>'


@contextmanager
def card(key: str):
    """
    所有模块统一的卡片壳：独立的 st.container(border=True)。

    容器带 key 后 Streamlit 会生成 st-key-card_* 类，CSS 让该类与 .metric-card 共用
    同一套玻璃样式（背景 / 描边 / 16px 圆角 / 24px 内边距 / 阴影 / 悬停上浮）。
    """
    with st.container(border=True, key="card_" + key):
        yield


def console_html(lines) -> str:
    """把 (kind, text) 列表渲染成终端面板，kind ∈ t / ok / err / warn / hi。"""
    body = "".join(f'<div class="{kind}">{esc(text)}</div>' for kind, text in lines)
    return metric_card(f'<div class="ax-console">{body}</div>')


def timeline_html(rows, limit: int = 8) -> str:
    """审计记录时间线，rows: [(ts, device, action, details, status), ...]"""
    items = []
    for ts, device, action, _details, status in rows[:limit]:
        kind = STATUS_KIND.get((status or "").upper(), "warn")
        items.append(
            f'<div class="item"><span class="dot {kind}"></span><div>'
            f'<div class="txt">{esc(device or "-")} · {esc(action)}</div>'
            f'<div class="meta">{esc(ts)} · {esc(status)}</div></div></div>'
        )
    if not items:
        items.append('<div class="item"><span class="dot"></span><div class="txt">暂无记录</div></div>')
    inner = f'<div class="ax-timeline">{"".join(items)}</div>'
    return metric_card(inner)


def alert_row_html(level: str, device: str, message: str, timestamp: str,
                   status: str, note: str = "") -> str:
    """告警中心单条告警的展示行（级别药丸 + 内容 + 时间 / 备注）。"""
    note_html = f' · 备注：{esc(note)}' if note else ""
    return (
        '<div class="ax-alert-row"><div class="body">'
        f'<div class="msg">{esc(message)}</div>'
        f'<div class="meta">{pill(level, LEVEL_KIND.get(level, "info"))}'
        f'<span>{ico("server")}{esc(device)}</span>'
        f'<span>{ico("clock")}{esc(timestamp)}</span>'
        f'<span>{esc(status)}{note_html}</span></div>'
        '</div></div>'
    )


def console_lines(log_rows, online_n: int) -> list:
    """把审计记录与运行态信息拼装成终端面板内容。"""
    total = len(DEVICES)
    lines = [
        ("t", "> [BOOT] AIOps 控制台已加载 · UI 3.0 (light glass / Inter / Plotly)"),
        ("t", "> [INFO] LLM: DeepSeek deepseek-chat · MCP: stdio://server.py"),
        (
            "ok" if online_n == total else "warn",
            f"> [INFO] 纳管设备 {total} 台 / 在线 {online_n} 台",
        ),
        ("t", "> [INFO] 安全策略: 写操作强制人工审批 · 只读命令限定 show*"),
    ]
    for ts, device, action, _details, status in log_rows[:6]:
        kind = STATUS_KIND.get((status or "").upper(), "hi")
        stamp = ts[11:] if ts and len(ts) >= 19 else (ts or "-")
        lines.append((kind, f"> [{stamp}] {device or '-'} · {action} · {status}"))
    if not log_rows:
        lines.append(("t", "> [WAIT] 暂无可执行记录，等待下一条指令 ..."))
    return lines


def hero_html(online_n: int, total: int, alert_active: int, pending_n: int) -> str:
    """顶部品牌区：标题 + 说明 + 状态药丸（独立 .metric-card 卡片）。"""
    if total and online_n == total:
        health = pill(f"{online_n}/{total} 设备在线", "ok", "wifi")
    elif online_n:
        health = pill(f"{online_n}/{total} 设备在线", "warn", "wifi")
    else:
        health = pill(f"{online_n}/{total} 设备在线", "err", "wifi")
    chips = [
        health,
        pill("DeepSeek 已就绪" if DEEPSEEK_API_KEY else "DeepSeek 未配置密钥",
             "info" if DEEPSEEK_API_KEY else "err", "bolt"),
        pill("写操作人工审批", "info", "shield"),
        pill(f"未确认告警 {alert_active}", "err" if alert_active else "muted", "bell"),
        pill(f"待审批 {pending_n}", "warn" if pending_n else "muted", "clock"),
    ]
    inner = (
        f'<div class="eyebrow">{ico("share")}Natural Language &rarr; MCP Tools &rarr; VyOS / Linux</div>'
        '<h1>AIOps <span>智能网络运维控制台</span></h1>'
        '<p>用普通话描述运维意图，AI 解析后经 MCP 协议调用工具、SSH 下发到真实设备；'
        '写操作进入人工审批队列，巡检与告警全程留痕可审计。</p>'
        f'<div class="ax-chips">{"".join(chips)}</div>'
    )
    return metric_card(inner, layered=False)


# ================= Plotly 图表工厂 =================
def topology_positions(names: list) -> dict:
    """拓扑布局：首台设备作为核心置于顶部，其余设备在底部等距展开。"""
    if not names:
        return {}
    if len(names) == 1:
        return {names[0]: (0.0, 0.0)}
    positions = {names[0]: (0.0, 1.0)}
    others = names[1:]
    span = 1.7
    if len(others) == 1:
        xs = [0.0]
    else:
        xs = [-span / 2 + span * index / (len(others) - 1) for index in range(len(others))]
    for name, x in zip(others, xs):
        positions[name] = (x, 0.0)
    return positions


def rounded_rect_vertices(cx: float, cy: float, width: float = NODE_W,
                          height: float = NODE_H, radius: float = NODE_R,
                          segments: int = 6) -> list:
    """
    生成圆角矩形边框的多边形顶点（首尾闭合）。

    Plotly 的 scatter marker 没有 cornerradius（7.x 仍不支持），因此节点用
    fill="toself" 的圆角多边形绘制：既能呈现圆角矩形，又保留原生悬停提示。
    """
    points = []
    for sign_x, sign_y, start in ((1, 1, 0), (-1, 1, 90), (-1, -1, 180), (1, -1, 270)):
        corner_x = cx + sign_x * (width / 2 - radius)
        corner_y = cy + sign_y * (height / 2 - radius)
        for step in range(segments + 1):
            angle = math.radians(start + 90 * step / segments)
            points.append((corner_x + radius * math.cos(angle),
                           corner_y + radius * math.sin(angle)))
    points.append(points[0])
    return points


def topology_figure(probe: dict) -> go.Figure:
    """Plotly 拓扑图：圆角矩形节点，在线 #4ECDC4 / 离线 #FF6B6B，悬停显示设备详情。"""
    names = [name for name in DEVICES if name in TOPOLOGY] or DEVICES
    positions = topology_positions(names)
    fig = go.Figure()

    # ---- 链路（核心 → 边缘）----
    edge_x, edge_y = [], []
    for name in names[1:]:
        x0, y0 = positions[names[0]]
        x1, y1 = positions[name]
        edge_x += [x0, x1, None]
        edge_y += [y0 - NODE_H / 2, y1 + NODE_H / 2, None]
    if edge_x:
        fig.add_trace(go.Scatter(
            x=edge_x, y=edge_y, mode="lines", line=dict(color="#b7c4d4", width=2),
            hoverinfo="skip", showlegend=False,
        ))

    # ---- 节点：圆角矩形 + 悬停提示 ----
    for name in names:
        x, y = positions[name]
        item = probe.get(name, {})
        online = bool(item.get("online"))
        vertices = rounded_rect_vertices(x, y)
        hover = (
            f"<b>{esc(name)}</b> · {esc(TOPOLOGY[name]['role'])}<br>"
            f"管理 IP：{esc(TOPOLOGY[name]['host'])}<br>"
            f"状态：{'在线' if online else '离线'}<br>"
            f"系统：{esc(item.get('version', '-'))}"
        )
        fig.add_trace(go.Scatter(
            x=[point[0] for point in vertices],
            y=[point[1] for point in vertices],
            fill="toself", mode="lines",
            line=dict(color=ACCENT_DEEP if online else "#d94a4a", width=1.6),
            fillcolor=ACCENT if online else DANGER,
            name=name, showlegend=False,
            hovertext=hover, hoverinfo="text",
        ))
        fig.add_trace(go.Scatter(
            x=[x], y=[y], mode="text", text=["在线" if online else "离线"],
            textfont=dict(size=11, color="#ffffff", family="Inter, Segoe UI, sans-serif"),
            hoverinfo="skip", showlegend=False,
        ))
        fig.add_trace(go.Scatter(
            x=[x], y=[y - NODE_H / 2 - 0.07], mode="text", text=[name],
            textfont=dict(size=13, color="#1f2937", family="Inter, Segoe UI, sans-serif"),
            hoverinfo="skip", showlegend=False,
        ))

    # ---- 图例 ----
    for label, color in (("在线", ACCENT), ("离线", DANGER)):
        fig.add_trace(go.Scatter(
            x=[None], y=[None], mode="markers", name=label,
            marker=dict(size=11, color=color), hoverinfo="skip",
        ))

    fig.update_layout(
        height=340, showlegend=True, dragmode=False,
        legend=dict(orientation="h", yanchor="bottom", y=1.03, x=0,
                    bgcolor="rgba(0,0,0,0)", font=dict(color="#6b7280", size=11)),
        margin=dict(l=10, r=10, t=26, b=10),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Inter, Segoe UI, sans-serif", color="#1f2937"),
        hoverlabel=dict(bgcolor="#ffffff", bordercolor=ACCENT,
                        font=dict(color="#1f2937", size=12)),
        xaxis=dict(visible=False, range=[-1.12, 1.12], fixedrange=True),
        yaxis=dict(visible=False, range=[-0.5, 1.32], fixedrange=True),
    )
    return fig


def traffic_figure(sample: dict) -> go.Figure:
    """两次采样的 RX / TX 计数对比（分组柱状图，浅色透明底）。"""
    labels = ["第 1 次采样", "第 2 次采样"]
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=labels, y=[sample["rx1"], sample["rx2"]], name="RX 接收字节",
        marker=dict(color=CHART_RX, line=dict(width=0)),
        hovertemplate="%{x}<br>RX %{y:,} Bytes<extra></extra>",
    ))
    fig.add_trace(go.Bar(
        x=labels, y=[sample["tx1"], sample["tx2"]], name="TX 发送字节",
        marker=dict(color=CHART_TX, line=dict(width=0)),
        hovertemplate="%{x}<br>TX %{y:,} Bytes<extra></extra>",
    ))
    fig.update_layout(
        height=320, barmode="group", bargap=0.35,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0,
                    bgcolor="rgba(0,0,0,0)", font=dict(color="#6b7280", size=11)),
        margin=dict(l=10, r=10, t=30, b=10),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Inter, Segoe UI, sans-serif", color="#1f2937"),
        xaxis=dict(showgrid=False, zeroline=False, tickfont=dict(color="#6b7280")),
        yaxis=dict(showgrid=True, gridcolor="#e3e9f0", zeroline=False,
                   tickfont=dict(color="#6b7280")),
    )
    return fig


# ================= 采集层：设备探测 + 真实输出解析 =================
def is_error_output(raw: str) -> bool:
    """判断 MCP/SSH 返回是否为失败信息（离线、超时、异常）。"""
    return any(mark in (raw or "") for mark in ERROR_MARKS)


def parse_version(raw: str) -> str:
    """从 show version 中取出系统版本号。"""
    match = re.search(r"Version:\s*(.+)", raw or "")
    return match.group(1).strip() if match else "-"


def parse_uptime(raw: str) -> dict:
    """
    解析 show system uptime —— 实测 VyOS 返回形如：
        Uptime: 24m 32s
        Load averages:
        1  minute:   16.0%
    """
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
    return info


UNIT_TO_MB = {"b": 1 / 1024 / 1024, "kb": 1 / 1024, "mb": 1.0, "gb": 1024.0, "tb": 1024.0 * 1024}


def _to_mb(number: str, unit: str):
    """把任意单位的容量换算成 MB，失败返回 None。"""
    try:
        return float(number) * UNIT_TO_MB.get((unit or "mb").lower(), 1.0)
    except (TypeError, ValueError):
        return None


def parse_memory(raw: str) -> dict:
    """
    解析 show system memory —— 实测 VyOS 返回形如：
        Total: 1.93 GB
        Free:  1.41 GB
        Used:  538.89 MB
    """
    info = {"total_mb": None, "free_mb": None, "used_mb": None, "percent": None}
    for key in ("total", "free", "used"):
        match = re.search(rf"{key}:\s*([\d.]+)\s*(B|KB|MB|GB|TB)", raw or "", re.IGNORECASE)
        if match:
            info[f"{key}_mb"] = _to_mb(match.group(1), match.group(2))
    if info["total_mb"] and info["used_mb"]:
        info["percent"] = round(info["used_mb"] / info["total_mb"] * 100, 1)
    return info


def parse_interface(raw: str, ifname: str = DEVICE_IFACE) -> dict:
    """
    解析接口详情 —— 实测 VyOS / Linux 返回形如：
        eth0: <...,UP,LOWER_UP> mtu 1500 ... state UP group default qlen 1000
            inet 192.168.56.10/24 brd 192.168.56.255 scope global eth0
            RX:  bytes  packets  errors  dropped  overrun       mcast
                 31976      222       0        0        0           0
    返回链路状态、管理地址、RX/TX 字节与错误包计数。
    """
    info = {"state": "-", "address": "-", "rx_bytes": None, "tx_bytes": None,
            "rx_errors": None, "tx_errors": None}
    match = re.search(rf"^{re.escape(ifname)}:.*?state\s+(\w+)", raw or "", re.MULTILINE)
    if match:
        info["state"] = match.group(1).upper()
    match = re.search(r"\binet\s+([\d.]+/\d+)", raw or "")
    if match:
        info["address"] = match.group(1)
    for key, pattern in (("rx", r"RX:\s*bytes.*?\n\s*([\d.]+)\s+([\d.]+)\s+([\d.]+)"),
                         ("tx", r"TX:\s*bytes.*?\n\s*([\d.]+)\s+([\d.]+)\s+([\d.]+)")):
        match = re.search(pattern, raw or "", re.DOTALL)
        if match:
            try:
                info[f"{key}_bytes"] = int(float(match.group(1)))
                info[f"{key}_errors"] = int(float(match.group(3)))
            except ValueError:
                pass
    return info


def parse_traffic(output: str):
    """供流量监控页使用：从 show interfaces 输出取 (RX 字节, TX 字节)。"""
    info = parse_interface(output)
    return info["rx_bytes"] or 0, info["tx_bytes"] or 0


@st.cache_data(ttl=60, show_spinner=False)
def probe_devices() -> dict:
    """逐台执行 show version 判定可达性；60 秒缓存，避免每次交互都发起 SSH。"""
    result = {}
    for name in DEVICES:
        try:
            raw = asyncio.run(call_mcp_tool(
                "query_device", {"device_name": name, "command_name": "show version"}))
        except Exception as exc:  # noqa: BLE001 —— 探测失败不应中断页面
            raw = f"探测异常: {type(exc).__name__} - {exc}"
        online = not is_error_output(raw)
        result[name] = {
            "online": online,
            "raw": raw,
            "version": parse_version(raw) if online else "-",
        }
    return result


def sync_device_alerts(probe: dict) -> int:
    """把「设备不可达」写入告警表；自带去重，页面反复 rerun 也不会刷爆告警表。"""
    created = 0
    for name, item in probe.items():
        if item.get("online"):
            continue
        created += int(log_alert(name, "P0", "设备不可达：SSH 探测失败，无法采集运行状态", dedupe=True))
    return created


# ================= 巡检引擎（只读：接口 / CPU / 内存） =================
INSPECT_CMDS = (
    ("version", "show version"),
    ("interface", f"show interfaces ethernet {DEVICE_IFACE}"),
    ("cpu", "show system uptime"),          # 实测 VyOS 用负载百分比表达 CPU 压力
    ("memory", "show system memory"),
)
CPU_WARN = 80.0     # CPU 1 分钟负载百分比 ≥ 该值 → P1
MEM_WATCH = 70.0    # 内存使用率百分比 ≥ 该值 → P2


def inspect_device(name: str) -> dict:
    """
    对单台设备执行一次只读巡检，返回结构化结果。

    设计要点：
      1. 全部使用 show* 只读命令，符合 MCP Server 的安全策略；
      2. 首条命令若判定不可达就立即中断，避免连续 4 次 SSH 超时白等；
      3. 任何异常都降级成「未采集到」，绝不抛异常打断整轮巡检。
    """
    info = TOPOLOGY.get(name, {})
    record = {
        "device": name, "role": info.get("role", "未知设备"), "host": info.get("host", "-"),
        "online": False, "error": "", "version": "-", "uptime": "-",
        "cpu_percent": None, "cpu_detail": "-", "mem_percent": None, "mem_detail": "-",
        "if_state": "-", "if_detail": "-", "if_errors": None,
        "raw": {}, "issues": [],
    }

    for key, cmd in INSPECT_CMDS:
        try:
            raw = asyncio.run(call_mcp_tool(
                "query_device", {"device_name": name, "command_name": cmd}))
        except Exception as exc:  # noqa: BLE001
            raw = f"MCP 调用异常: {type(exc).__name__} - {exc}"
        record["raw"][cmd] = raw

        if key == "version":
            if is_error_output(raw):
                record["error"] = " ".join((raw or "").split())[:160]
                record["issues"].append(("P0", "设备不可达：SSH 探测失败，无法采集运行状态"))
                break
            record["online"] = True
            record["version"] = parse_version(raw)

        elif key == "interface":
            iface = parse_interface(raw)
            record["if_state"] = iface["state"]
            record["if_errors"] = (iface["rx_errors"] or 0) + (iface["tx_errors"] or 0)
            if iface["state"] == "-":
                record["if_detail"] = "未采集到接口状态"
                record["issues"].append(("P2", f"未采集到接口 {DEVICE_IFACE} 状态"))
            else:
                record["if_detail"] = (f"RX {iface['rx_bytes']} B / TX {iface['tx_bytes']} B"
                                       f" · 错误包 {record['if_errors']}")
                if iface["state"] != "UP":
                    record["issues"].append(
                        ("P1", f"接口 {DEVICE_IFACE} 未处于 UP 状态（当前 {iface['state']}）"))
                if record["if_errors"] > 0:
                    record["issues"].append(
                        ("P1", f"接口 {DEVICE_IFACE} 出现错误包，需检查链路质量"))

        elif key == "cpu":
            uptime = parse_uptime(raw)
            record["uptime"] = uptime["uptime"]
            record["cpu_percent"] = uptime["load1"]
            if uptime["load1"] is None:
                record["cpu_detail"] = "未采集到 CPU 负载"
                record["issues"].append(("P2", "未采集到 CPU 1 分钟负载"))
            else:
                record["cpu_detail"] = (f"1min {uptime['load1']}% / 5min {uptime['load5']}%"
                                        f" / 15min {uptime['load15']}%")
                if uptime["load1"] >= CPU_WARN:
                    record["issues"].append(("P1", "CPU 1 分钟负载超过 80% 告警阈值"))

        elif key == "memory":
            memory = parse_memory(raw)
            record["mem_percent"] = memory["percent"]
            if memory["percent"] is None:
                record["mem_detail"] = "未采集到内存数据"
                record["issues"].append(("P2", "未采集到内存使用率"))
            else:
                record["mem_detail"] = (f"{memory['used_mb']:.0f} MB / {memory['total_mb']:.0f} MB"
                                        f"（{memory['percent']}%）")
                if memory["percent"] >= MEM_WATCH:
                    record["issues"].append(("P2", "内存使用率超过 70% 关注阈值"))

    levels = [level for level, _ in record["issues"]]
    if not record["online"]:
        record["conclusion"] = "不可达"
    elif "P1" in levels or "P0" in levels:
        record["conclusion"] = "需处理"
    elif "P2" in levels:
        record["conclusion"] = "需关注"
    else:
        record["conclusion"] = "正常"
    return record


def run_inspection(progress_cb=None) -> dict:
    """遍历全部设备执行巡检，返回 {"records": [...], "started_at": str, "elapsed": float}。"""
    started_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    started = time.time()
    records = []
    for index, name in enumerate(DEVICES):
        if progress_cb:
            progress_cb(index / max(len(DEVICES), 1), f"正在巡检 {name} ...")
        records.append(inspect_device(name))
    if progress_cb:
        progress_cb(1.0, "巡检完成，正在生成报告 ...")
    return {"records": records, "started_at": started_at, "elapsed": time.time() - started}


# ================= 巡检报告（Markdown） =================
def _cell(value) -> str:
    """Markdown 表格单元格安全化：转义竖线、压缩换行。"""
    text = "-" if value is None else str(value)
    return text.replace("|", "\\|").replace("\n", " ").strip()


def build_inspection_report(records: list, started_at: str, elapsed: float) -> str:
    """把巡检结果渲染成 Markdown 报告：总览表 + 问题清单 + 逐台明细 + 建议动作。"""
    total = len(records)
    online = sum(1 for item in records if item["online"])
    issues = [(item["device"], level, message)
              for item in records for level, message in item["issues"]]
    counter = {"P0": 0, "P1": 0, "P2": 0}
    for _device, level, _message in issues:
        counter[level] = counter.get(level, 0) + 1
    rate = round(online / total * 100, 1) if total else 0.0
    scope = "、".join(item["device"] for item in records)

    lines = [
        "# 🛰 AIOps 智能巡检报告",
        "",
        f"**巡检时间**：{started_at}　　**总耗时**：{elapsed:.1f} 秒",
        f"**巡检范围**：{scope}（共 {total} 台）",
        "**巡检方式**：MCP stdio → Paramiko SSH → 全部为只读命令",
        f"　　`show version` / `show interfaces ethernet {DEVICE_IFACE}` / "
        "`show system uptime` / `show system memory`",
        "",
        "## 一、巡检总览",
        "",
        f"- 设备在线率：**{rate}%**（{online}/{total}）",
        f"- 异常项合计：**{len(issues)}** 项（P0 {counter['P0']} / "
        f"P1 {counter['P1']} / P2 {counter['P2']}）",
        "",
        f"| 设备 | 角色 | 管理 IP | 状态 | {DEVICE_IFACE} | CPU 1min | 内存 | 结论 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for item in records:
        status = "🟢 在线" if item["online"] else "🔴 离线"
        cpu = f"{item['cpu_percent']}%" if item["cpu_percent"] is not None else "-"
        mem = f"{item['mem_percent']}%" if item["mem_percent"] is not None else "-"
        lines.append(
            f"| {_cell(item['device'])} | {_cell(item['role'])} | {_cell(item['host'])} | {status} "
            f"| {_cell(item['if_state'])} | {cpu} | {mem} | {_cell(item['conclusion'])} |"
        )

    lines += ["", "## 二、问题清单", ""]
    if issues:
        lines += ["| 级别 | 设备 | 问题描述 |", "| --- | --- | --- |"]
        lines += [f"| {level} | {_cell(device)} | {_cell(message)} |"
                  for device, level, message in issues]
    else:
        lines.append("未发现异常项，所有被巡检设备的关键指标均处于阈值内。")

    lines += ["", "## 三、逐台明细", ""]
    for index, item in enumerate(records, start=1):
        lines.append(f"### {index}. {item['device']}（{item['role']} · {item['host']}）")
        lines.append("")
        if not item["online"]:
            lines.append(f"- 状态：**离线 / 不可达**；SSH 探测返回：`{_cell(item['error']) or '未知原因'}`")
            lines.append("")
            continue
        lines += [
            f"- 系统版本：{item['version']}",
            f"- 运行时长：{item['uptime']}",
            f"- 接口 {DEVICE_IFACE}：state **{item['if_state']}**；{item['if_detail']}",
            f"- CPU 负载：{item['cpu_detail']}",
            f"- 内存占用：{item['mem_detail']}",
            "",
        ]

    lines += ["## 四、建议动作", ""]
    advice = []
    for item in records:
        if not item["online"]:
            advice.append(
                f"- **{item['device']}**：先确认设备电源与链路，再核对 `inventory.json` 中的"
                f"管理 IP / 端口 / 账号是否可达（当前探测结果：{_cell(item['error']) or '未知原因'}）。"
            )
    for item in records:
        for level, message in item["issues"]:
            if level == "P1":
                advice.append(f"- **{item['device']}**：{message}，建议登录设备核验后按流程处置。")
    for item in records:
        for level, message in item["issues"]:
            if level == "P2":
                advice.append(f"- **{item['device']}**：{message}，可纳入下一轮观察。")
    lines += advice or ["- 本轮巡检未发现需要处置的问题，保持现有监控节奏即可。"]
    lines += ["", "---", "", "_报告由 AIOps 控制台自动生成 · 审计与告警数据持久化在 SQLite_"]
    return "\n".join(lines)


# ================= 页面渲染：CSS 注入 + 运行态数据 =================
inject_css()

probe = probe_devices()
total_n = len(DEVICES)
online_n = sum(1 for item in probe.values() if item.get("online"))
online_rate = round(online_n / total_n * 100, 1) if total_n else 0.0

sync_device_alerts(probe)                       # 不可达设备 → P0 告警（自动去重）
audit_rows = get_all_logs()
alert_stats = get_alert_stats()
alert_active = sum(stat["ACTIVE"] for stat in alert_stats.values())
pending_n = sum(1 for row in audit_rows if (row[4] or "").upper() == "PENDING")

if "messages" not in st.session_state:
    st.session_state.messages = [
        {"role": "system",
         "content": "你是一个专业的网络运维助手。你可以查询设备状态、开启/关闭端口、监控流量。"
                    "请根据用户指令调用对应工具。"}
    ]
st.session_state.setdefault("pending_task", None)
st.session_state.setdefault("inspect_result", None)
st.session_state.setdefault("traffic_sample", None)

# ================= 侧边栏：品牌 / 导航 / 系统状态 / 设备 / 告警 =================
with st.sidebar:
    st.markdown(
        f'<div class="ax-brand"><div class="mark">{ico("light")}</div><div>'
        '<div class="name">AIOps Console</div>'
        '<div class="desc">MCP &middot; VyOS &middot; DeepSeek</div></div></div>',
        unsafe_allow_html=True,
    )

    with card("side_system"):
        st.markdown(metric_card(card_head("系统状态", "System", "activity")),
                    unsafe_allow_html=True)
        st.markdown(metric_card(metric_head("设备在线率", "wifi")), unsafe_allow_html=True)
        st.metric("设备在线率", f"{online_rate}%", f"{online_n} / {total_n} 台在线",
                  label_visibility="collapsed")
        st.progress(
            (online_n / total_n) if total_n else 0.0,
            text=f"在线 {online_n} 台 · 离线 {total_n - online_n} 台",
        )
        st.markdown(metric_card(kv_rows([
            ("LLM 引擎", "DeepSeek · function calling"),
            ("通信协议", "MCP · stdio"),
            ("执行引擎", "Paramiko SSH"),
            ("审计存储", "SQLite · audit.db"),
        ], ["bolt", "share", "terminal", "database"])), unsafe_allow_html=True)
        if st.button("刷新设备状态", width="stretch", key="side_refresh"):
            probe_devices.clear()
            st.rerun()

    with card("side_nav"):
        st.markdown(metric_card(card_head("功能导航", "Modules", "filter")),
                    unsafe_allow_html=True)
        st.markdown(metric_card(kv_rows([
            ("01 · AI 运维对话", pill("TAB", "info", "chat")),
            ("02 · 流量监控", pill("TAB", "info", "traffic")),
            ("03 · 智能巡检", pill("TAB", "info", "search")),
            ("04 · 告警中心", pill(f"{alert_active}", "err" if alert_active else "muted", "bell")),
            ("05 · 审计日志", pill(f"{len(audit_rows)}", "muted", "clipboard")),
        ], ["chat", "traffic", "search", "bell", "clipboard"])), unsafe_allow_html=True)
        st.markdown(
            metric_card(
                '<div class="ax-note">侧边栏全部入口均使用 Feather 线性图标；'
                '图标以 CSS <code>background-image</code>（SVG data URI）内嵌，无图标字体依赖。</div>'),
            unsafe_allow_html=True,
        )

    with card("side_devices"):
        st.markdown(metric_card(card_head("设备清单", "Inventory", "server")),
                    unsafe_allow_html=True)
        device_rows, device_icons = [], []
        for name in DEVICES:
            online = bool(probe.get(name, {}).get("online"))
            device_rows.append((
                f"{name} · {TOPOLOGY[name]['role']}",
                pill("在线" if online else "离线", "ok" if online else "err"),
            ))
            device_icons.append("wifi" if online else "alert")
        st.markdown(metric_card(kv_rows(device_rows, device_icons)), unsafe_allow_html=True)
        st.markdown(
            metric_card('<div class="ax-note" style="margin-top:12px">可达性每 60 秒重新探测一次'
                        '（SSH · <code>show version</code>），也可点上按钮立即刷新。</div>'),
            unsafe_allow_html=True,
        )

    with card("side_alerts"):
        st.markdown(metric_card(card_head("告警概览", "Alerts", "bell")),
                    unsafe_allow_html=True)
        alert_rows_view = []
        for level in ("P0", "P1", "P2"):
            stat = alert_stats.get(level, {"ACTIVE": 0, "ACKED": 0})
            alert_rows_view.append((
                f"{level} · 未确认",
                f'{pill(stat["ACTIVE"], LEVEL_KIND[level])}'
                f'<span class="ax-pill muted" style="margin-left:6px">已确认 {stat["ACKED"]}</span>',
            ))
        st.markdown(metric_card(kv_rows(alert_rows_view, ["alert", "cpu", "memory"])),
                    unsafe_allow_html=True)
        st.markdown(
            metric_card('<div class="ax-note" style="margin-top:12px">P0 设备不可达 · P1 接口/CPU 异常 · '
                        'P2 内存与采集缺失；统一在【04 告警中心】确认闭环（可填写备注）。</div>'),
            unsafe_allow_html=True,
        )

    st.caption("AIOps Console v3.0 · 浅色 Glass 主题 / Plotly 圆角拓扑 / 巡检与告警闭环")


# ================= 顶部：品牌区 + 核心指标卡 + 拓扑 / 实时控制台 =================
st.markdown(hero_html(online_n, total_n, alert_active, pending_n), unsafe_allow_html=True)
st.write("")

metric_cards = [
    ("纳管设备", f"{total_n} 台", "inventory.json 资产", "server"),
    ("在线设备", f"{online_n} 台", f"在线率 {online_rate}%", "wifi"),
    ("未确认告警", f"{alert_active} 条",
     f"P0 {alert_stats['P0']['ACTIVE']} · P1 {alert_stats['P1']['ACTIVE']}", "bell"),
    ("审计记录", f"{len(audit_rows)} 条", f"待审批 {pending_n} 项", "clipboard"),
]
metric_cols = st.columns(4, gap="medium")
for index, (label, value, delta, icon) in enumerate(metric_cards):
    with metric_cols[index]:
        with card(f"metric_{index}"):
            st.markdown(metric_card(metric_head(label, icon)), unsafe_allow_html=True)
            st.metric(label, value, delta, label_visibility="collapsed")

col_topo, col_console = st.columns([2.15, 1], gap="large")
with col_topo:
    with card("topology"):
        st.markdown(
            metric_card(card_head("网络拓扑总览", f"Topology · {online_n}/{total_n} 在线", "share")),
            unsafe_allow_html=True,
        )
        st.plotly_chart(topology_figure(probe), width="stretch", theme=None,
                        config={"displayModeBar": False})
        st.markdown(
            metric_card('<div class="ax-note">拓扑节点为<b>圆角矩形</b>：'
                        '<b>#4ECDC4 在线</b> / <b>#FF6B6B 离线</b>；'
                        '鼠标悬停可查看角色、管理 IP 与系统版本。</div>'),
            unsafe_allow_html=True,
        )
with col_console:
    with card("console"):
        st.markdown(metric_card(card_head("实时运行控制台", "Live Console", "terminal")),
                    unsafe_allow_html=True)
        st.markdown(console_html(console_lines(audit_rows, online_n)), unsafe_allow_html=True)
        st.markdown(
            metric_card('<div class="ax-note" style="margin-top:12px">'
                        '与审计库同源，最近 6 条操作实时回显。</div>'),
            unsafe_allow_html=True,
        )

tab_chat, tab_traffic, tab_inspect, tab_alert, tab_audit = st.tabs([
    "01　AI 运维对话", "02　流量监控", "03　智能巡检", "04　告警中心", "05　审计日志",
])


# ================= Tab 1：AI 自然语言运维 =================
with tab_chat:
    col_chat, col_side = st.columns([2.1, 1], gap="large")

    with col_chat:
        with card("chat"):
            st.markdown(metric_card(card_head("AI 运维助手", "Conversation", "chat")),
                        unsafe_allow_html=True)
            if not DEEPSEEK_API_KEY:
                st.markdown(
                    metric_card('<div class="ax-note err"><b>未检测到 DeepSeek 密钥</b>：请在 '
                                '<code>.streamlit/secrets.toml</code> 中配置 '
                                '<code>DEEPSEEK_API_KEY</code>，或设置同名环境变量后重启控制台。</div>'),
                    unsafe_allow_html=True,
                )
            st.markdown(
                metric_card('<div class="ax-note">指令示例：<b>帮我查一下 R1 的 eth0 流量</b> / '
                            '<b>关闭 SW1 的 eth1 端口</b>（写操作会被拦截到人工审批队列）。</div>'),
                unsafe_allow_html=True,
            )
            st.write("")

            for msg in st.session_state.messages:
                if msg["role"] == "system":
                    continue
                if msg["role"] == "tool":
                    with st.expander("MCP 工具原始返回"):
                        st.code(msg["content"])
                elif msg["role"] == "assistant" and msg.get("tool_calls"):
                    with st.expander("AI 已发起工具调用（内部报文）"):
                        st.code(json.dumps(msg["tool_calls"], ensure_ascii=False, indent=2))
                else:
                    with st.chat_message(msg["role"]):
                        st.markdown(msg["content"])

            prompt = st.chat_input("例如：帮我查一下 R1 的 eth0 流量")

            # 右侧快捷指令通过 session_state 注入问题（先入队、再 rerun 消费）
            if not prompt and st.session_state.get("quick_prompt"):
                prompt = st.session_state.pop("quick_prompt")

            if prompt:
                st.session_state.messages.append({"role": "user", "content": prompt})
                with st.chat_message("user"):
                    st.markdown(prompt)

                with st.chat_message("assistant"):
                    with st.spinner("AI 正在解析意图并通过 MCP 协议执行..."):
                        try:
                            response = client.chat.completions.create(
                                model="deepseek-chat",
                                messages=st.session_state.messages,
                                tools=tools,
                                tool_choice="auto",
                            )
                            response_message = response.choices[0].message

                            if response_message.tool_calls:
                                st.session_state.messages.append(response_message.model_dump())

                                for tool_call in response_message.tool_calls:
                                    function_name = tool_call.function.name
                                    args = json.loads(tool_call.function.arguments)

                                    # 【核心安全机制】区分读操作与写操作
                                    if function_name == "configure_interface":
                                        # 写操作：存入待审批队列，不直接执行
                                        st.session_state.pending_task = {
                                            "function_name": function_name,
                                            "args": args,
                                            "tool_call_id": tool_call.id,
                                        }
                                        result = ("操作已提交至安全审批队列。"
                                                  "请管理员在【安全审批中心】点击批准执行或拒绝执行。")
                                        log_action(args.get("device_name"), function_name,
                                                   str(args), "PENDING")
                                    else:
                                        # 读操作：直接执行
                                        result = asyncio.run(call_mcp_tool(function_name, args))
                                        log_action(args.get("device_name"), function_name,
                                                   str(args), "SUCCESS")

                                    st.session_state.messages.append({
                                        "role": "tool",
                                        "tool_call_id": tool_call.id,
                                        "content": f"执行结果：\n{result}",
                                    })

                                    with st.expander(f"MCP 工具调用 · {function_name}"):
                                        st.code(result)

                                second_response = client.chat.completions.create(
                                    model="deepseek-chat",
                                    messages=st.session_state.messages,
                                )
                                final_answer = second_response.choices[0].message.content
                                st.markdown(final_answer)
                                st.session_state.messages.append(
                                    {"role": "assistant", "content": final_answer})

                            else:
                                final_answer = response_message.content
                                st.markdown(final_answer)
                                st.session_state.messages.append(
                                    {"role": "assistant", "content": final_answer})

                        except Exception as exc:  # noqa: BLE001 —— 单轮失败不应污染上下文
                            st.error(f"AI 调用或工具执行出错：{exc}")
                            while len(st.session_state.messages) > 1:
                                last_msg = st.session_state.messages[-1]
                                if last_msg["role"] == "tool" or (
                                        last_msg["role"] == "assistant" and "tool_calls" in last_msg):
                                    st.session_state.messages.pop()
                                else:
                                    break

        # ============ 安全审批中心（Human-in-the-loop） ============
        if st.session_state.get("pending_task"):
            task = st.session_state.pending_task
            action = (task["args"].get("action") or "").lower()
            action_pill = (pill("disable · 关闭端口", "err", "reject") if action == "disable"
                           else pill("enable · 开启端口", "ok", "check"))
            with card("approval"):
                st.markdown(metric_card(card_head("安全审批中心", "Human-in-the-loop", "shield")),
                            unsafe_allow_html=True)
                st.markdown(
                    metric_card('<div class="ax-note warn"><b>检测到待审批的写操作</b>：'
                                '请核对目标设备与端口后再决定是否执行。</div>'),
                    unsafe_allow_html=True,
                )
                st.write("")
                st.markdown(metric_card(kv_rows([
                    ("目标设备", esc(task["args"].get("device_name"))),
                    ("目标端口", esc(task["args"].get("interface"))),
                    ("动作", action_pill),
                    ("工具", esc(task["function_name"])),
                ], ["server", "share", "bolt", "terminal"])), unsafe_allow_html=True)
                with st.expander("查看原始参数"):
                    st.code(str(task["args"]))

                col_approve, col_reject = st.columns(2)
                with col_approve:
                    if st.button("批准执行", type="primary", width="stretch", key="btn_approve"):
                        with st.spinner("正在下发配置..."):
                            result = asyncio.run(
                                call_mcp_tool(task["function_name"], task["args"]))
                            log_action(task["args"].get("device_name"), task["function_name"],
                                       str(task["args"]), "EXECUTED")
                            st.session_state.flash = ("success", f"配置已下发！执行结果：{result}")
                            st.session_state.pending_task = None
                        st.rerun()
                with col_reject:
                    if st.button("拒绝执行", width="stretch", key="btn_reject"):
                        log_action(task["args"].get("device_name"), task["function_name"],
                                   str(task["args"]), "REJECTED")
                        st.session_state.flash = ("error", "操作已被管理员拒绝，已写入审计日志。")
                        st.session_state.pending_task = None
                        st.rerun()

        if st.session_state.get("flash"):
            kind, text = st.session_state.pop("flash")
            (st.success if kind == "success" else st.error)(text)

    with col_side:
        with card("quick"):
            st.markdown(metric_card(card_head("快捷指令", "Quick Actions", "bolt")),
                        unsafe_allow_html=True)
            quick_prompts = [
                ("查询 R1 路由表", "帮我查询 R1 的 ip route 路由表"),
                ("查看 SW1 端口状态", "查一下 SW1 的 interfaces 端口状态"),
                ("采集 R1 eth0 流量", "监控 R1 的 eth0 端口流量"),
            ]
            for label, text_value in quick_prompts:
                if st.button(label, width="stretch", key=f"quick_{label}"):
                    st.session_state.quick_prompt = text_value
                    st.rerun()
            if st.button("清空对话上下文", width="stretch", key="btn_clear_chat"):
                st.session_state.messages = [st.session_state.messages[0]]
                st.session_state.pending_task = None
                st.rerun()

        with card("security"):
            st.markdown(metric_card(card_head("安全机制", "Guardrails", "shield")),
                        unsafe_allow_html=True)
            st.markdown(metric_card(kv_rows([
                ("只读命令", "仅放行 show*"),
                ("写操作", "强制人工审批"),
                ("审批留痕", "SQLite 审计库"),
                ("拒绝动作", "记录 REJECTED"),
            ], ["check", "shield", "database", "reject"])), unsafe_allow_html=True)
            st.markdown(
                metric_card('<div class="ax-note" style="margin-top:12px">AI 仅可执行 show 类只读命令；'
                            '涉及端口启停的写操作会被拦截到审批队列，审批与执行结果全部写入 SQLite '
                            '审计库。</div>'),
                unsafe_allow_html=True,
            )


# ================= Tab 2：真实流量监控 =================
with tab_traffic:
    with card("traffic_run"):
        st.markdown(metric_card(card_head("流量采样", "Traffic Monitor", "traffic")),
                    unsafe_allow_html=True)
        col_action, col_info = st.columns([1, 2.4], gap="large")
        with col_action:
            sample_clicked = st.button("开始真实采样", type="primary", width="stretch",
                                       key="btn_sample")
        with col_info:
            st.markdown(
                metric_card(f'<div class="ax-note">采样会连续发起两次 '
                            f'<code>show interfaces ethernet {DEVICE_IFACE}</code>（间隔 3 秒），'
                            f'增量 Δ = 第二次计数 − 第一次计数；'
                            f'若设备无计数回显则降级为演示数据。</div>'),
                unsafe_allow_html=True,
            )

        if sample_clicked and DEVICES:
            with st.spinner("正在通过 MCP 采集真实数据..."):
                cmd = f"show interfaces ethernet {DEVICE_IFACE}"
                out1 = asyncio.run(call_mcp_tool(
                    "query_device", {"device_name": DEVICES[0], "command_name": cmd}))
                time.sleep(3)
                out2 = asyncio.run(call_mcp_tool(
                    "query_device", {"device_name": DEVICES[0], "command_name": cmd}))

                rx1, tx1 = parse_traffic(out1)
                rx2, tx2 = parse_traffic(out2)
                source = "真实采样"

                if rx1 == 0 and rx2 == 0:
                    rx1 = random.randint(10000, 20000)
                    rx2 = rx1 + random.randint(5000, 15000)
                    tx1 = random.randint(20000, 30000)
                    tx2 = tx1 + random.randint(8000, 20000)
                    source = "演示数据"

                st.session_state.traffic_sample = {
                    "rx1": rx1, "rx2": rx2, "tx1": tx1, "tx2": tx2,
                    "source": source, "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
                }
                st.session_state.traffic_raw = {"first": out1, "second": out2}

    sample = st.session_state.get("traffic_sample")
    with card("traffic_result"):
        st.markdown(metric_card(card_head("采样结果与趋势", "Throughput", "traffic")),
                    unsafe_allow_html=True)
        if not sample:
            st.markdown(
                metric_card('<div class="ax-note warn">尚未采样。点击上方【开始真实采样】后，'
                            '这里会展示 RX / TX 增量与趋势图。</div>'),
                unsafe_allow_html=True,
            )
        else:
            delta_rx = sample["rx2"] - sample["rx1"]
            delta_tx = sample["tx2"] - sample["tx1"]
            metric_row = st.columns(3, gap="medium")
            traffic_metrics = [
                ("RX 接收增量", f"+{delta_rx:,} Bytes", f"{sample['source']} · RX", "download"),
                ("TX 发送增量", f"+{delta_tx:,} Bytes", f"{sample['source']} · TX", "download"),
                ("采样时刻", sample["ts"][11:], sample["ts"][:10], "clock"),
            ]
            for index, (label, value, delta, icon) in enumerate(traffic_metrics):
                with metric_row[index]:
                    with card(f"traffic_metric_{index}"):
                        st.markdown(metric_card(metric_head(label, icon)), unsafe_allow_html=True)
                        st.metric(label, value, delta, label_visibility="collapsed")

            st.plotly_chart(traffic_figure(sample), width="stretch", theme=None,
                            config={"displayModeBar": False})

            detail_df = pd.DataFrame({
                "采样点": ["第 1 次采样", "第 2 次采样"],
                "RX (接收字节)": [sample["rx1"], sample["rx2"]],
                "TX (发送字节)": [sample["tx1"], sample["tx2"]],
            })
            st.dataframe(detail_df, width="stretch", hide_index=True)

            with st.expander("查看两次 MCP 原始返回"):
                st.code(st.session_state.get("traffic_raw", {}).get("first", "无数据"))
                st.code(st.session_state.get("traffic_raw", {}).get("second", "无数据"))


# ================= Tab 3：智能巡检（接口 / CPU / 内存 → Markdown 报告） =================
with tab_inspect:
    with card("inspect_run"):
        st.markdown(metric_card(card_head("一键巡检", "Inspection", "search")),
                    unsafe_allow_html=True)
        col_btn, col_tip = st.columns([1, 2.6], gap="large")
        with col_btn:
            run_clicked = st.button("一键巡检", type="primary", width="stretch",
                                    key="btn_inspect")
        with col_tip:
            st.markdown(
                metric_card(f'<div class="ax-note">逐台执行 4 条<b>只读</b>命令：'
                            f'<code>show version</code> / '
                            f'<code>show interfaces ethernet {DEVICE_IFACE}</code> / '
                            f'<code>show system uptime</code>（CPU 负载）/ '
                            f'<code>show system memory</code>，解析接口状态、CPU 负载与内存使用率'
                            f'并生成 Markdown 报告；异常项自动写入告警中心'
                            f'（P0 不可达 / P1 接口·CPU / P2 内存·采集缺失）。</div>'),
                unsafe_allow_html=True,
            )

        if run_clicked:
            bar = st.progress(0.0, text="准备巡检 ...")
            st.session_state.inspect_result = run_inspection(
                progress_cb=lambda value, text: bar.progress(value, text=text))
            finished = st.session_state.inspect_result
            for item in finished["records"]:
                for level, message in item["issues"]:
                    log_alert(item["device"], level, message, dedupe=True)
            log_action(
                "ALL", "inspection",
                f"巡检 {len(finished['records'])} 台设备，异常 "
                f"{sum(len(item['issues']) for item in finished['records'])} 项",
                "SUCCESS",
            )
            st.rerun()

    result = st.session_state.get("inspect_result")
    if result:
        records = result["records"]
        issue_total = sum(len(item["issues"]) for item in records)
        issue_kind = {"P0": 0, "P1": 0, "P2": 0}
        for item in records:
            for level, _message in item["issues"]:
                issue_kind[level] = issue_kind.get(level, 0) + 1
        online_inspect = sum(1 for item in records if item["online"])
        rate = round(online_inspect / len(records) * 100, 1) if records else 0.0
        summary_cards = [
            ("巡检设备", f"{len(records)} 台", f"耗时 {result['elapsed']:.1f} 秒", "server"),
            ("在线设备", f"{online_inspect} 台", f"在线率 {rate}%", "wifi"),
            ("异常项", f"{issue_total} 项",
             f"P0 {issue_kind['P0']} · P1 {issue_kind['P1']} · P2 {issue_kind['P2']}", "alert"),
            ("报告时间", result["started_at"][11:], result["started_at"][:10], "clock"),
        ]
        summary = st.columns(4, gap="medium")
        for index, (label, value, delta, icon) in enumerate(summary_cards):
            with summary[index]:
                with card(f"inspect_metric_{index}"):
                    st.markdown(metric_card(metric_head(label, icon)), unsafe_allow_html=True)
                    st.metric(label, value, delta, label_visibility="collapsed")

    with card("inspect_report"):
        st.markdown(metric_card(card_head("巡检报告", "Report · Markdown", "file")),
                    unsafe_allow_html=True)
        if not result:
            st.markdown(
                metric_card('<div class="ax-note warn">尚未巡检。点击上方【一键巡检】后，'
                            '这里会展示 Markdown 格式的巡检报告。</div>'),
                unsafe_allow_html=True,
            )
        else:
            report = build_inspection_report(result["records"], result["started_at"],
                                             result["elapsed"])
            st.markdown(report)
            stamp = (result["started_at"].replace("-", "").replace(":", "").replace(" ", "_"))
            st.download_button(
                "下载巡检报告 (.md)",
                data=report.encode("utf-8"),
                file_name=f"aiops_inspection_{stamp}.md",
                mime="text/markdown",
                width="stretch",
                key="btn_download_report",
            )
            with st.expander("查看各设备 MCP 原始返回"):
                for item in result["records"]:
                    st.markdown(
                        f'<div class="ax-head"><span class="ax-left">{ico("server")}'
                        f'<span class="ax-title">{esc(item["device"])} · {esc(item["role"])}</span>'
                        f'</span><span class="ax-sub">{esc(item["host"])}</span></div>',
                        unsafe_allow_html=True,
                    )
                    for cmd, raw in item["raw"].items():
                        st.caption(cmd)
                        st.code(raw)


# ================= Tab 4：告警中心（SQLite 历史告警 · 级别筛选 · 确认闭环 + 备注） =================
with tab_alert:
    if st.session_state.get("flash_alert"):
        st.toast(st.session_state.pop("flash_alert"))

    alert_summary = get_alert_stats()
    active_total = sum(stat["ACTIVE"] for stat in alert_summary.values())
    acked_total = sum(stat["ACKED"] for stat in alert_summary.values())

    alert_metric = st.columns(4, gap="medium")
    with alert_metric[0]:
        with card("alert_metric_total"):
            st.markdown(metric_card(metric_head("未确认告警", "bell")), unsafe_allow_html=True)
            st.metric("未确认告警", f"{active_total} 条", f"已确认 {acked_total} 条",
                      label_visibility="collapsed")
    for index, level in enumerate(("P0", "P1", "P2"), start=1):
        stat = alert_summary.get(level, {"ACTIVE": 0, "ACKED": 0})
        with alert_metric[index]:
            with card(f"alert_metric_{level}"):
                st.markdown(metric_card(metric_head(f"{level} 未确认", "alert")),
                            unsafe_allow_html=True)
                st.metric(f"{level} 未确认", f"{stat['ACTIVE']} 条", f"已确认 {stat['ACKED']} 条",
                          label_visibility="collapsed")

    with card("alert_filter"):
        st.markdown(metric_card(card_head("告警筛选与导出", "Alerts Filter", "filter")),
                    unsafe_allow_html=True)
        col_level, col_status, col_export = st.columns([1.2, 1.15, 1], gap="large")
        with col_level:
            level_pick = st.radio("级别", ["全部", "P0", "P1", "P2"], horizontal=True,
                                  key="alert_level")
        with col_status:
            status_pick = st.radio("状态", ["未确认", "已确认", "全部"], horizontal=True,
                                   key="alert_status")
        with col_export:
            all_alert_rows = get_alerts()
            alert_export = pd.DataFrame(
                all_alert_rows,
                columns=["ID", "时间", "设备", "级别", "告警内容", "状态", "备注"],
            )
            st.download_button(
                "导出告警 CSV",
                data=alert_export.to_csv(index=False).encode("utf-8-sig"),
                file_name=f"aiops_alerts_{datetime.now():%Y%m%d_%H%M%S}.csv",
                mime="text/csv",
                width="stretch",
                key="btn_export_alerts",
            )
            if st.button("刷新告警", width="stretch", key="btn_refresh_alerts"):
                st.rerun()
        st.markdown(
            metric_card('<div class="ax-note" style="margin-top:10px">告警来源：设备可达性探测'
                        '（P0 不可达）、一键巡检（P1 接口/CPU 异常、P2 内存与采集缺失）；'
                        '同一设备同一内容的未确认告警会自动去重，确认后才会重新写入。'
                        '确认时可填写处置备注，备注随 CSV 一同导出。</div>'),
            unsafe_allow_html=True,
        )

    status_map = {"未确认": "ACTIVE", "已确认": "ACKED", "全部": None}
    alert_rows = get_alerts(
        level=None if level_pick == "全部" else level_pick,
        status=status_map[status_pick],
    )

    with card("alert_list"):
        st.markdown(
            metric_card(card_head("告警列表",
                                  f"{level_pick} · {status_pick} · 共 {len(alert_rows)} 条",
                                  "bell")),
            unsafe_allow_html=True,
        )
        if not alert_rows:
            st.markdown(
                metric_card('<div class="ax-note warn">当前筛选条件下没有告警记录。'
                            '可执行【03 智能巡检】或等待下一次设备探测后查看。</div>'),
                unsafe_allow_html=True,
            )
        else:
            alert_table = pd.DataFrame(
                [(row[1], row[2], row[3], row[4],
                  "已确认" if row[5] == "ACKED" else "未确认", row[6] or "")
                 for row in alert_rows],
                columns=["时间", "设备", "级别", "告警内容", "状态", "备注"],
            )
            st.dataframe(alert_table, width="stretch", hide_index=True)

            pending_rows = [row for row in alert_rows if row[5] == "ACTIVE"]
            if pending_rows:
                st.markdown(
                    metric_card(card_head(f"待确认告警 · {len(pending_rows)} 条",
                                          "Acknowledge", "check")),
                    unsafe_allow_html=True,
                )
                col_bulk, col_bulk_note = st.columns([1, 2.4], gap="large")
                with col_bulk:
                    if st.button("全部标记已确认", type="primary", width="stretch",
                                 key="btn_ack_all"):
                        changed = ack_all_alerts(
                            level=None if level_pick == "全部" else level_pick,
                            note=st.session_state.get("ack_note_all", "") or "",
                        )
                        st.session_state.flash_alert = f"已确认 {changed} 条告警"
                        st.rerun()
                with col_bulk_note:
                    st.text_input("批量备注", key="ack_note_all",
                                  placeholder="可选：批量确认时统一写入的备注（如：计划维护窗口）")
                    st.markdown(
                        metric_card(f'<div class="ax-note">逐条确认会写入 <code>acked_at</code> 时间戳'
                                    f'与备注；批量确认仅作用于当前筛选级别（{level_pick}）。</div>'),
                        unsafe_allow_html=True,
                    )

                for row in pending_rows[:15]:
                    ack_id, stamp, device, level, message, _status = row[:6]
                    note = row[6] if len(row) > 6 else ""
                    st.markdown(
                        metric_card(alert_row_html(level, device, message, stamp, "未确认", note or "")),
                        unsafe_allow_html=True,
                    )
                    col_note, col_btn = st.columns([2.6, 1], gap="large")
                    with col_note:
                        note_value = st.text_input(
                            "处置备注", key=f"note_{ack_id}",
                            placeholder="可选：填写处置说明 / 工单号（会随告警一起存档并导出）",
                        )
                    with col_btn:
                        st.write("")
                        if st.button("标记已确认", type="primary", width="stretch",
                                     key=f"ack_{ack_id}"):
                            ack_alert(ack_id, note_value)
                            st.session_state.flash_alert = f"已确认 {device} 的 {level} 告警"
                            st.rerun()
                if len(pending_rows) > 15:
                    st.caption(f"仅展示最近 15 条待确认告警，其余 "
                               f"{len(pending_rows) - 15} 条可在上方表格中查看。")


# ================= Tab 5：审计日志（状态筛选 + CSV 导出） =================
with tab_audit:
    audit_now = get_all_logs()
    success_n = sum(1 for row in audit_now if (row[4] or "").upper() in ("SUCCESS", "EXECUTED"))
    reject_n = sum(1 for row in audit_now if (row[4] or "").upper() in ("REJECTED", "FAILED"))
    pending_log_n = sum(1 for row in audit_now if (row[4] or "").upper() == "PENDING")

    audit_cards = [
        ("日志总条数", f"{len(audit_now)} 条", "按写入时间倒序", "clipboard"),
        ("执行成功", f"{success_n} 条", "读操作与已批准写操作", "check"),
        ("待审批", f"{pending_log_n} 条", "拦截在审批队列", "clock"),
        ("已拒绝 / 失败", f"{reject_n} 条", "管理员拒绝或执行异常", "reject"),
    ]
    audit_metric = st.columns(4, gap="medium")
    for index, (label, value, delta, icon) in enumerate(audit_cards):
        with audit_metric[index]:
            with card(f"audit_metric_{index}"):
                st.markdown(metric_card(metric_head(label, icon)), unsafe_allow_html=True)
                st.metric(label, value, delta, label_visibility="collapsed")

    with card("audit_filter"):
        st.markdown(metric_card(card_head("筛选与导出", "Audit Trail", "filter")),
                    unsafe_allow_html=True)
        col_filter, col_export = st.columns([1.6, 1], gap="large")
        with col_filter:
            audit_status = st.selectbox(
                "状态筛选",
                ["全部", "SUCCESS", "EXECUTED", "PENDING", "REJECTED", "FAILED"],
                index=0,
                key="audit_status",
            )
        with col_export:
            audit_export = pd.DataFrame(
                audit_now, columns=["时间", "设备", "操作类型", "参数详情", "状态"])
            st.download_button(
                "导出 CSV",
                data=audit_export.to_csv(index=False).encode("utf-8-sig"),
                file_name=f"aiops_audit_logs_{datetime.now():%Y%m%d_%H%M%S}.csv",
                mime="text/csv",
                width="stretch",
                key="btn_export_audit",
            )
            if st.button("刷新日志", width="stretch", key="btn_refresh_audit"):
                st.rerun()
        st.markdown(
            metric_card('<div class="ax-note" style="margin-top:10px">导出为 <b>UTF-8 BOM</b> 编码 '
                        'CSV，可直接用 Excel 打开且不乱码；导出内容为<b>全量</b>记录，'
                        '不受上方筛选条件影响。</div>'),
            unsafe_allow_html=True,
        )

    filtered_rows = [
        row for row in audit_now
        if audit_status == "全部" or (row[4] or "").upper() == audit_status
    ]
    with card("audit_list"):
        st.markdown(metric_card(card_head("操作明细", f"Records · {len(filtered_rows)} 条",
                                           "clipboard")), unsafe_allow_html=True)
        if filtered_rows:
            st.dataframe(
                pd.DataFrame(filtered_rows,
                             columns=["时间", "设备", "操作类型", "参数详情", "状态"]),
                width="stretch",
                hide_index=True,
            )
        else:
            st.markdown(metric_card('<div class="ax-note warn">暂无操作记录。</div>'),
                        unsafe_allow_html=True)

        st.markdown(metric_card(card_head("最近操作时间线", "Recent Activity", "clock")),
                    unsafe_allow_html=True)
        st.markdown(timeline_html(filtered_rows or audit_now, 8), unsafe_allow_html=True)
