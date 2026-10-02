# -*- coding: utf-8 -*-
"""
AIOps 控制台 UI 回归测试（Streamlit AppTest）

覆盖场景：
    S0 静态检查        废弃选择器 / 硬编码密钥 / 关键 API / 浅色 Glass 设计系统令牌是否就位
    S1 默认首屏        浅色渐变 CSS 注入 / metric-card / 线性图标 / 5 个标签页 / Plotly 圆角拓扑 / 在线率进度条
    S2 审批队列注入    pending_task 存在时渲染安全审批中心
    S3 巡检报告注入    注入合成巡检结果，校验 Markdown 报告渲染与下载按钮
    S4 告警筛选交互    P0/P1/P2 级别与状态筛选切换 + 备注输入 + 确认入口
    S4b 告警备注落库   确认写入 acked_at，备注写入 note 列
    S5 审计筛选交互    selectbox 切到 SUCCESS + CSV 导出按钮
    S6 真实全链路巡检  可选（--with-devices）：点击【一键巡检】走真实 MCP + SSH


用法：
    python _ui_smoke_test.py                  # 快速回归（不发真实 SSH）
    python _ui_smoke_test.py --with-devices   # 追加真实巡检（约 30~60 秒）

退出码：0 全通过 / 1 存在失败项；详细报告写入 _smoke_report.txt（UTF-8）。
"""

import sys
import traceback
from datetime import datetime

from streamlit.testing.v1 import AppTest

APP_FILE = "app.py"
REPORT_FILE = "_smoke_report.txt"
WITH_DEVICES = "--with-devices" in sys.argv

failures = []
lines = []


def log(text: str = "") -> None:
    lines.append(text)
    print(text.encode("ascii", "replace").decode("ascii"))


def check(condition: bool, label: str) -> bool:
    log(("  [PASS] " if condition else "  [FAIL] ") + label)
    if not condition:
        failures.append(label)
    return bool(condition)


def markdown_blob(at) -> str:
    return "\n".join(element.value for element in at.markdown)


def button_labels(at) -> list:
    return [element.label for element in at.button] + \
           [element.label for element in at.download_button]


def exception_detail(at) -> str:
    return "; ".join(f"{item.type}: {item.value}" for item in at.exception)


def count_elements(at, element_type: str) -> int:
    """统计某类元素数量；AppTest 未暴露该类型时返回 -1。"""
    try:
        return len(at.get(element_type))
    except Exception:  # noqa: BLE001 —— 未注册的元素类型
        return -1



log(f"=== AIOps UI 回归测试 · {datetime.now():%Y-%m-%d %H:%M:%S} · 真实设备模式={WITH_DEVICES} ===")

