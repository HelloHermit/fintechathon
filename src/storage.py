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
    # 迁移旧防重放表时清理被删除的数据库页；外部备份仍须另行保管。
    connection.execute("PRAGMA secure_delete=ON")
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
    CREATE TABLE IF NOT EXISTS investment_products(
        product_id TEXT PRIMARY KEY, name TEXT NOT NULL, risk_level TEXT NOT NULL,
        min_days INTEGER NOT NULL, liquidity TEXT NOT NULL,
        illustrative_annual_rate_bps INTEGER NOT NULL);
    CREATE TABLE IF NOT EXISTS service_catalog(
        service_id TEXT PRIMARY KEY, name TEXT NOT NULL, price_cents INTEGER NOT NULL CHECK(price_cents>0));
    CREATE TABLE IF NOT EXISTS cards(
        card_id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users,
        account_id TEXT NOT NULL REFERENCES accounts, kind TEXT NOT NULL,
        status TEXT NOT NULL, daily_limit_cents INTEGER NOT NULL CHECK(daily_limit_cents>0),
        created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS budgets(
        user_id TEXT NOT NULL REFERENCES users, budget_id TEXT NOT NULL,
        account_id TEXT NOT NULL REFERENCES accounts, event_date TEXT NOT NULL,
        amount_cents INTEGER NOT NULL CHECK(amount_cents>0),
        remaining_cents INTEGER NOT NULL CHECK(remaining_cents>=0),
        spent_cents INTEGER NOT NULL CHECK(spent_cents>=0),
        released_cents INTEGER NOT NULL CHECK(released_cents>=0),
        status TEXT NOT NULL CHECK(status IN ('active','exhausted','released')),
        created_at TEXT NOT NULL, PRIMARY KEY(user_id,budget_id),
        CHECK(amount_cents=remaining_cents+spent_cents+released_cents));
    CREATE TABLE IF NOT EXISTS orders(
        order_id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users,
        budget_id TEXT NOT NULL, account_id TEXT NOT NULL REFERENCES accounts,
        service_id TEXT NOT NULL REFERENCES service_catalog, card_id TEXT REFERENCES cards,
        event_date TEXT NOT NULL, amount_cents INTEGER NOT NULL CHECK(amount_cents>0),
        status TEXT NOT NULL CHECK(status='paid'), executed_at TEXT NOT NULL,
        shanghai_date TEXT NOT NULL, FOREIGN KEY(user_id,budget_id) REFERENCES budgets(user_id,budget_id));
    CREATE TABLE IF NOT EXISTS requests(
        request_id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users,
        intent TEXT NOT NULL, params_json TEXT NOT NULL, tier TEXT NOT NULL,
        status TEXT NOT NULL, created_at TEXT NOT NULL, expires_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS verification_state(
        user_id TEXT NOT NULL REFERENCES users, intent TEXT NOT NULL,
        failures INTEGER NOT NULL DEFAULT 0, locked_until TEXT,
        PRIMARY KEY(user_id,intent));
    CREATE TABLE IF NOT EXISTS strong_auth(
        user_id TEXT PRIMARY KEY REFERENCES users,
        password_hash TEXT NOT NULL, password_salt TEXT NOT NULL,
        kdf_iterations INTEGER NOT NULL, totp_secret TEXT NOT NULL,
        enrolled_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS strong_auth_replay(
        user_id TEXT NOT NULL REFERENCES users, step INTEGER NOT NULL,
        used_at TEXT NOT NULL, PRIMARY KEY(user_id,step));
    CREATE TABLE IF NOT EXISTS audit_log(
        id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT NOT NULL,
        request_id TEXT NOT NULL, step_id TEXT, user_id TEXT NOT NULL,
        raw_input_redacted TEXT NOT NULL, intent TEXT NOT NULL, tier TEXT NOT NULL,
        params_redacted TEXT NOT NULL, event TEXT NOT NULL, result TEXT NOT NULL,
        reason TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS recovery_plans(
        plan_id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users,
        snapshot_json TEXT NOT NULL, revision INTEGER NOT NULL CHECK(revision>0),
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS recovery_handovers(
        handover_id TEXT PRIMARY KEY, plan_id TEXT NOT NULL UNIQUE REFERENCES recovery_plans,
        user_id TEXT NOT NULL REFERENCES users, status TEXT NOT NULL,
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS recovery_handover_entries(
        entry_id TEXT PRIMARY KEY, handover_id TEXT NOT NULL REFERENCES recovery_handovers,
        actor_user_id TEXT NOT NULL REFERENCES users, actor_role TEXT NOT NULL,
        recorded_at TEXT NOT NULL, disposition TEXT NOT NULL,
        compensation TEXT NOT NULL, note_redacted TEXT NOT NULL);
    CREATE TRIGGER IF NOT EXISTS handover_entry_no_update BEFORE UPDATE ON recovery_handover_entries
        BEGIN SELECT RAISE(ABORT,'handover entries are append only'); END;
    CREATE TRIGGER IF NOT EXISTS handover_entry_no_delete BEFORE DELETE ON recovery_handover_entries
        BEGIN SELECT RAISE(ABORT,'handover entries are append only'); END;
    CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit_log
        BEGIN SELECT RAISE(ABORT,'audit log is append only'); END;
    CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit_log
        BEGIN SELECT RAISE(ABORT,'audit log is append only'); END;
    """)
    connection.execute("BEGIN IMMEDIATE")
    try:
        replay_columns = {row[1] for row in connection.execute("PRAGMA table_info(strong_auth_replay)")}
        if replay_columns == {"user_id", "code", "step", "used_at"}:
            # 同一用户、同一时间步曾存有不同原码时，合并为一个已用时间步。
            # 新表、复制、删除旧表及改名一起提交；任一步失败则保留原表。
            connection.execute("""CREATE TABLE strong_auth_replay_migrated(
                user_id TEXT NOT NULL REFERENCES users, step INTEGER NOT NULL,
                used_at TEXT NOT NULL, PRIMARY KEY(user_id,step))""")
            connection.execute("""INSERT INTO strong_auth_replay_migrated(user_id,step,used_at)
                SELECT user_id,step,MAX(used_at) FROM strong_auth_replay GROUP BY user_id,step""")
            connection.execute("DROP TABLE strong_auth_replay")
            connection.execute("ALTER TABLE strong_auth_replay_migrated RENAME TO strong_auth_replay")
        elif replay_columns != {"user_id", "step", "used_at"}:
            raise sqlite3.DatabaseError("unsupported strong authentication replay schema")
        replay_primary_key = {
            row[1]: row[5] for row in connection.execute("PRAGMA table_info(strong_auth_replay)")
            if row[5]
        }
        if replay_primary_key != {"user_id": 1, "step": 2}:
            raise sqlite3.DatabaseError("invalid strong authentication replay primary key")
        request_columns = {row[1] for row in connection.execute("PRAGMA table_info(requests)")}
        if "binding_json" not in request_columns:
            connection.execute("ALTER TABLE requests ADD COLUMN binding_json TEXT NOT NULL DEFAULT '{}'")
        for column in ("plan_id", "step_id", "result_json"):
            if column not in request_columns:
                connection.execute("ALTER TABLE requests ADD COLUMN " + column + " TEXT")
        audit_columns = {row[1] for row in connection.execute("PRAGMA table_info(audit_log)")}
        if "plan_id" not in audit_columns:
            connection.execute("ALTER TABLE audit_log ADD COLUMN plan_id TEXT")
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
        # 新目录只补不存在的固定行；重启不重置已办理的卡、预算或订单。
        connection.executemany("INSERT OR IGNORE INTO investment_products VALUES(?,?,?,?,?,?)", [
            ("p-cash", "模拟活期A", "low", 1, "immediate", 180),
            ("p-flex", "模拟灵活B", "medium", 7, "flexible", 220),
            ("p-steady", "模拟稳健C", "medium", 90, "locked", 260),
            ("p-growth", "模拟成长D", "high", 365, "locked", 420)])
        connection.executemany("INSERT OR IGNORE INTO service_catalog VALUES(?,?,?)", [
            ("flower-basic", "模拟鲜花", 12900), ("cake-basic", "模拟蛋糕", 9900)])
        for owner in ("alice", "bob"):
            account_id = owner + "-main"
            if connection.execute("SELECT 1 FROM accounts WHERE user_id=? AND account_id=?", (owner, account_id)).fetchone():
                connection.execute("INSERT OR IGNORE INTO cards VALUES(?,?,?,?,?,?,?)",
                                   ("card-" + account_id, owner, account_id, "debit", "active", 100000, now.isoformat()))
        connection.commit()
    except Exception:
        connection.rollback()
        raise
