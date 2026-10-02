# 界面截图说明

本目录图片均为 **2026-10-02 在实验环境实拍** 的 Vue3 控制台界面 —— 不是设计稿，也没有使用任何模拟/演示数据。

采集时真实运行的三端：

| 层 | 实例 | 说明 |
| --- | --- | --- |
| 展示层 | `aiops-frontend` | Vite dev server `http://localhost:5173`，Chrome 1600×1000（DPR 2）截图 |
| 接口层 | `aiops-api` | 真实 uvicorn 进程 `http://localhost:8000` |
| 智能层 | DeepSeek Function Calling | 图中「查一下 R1 的 eth0 流量」为真实调用（含真实耗时，约 8s） |
| 协议层 / 工具层 | MCP Server | FastMCP（stdio 子进程）4 个工具：`get_topology` / `query_device` / `monitor_traffic` / `configure_interface` |
| 设备层 | VyOS R1 | `192.168.56.10` 在线；`SW1` / `SW2` 当前离线，**故障态即真实态**（告警中心里能看到对应 P0 记录） |

| 文件 | 场景 |
| --- | --- |
| `01-console-overview.png` | 控制台总览：设备清单与在线状态、关键指标卡、拓扑、AI 对话、接口流量曲线 |
| `02-ai-chat.png` | AI 运维对话：DeepSeek 给出的中文结论与运维建议 |
| `03-ai-toolcall.png` | 对话中的 MCP 工具调用：`monitor_traffic` + `SUCCESS` + 入参 JSON + 结论开头 |
| `04-device-detail.png` | 设备详情抽屉：版本、接口状态、CPU/内存与 **MCP 原始命令输出**（version / interface / cpu / memory） |
| `05-audit-alerts.png` | 审计日志（SQLite 分页、CSV 导出）与 P0/P1/P2 告警中心（含确认操作） |
| `06-about.png` | 关于页：六层系统架构、REST 接口清单、「查一下 R1 的 eth0 流量」全链路 |
| `07-menu.png` | 两横整屏菜单（⌘/Ctrl+K 呼出，数字 1/2/3 直达、Esc 关闭） |

两点补充说明，便于复现与理解：

1. **流量曲线是真实差值**：为了验证「两次采样差值 → Mbps」这条计算链路，截图期间在本机对 R1 注入 ICMP 大包（6 路 `ping -t -l 60000 192.168.56.10`），
   因此流量面板上的 RX/TX Mbps 与曲线均有数据；设备空闲时该数值本就接近 0。
2. **看板娘遮挡处理**：`01` / `05` / `06` 三张图在截图时临时隐藏了右下角的 Live2D 看板娘（仅改内联 `display`，**未改动任何源码**），
   否则人物会遮住流量曲线、审计表「状态」列与架构分层的说明文字；`02` / `03` / `04` / `07` 均保留看板娘（`04` 中她位于抽屉后方）。