# ---------- S0 静态检查 ----------
log()
log("== S0 静态检查（app.py 源码）==")
source = ""
try:
    with open(APP_FILE, "r", encoding="utf-8") as fp:
        source = fp.read()
    check("data-baseweb" not in source, "不再使用已废弃的 data-baseweb 选择器")
    check("ui_theme" not in source, "主题自包含，不再依赖旧 ui_theme 模块")
    check("stVerticalBlockBorderWrapper" not in source, "不再引用已移除的 stVerticalBlockBorderWrapper")
    # 这里不要内联真实 key 的前缀（哪怕只是片段）：用通用前缀检测即可
    check("sk-" not in source, "硬编码 API Key 已移出 app.py")
    check('st.container(border=True, key="card_' in source, "卡片统一 st.container(border=True, key=card_*)")
    check("st.progress(" in source, "使用进度条展示设备在线率")
    check("st.plotly_chart(" in source, "拓扑改用 Plotly 绘制")
    check("import plotly.graph_objects as go" in source, "已引入 plotly.graph_objects")
    # ---- 设计系统（浅色 Glass / Inter / Plotly 圆角拓扑）----
    check("linear-gradient(135deg, #f5f7fa 0%, #e8ecf1 100%)" in source, "画布为指定线性渐变")
    check("font-family:'Inter'" in source, "全局字体 Inter")
    check("background:rgba(255,255,255,.8)" in source, "卡片底色 rgba(255,255,255,.8)")
    check("border:1px solid rgba(255,255,255,.5)" in source, "卡片描边 1px solid rgba(255,255,255,.5)")
    check("border-radius:16px" in source and "padding:24px" in source, "卡片圆角 16px / 内边距 24px")
    check("0 4px 20px rgba(0,0,0,.05)" in source, "卡片阴影 0 4px 20px rgba(0,0,0,.05)")
    check("translateY(-4px)" in source, "卡片悬停上浮 translateY(-4px) 并加深阴影")
    check('"metric-card metric-card--inner" if layered else "metric-card"' in source
          and 'class="{cls}"' in source, "容器内容统一通过 .metric-card 包装类渲染")
    check('background-image:url("data:image/svg+xml' in source, "线性图标以 CSS background-image 内嵌")
    check("stroke='%236b7280'" in source, "图标为 SVG 线性描边（Feather）风格")
    check("#4ECDC4" in source and "#FF6B6B" in source, "拓扑节点配色：在线 #4ECDC4 / 离线 #FF6B6B")
    check('fill="toself"' in source, "节点用圆角矩形多边形绘制（Plotly 无 cornerradius 支持）")
    check("#MainMenu" in source and 'data-testid="stHeader"' in source and "footer" in source,
          "已隐藏 #MainMenu / footer / header")
    check('label_visibility="collapsed"' in source, "指标卡使用自绘小标题 + 隐藏原生标签")
    check("ack_all_alerts(" in source and "ack_note_all" in source, "告警批量确认支持统一备注")
    check(source.count("with card(") >= 20, f"模块卡片数量 = {source.count('with card(')}（≥20）")

except Exception:
    log(traceback.format_exc())
    failures.append("S0 静态检查执行失败")

# ---------- S1 默认首屏 ----------
log()
log("== S1 默认首屏 ==")
at = AppTest.from_file(APP_FILE, default_timeout=300)
at.run()
check(not at.exception, f"无未捕获异常（{exception_detail(at) or 'clean'}）")
if at.exception:
    log("  [!!] S1 异常，后续场景可能连带失败")

blob = markdown_blob(at)
check(len(at.tabs) == 5, f"标签页数量 = {len(at.tabs)}")
tab_labels = [tab.label for tab in at.tabs]
log(f"  标签页：{tab_labels}")
check("智能巡检" in "".join(tab_labels), "包含【智能巡检】标签页")
check("告警中心" in "".join(tab_labels), "包含【告警中心】标签页")

check("<style>" in blob, "CSS 已通过 st.markdown 注入")
check(all(token in blob for token in ("#f5f7fa", "#e8ecf1", "rgba(255,255,255,.8)", "#4ECDC4")),
      "画布 / 卡片 / 圆角 / 主色 令牌齐全")
check("linear-gradient(135deg, #f5f7fa 0%, #e8ecf1 100%)" in blob and "translateY(-4px)" in blob,
      "渐变画布与悬停动效已在首屏生效")
check("Inter" in blob, "Inter 字体已引入")
check("st-key-card_" in blob, "卡片皮肤选择器已注入")
check("metric-card" in blob, "容器内容带 metric-card 样式类")
check("ax-ico" in blob, "线性图标（SVG background-image）已渲染")
check("ax-hero" in blob, "顶部品牌区已渲染")
check("#MainMenu" in blob and "visibility:hidden" in blob, "已隐藏 Streamlit 默认菜单 / 页脚 / 顶栏")


metric_labels = [element.label for element in at.metric]
log(f"  指标卡：{metric_labels}")
for expected in ("设备在线率", "纳管设备", "在线设备", "未确认告警", "审计记录"):
    check(expected in metric_labels, f"指标卡存在：{expected}")
rate_metric = next((item for item in at.metric if item.label == "设备在线率"), None)
check(rate_metric is not None and str(rate_metric.value).endswith("%"),
      f"设备在线率取值 = {rate_metric.value if rate_metric else '缺失'}")

plotly_count = count_elements(at, "plotly_chart")
if plotly_count < 0:
    log("  [NOTE] AppTest 未暴露 plotly_chart 类型，降级为源码静态断言")
    plotly_count = 1 if "st.plotly_chart(" in source else 0
