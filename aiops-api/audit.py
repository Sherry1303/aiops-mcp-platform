# -*- coding: utf-8 -*-
"""SQLite 审计库读写层。

与 Streamlit 控制台共用同一个 audit.db，表结构完全一致，
因此后端写入的 API 调用记录会直接出现在原有控制台的审计日志页里。

表结构：
    audit_logs(id, timestamp, device_name, action, details, status)
    alerts(id, timestamp, device_name, level, message, status, acked_at, note)
"""
from __future__ import annotations

import sqlite3
from datetime import datetime

from config import AUDIT_DB

ALERT_LEVELS = ("P0", "P1", "P2")


def _connect() -> sqlite3.Connection:
    AUDIT_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(AUDIT_DB, timeout=5)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """建表 + 兼容旧库（缺 note 列时补齐）。"""
    with _connect() as conn:
        cur = conn.cursor()
        cur.execute("""CREATE TABLE IF NOT EXISTS audit_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT, device_name TEXT, action TEXT,
                details TEXT, status TEXT)""")
        cur.execute("""CREATE TABLE IF NOT EXISTS alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT, device_name TEXT, level TEXT, message TEXT,
                status TEXT DEFAULT 'ACTIVE', acked_at TEXT, note TEXT DEFAULT '')""")
        columns = {row[1] for row in cur.execute("PRAGMA table_info(alerts)")}
        if "note" not in columns:
            cur.execute("ALTER TABLE alerts ADD COLUMN note TEXT DEFAULT ''")
        conn.commit()


def log_action(device_name: str, action: str, details: str, status: str = "SUCCESS") -> int:
    """写入一条审计日志，返回新记录 id。"""
    init_db()
    with _connect() as conn:
        cur = conn.cursor()
        cur.execute("""INSERT INTO audit_logs (timestamp, device_name, action, details, status)
                       VALUES (?, ?, ?, ?, ?)""",
                    (datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                     device_name or "-", action, details, status))
        conn.commit()
        return int(cur.lastrowid or 0)


def _build_filter(status=None, device=None, keyword=None):
    sql, params = " WHERE 1 = 1", []
    if status:
        sql += " AND UPPER(status) = ?"
        params.append(status.upper())
    if device:
        sql += " AND device_name = ?"
        params.append(device)
    if keyword:
        sql += " AND (details LIKE ? OR action LIKE ?)"
        params += [f"%{keyword}%", f"%{keyword}%"]
    return sql, params


def query_logs(status=None, device=None, keyword=None, limit: int = 100,
               offset: int = 0) -> tuple[int, list[dict]]:
    """分页查询审计日志（时间倒序），返回 (总数, 记录列表)。"""
    init_db()
    where, params = _build_filter(status, device, keyword)
    with _connect() as conn:
        cur = conn.cursor()
        total = cur.execute(f"SELECT COUNT(*) FROM audit_logs{where}", params).fetchone()[0]
        rows = cur.execute(
            f"""SELECT id, timestamp, device_name, action, details, status
                  FROM audit_logs{where} ORDER BY id DESC LIMIT ? OFFSET ?""",
            params + [int(limit), int(offset)]).fetchall()
    return int(total), [dict(row) for row in rows]


def count_logs(status: str | None = None) -> int:
    """统计日志条数（status=None 为全部，FAILED 可统计失败次数）。"""
    init_db()
    where, params = _build_filter(status)
    with _connect() as conn:
        return int(conn.execute(f"SELECT COUNT(*) FROM audit_logs{where}", params).fetchone()[0])


def list_alerts(level: str | None = None, status: str | None = None,
                limit: int = 50) -> list[dict]:
    """读取告警（时间倒序）。"""
    init_db()
    sql = ("SELECT id, timestamp, device_name, level, message, status, COALESCE(note, '') AS note "
           "FROM alerts WHERE 1 = 1")
    params: list = []
    if level:
        sql += " AND level = ?"
        params.append(level.upper())
    if status:
        sql += " AND status = ?"
        params.append(status.upper())
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(int(limit))
    with _connect() as conn:
        return [dict(row) for row in conn.execute(sql, params).fetchall()]


def ack_alert(alert_id: int, note: str = "") -> bool:
    """确认一条告警（可附处置备注）。"""
    init_db()
    with _connect() as conn:
        cur = conn.cursor()
        cur.execute("""UPDATE alerts SET status = 'ACKED', acked_at = ?,
                              note = COALESCE(NULLIF(?, ''), note, '')
                        WHERE id = ? AND status = 'ACTIVE'""",
                    (datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                     (note or "").strip(), int(alert_id)))
        changed = cur.rowcount
        conn.commit()
        return bool(changed)


def alert_stats() -> dict:
    """按级别统计告警数量：{"P0": {"ACTIVE": n, "ACKED": n}, ...}"""
    init_db()
    stats = {lvl: {"ACTIVE": 0, "ACKED": 0} for lvl in ALERT_LEVELS}
    with _connect() as conn:
        for level, status, count in conn.execute(
                "SELECT level, status, COUNT(*) FROM alerts GROUP BY level, status"):
            bucket = stats.setdefault((level or "P2").upper(), {"ACTIVE": 0, "ACKED": 0})
            bucket["ACTIVE" if status == "ACTIVE" else "ACKED"] = int(count)
    return stats


def count_alerts(status: str | None = "ACTIVE") -> int:
    init_db()
    sql = "SELECT COUNT(*) FROM alerts WHERE 1 = 1"
    params: list = []
    if status:
        sql += " AND status = ?"
        params.append(status.upper())
    with _connect() as conn:
        return int(conn.execute(sql, params).fetchone()[0])
