"""v2 演示库表结构。金额一律整数分；审计表只追加（触发器禁止改删）。"""

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS users(
    user_id TEXT PRIMARY KEY, display_name TEXT NOT NULL, phone TEXT NOT NULL,
    pin_hash TEXT NOT NULL, pin_salt TEXT NOT NULL, pin_iterations INTEGER NOT NULL,
    risk_level TEXT, risk_score INTEGER, risk_assessed_at TEXT, risk_valid_until TEXT);
CREATE TABLE IF NOT EXISTS accounts(
    account_id TEXT PRIMARY KEY, user_id TEXT REFERENCES users, name TEXT NOT NULL,
    tail TEXT NOT NULL, kind TEXT NOT NULL CHECK(kind IN ('internal','external')),
    balance_cents INTEGER NOT NULL CHECK(balance_cents>=0),
    reserved_cents INTEGER NOT NULL DEFAULT 0 CHECK(reserved_cents>=0),
    holder_name TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS contacts(
    contact_id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users,
    name TEXT NOT NULL, aliases TEXT NOT NULL, relation TEXT NOT NULL,
    phone TEXT NOT NULL, account_id TEXT NOT NULL, birthday TEXT, note TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS phone_directory(
    phone TEXT PRIMARY KEY, masked_name TEXT NOT NULL, account_id TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS risk_list(account_id TEXT PRIMARY KEY, reason TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS cards(
    card_id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users, name TEXT NOT NULL,
    kind TEXT NOT NULL CHECK(kind IN ('debit','virtual')), tail TEXT NOT NULL,
    account_id TEXT NOT NULL REFERENCES accounts,
    status TEXT NOT NULL CHECK(status IN ('active','frozen','lost')),
    daily_limit_cents INTEGER NOT NULL CHECK(daily_limit_cents>0), purpose TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS subscriptions(
    subscription_id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users,
    name TEXT NOT NULL, merchant TEXT NOT NULL, amount_cents INTEGER NOT NULL,
    cycle TEXT NOT NULL, charge_day INTEGER NOT NULL, next_charge_date TEXT,
    status TEXT NOT NULL CHECK(status IN ('active','cancelled')),
    card_id TEXT, last_used_at TEXT, cancelled_at TEXT);
CREATE TABLE IF NOT EXISTS transactions(
    txn_id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users,
    account_id TEXT NOT NULL, time TEXT NOT NULL, merchant TEXT NOT NULL,
    category TEXT NOT NULL, amount_cents INTEGER NOT NULL, status TEXT NOT NULL,
    card_id TEXT, memo TEXT, counterparty TEXT, foreign_flag INTEGER NOT NULL DEFAULT 0,
    ref_id TEXT);
CREATE INDEX IF NOT EXISTS idx_txn_user_time ON transactions(user_id, time);
CREATE TABLE IF NOT EXISTS transfers(
    transfer_id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users,
    source_account_id TEXT NOT NULL, target_account_id TEXT NOT NULL,
    payee_name TEXT NOT NULL, amount_cents INTEGER NOT NULL CHECK(amount_cents>0),
    memo TEXT NOT NULL DEFAULT '', kind TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('in_transit','completed','revoked')),
    created_at TEXT NOT NULL, arrive_at TEXT NOT NULL, shanghai_date TEXT NOT NULL,
    request_id TEXT, risk_score INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS products(
    product_id TEXT PRIMARY KEY, name TEXT NOT NULL, aliases TEXT NOT NULL, type TEXT NOT NULL,
    risk_level TEXT NOT NULL, term_days INTEGER NOT NULL, liquidity TEXT NOT NULL,
    yield_text TEXT NOT NULL, min_amount_cents INTEGER NOT NULL, description TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS holdings(
    holding_id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users,
    product_id TEXT NOT NULL REFERENCES products, amount_cents INTEGER NOT NULL CHECK(amount_cents>=0),
    profit_cents INTEGER NOT NULL, purchased_at TEXT NOT NULL, matures_at TEXT NOT NULL,
    account_id TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS services(
    service_id TEXT PRIMARY KEY, name TEXT NOT NULL, price_cents INTEGER NOT NULL CHECK(price_cents>0));
CREATE TABLE IF NOT EXISTS budgets(
    budget_id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users, name TEXT NOT NULL,
    account_id TEXT NOT NULL, amount_cents INTEGER NOT NULL CHECK(amount_cents>0),
    remaining_cents INTEGER NOT NULL CHECK(remaining_cents>=0),
    spent_cents INTEGER NOT NULL CHECK(spent_cents>=0),
    released_cents INTEGER NOT NULL CHECK(released_cents>=0),
    until TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('active','exhausted','released')),
    plan_id TEXT, created_at TEXT NOT NULL,
    CHECK(amount_cents=remaining_cents+spent_cents+released_cents));
CREATE TABLE IF NOT EXISTS orders(
    order_id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users,
    service_id TEXT NOT NULL REFERENCES services, service_name TEXT NOT NULL,
    amount_cents INTEGER NOT NULL CHECK(amount_cents>0), budget_id TEXT, account_id TEXT NOT NULL,
    deliver_date TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('paid','cancelled','refunded')),
    created_at TEXT NOT NULL, shanghai_date TEXT NOT NULL, plan_id TEXT);
CREATE TABLE IF NOT EXISTS schedules(
    schedule_id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users,
    kind TEXT NOT NULL, title TEXT NOT NULL, intent TEXT NOT NULL, params_json TEXT NOT NULL,
    amount_cents INTEGER NOT NULL DEFAULT 0, run_at TEXT NOT NULL,
    repeat TEXT NOT NULL CHECK(repeat IN ('none','monthly','weekly')),
    status TEXT NOT NULL CHECK(status IN ('scheduled','executed','failed','cancelled','needs_reauth','running')),
    authorized_tier TEXT NOT NULL, plan_id TEXT, node_id TEXT, created_at TEXT NOT NULL,
    last_result TEXT);
CREATE TABLE IF NOT EXISTS requests(
    request_id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users, intent TEXT NOT NULL,
    params_json TEXT NOT NULL, params_hash TEXT NOT NULL, tier TEXT NOT NULL,
    kind TEXT NOT NULL, code_hash TEXT, code_salt TEXT,
    status TEXT NOT NULL, created_at TEXT NOT NULL, expires_at TEXT NOT NULL,
    view_json TEXT NOT NULL, risk_json TEXT, not_before TEXT, plan_id TEXT,
    turn_id TEXT, provenance_json TEXT NOT NULL DEFAULT '{}', result_json TEXT,
    otp_sent_at TEXT);
CREATE TABLE IF NOT EXISTS otps(
    otp_id TEXT PRIMARY KEY, request_id TEXT NOT NULL, user_id TEXT NOT NULL,
    params_hash TEXT NOT NULL, code_hash TEXT NOT NULL, code_salt TEXT NOT NULL,
    created_at TEXT NOT NULL, expires_at TEXT NOT NULL, used INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS sms(
    sms_id TEXT PRIMARY KEY, user_id TEXT NOT NULL, sender TEXT NOT NULL,
    text TEXT NOT NULL, received_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS lockouts(
    user_id TEXT NOT NULL, scope TEXT NOT NULL, failures INTEGER NOT NULL DEFAULT 0,
    locked_until TEXT, PRIMARY KEY(user_id, scope));
CREATE TABLE IF NOT EXISTS suspicious_events(
    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL, time TEXT NOT NULL,
    kind TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS notifications(
    notification_id TEXT PRIMARY KEY, user_id TEXT NOT NULL, time TEXT NOT NULL,
    kind TEXT NOT NULL, title TEXT NOT NULL, body TEXT NOT NULL, read INTEGER NOT NULL DEFAULT 0, ref TEXT);
CREATE TABLE IF NOT EXISTS aa_requests(
    aa_id TEXT PRIMARY KEY, batch_id TEXT NOT NULL, from_user TEXT NOT NULL,
    payer_contact_id TEXT NOT NULL, payer_name TEXT NOT NULL, payer_user TEXT,
    amount_cents INTEGER NOT NULL CHECK(amount_cents>0), memo TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('open','paid','declined')), created_at TEXT NOT NULL,
    paid_at TEXT);
CREATE TABLE IF NOT EXISTS plans(
    plan_id TEXT PRIMARY KEY, user_id TEXT NOT NULL, title TEXT NOT NULL, status TEXT NOT NULL,
    plan_json TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS handovers(
    ticket_id TEXT PRIMARY KEY, user_id TEXT NOT NULL, summary TEXT NOT NULL,
    status TEXT NOT NULL, created_at TEXT NOT NULL, plan_id TEXT);
CREATE TABLE IF NOT EXISTS anomaly_marks(
    user_id TEXT NOT NULL, finding_id TEXT NOT NULL, mark TEXT NOT NULL, time TEXT NOT NULL,
    PRIMARY KEY(user_id, finding_id));
CREATE TABLE IF NOT EXISTS turns(
    turn_id TEXT PRIMARY KEY, user_id TEXT NOT NULL, time TEXT NOT NULL,
    input_redacted TEXT NOT NULL, trace_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS audit(
    id INTEGER PRIMARY KEY AUTOINCREMENT, time TEXT NOT NULL, user_id TEXT NOT NULL,
    turn_id TEXT, request_id TEXT, intent TEXT NOT NULL, tier TEXT NOT NULL,
    event TEXT NOT NULL, result TEXT NOT NULL, reason TEXT NOT NULL, actor TEXT NOT NULL,
    params_redacted TEXT NOT NULL, prev_hash TEXT NOT NULL, hash TEXT NOT NULL);
CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit
    BEGIN SELECT RAISE(ABORT,'audit is append only'); END;
CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit
    BEGIN SELECT RAISE(ABORT,'audit is append only'); END;
"""


def connect(path):
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(path), timeout=10, isolation_level=None, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA busy_timeout=10000")
    if str(path) != ":memory:":
        connection.execute("PRAGMA journal_mode=WAL")
    connection.executescript(SCHEMA)
    migrate(connection)
    return connection


def migrate(connection):
    """给旧演示库补列（只加列，不删数据）。"""
    columns = {row[1] for row in connection.execute("PRAGMA table_info(notifications)")}
    if "ref" not in columns:
        connection.execute("ALTER TABLE notifications ADD COLUMN ref TEXT")