check(plotly_count >= 1, f"Plotly 图表数量 = {plotly_count}")

progress_count = count_elements(at, "progress")
if progress_count < 0:
    log("  [NOTE] AppTest 未暴露 progress 类型，降级为源码静态断言")
    progress_count = 1 if "st.progress(" in source else 0
check(progress_count >= 1, f"进度条数量 = {progress_count}")
check("刷新设备状态" in button_labels(at), "侧边栏刷新按钮存在")

# ---------- S2 审批队列注入 ----------
log()
log("== S2 审批队列注入（Human-in-the-loop）==")
at.session_state["pending_task"] = {
    "function_name": "configure_interface",
    "args": {"device_name": "R1", "interface": "eth1", "action": "disable"},
    "tool_call_id": "call_smoke",
}
at.run()
check(not at.exception, f"审批态无异常（{exception_detail(at) or 'clean'}）")
blob = markdown_blob(at)
check("安全审批中心" in blob, "审批卡片已渲染")
check("eth1" in blob and "disable" in blob, "审批详情含目标端口与动作")
check("批准执行" in button_labels(at) and "拒绝执行" in button_labels(at), "批准 / 拒绝按钮存在")
at.session_state["pending_task"] = None


# ---------- S3 巡检报告注入 ----------
log()
log("== S3 巡检报告注入（Markdown 报告渲染）==")
online_record = {
    "device": "R1", "role": "核心路由器", "host": "192.168.56.10", "online": True, "error": "",
    "version": "VyOS 2026.09.09-0029-rolling", "uptime": "24m 32s",
    "cpu_percent": 16.0, "cpu_detail": "1min 16.0% / 5min 3.0% / 15min 1.0%",
    "mem_percent": 27.2, "mem_detail": "539 MB / 1977 MB（27.2%）",
    "if_state": "UP", "if_detail": "RX 31976 B / TX 56688 B · 错误包 0", "if_errors": 0,
    "raw": {"show version": "Version: VyOS 2026.09.09-0029-rolling"}, "issues": [],
    "conclusion": "正常",
}
offline_record = {
    "device": "SW1", "role": "汇聚交换机", "host": "192.168.56.11", "online": False,
    "error": "SSH执行出错: TimeoutError - timed out", "version": "-", "uptime": "-",
    "cpu_percent": None, "cpu_detail": "-", "mem_percent": None, "mem_detail": "-",
    "if_state": "-", "if_detail": "-", "if_errors": None,
    "raw": {"show version": "SSH执行出错: TimeoutError - timed out"},
    "issues": [("P0", "设备不可达：SSH 探测失败，无法采集运行状态")],
    "conclusion": "不可达",
}
at.session_state["inspect_result"] = {
    "records": [online_record, offline_record],
    "started_at": "2026-10-02 17:20:00",
    "elapsed": 12.5,
}
at.run()
check(not at.exception, f"报告态无异常（{exception_detail(at) or 'clean'}）")
blob = markdown_blob(at)
check("AIOps 智能巡检报告" in blob, "Markdown 报告标题已渲染")
check(all(section in blob for section in ("巡检总览", "问题清单", "逐台明细", "建议动作")),
      "报告四个章节齐全")
check("| 设备 | 角色 | 管理 IP | 状态 |" in blob, "报告含 Markdown 总览表格")
check("VyOS 2026.09.09" in blob, "报告含设备版本信息")
check("不可达" in blob, "报告含离线设备结论")
check("下载巡检报告 (.md)" in button_labels(at), "报告下载按钮存在")
check("一键巡检" in button_labels(at), "一键巡检按钮存在")

# ---------- S4 告警筛选交互 ----------
log()
log("== S4 告警筛选交互 ==")
level_ok = True
for level in ("P0", "P1", "P2", "全部"):
    at.get_by_key("alert_level").set_value(level)
    at.run()
    if at.exception:
        level_ok = False
        log(f"  级别 {level} 异常：{exception_detail(at)}")
check(level_ok, "P0 / P1 / P2 / 全部 级别切换无异常")

status_ok = True
for status in ("已确认", "全部", "未确认"):
    at.get_by_key("alert_status").set_value(status)
    at.run()
    if at.exception:
        status_ok = False
        log(f"  状态 {status} 异常：{exception_detail(at)}")
