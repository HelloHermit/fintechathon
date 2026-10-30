"""从文字里提取金额（整数分）。"""
import re

MONEY = re.compile(r"(?:¥|￥)\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d{1,2}))?|(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d{1,2}))?\s?(?:元|块)")


def money_cents_in_text(text: str):
    out = []
    for m in MONEY.finditer(text or ""):
        ip = (m.group(1) or m.group(3) or "").replace(",", "")
        dp = m.group(2) or m.group(4) or ""
        if not ip:
            continue
        out.append(int(ip) * 100 + (int(dp.ljust(2, "0")) if dp else 0))
    return out


def all_ints(obj, acc=None):
    acc = set() if acc is None else acc
    if isinstance(obj, bool):
        return acc
    if isinstance(obj, int):
        acc.add(abs(obj))
    elif isinstance(obj, float):
        acc.add(abs(int(round(obj))))
    elif isinstance(obj, str):
        for c in money_cents_in_text(obj):
            acc.add(c)
    elif isinstance(obj, dict):
        for v in obj.values():
            all_ints(v, acc)
    elif isinstance(obj, list):
        for v in obj:
            all_ints(v, acc)
    return acc
