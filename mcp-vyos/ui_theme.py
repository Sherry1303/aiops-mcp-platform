# -*- coding: utf-8 -*-
"""
ui_theme.py —— AIOps 控制台视觉主题层（设计 token + 注入式 CSS + HTML 组件）

设计语言参考：https://world.webdesignclip.com/ （海外优秀网页设计图库）
从该站点原始 CSS 中提取并复用的真实设计 token：
    --main-color:#3e5766   --sub-color:#4f6674   --color-01:#9fabb3
    --color-02:#6e818c     --cm-base:#384e5c     --cm-dark:#2d3e4a
    --cm-over:#24323b      --cm-opa50:#c4cace
    画布 #f3f0e9（暖米色） / 卡片 #fff + 1px 描边 #dbd4c8（无阴影，扁平印刷感）
    字体 'Roboto Condensed' + 大字距 label（letter-spacing:.1rem~.15rem）
    交互统一 all .2s ease-in（描边加深 / 轻微上浮 / 底色反白）
"""

import html as _html

import streamlit as st

# ============================ 设计 token ============================
TOKENS = {
    "ink": "#2d3e4a",        # 主文字（cm-dark）
    "slate": "#3e5766",      # 品牌主色（main-color）
    "slate2": "#4f6674",     # 次级主色（sub-color）
    "muted": "#6e818c",      # 说明文字（color-02）
    "faint": "#9fabb3",      # 极淡文字（color-01）
    "line": "#dbd4c8",       # 发丝描边
    "soft": "#e9e5de",       # 次级面
    "paper": "#f3f0e9",      # 页面画布
    "card": "#ffffff",       # 卡片
    "panel": "#384e5c",      # 深色面板（cm-base）
    "deep": "#24323b",       # 终端底色（cm-over）
    "ok": "#00d084",         # 在线
    "err": "#cf2e2e",        # 离线
    "warn": "#ff6900",       # 待审批
    "info": "#0693e3",       # 提示
}


def token(name: str, default: str = "") -> str:
    """读取设计 token，便于 app.py 与图表配色复用。"""
    return TOKENS.get(name, default)


def esc(text) -> str:
    """HTML 转义，避免设备回显内容破坏页面结构。"""
    return _html.escape(str(text if text is not None else ""))


# ============================ 注入式全局 CSS ============================
CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Roboto+Condensed:wght@400;500;700&family=Noto+Sans+SC:wght@300;400;500;700&display=swap');

:root{
  --ax-ink:#2d3e4a; --ax-slate:#3e5766; --ax-slate2:#4f6674;
  --ax-muted:#6e818c; --ax-faint:#9fabb3; --ax-line:#dbd4c8;
  --ax-soft:#e9e5de; --ax-paper:#f3f0e9; --ax-card:#ffffff;
  --ax-panel:#384e5c; --ax-deep:#24323b;
  --ax-ok:#00d084; --ax-ok-ink:#1c7a54; --ax-err:#cf2e2e;
  --ax-warn:#ff6900; --ax-warn-ink:#b14b00; --ax-info:#0693e3;
  --ax-radius:8px; --ax-pill:20px; --ax-ease:all .2s ease-in;
  --ax-font:'Roboto Condensed','Noto Sans SC','Hiragino Sans GB','Microsoft YaHei',sans-serif;
  --ax-mono:'JetBrains Mono','Cascadia Mono','Consolas','Courier New',monospace;
}

/* ---------- 画布与基础排版 ---------- */
html, body, .stApp{ background:var(--ax-paper) !important; color:var(--ax-ink); }
.stApp, .stApp p, .stApp li, .stApp label, .stApp input, .stApp textarea,
.stApp button, .stApp select, .stApp h1, .stApp h2, .stApp h3, .stApp h4,
.stApp h5, .stApp h6, .stApp table{ font-family:var(--ax-font); }
.block-container, [data-testid="stMainBlockContainer"]{ padding-top:2.0rem; padding-bottom:3rem; max-width:1520px; }
[data-testid="stHeader"]{ background:transparent; height:0; }
#MainMenu, footer, [data-testid="stToolbar"], [data-testid="stStatusWidget"]{ display:none !important; }
h1, h2, h3, h4{ color:var(--ax-ink); letter-spacing:.02em; font-weight:700; }
h2{ font-size:1.45rem; } h3{ font-size:1.1rem; }
hr{ border:none; border-top:1px solid var(--ax-line); margin:1.2rem 0; }
a{ color:var(--ax-slate); }

