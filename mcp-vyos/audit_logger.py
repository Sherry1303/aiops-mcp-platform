import sqlite3
from datetime import datetime

DB_FILE = "D:\\mcp-vyos\\audit.db"

def init_db():
    """初始化数据库表"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            device_name TEXT,
            action TEXT,
            details TEXT,
            status TEXT
        )
    ''')
    conn.commit()
    conn.close()

def log_action(device_name: str, action: str, details: str, status: str = "SUCCESS"):
    """写入一条审计日志"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute('''
        INSERT INTO audit_logs (timestamp, device_name, action, details, status)
        VALUES (?, ?, ?, ?, ?)
    ''', (timestamp, device_name, action, details, status))
    conn.commit()
    conn.close()

def get_all_logs():
    """获取所有日志用于前端展示"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT timestamp, device_name, action, details, status FROM audit_logs ORDER BY id DESC")
    rows = cursor.fetchall()
    conn.close()
    return rows