check(status_ok, "未确认 / 已确认 / 全部 状态切换无异常")

blob = markdown_blob(at)
check("告警列表" in blob, "告警列表卡片已渲染")
check(("待确认告警" in blob) or ("没有告警记录" in blob), "告警列表/空态提示正常渲染")
check("导出告警 CSV" in button_labels(at), "告警 CSV 导出按钮存在")

note_labels = [widget.label for widget in at.text_input]
log(f"  备注输入框：{note_labels}")
has_pending = "没有告警记录" not in blob
check(any("备注" in label for label in note_labels) or not has_pending,
      "待确认告警提供备注输入框（无待确认时跳过）")
check(any("标记已确认" in label for label in button_labels(at)) or not has_pending,
      "待确认告警提供【标记已确认】按钮（无待确认时跳过）")

# ---------- S4b 告警确认 + 备注落库（audit_logger 直连自检） ----------
log()
log("== S4b 告警确认与备注落库 ==")
from audit_logger import ack_alert as _ack, get_alerts as _get_alerts, log_alert as _log_alert  # noqa: E402

_marker = f"备注链路自检 {datetime.now():%Y%m%d_%H%M%S}"
_log_alert("SMOKE_NOTE", "P2", _marker, dedupe=False)
_sample = next(row for row in _get_alerts() if (row[4] or "") == _marker)
check(_ack(_sample[0], "已联系厂商-工单12345"), "告警确认成功（写入 acked_at）")
_saved = next(row for row in _get_alerts() if row[0] == _sample[0])
check(_saved[5] == "ACKED" and _saved[6] == "已联系厂商-工单12345",
      f"处置备注已落库：status={_saved[5]} note={_saved[6]}")


# ---------- S5 审计筛选交互 ----------
log()
log("== S5 审计筛选交互 ==")
at.get_by_key("audit_status").select("SUCCESS")
at.run()
check(not at.exception, f"审计筛选无异常（{exception_detail(at) or 'clean'}）")
check("导出 CSV" in button_labels(at), "审计 CSV 导出按钮存在")
check("最近操作时间线" in markdown_blob(at), "审计时间线已渲染")

# ---------- S6 真实全链路巡检（可选） ----------
if WITH_DEVICES:
    log()
    log("== S6 真实全链路巡检（MCP + SSH）==")
    at.get_by_key("btn_inspect").click()
    at.run(timeout=300)
    check(not at.exception, f"真实巡检无异常（{exception_detail(at) or 'clean'}）")
    blob = markdown_blob(at)
    check("AIOps 智能巡检报告" in blob, "真实巡检报告已生成")
    check("show system memory" in blob, "报告记录了真实执行过的命令")
    report_rows = [line for line in blob.splitlines()
                   if line.startswith("| ") and " | " in line and "---" not in line]
    real_rows = [line for line in report_rows if line.split("|")[1].strip() in ("R1", "SW1", "SW2")]
    log(f"  总览表设备行：{real_rows}")
    check(bool(real_rows), "总览表含真实设备行")

    from audit_logger import get_alerts, get_all_logs
    alert_rows = get_alerts()
    log(f"  告警表记录数 = {len(alert_rows)}")
    check(len(alert_rows) >= 1, "探测/巡检已写入告警记录")
    check(all(len(row) == 7 for row in alert_rows), "告警表查询已包含备注列（7 列）")
    check(any((row[2] or "") == "inspection" for row in get_all_logs()),
          "巡检动作已写入审计日志")
    for row in alert_rows[:3]:
        log(f"  告警样本：{row[1]} | {row[2]} | {row[3]} | {row[4]} | {row[5]} | note={row[6]!r}")


log()
log(f"=== 结果：{'全部通过' if not failures else '存在失败'} · 失败 {len(failures)} 项 ===")
for item in failures:
    log(f"  - {item}")

with open(REPORT_FILE, "w", encoding="utf-8") as fp:
    fp.write("\n".join(lines))

print(f"\nSMOKE {'OK' if not failures else 'FAILED'} failures={len(failures)}")
sys.exit(1 if failures else 0)

