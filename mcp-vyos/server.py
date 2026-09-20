import os
import time
import json
import paramiko
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("AIOps-MCP-Server")

# ================= 资产加载引擎 =================
INVENTORY_FILE = "D:\\mcp-vyos\\inventory.json"

def load_inventory():
    default_topology = {
        "R1": {
            "host": os.getenv("VYOS_HOST", "192.168.56.10"),
            "port": int(os.getenv("VYOS_PORT", "22")),
            "user": os.getenv("VYOS_USER", "vyos"),
            "pass": os.getenv("VYOS_PASS", "123456"),
            "role": "核心路由器"
        }
    }
    if not os.path.exists(INVENTORY_FILE):
        return default_topology
    
    try:
        with open(INVENTORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            topology = {}
            for name, info in data.get("devices", {}).items():
                topology[name] = {
                    "host": info["ip"],
                    "port": int(info.get("port", os.getenv("VYOS_PORT", "22"))),
                    "user": info.get("user", os.getenv("VYOS_USER", "vyos")),
                    "pass": info.get("pass", os.getenv("VYOS_PASS", "123456")),
                    "role": info.get("role", "未知设备")
                }
            return topology if topology else default_topology
    except Exception as e:
        print(f"读取设备清单失败: {e}, 使用默认单机配置")
        return default_topology

TOPOLOGY = load_inventory()

def _get_device(device_name: str):
    if device_name not in TOPOLOGY:
        raise ValueError(f"设备 {device_name} 不存在。可用设备: {list(TOPOLOGY.keys())}")
    return TOPOLOGY[device_name]

# ================= SSH 底层执行引擎字符串返回 =================
def _ssh_exec(device_name: str, vyos_cmd: str) -> str:
    try:
        dev = _get_device(device_name)
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(
            dev["host"], dev["port"], dev["user"], dev["pass"],
            look_for_keys=False, allow_agent=False, timeout=5
        )
        
        # 智能探测设备类型
        check_cmd = "test -f /opt/vyatta/bin/vyatta-op-cmd-wrapper && echo 'vyos' || echo 'linux'"
        stdin, stdout, stderr = ssh.exec_command(check_cmd)
        os_type = stdout.read().decode(errors="ignore").strip()
        
        if os_type == "linux":
            # Linux 环境（如 Ubuntu 容器）：翻译 VyOS 命令
            if "show version" in vyos_cmd:
                vyos_cmd = "cat /etc/os-release"
            elif "show interfaces ethernet" in vyos_cmd:
                intf = vyos_cmd.split()[-1]
                # 增加双重兜底命令
                vyos_cmd = f"ip -s link show {intf} || cat /proc/net/dev"
            elif "show ip route" in vyos_cmd:
                vyos_cmd = "ip route"
            stdin, stdout, stderr = ssh.exec_command(vyos_cmd)
        else:
            # VyOS 环境
            full_cmd = f"/opt/vyatta/bin/vyatta-op-cmd-wrapper {vyos_cmd}"
            stdin, stdout, stderr = ssh.exec_command(full_cmd)
            
        # errors="ignore" 防止非 UTF-8 字符导致解码崩溃
        output = stdout.read().decode("utf-8", errors="ignore")
        error = stderr.read().decode("utf-8", errors="ignore")
        ssh.close()
        return output if output else error
    except Exception as e:
        # ★ 核心修复：捕获所有异常，返回文字而不是让程序崩溃
        return f"SSH执行出错: {type(e).__name__} - {str(e)}"

def _ssh_configure(device_name: str, commands: list) -> str:
    try:
        dev = _get_device(device_name)
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(
            dev["host"], dev["port"], dev["user"], dev["pass"],
            look_for_keys=False, allow_agent=False, timeout=10
        )
        shell = ssh.invoke_shell()
        time.sleep(1)
        shell.send("configure\n")
        time.sleep(1)
        for cmd in commands:
            shell.send(cmd + "\n")
            time.sleep(0.5)
        shell.send("commit\n")
        time.sleep(1.5)
        shell.send("save\n")
        time.sleep(1)
        shell.send("exit\n")
        time.sleep(1)
        output = shell.recv(65535).decode("utf-8", errors="ignore")
        shell.close()
        return output
    except Exception as e:
        return f"配置执行失败: {type(e).__name__} - {str(e)}"

# ================= MCP 工具定义区 =================

@mcp.tool()
def get_topology() -> str:
    inventory = {name: {"host": info["host"], "role": info["role"]} for name, info in TOPOLOGY.items()}
    return json.dumps(inventory, ensure_ascii=False, indent=2)

@mcp.tool()
def query_device(device_name: str, command_name: str) -> str:
    if not command_name.startswith("show"):
        return "安全拒绝：只允许执行以 'show' 开头的只读命令。"
    return _ssh_exec(device_name, command_name)

@mcp.tool()
def configure_interface(device_name: str, interface: str, action: str) -> str:
    if action == "disable":
        return f"已成功关闭 {device_name} 的 {interface} 端口。\n" + _ssh_configure(device_name, [f"set interfaces ethernet {interface} disable"])
    elif action == "enable":
        return f"已成功开启 {device_name} 的 {interface} 端口。\n" + _ssh_configure(device_name, [f"delete interfaces ethernet {interface} disable"])
    else:
        return "错误：action 只支持 'enable' 或 'disable'。"

@mcp.tool()
def monitor_traffic(device_name: str, interface: str) -> str:
    """检测指定设备端口的流量统计信息。"""
    result = _ssh_exec(device_name, f"show interfaces ethernet {interface}")
    return result

if __name__ == "__main__":
    mcp.run(transport="stdio")