<img width="2483" height="1326" alt="image" src="https://github.com/user-attachments/assets/1c2ac132-d57e-4945-8541-316564f392be" />
<img width="2498" height="1332" alt="image" src="https://github.com/user-attachments/assets/6c8b0100-99f2-423b-942d-b2eeeb3d2bff" />
<img width="2494" height="1332" alt="image" src="https://github.com/user-attachments/assets/07791b39-a7b0-48ee-ba02-912920b67f38" />
<img width="2488" height="1322" alt="image" src="https://github.com/user-attachments/assets/6397fbff-1159-414e-b7e2-2f974419e91d" />
## 受管环境与真实设备适配（深度解析）

本系统并非只停留在“发送 SSH 命令”的浅层，而是针对网络操作系统的底层特性进行了深度适配。实验环境以 **VyOS（开源企业级路由操作系统）** 作为核心受管节点。

### 1. 针对 VyOS 的底层驱动适配
VyOS 的操作模式与普通 Linux 有本质区别。为了实现对真实路由器的精准控制，底层驱动（`_ssh_exec`）做了以下设计：
- **专用命令包装器**：VyOS 的 `show` 命令必须通过 `/opt/vyatta/bin/vyatta-op-cmd-wrapper` 执行，系统已自动在底层拼接该包装器，确保查询命令（如 `show version`、`show interfaces`）被正确解析。
- **配置生命周期管控**：针对写操作（如关闭端口），系统严格遵循 VyOS 的安全配置流程：自动进入 `configure` 模式 -> 执行 `set/delete` 指令 -> 自动 `commit` 提交 -> 自动 `save` 持久化。确保配置在不重启的情况下即时生效且重启后不丢失。
- **异常安全回滚**：针对 Python 3.11+ 异步框架特有的 `ExceptionGroup`（TaskGroup 异常组）导致 MCP 服务崩溃的难题，底层通过捕获 `BaseException` 并将异常转化为可读文本返回，保障了系统在面临复杂网络超时时不会整体崩溃。

### 2. 跨平台智能探测与命令翻译
为了验证系统在企业复杂环境下的横向扩展能力，底层驱动加入了**智能设备探测机制**：
- 建立 SSH 连接后，首先通过 `test -f /opt/vyatta/bin/vyatta-op-cmd-wrapper` 判断受管节点的操作系统类型。
- 若探测为 **VyOS**，则按上述原生流程执行；
- 若探测为 **Linux 容器**（如 Docker 运行的精简版 Ubuntu），则自动将 VyOS 命令翻译为 Linux 原生指令（例如将 `show interfaces ethernet eth0` 翻译为 `ip -s link show eth0` 或读取 `/proc/net/dev`）。
- 这种设计实现了“**一次开发，多厂商纳管**”的架构目标。