/* ---------- 侧边栏 ---------- */
[data-testid="stSidebar"]{ background:var(--ax-card); border-right:1px solid var(--ax-line); }
[data-testid="stSidebar"] > div:first-child{ padding-top:1.2rem; }
[data-testid="stSidebarHeader"]{ padding-bottom:.4rem; }
[data-testid="stSidebarUserContent"]{ padding-top:.4rem; padding-bottom:2.5rem; }
[data-testid="stSidebar"] hr{ border-top:1px solid var(--ax-line); }
[data-testid="stSidebar"] *::-webkit-scrollbar{ width:6px; height:6px; }
[data-testid="stSidebar"] *::-webkit-scrollbar-thumb{ background:var(--ax-line); border-radius:3px; }
[data-testid="stSidebar"] *::-webkit-scrollbar-thumb:hover{ background:var(--ax-faint); }

/* ---------- 顶部导航式 Tab（55px 高、hover 反白） ----------
   Streamlit ≥1.5x 的 Tabs 已不再使用 BaseWeb，DOM 为：
   div.stTabs > div > div(标签条) + div[data-testid="stTabPanel"]；
   选中态类名由 CSS-in-JS 生成，这里只对可能的属性做防御性匹配，
   主色下划线仍由主题 primaryColor 提供。 */
.stTabs > div > div:first-child{ gap:2px; border-bottom:1px solid var(--ax-line); padding:0; }
.stTabs [data-testid="stTab"]{
  height:55px; min-height:55px; padding:0 22px; margin:0;
  background:transparent; border-radius:0;
  color:var(--ax-muted); transition:var(--ax-ease);
}
.stTabs [data-testid="stTab"] p{
  font-size:.95rem; font-weight:500; letter-spacing:.12em; color:inherit;
}
.stTabs [data-testid="stTab"]:hover{ background:var(--ax-card); color:var(--ax-ink); }
.stTabs [data-testid="stTab"][aria-selected="true"],
.stTabs [data-testid="stTab"][data-selected="true"],
.stTabs [data-testid="stTab"][data-state="active"]{ background:var(--ax-card); color:var(--ax-ink); }
.stTabs [data-testid="stTab"][aria-selected="true"] p,
.stTabs [data-testid="stTab"][data-selected="true"] p,
.stTabs [data-testid="stTab"][data-state="active"] p{ font-weight:700; }
.stTabs [data-testid="stTabPanel"]{ padding-top:1.5rem; }

/* ---------- 按钮：胶囊形、扁平、hover 反白 ----------
   st.button 的 DOM 为 div.stButton >（可选 help 包裹层）> button，
   因此统一下沉为后代选择器，避免包裹层变化导致样式失效。 */
