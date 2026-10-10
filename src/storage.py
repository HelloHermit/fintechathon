"""SQLite 账本、追加审计和固定模拟数据。金额单位都是分。"""

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

SHANGHAI = timezone(timedelta(hours=8), "Asia/Shanghai")


def connect(database_path):
    """打开账本；不重置已经存在的业务状态。"""
    if str(database_path) != ":memory:":
        Path(database_path).parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(database_path), timeout=10, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA busy_timeout=10000")
    return connection


def initialize(connection, now):
    """建表并仅在全新数据库中种入可手算的模拟夹具。"""
    connection.executescript("""
    CREATE TABLE IF NOT EXISTS users(user_id TEXT PRIMARY KEY, name TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS accounts(
        account_id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users,
        balance_cents INTEGER NOT NULL CHECK(balance_cents>=0));
    CREATE TABLE IF NOT EXISTS contacts(
        contact_id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users,
        name TEXT NOT NULL, account_id TEXT NOT NULL REFERENCES accounts);
    CREATE TABLE IF NOT EXISTS subscriptions(
        subscription_id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users,
        name TEXT NOT NULL, amount_cents INTEGER NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('active','cancelled')));
    CREATE TABLE IF NOT EXISTS transactions(
        transaction_id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users,
        account_id TEXT NOT NULL REFERENCES accounts, amount_cents INTEGER NOT NULL,
        category TEXT NOT NULL, occurred_at TEXT NOT NULL, status TEXT NOT NULL,
        kind TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS transfers(
        request_id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users,
        source_account_id TEXT NOT NULL REFERENCES accounts,
        target_account_id TEXT NOT NULL REFERENCES accounts, amount_cents INTEGER NOT NULL,
        executed_at TEXT NOT NULL, shanghai_date TEXT NOT NULL, status TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS requests(
        request_id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users,
        intent TEXT NOT NULL, params_json TEXT NOT NULL, tier TEXT NOT NULL,
        status TEXT NOT NULL, created_at TEXT NOT NULL, expires_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS verification_state(
        user_id TEXT NOT NULL REFERENCES users, intent TEXT NOT NULL,
        failures INTEGER NOT NULL DEFAULT 0, locked_until TEXT,
        PRIMARY KEY(user_id,intent));
    CREATE TABLE IF NOT EXISTS audit_log(
        id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT NOT NULL,
        request_id TEXT NOT NULL, step_id TEXT, user_id TEXT NOT NULL,
        raw_input_redacted TEXT NOT NULL, intent TEXT NOT NULL, tier TEXT NOT NULL,
        params_redacted TEXT NOT NULL, event TEXT NOT NULL, result TEXT NOT NULL,
        reason TEXT NOT NULL);
    CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit_log
        BEGIN SELECT RAISE(ABORT,'audit log is append only'); END;
    CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit_log
        BEGIN SELECT RAISE(ABORT,'audit log is append only'); END;
    """)
    request_columns = {row[1] for row in connection.execute("PRAGMA table_info(requests)")}
    if "binding_json" not in request_columns:
        connection.execute("ALTER TABLE requests ADD COLUMN binding_json TEXT NOT NULL DEFAULT '{}'")
    connection.execute("BEGIN IMMEDIATE")
    try:
        if connection.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
            connection.executemany("INSERT INTO users VALUES(?,?)", [("alice", "小阚"), ("bob", "小王")])
            connection.executemany("INSERT INTO accounts VALUES(?,?,?)", [
                ("alice-main", "alice", 1000000), ("alice-savings", "alice", 500000),
                ("bob-main", "bob", 100000)])
            connection.executemany("INSERT INTO contacts VALUES(?,?,?,?)", [
                ("wang", "alice", "小王", "bob-main"), ("li", "alice", "小李", "bob-main"),
                ("alice-contact", "bob", "小阚", "alice-main")])
            connection.executemany("INSERT INTO subscriptions VALUES(?,?,?,?,?)", [
                ("sub-cloud", "alice", "云存储", 990, "active"),
                ("sub-music", "alice", "音乐会员", 1990, "active"),
                ("sub-video", "alice", "视频会员", 2990, "active"),
                ("bob-video", "bob", "视频会员", 3990, "active")])
            first_day = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            last_month = first_day - timedelta(days=1)
            next_month = (first_day.replace(day=28) + timedelta(days=4)).replace(day=1)
            rows = [
                ("bill-cloud", "alice", "alice-main", 990, "云存储", first_day.isoformat(), "success", "expense"),
                ("bill-music", "alice", "alice-main", 1990, "音乐会员", first_day.isoformat(), "success", "expense"),
                ("bill-video", "alice", "alice-main", 2990, "视频会员", first_day.isoformat(), "success", "expense"),
                ("last-month", "alice", "alice-main", 5000, "餐饮", last_month.isoformat(), "success", "expense"),
                ("failed-bill", "alice", "alice-main", 700, "餐饮", now.isoformat(), "failed", "expense"),
                ("future-bill", "alice", "alice-main", 800, "餐饮", next_month.isoformat(), "scheduled", "expense"),
                ("bob-bill", "bob", "bob-main", 3990, "视频会员", first_day.isoformat(), "success", "expense")]
            connection.executemany("INSERT INTO transactions VALUES(?,?,?,?,?,?,?,?)", rows)
        connection.commit()
    except Exception:
        connection.rollback()
        raise
