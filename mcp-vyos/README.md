#  AIOps 智能网络运维平台 (MCP + LLM)

基于 MCP 协议与大语言模型的自然语言驱动网络自动化运维系统。实现“普通话 -> AI意图解析 -> MCP工具调用 -> SSH设备执行”的闭环。

##  核心特性
- **MCP 协议解耦**：彻底分离 UI 展示层、LLM 逻辑层与底层设备执行层，支持 Stdio/SSE 双模式。
- **Human-in-the-loop 安全审批**：针对写操作（如关闭端口）引入人工审批机制，杜绝 AI 幻觉引发生产事故。
- **跨平台设备纳管**：底层驱动支持智能识别设备类型（兼容 VyOS 和 Linux 容器），并自动翻译执行命令。
- **审计日志持久化**：基于 SQLite 记录每一次操作的详细时间、设备、参数与执行状态。
- **可视化大屏**：集成动态拓扑图（实时设备健康状态）、流量监控与实时执行日志。

##  技术架构
- **前端 UI**: Streamlit, HTML/CSS (拓扑渲染)
- **AI Agent**: DeepSeek API (Function Calling)
- **通信协议**: MCP (Model Context Protocol) - stdio 模式
- **底层驱动**: Paramiko (SSH), 异常安全回滚
- **数据存储**: SQLite (审计日志)

##  快速开始
1. 安装依赖：
   ```bash
   pip install streamlit pandas openai mcp paramiko
2. 设置 DeepSeek API Key（环境变量）：
    set DEEPSEEK_API_KEY=你的key
3. 启动 MCP 服务与前端大屏：
    streamlit run app.py