.stButton button, .stDownloadButton button, .stFormSubmitButton button{
  width:auto; border:1px solid var(--ax-line); border-radius:var(--ax-pill);
  background:var(--ax-card); color:var(--ax-slate);
  font-size:.92rem; font-weight:500; letter-spacing:.1em;
  padding:.52rem 1.15rem; box-shadow:none; transition:var(--ax-ease);
}
.stButton button:hover, .stDownloadButton button:hover, .stFormSubmitButton button:hover{
  background:var(--ax-slate); border-color:var(--ax-slate); color:#fff !important; transform:translateY(-1px);
}
.stButton button:hover *, .stDownloadButton button:hover *{ color:#fff !important; }
.stButton button:active, .stDownloadButton button:active{
  transform:translateY(0); background:var(--ax-deep); color:#fff;
}
.stButton button:focus, .stDownloadButton button:focus{
  outline:none; box-shadow:0 0 0 3px rgba(62,87,102,.14);
}
.stButton button[kind="primary"], .stButton button[data-testid="stBaseButton-primary"],
.stDownloadButton button[kind="primary"]{
  background:var(--ax-slate); border-color:var(--ax-slate); color:#fff;
}
.stButton button[kind="primary"] *{ color:#fff !important; }
.stButton button[kind="primary"]:hover{ background:var(--ax-deep); border-color:var(--ax-deep); }
.stButton button:disabled{ opacity:.45; }

/* ---------- 输入类：胶囊、发丝描边、聚焦晕环 ---------- */
[data-testid="stChatInput"]{
  background:var(--ax-card); border:1px solid var(--ax-line);
  border-radius:var(--ax-pill); transition:var(--ax-ease);
}
[data-testid="stChatInput"]:focus-within{
  border-color:var(--ax-slate); box-shadow:0 0 0 3px rgba(62,87,102,.10);
}
[data-testid="stChatInput"] textarea{
  background:transparent !important; color:var(--ax-ink) !important; font-size:.98rem;
}
/* Streamlit ≥1.5x 已移除 BaseWeb，输入类控件用各自的 testid / role 定位 */
.stTextInput input, .stNumberInput input{
  border-radius:var(--ax-pill); border:1px solid var(--ax-line);
  background:var(--ax-card); color:var(--ax-ink); box-shadow:none;
}
.stTextInput input:focus, .stNumberInput input:focus{ border-color:var(--ax-slate); box-shadow:none; }
[data-testid="stTextInputRootElement"]{
  border-radius:var(--ax-pill) !important; border:1px solid var(--ax-line) !important;
  background:var(--ax-card);
}
[data-testid="stSelectbox"] [role="combobox"], [data-testid="stSelectbox"] button{
  border-radius:var(--ax-pill); border-color:var(--ax-line); background:var(--ax-card); color:var(--ax-ink);
}
[data-testid="stSelectbox"]:focus-within [role="combobox"]{ border-color:var(--ax-slate); }
[data-testid="stWidgetLabel"] p{ color:var(--ax-muted) !important; font-size:.82rem !important; letter-spacing:.08em; }

/* ---------- 对话气泡 ---------- */
[data-testid="stChatMessage"]{
  background:var(--ax-card); border:1px solid var(--ax-line); border-radius:var(--ax-radius);
  padding:14px 18px; margin-bottom:10px; transition:var(--ax-ease);
}
[data-testid="stChatMessage"]:hover{ border-color:#cfc7b6; }
[data-testid="stChatMessageContent"] p{ font-size:.95rem; line-height:1.85; }
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]){
  background:var(--ax-soft); border-color:#ded7c9;
}
[data-testid="stChatMessageAvatarUser"]{ background:var(--ax-slate) !important; color:#fff !important; }
[data-testid="stChatMessageAvatarAssistant"]{
  background:var(--ax-paper) !important; border:1px solid var(--ax-line);
}
/* ---------- 指标 / 提示 / 折叠 / 代码 / 表格 ---------- */
[data-testid="stMetric"]{
  background:var(--ax-card); border:1px solid var(--ax-line); border-radius:var(--ax-radius);
  padding:16px 18px; transition:var(--ax-ease);
}
[data-testid="stMetric"]:hover{ border-color:var(--ax-slate); transform:translateY(-2px); }
[data-testid="stMetricLabel"] p{
  font-size:.7rem !important; letter-spacing:.2em; text-transform:uppercase; color:var(--ax-muted) !important;
}
[data-testid="stMetricValue"]{ color:var(--ax-ink); font-weight:700; }

[data-testid="stAlert"]{
  border-radius:var(--ax-radius); border:1px solid var(--ax-line);
  border-left-width:3px; box-shadow:none; padding:14px 18px;
}
[data-testid="stAlert"] p{ font-size:.9rem; line-height:1.75; }

[data-testid="stExpander"]{
  border:1px solid var(--ax-line) !important; border-radius:var(--ax-radius);
  background:var(--ax-card); box-shadow:none !important; overflow:hidden;
}
[data-testid="stExpander"] summary{ color:var(--ax-slate); font-size:.88rem; letter-spacing:.06em; }
[data-testid="stExpander"] summary:hover{ color:var(--ax-ink); }

.stCode, [data-testid="stCode"], [data-testid="stMarkdownPre"]{
  background:var(--ax-deep) !important; border:1px solid #1c252c; border-radius:var(--ax-radius);
}
.stCode pre, .stCode code, [data-testid="stCode"] pre, [data-testid="stCode"] code,
[data-testid="stMarkdownPre"] pre, [data-testid="stMarkdownPre"] code{
  background:transparent !important; color:#e2e9ee !important;
  font-family:var(--ax-mono) !important; font-size:.82rem; line-height:1.75;
}
.stCode pre, [data-testid="stCode"] pre, [data-testid="stMarkdownPre"] pre{ padding:14px 16px; margin:0; }
[data-testid="stDataFrame"]{
  border:1px solid var(--ax-line); border-radius:var(--ax-radius);
  background:var(--ax-card); overflow:hidden;
}
[data-testid="stSpinner"] p{ color:var(--ax-muted); font-size:.88rem; letter-spacing:.06em; }
[data-testid="stExpanderDetails"]{ padding-top:.2rem; }
/* 说明：Streamlit ≥1.5x 不再提供 stVerticalBlockBorderWrapper，
   因此审批卡等"带边框容器"统一改用自定义 HTML 卡片（.ax-card）实现，见 app.py。 */
/* ================= 自定义组件（HTML 片段） ================= */
.ax-eyebrow{
  font-size:.7rem; letter-spacing:.24em; text-transform:uppercase;
  color:var(--ax-faint); font-weight:500; margin:0 0 .6rem;
}
.ax-h1{
  font-size:2rem; font-weight:700; line-height:1.2; color:var(--ax-ink);
  margin:0 0 .55rem; letter-spacing:.01em;
}
.ax-h1 em{ font-style:normal; color:var(--ax-slate); }
.ax-sub{ color:var(--ax-muted); font-size:.92rem; line-height:1.8; margin:0; max-width:64ch; }
.ax-hero{
  position:relative; background:var(--ax-card); border:1px solid var(--ax-line);
  border-radius:var(--ax-radius); padding:30px 34px 26px; margin-bottom:16px; overflow:hidden;
}
.ax-hero:before{ content:''; position:absolute; top:0; left:0; width:120px; height:3px; background:var(--ax-slate); }
.ax-hero-row{ display:flex; justify-content:space-between; align-items:flex-end; gap:28px; flex-wrap:wrap; }
.ax-hero-meta{ text-align:right; }
.ax-hr{ height:1px; background:var(--ax-line); margin:20px 0; border:none; }

.ax-kpis{ display:grid; grid-template-columns:repeat(auto-fit,minmax(185px,1fr)); gap:14px; margin:0 0 4px; }
.ax-kpi{
  background:var(--ax-card); border:1px solid var(--ax-line); border-radius:var(--ax-radius);
  padding:16px 18px; transition:var(--ax-ease);
}
.ax-kpi:hover{ border-color:var(--ax-slate); transform:translateY(-2px); }
.ax-kpi-k{ font-size:.68rem; letter-spacing:.2em; text-transform:uppercase; color:var(--ax-faint); margin-bottom:12px; }
.ax-kpi-v{ font-size:1.65rem; font-weight:700; line-height:1; color:var(--ax-ink); }
.ax-kpi-v small{ font-size:.78rem; font-weight:400; color:var(--ax-muted); letter-spacing:.08em; margin-left:6px; }
.ax-kpi-n{ margin-top:10px; font-size:.78rem; color:var(--ax-muted); letter-spacing:.04em; }

.ax-card{
  background:var(--ax-card); border:1px solid var(--ax-line); border-radius:var(--ax-radius);
  padding:20px 22px; margin-bottom:14px;
}
.ax-card-t{ font-size:.68rem; letter-spacing:.2em; text-transform:uppercase; color:var(--ax-faint); margin-bottom:14px; }
.ax-dot{ display:inline-block; width:8px; height:8px; border-radius:50%; margin-right:8px; vertical-align:middle; }
.ax-chip{
  display:inline-flex; align-items:center; gap:8px; border:1px solid var(--ax-line);
  background:var(--ax-card); border-radius:var(--ax-pill); padding:6px 14px;
  font-size:.74rem; letter-spacing:.12em; color:var(--ax-slate2); text-transform:uppercase;
}
.ax-chips{ display:flex; flex-wrap:wrap; gap:8px; justify-content:flex-end; }
.ax-pill{
  display:inline-block; padding:3px 11px; border-radius:var(--ax-pill);
  font-size:.7rem; letter-spacing:.12em; border:1px solid transparent; white-space:nowrap;
}
.ax-pill.ok{ background:rgba(0,208,132,.12); color:var(--ax-ok-ink); border-color:rgba(0,208,132,.35); }
.ax-pill.err{ background:rgba(207,46,46,.10); color:#a52323; border-color:rgba(207,46,46,.30); }
.ax-pill.warn{ background:rgba(255,105,0,.10); color:var(--ax-warn-ink); border-color:rgba(255,105,0,.30); }
.ax-pill.info{ background:rgba(6,147,227,.10); color:#0a6ea3; border-color:rgba(6,147,227,.30); }
.ax-pill.mute{ background:var(--ax-soft); color:var(--ax-muted); border-color:var(--ax-line); }

.ax-list{ list-style:none; margin:0; padding:0; }
.ax-list li{
  display:flex; justify-content:space-between; align-items:baseline; gap:14px;
  padding:10px 2px; border-bottom:1px dashed var(--ax-line); font-size:.86rem; color:var(--ax-slate2);
}
.ax-list li:last-child{ border-bottom:none; }
.ax-list .k{ color:var(--ax-faint); letter-spacing:.12em; font-size:.72rem; text-transform:uppercase; }
.ax-list .v{ color:var(--ax-ink); font-weight:500; }
.ax-console{
  background:var(--ax-deep); border:1px solid #1c252c; border-radius:var(--ax-radius);
  padding:16px 18px; font-family:var(--ax-mono); font-size:.79rem; line-height:1.95;
  color:#c3ced6; max-height:330px; overflow-y:auto;
}
.ax-console::-webkit-scrollbar{ width:6px; }
.ax-console::-webkit-scrollbar-thumb{ background:#3d4b55; border-radius:3px; }
.ax-console .t{ color:#7d909c; }
.ax-console .ok{ color:#63dcac; }
.ax-console .warn{ color:#ffb066; }
.ax-console .err{ color:#ff8f8f; }
.ax-console .hi{ color:#eaf0f4; }

.ax-note{ border-left:2px solid var(--ax-slate); padding:2px 0 2px 16px; color:var(--ax-muted); font-size:.84rem; line-height:1.85; }
.ax-card-warn{ border-left:3px solid var(--ax-warn); }
.ax-note-warn{
  border-left:2px solid var(--ax-warn); background:rgba(255,105,0,.06);
  color:var(--ax-warn-ink); padding:12px 16px; border-radius:0 6px 6px 0;
  font-size:.86rem; line-height:1.8; margin-bottom:14px;
}
.ax-foot{ color:var(--ax-faint); font-size:.7rem; letter-spacing:.14em; text-transform:uppercase; line-height:2; }

.ax-logo{ display:flex; align-items:center; gap:12px; margin-bottom:6px; }
.ax-logo-m{
  width:38px; height:38px; border:1px solid var(--ax-line); border-radius:6px;
  background:var(--ax-slate); color:#fff; font-weight:700; font-size:1.02rem;
  display:flex; align-items:center; justify-content:center; letter-spacing:.02em;
}
.ax-logo-t{ font-size:1.02rem; font-weight:700; color:var(--ax-ink); letter-spacing:.06em; line-height:1.3; }
.ax-logo-s{ font-size:.68rem; color:var(--ax-faint); letter-spacing:.18em; text-transform:uppercase; }

.ax-tl{ list-style:none; margin:0; padding:0; }
.ax-tl li{
  display:flex; gap:14px; align-items:center; padding:10px 0;
  border-bottom:1px dashed var(--ax-line); font-size:.84rem;
}
.ax-tl li:last-child{ border-bottom:none; }
.ax-tl .ts{ color:var(--ax-faint); font-size:.75rem; letter-spacing:.06em; min-width:132px; }
.ax-tl .dv{ color:var(--ax-ink); font-weight:600; min-width:50px; }
.ax-tl .ac{ color:var(--ax-slate2); flex:1; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
</style>
"""


# ============================ 渲染入口 ============================
def inject_css() -> None:
    """每个页面渲染周期注入一次全局样式。"""
    st.markdown(CSS, unsafe_allow_html=True)


# ============================ HTML 组件 ============================
def logo(title: str = "AIOps 控制台", subtitle: str = "MCP · LLM · NET-ORCHESTRATION") -> str:
    return f"""
    <div class="ax-logo">
      <div class="ax-logo-m">AI</div>
      <div>
        <div class="ax-logo-t">{esc(title)}</div>
        <div class="ax-logo-s">{esc(subtitle)}</div>
      </div>
    </div>
    """


def eyebrow(text: str) -> str:
    return f'<div class="ax-eyebrow">{esc(text)}</div>'


def hero(title: str, accent: str, subtitle: str, chips=None, eyebrow_text: str = "") -> str:
    """首屏标题卡：扁平白卡 + 左侧 3px 主色标尺（参考站点的 :after 短下划线手法）。"""
    chip_html = ""
    if chips:
        items = "".join(
            f'<span class="ax-chip"><span class="ax-dot" style="background:{color}"></span>{esc(label)}</span>'
            for label, color in chips
        )
        chip_html = f'<div class="ax-chips">{items}</div>'
    eyebrow_html = f'<div class="ax-eyebrow">{esc(eyebrow_text)}</div>' if eyebrow_text else ""
    return f"""
    <div class="ax-hero">
      <div class="ax-hero-row">
        <div>
          {eyebrow_html}
          <h1 class="ax-h1">{esc(title)} <em>{esc(accent)}</em></h1>
          <p class="ax-sub">{esc(subtitle)}</p>
        </div>
        <div class="ax-hero-meta">{chip_html}</div>
      </div>
    </div>
    """


def kpis(items) -> str:
    """KPI 卡片组。items: [(label, value, unit, note), ...]"""
    cells = []
    for item in items:
        label, value = item[0], item[1]
        unit = item[2] if len(item) > 2 and item[2] else ""
        note = item[3] if len(item) > 3 and item[3] else ""
        unit_html = f"<small>{esc(unit)}</small>" if unit else ""
        note_html = f'<div class="ax-kpi-n">{note}</div>' if note else ""
        cells.append(
            f'<div class="ax-kpi"><div class="ax-kpi-k">{esc(label)}</div>'
            f'<div class="ax-kpi-v">{esc(value)}{unit_html}</div>{note_html}</div>'
        )
    return f'<div class="ax-kpis">{"".join(cells)}</div><div class="ax-hr"></div>'


def section(title: str, eyebrow_text: str = "", desc: str = "") -> str:
    """区块标题：小号大字距 label + 常规标题 + 说明。"""
    eyebrow_html = f'<div class="ax-eyebrow">{esc(eyebrow_text)}</div>' if eyebrow_text else ""
    desc_html = f'<p class="ax-sub">{esc(desc)}</p>' if desc else ""
    return f"""
    <div style="margin:6px 0 14px">
      {eyebrow_html}
      <div class="ax-h1" style="font-size:1.25rem;margin-bottom:.35rem">{esc(title)}</div>
      {desc_html}
    </div>
    """


def kv_list(pairs) -> str:
    """键值列表。pairs: [(key, value), ...]，value 可为已转义好的富文本。"""
    rows = "".join(
        f'<li><span class="k">{esc(k)}</span><span class="v">{v}</span>' for k, v in pairs
    )
    return f'<ul class="ax-list">{rows}</ul>'


def console(lines) -> str:
    """深色终端面板。lines: [(kind, text), ...]，kind ∈ t/ok/warn/err/hi。"""
    rows = []
    for kind, text in lines:
        style = kind if kind in ("t", "ok", "warn", "err", "hi") else "t"
        rows.append(f'<div><span class="{style}">{esc(text)}</span></div>')
    return f'<div class="ax-console">{"".join(rows)}</div>'


def note(text: str) -> str:
    return f'<div class="ax-note">{text}</div>'


def footer(text: str) -> str:
    return f'<div class="ax-foot">{esc(text)}</div>'


def status_pill(status: str) -> str:
    """把审计状态映射为主题化标签。"""
    s = (status or "").upper()
    if s in ("SUCCESS", "EXECUTED"):
        cls, label = "ok", s
    elif s == "PENDING":
        cls, label = "warn", s
    elif s in ("REJECTED", "FAILED"):
        cls, label = "err", s
    else:
        cls, label = "mute", s or "UNKNOWN"
    return f'<span class="ax-pill {cls}">{esc(label)}</span>'


def timeline(rows, limit: int = 8) -> str:
    """审计时间线。rows: [(timestamp, device, action, status), ...]（新→旧）"""
    if not rows:
        return '<div class="ax-note">暂无操作记录，等待第一条 AI 指令。</div>'
    items = []
    for row in rows[:limit]:
        ts, device, action, status = row[0], row[1], row[2], row[-1]
        items.append(
            f'<li><span class="ts">{esc(ts)}</span>'
            f'<span class="dv">{esc(device or "-")}</span>'
            f'<span class="ac">{esc(action)}</span>{status_pill(status)}</li>'
        )
    return f'<ul class="ax-tl">{"".join(items)}</ul>'


# ============================ 拓扑可视化 ============================
def _rgba(hex_color: str, alpha: float) -> str:
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"


def _layout(count: int):
    """节点百分比坐标：首个设备居中在上，其余设备在下排均匀分布。"""
    if count <= 1:
        return [(50, 50)]
    if count == 2:
        return [(50, 26), (50, 76)]
    positions = [(50, 24)]
    bottom = count - 1
    if bottom == 1:
        xs = [50]
    elif bottom == 2:
        xs = [26, 74]
    elif bottom == 3:
        xs = [18, 50, 82]
    else:
        step = 68 / (bottom - 1)
        xs = [16 + i * step for i in range(bottom)]
    positions.extend((x, 76) for x in xs)
    return positions


def topology_html(topology: dict, probe: dict) -> str:
    """渲染拓扑图片段（内联 HTML，供 st.markdown(unsafe_allow_html=True) 使用）。

    topology: {"R1": {"host": ..., "role": ...}, ...}
    probe:    {"R1": {"online": True/False}, ...}

    片段不带 <html>/<body> 包裹，所有类名加 axt- 前缀，避免污染全局主题样式。
    """
    names = list(topology.keys())
    if not names:
        return '<div class="ax-note">未发现纳管设备，请检查 inventory.json。</div>'
    positions = _layout(len(names))

    # 关键帧单独拼接，避免在 f-string 中出现大量花括号转义
    keyframes = (
        "@keyframes axt-pulse{0%,100%{box-shadow:0 0 0 0 " + _rgba(TOKENS["ok"], .45) + ";}"
        "50%{box-shadow:0 0 0 8px " + _rgba(TOKENS["ok"], 0) + ";}}"
    )

    lines, nodes = [], []
    online = 0
    for name, (x, y) in zip(names, positions):
        info = probe.get(name, {}) if isinstance(probe, dict) else {}
        is_online = bool(info.get("online"))
        online += 1 if is_online else 0
        color = TOKENS["ok"] if is_online else TOKENS["err"]
        if y > 40:  # 下排节点与上层核心设备连线
            lines.append(
                f'<line x1="50" y1="24" x2="{x}" y2="{y}" stroke="{TOKENS["line"]}" '
                f'stroke-width="1.5" stroke-dasharray="5 5" vector-effect="non-scaling-stroke"/>'
            )
        role = (topology.get(name) or {}).get("role", "")
        state = "ONLINE" if is_online else "OFFLINE"
        nodes.append(
            f'<div class="axt-node" style="left:{x}%;top:{y}%">'
            f'<div class="axt-ring" style="border-color:{_rgba(color, .55)};'
            f'box-shadow:0 0 0 5px {_rgba(color, .10)}">'
            f'<div class="axt-core{" axt-pulse" if is_online else ""}" style="background:{color}"></div>'
            '</div>'
            f'<div class="axt-name">{esc(name)}</div>'
            f'<div class="axt-role">{esc(role)}</div>'
            f'<div class="axt-state" style="color:{color}">{state}</div>'
            '</div>'
        )

    style = """
.axt-wrap{position:relative;width:100%;height:230px;background:__PAPER__;border:1px solid __LINE__;
border-radius:8px;overflow:hidden;font-family:'Roboto Condensed','Noto Sans SC','Microsoft YaHei',sans-serif;color:__INK__}
.axt-wrap svg{position:absolute;inset:0;width:100%;height:100%}
.axt-node{position:absolute;transform:translate(-50%,-50%);text-align:center;transition:all .2s ease-in}
.axt-ring{width:46px;height:46px;border-radius:50%;background:__CARD__;border:1px solid __LINE__;
display:flex;align-items:center;justify-content:center;margin:0 auto;transition:all .2s ease-in}
.axt-node:hover .axt-ring{transform:translateY(-2px);border-color:__SLATE__}
.axt-core{width:11px;height:11px;border-radius:50%}
.axt-name{margin-top:8px;font-size:12px;font-weight:700;letter-spacing:.08em}
.axt-role{font-size:9px;letter-spacing:.14em;text-transform:uppercase;color:__FAINT__;margin-top:2px}
.axt-state{font-size:9px;letter-spacing:.16em;font-weight:700;margin-top:2px}
__KEYFRAMES__
.axt-pulse{animation:axt-pulse 2.6s ease-in-out infinite}
.axt-legend{display:flex;justify-content:space-between;align-items:center;margin-top:10px;font-size:10px;
letter-spacing:.14em;text-transform:uppercase;color:__MUTED__}
.axt-legend b{color:__INK__;font-weight:700}
"""
    for token, value in (
        ("__PAPER__", TOKENS["paper"]),
        ("__LINE__", TOKENS["line"]),
        ("__INK__", TOKENS["ink"]),
        ("__CARD__", TOKENS["card"]),
        ("__SLATE__", TOKENS["slate"]),
        ("__FAINT__", TOKENS["faint"]),
        ("__MUTED__", TOKENS["muted"]),
        ("__KEYFRAMES__", keyframes),
    ):
        style = style.replace(token, value)

    return (
        f"<style>{style}</style>"
        f'<div class="axt-wrap">'
        f'<svg viewBox="0 0 100 100" preserveAspectRatio="none">{"".join(lines)}</svg>'
        f'{"".join(nodes)}'
        '</div>'
        '<div class="axt-legend">'
        f'<span>{len(names)} NODES · <b>{online}</b> ONLINE</span>'
        '<span>MCP STDIO · SSH</span>'
        '</div>'
    )

