#  AIOps 智能网络运维平台 (MCP + LLM)

基于 MCP 协议与大语言模型的自然语言驱动网络自动化运维系统。实现“普通话 -> AI意图解析 -> MCP工具调用 -> SSH设备执行”的闭环。

##  核心特性
- **MCP 协议解耦**：彻底分离 UI 展示层、LLM 逻辑层与底层设备执行层，支持 Stdio/SSE 双模式。
- **Human-in-the-loop 安全审批**：针对写操作（如关闭端口）引入人工审批机制，杜绝 AI 幻觉引发生产事故。
- **跨平台设备纳管**：底层驱动支持智能识别设备类型（兼容 VyOS 和 Linux 容器），并自动翻译执行命令。
- **智能巡检**：一键遍历全部设备采集接口状态、CPU 负载与内存使用率，输出 Markdown 巡检报告（阈值化判定 P0/P1/P2）。
- **告警中心**：告警持久化到 SQLite，按 P0/P1/P2 分级筛选、支持逐条与批量标记已确认（写入 `acked_at`）并填写**处置备注**，备注随告警 CSV 一同导出。
- **审计日志持久化**：基于 SQLite 记录每一次操作的详细时间、设备、参数与执行状态，支持按状态筛选并导出 UTF-8 BOM 编码 CSV。
- **可视化大屏**：浅色 Glass 设计系统 —— 线性渐变画布（`linear-gradient(135deg, #f5f7fa, #e8ecf1)`）+ Inter 字体 + `.metric-card` 玻璃卡片（16px 圆角 / 24px 内边距 / 悬停上浮 4px）；Plotly 拓扑使用**圆角矩形**节点（在线 `#4ECDC4` / 离线 `#FF6B6B`，悬停显示角色 / IP / 版本）；侧边栏全部入口使用 Feather 线性图标（以 CSS `background-image` 内嵌 SVG，无图标字体依赖）。

##  技术架构
- **前端 UI**: Streamlit 1.64 + Plotly（拓扑/趋势）+ 注入式自定义 CSS（设计令牌集中在 `.streamlit/config.toml` 与 `app.py` 顶部 `inject_css()`）
- **AI Agent**: DeepSeek API (Function Calling)
- **通信协议**: MCP (Model Context Protocol) - stdio 模式
- **底层驱动**: Paramiko (SSH), 异常安全回滚
- **数据存储**: SQLite（`audit_logs` 审计日志 + `alerts` 分级告警，含 `note` 处置备注列）


##  快速开始
1. 安装依赖：
   ```bash
   pip install streamlit pandas plotly openai mcp paramiko
   ```
2. 设置 DeepSeek API Key（二者取一，推荐前者）：
   - 写入 `.streamlit/secrets.toml`：
     ```toml
     DEEPSEEK_API_KEY = "你的key"
     ```
   - 或设置环境变量：`set DEEPSEEK_API_KEY=你的key`
3. 启动 MCP 服务与前端大屏：
   ```bash
   streamlit run app.py
   ```
4. UI 回归测试（可选，`--with-devices` 会走真实 MCP + SSH 全链路）：
   ```bash
   python _ui_smoke_test.py --with-devices
   ```
   详细结果写入 `_smoke_report.txt`。
