import sqlite3
from datetime import datetime

DB_FILE = "D:\\mcp-vyos\\audit.db"

# 告警级别：P0 致命（不可达）/ P1 严重（接口、CPU）/ P2 提示（内存、采集缺失）
ALERT_LEVELS = ("P0", "P1", "P2")

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
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            device_name TEXT,
            level TEXT,
            message TEXT,
            status TEXT DEFAULT 'ACTIVE',
            acked_at TEXT,
            note TEXT DEFAULT ''
        )
    ''')
    # 兼容早期版本创建的 alerts 表：缺少 note 列时补齐（确认告警时可填写处置备注）
    columns = {row[1] for row in cursor.execute("PRAGMA table_info(alerts)")}
    if "note" not in columns:
        cursor.execute("ALTER TABLE alerts ADD COLUMN note TEXT DEFAULT ''")
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

# ================= 告警中心（P0 / P1 / P2 分级 + 确认闭环） =================

def log_alert(device_name: str, level: str, message: str, dedupe: bool = True) -> bool:
    """
    写入一条告警。

    dedupe=True 时，同一设备 + 同一告警内容的【未确认】告警不会重复写入，
    因此页面每次 rerun 反复探测也不会把告警表刷爆。
    返回 True 表示确实新增了一条告警。
    """
    init_db()
    level = (level or "P2").upper()
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    if dedupe:
        cursor.execute(
            "SELECT id FROM alerts WHERE device_name = ? AND message = ? AND status = 'ACTIVE'",
            (device_name, message),
        )
        if cursor.fetchone():
            conn.close()
            return False
    cursor.execute(
        '''INSERT INTO alerts (timestamp, device_name, level, message, status)
           VALUES (?, ?, ?, ?, 'ACTIVE')''',
        (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), device_name, level, message),
    )
    conn.commit()
    conn.close()
    return True

def get_alerts(level: str = None, status: str = None, limit: int = None):
    """
    读取历史告警（按写入时间倒序）。

    返回 [(id, timestamp, device_name, level, message, status, note), ...]
    level:  P0 / P1 / P2 / None（全部）
    status: ACTIVE（未确认）/ ACKED（已确认）/ None（全部）
    """
    sql = ("SELECT id, timestamp, device_name, level, message, status, COALESCE(note, '') "
           "FROM alerts WHERE 1 = 1")
    params = []
    if level:
        sql += " AND level = ?"
        params.append(level.upper())
    if status:
        sql += " AND status = ?"
        params.append(status.upper())
    sql += " ORDER BY id DESC"
    if limit:
        sql += " LIMIT ?"
        params.append(int(limit))

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute(sql, params)
    rows = cursor.fetchall()
    conn.close()
    return rows


def ack_alert(alert_id: int, note: str = "") -> bool:
    """
    把一条告警标记为已确认，返回是否命中记录。

    note 为可选处置备注：留空时保留原有备注，填写时覆盖写入。
    """
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute(
        """UPDATE alerts
              SET status = 'ACKED',
                  acked_at = ?,
                  note = COALESCE(NULLIF(?, ''), note, '')
            WHERE id = ? AND status = 'ACTIVE'""",
        (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), (note or "").strip(), int(alert_id)),
    )
    changed = cursor.rowcount
    conn.commit()
    conn.close()
    return bool(changed)


def ack_all_alerts(level: str = None, note: str = "") -> int:
    """批量确认为（可选按级别）所有未确认告警，可统一写入备注，返回确认条数。"""
    init_db()
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    sql = ("UPDATE alerts SET status = 'ACKED', acked_at = ?, "
           "note = COALESCE(NULLIF(?, ''), note, '') WHERE status = 'ACTIVE'")
    params = [datetime.now().strftime("%Y-%m-%d %H:%M:%S"), (note or "").strip()]
    if level:
        sql += " AND level = ?"
        params.append(level.upper())
    cursor.execute(sql, params)
    changed = cursor.rowcount
    conn.commit()
    conn.close()
    return int(changed)


def get_alert_stats() -> dict:
    """按级别统计告警数量，返回 {"P0": {"ACTIVE": n, "ACKED": n}, ...}"""
    init_db()
    stats = {lvl: {"ACTIVE": 0, "ACKED": 0} for lvl in ALERT_LEVELS}
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT level, status, COUNT(*) FROM alerts GROUP BY level, status")
    for level, status, count in cursor.fetchall():
        stats.setdefault((level or "P2").upper(), {"ACTIVE": 0, "ACKED": 0})[
            "ACTIVE" if status == "ACTIVE" else "ACKED"] = count
    conn.close()
    return stats