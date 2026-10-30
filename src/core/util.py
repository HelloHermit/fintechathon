"""通用小工具：金额（整数分）、掩码、规范化 JSON、哈希、时间。"""

import hashlib
import hmac
import json
import re
import secrets
from datetime import datetime, timedelta, timezone

SHANGHAI = timezone(timedelta(hours=8), "Asia/Shanghai")
SIMULATION_NOTICE = "模拟数据，非真实资金"


def yuan(cents, sign=False):
    """整数分 → “¥1,234.56”。只用整数运算，不经过浮点数。"""
    if type(cents) is not int:
        raise TypeError("amount must be integer cents")
    prefix = "-" if cents < 0 else ("+" if sign and cents > 0 else "")
    value = abs(cents)
    return f"{prefix}¥{value // 100:,}.{value % 100:02d}"


def plain_yuan(cents):
    """短信与回复里用的“2,000.00”。"""
    value = abs(cents)
    return f"{value // 100:,}.{value % 100:02d}"


def mask_phone(phone):
    if not phone or len(phone) < 7:
        return "***"
    return phone[:3] + "****" + phone[-4:]


def mask_name(name):
    """外部姓名只露最后一个字：王磊 → *磊。"""
    if not name:
        return "*"
    return "*" + name[-1] if len(name) <= 2 else "*" + name[-2:]


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_hex(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def new_id(prefix):
    return prefix + "_" + secrets.token_hex(8)


def numeric_code(digits=6):
    return "".join(secrets.choice("0123456789") for _ in range(digits))


def salted_hash(secret, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", secret.encode("utf-8"), bytes.fromhex(salt), 20000).hex()
    return digest, salt


def check_salted(secret, digest, salt):
    if type(secret) is not str or not digest or not salt:
        return False
    candidate, _ = salted_hash(secret, salt)
    return hmac.compare_digest(candidate, digest)


def iso(dt):
    return dt.astimezone(SHANGHAI).isoformat(timespec="seconds")


def parse_iso(text):
    value = datetime.fromisoformat(text)
    if value.tzinfo is None:
        value = value.replace(tzinfo=SHANGHAI)
    return value.astimezone(SHANGHAI)


def month_bounds(year, month):
    start = datetime(year, month, 1, tzinfo=SHANGHAI)
    end = datetime(year + (month == 12), month % 12 + 1, 1, tzinfo=SHANGHAI)
    return start, end


def add_months(year, month, delta):
    index = year * 12 + (month - 1) + delta
    return index // 12, index % 12 + 1


WEEKDAYS = "一二三四五六日"


def human_date(dt, now=None):
    text = f"{dt.year}-{dt.month:02d}-{dt.day:02d}"
    if now is not None:
        days = (dt.date() - now.date()).days
        label = {0: "今天", 1: "明天", 2: "后天", -1: "昨天"}.get(days)
        if label:
            return text + f"（{label}）"
        return text + f"（周{WEEKDAYS[dt.weekday()]}）"
    return text


def human_datetime(dt, now=None):
    return human_date(dt, now) + f" {dt.hour:02d}:{dt.minute:02d}"


SENSITIVE_PATTERN = re.compile(r"(?<![0-9])[0-9]{6}(?![0-9])")


def redact_text(text, limit=200):
    """日志里的用户原话：去掉 6 位数字（可能是密码/动态码）和完整手机号，截断。"""
    if type(text) is not str:
        return ""
    text = re.sub(r"1[3-9][0-9]{9}", lambda m: mask_phone(m.group(0)), text)
    text = SENSITIVE_PATTERN.sub("[6位数字已隐藏]", text)
    return text[:limit]
