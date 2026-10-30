"""代码解析器：金额、日期、联系人。模型给出的参数必须能被这些解析器在用户原话里找到依据。"""

import json
import re
from datetime import datetime, timedelta

from ..core.util import SHANGHAI, add_months

DIGITS = {"零": 0, "〇": 0, "一": 1, "壹": 1, "幺": 1, "二": 2, "贰": 2, "两": 2, "俩": 2, "三": 3, "叁": 3, "四": 4, "肆": 4,
          "五": 5, "伍": 5, "六": 6, "陆": 6, "七": 7, "柒": 7, "八": 8, "捌": 8, "九": 9, "玖": 9}
UNITS = {"十": 10, "拾": 10, "百": 100, "佰": 100, "千": 1000, "仟": 1000}
BIG = {"万": 10000, "萬": 10000}
CN_CHARS = "零〇一壹幺二贰两俩三叁四肆五伍六陆七柒八捌九玖十拾百佰千仟万萬"


def chinese_to_int(text):
    """“一万二”→12000，“两千五”→2500，“三百六”→360，“十五”→15。无法解析返回 None。"""
    if not text or any(ch not in CN_CHARS for ch in text):
        return None
    total, section, number, last_unit = 0, 0, None, None
    for ch in text:
        if ch in DIGITS:
            if number is not None and last_unit is None:
                number = number * 10 + DIGITS[ch]  # “二零零”
            else:
                number = DIGITS[ch]
        elif ch in UNITS:
            unit = UNITS[ch]
            section += (1 if number is None else number) * unit
            number, last_unit = None, unit
        elif ch in BIG:
            section += number or 0
            total += (section or 1) * BIG[ch]
            section, number, last_unit = 0, None, BIG[ch]
    if number is not None:
        # 口语省略：“两千五”= 2500，“一万二”= 12000，“三百六”= 360
        if last_unit and last_unit >= 100 and len(text) >= 2 and text[-2] in "千仟百佰万萬":
            number *= last_unit // 10
        section += number
    return total + section


AMOUNT_PATTERN = re.compile(
    r"(?:¥|￥|RMB)?\s*(?P<num>[0-9][0-9,]*(?:\.[0-9]{1,2})?)\s*(?P<suffix>[kKwW]|千|万|块钱|块|元|圆)?"
    r"|(?P<cn>[" + CN_CHARS + r"]{1,8})\s*(?P<cnsuffix>块钱|块|元|圆)?")


def parse_amounts(text):
    """从一句话里找出所有金额（整数分）。忽略手机号、日期、时间里的数字。"""
    if not isinstance(text, str):
        return []
    results = []
    cleaned = re.sub(r"1[3-9][0-9]{9}", " ", text)  # 手机号
    cleaned = re.sub(r"[0-9]{4}[-/年][0-9]{1,2}[-/月][0-9]{1,2}[日号]?", " ", cleaned)
    cleaned = re.sub(r"[0-9]{1,2}\s*月\s*[0-9]{1,2}\s*[日号]", " ", cleaned)
    cleaned = re.sub(r"(?<![0-9])[0-9]{1,2}\s*[日号](?!\s*[0-9])", " ", cleaned)
    cleaned = re.sub(r"[0-9]{1,2}[:：][0-9]{2}", " ", cleaned)
    cleaned = re.sub(r"[0-9" + CN_CHARS + r"]{1,3}\s*[点時时](?:[0-9半]|钟)?", " ", cleaned)
    cleaned = re.sub(r"尾号\s*[0-9]{4}", " ", cleaned)
    cleaned = re.sub(r"[0-9" + CN_CHARS + r"]+\s*(?:天|个月|月份|周|年|笔|张|个|次|人|岁|支|寸|小时|分钟|%|％)", " ", cleaned)
    cleaned = re.sub(r"(?:周|星期|礼拜)[一二三四五六日天]", " ", cleaned)
    for match in AMOUNT_PATTERN.finditer(cleaned):
        cents = None
        if match.group("num"):
            raw = match.group("num").replace(",", "")
            suffix = match.group("suffix") or ""
            try:
                if "." in raw:
                    whole, frac = raw.split(".")
                    cents = int(whole) * 100 + int(frac.ljust(2, "0"))
                else:
                    cents = int(raw) * 100
            except ValueError:
                continue
            if suffix in ("k", "K", "千"):
                cents *= 1000
            elif suffix in ("w", "W", "万"):
                cents *= 10000
            if not suffix and len(raw.replace(".", "")) >= 9:
                continue
        elif match.group("cn"):
            word = match.group("cn")
            if len(word) == 1 and word in "一两俩" and not match.group("cnsuffix"):
                continue  # “一下”“两个”之类不是金额
            value = chinese_to_int(word)
            if value is None or value == 0:
                continue
            if len(word) == 1 and not match.group("cnsuffix") and value < 10:
                continue
            cents = value * 100
        if cents and cents > 0:
            results.append(cents)
    return results


WEEKDAY_MAP = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6, "1": 0, "2": 1, "3": 2, "4": 3, "5": 4, "6": 5, "7": 6}


def _num(token):
    if token is None:
        return None
    if token.isdigit():
        return int(token)
    return chinese_to_int(token)


def resolve_date(expression, now):
    """把用户的日期表达换算成具体日期时间（默认 09:00）。返回 (datetime, 说明) 或 (None, 原因)。"""
    if not isinstance(expression, str) or not expression.strip():
        return None, "没有日期表达"
    text = expression.strip()
    base = now.astimezone(SHANGHAI)
    day = None
    m = re.search(r"([0-9]{4})[-/年]([0-9]{1,2})[-/月]([0-9]{1,2})", text)
    if m:
        try:
            day = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), tzinfo=SHANGHAI)
        except ValueError:
            return None, "日期不存在"
    if day is None:
        m = re.search(r"([0-9" + CN_CHARS + r"]{1,3})\s*月\s*([0-9" + CN_CHARS + r"]{1,3})\s*[日号]?", text)
        if m and "个月" not in text[:m.start() + 3]:
            month, dom = _num(m.group(1)), _num(m.group(2))
            if month and dom:
                try:
                    year = base.year if (month, dom) >= (base.month, base.day) else base.year + 1
                    day = datetime(year, month, dom, tzinfo=SHANGHAI)
                except ValueError:
                    return None, "日期不存在"
    if day is None:
        relative = {"今天": 0, "今日": 0, "明天": 1, "明儿": 1, "明日": 1, "后天": 2, "后儿": 2, "大后天": 3}
        for word in sorted(relative, key=len, reverse=True):
            if word in text:
                day = base + timedelta(days=relative[word])
                break
    if day is None:
        m = re.search(r"([0-9" + CN_CHARS + r"]{1,3})\s*天[以之]?后", text)
        if m and _num(m.group(1)):
            day = base + timedelta(days=_num(m.group(1)))
    if day is None:
        m = re.search(r"(下下|下|这|本|本周|这周)?\s*(?:周|星期|礼拜)([一二三四五六日天1-7])", text)
        if m:
            target = WEEKDAY_MAP[m.group(2)]
            prefix = m.group(1) or ""
            monday = base - timedelta(days=base.weekday())
            if prefix.startswith("下下"):
                day = monday + timedelta(days=14 + target)
            elif prefix.startswith("下"):
                day = monday + timedelta(days=7 + target)
            elif prefix:
                day = monday + timedelta(days=target)
            else:
                day = monday + timedelta(days=target)
                if day.date() < base.date():
                    day += timedelta(days=7)
    if day is None and re.search(r"月底|月末", text):
        y, mo = (base.year, base.month)
        if "下个月" in text or "下月" in text:
            y, mo = add_months(y, mo, 1)
        ny, nm = add_months(y, mo, 1)
        day = datetime(ny, nm, 1, tzinfo=SHANGHAI) - timedelta(days=1)
    if day is None:
        m = re.search(r"(下个?月|这个?月|本月)?\s*([0-9" + CN_CHARS + r"]{1,3})\s*[号日]", text)
        if m and _num(m.group(2)):
            dom = _num(m.group(2))
            y, mo = base.year, base.month
            if m.group(1) and m.group(1).startswith("下"):
                y, mo = add_months(y, mo, 1)
            elif not m.group(1) and dom < base.day:
                y, mo = add_months(y, mo, 1)
            try:
                day = datetime(y, mo, dom, tzinfo=SHANGHAI)
            except ValueError:
                return None, "日期不存在"
    if day is None and re.search(r"下个?月", text):
        y, mo = add_months(base.year, base.month, 1)
        day = datetime(y, mo, 1, tzinfo=SHANGHAI)
    if day is None:
        return None, "没能识别出日期"
    hour, minute = 9, 0
    m = re.search(r"(凌晨|早上|上午|中午|下午|傍晚|晚上|夜里)?\s*([0-9" + CN_CHARS + r"]{1,3})\s*[点时:：]\s*(半|[0-9]{1,2})?", text)
    if m and _num(m.group(2)) is not None and _num(m.group(2)) <= 24:
        hour = _num(m.group(2))
        if m.group(1) in ("下午", "傍晚", "晚上", "夜里") and hour < 12:
            hour += 12
        if m.group(1) == "中午" and hour < 6:
            hour += 12
        minute = 30 if m.group(3) == "半" else int(m.group(3)) if m.group(3) and m.group(3).isdigit() else 0
        if hour == 24:
            hour = 23
        minute = min(minute, 59)
    result = day.replace(hour=hour, minute=minute, second=0, microsecond=0)
    return result, f"{expression} → {result:%Y-%m-%d %H:%M}"


DATE_HINT = re.compile(r"今天|今日|明天|明儿|明日|后天|大后天|天[以之]?后|周[一二三四五六日天1-7]|星期[一二三四五六日天]|礼拜[一二三四五六日天]|月底|月末|"
                       r"[0-9" + CN_CHARS + r"]{1,3}\s*月\s*[0-9" + CN_CHARS + r"]{1,3}|[0-9" + CN_CHARS + r"]{1,3}\s*[号日]|下个?月|[0-9]{4}-[0-9]{1,2}-[0-9]{1,2}")


def scan_dates(texts, now):
    """从用户原话里找出所有能解析的日期（只到日）。用于日期参数溯源。"""
    found = set()
    for text in texts:
        if not isinstance(text, str):
            continue
        for clause in re.split(r"[，,。；;！!？?\s]", text):
            if clause and DATE_HINT.search(clause):
                value, _ = resolve_date(clause, now)
                if value is not None:
                    found.add(value.date().isoformat())
    return found


def has_date_expression(texts):
    return any(isinstance(t, str) and DATE_HINT.search(t) for t in texts)


PHONE_PATTERN = re.compile(r"(?<![0-9])1[3-9][0-9]{9}(?![0-9])")


def contact_matches(kernel, user_id, query):
    """按姓名、称呼、关系、手机号、备注用途查找联系人。返回规范化候选列表。"""
    db = kernel.db
    query = (query or "").strip()
    if not query:
        return []
    results = []
    phone = PHONE_PATTERN.search(query)
    rows = db.execute("SELECT * FROM contacts WHERE user_id=?", (user_id,)).fetchall()
    for row in rows:
        aliases = json.loads(row["aliases"])
        reason = None
        if phone and row["phone"] == phone.group(0):
            reason = "手机号"
        elif query == row["name"] or query in aliases:
            reason = "姓名" if query == row["name"] else "称呼"
        elif query == row["relation"]:
            reason = "关系"
        elif len(query) >= 2 and query in row["name"]:
            reason = "姓名"
        if reason:
            results.append(_contact_view(kernel, row, reason))
    if not results and not phone and len(query) >= 2:
        # 按用途（交易备注）找：例如“房租”→ 每月备注“房租”的收款人。
        hits = db.execute("""SELECT counterparty, COUNT(*) n, MAX(time) last FROM transactions WHERE user_id=? AND amount_cents<0
            AND memo LIKE ? AND counterparty IS NOT NULL GROUP BY counterparty ORDER BY n DESC""",
                          (user_id, "%" + query + "%")).fetchall()
        for hit in hits:
            row = next((r for r in rows if r["name"] == hit["counterparty"]), None)
            if row:
                results.append(_contact_view(kernel, row, f"历史转账备注含“{query}”"))
        for row in rows:
            if query in row["note"] and all(r["contact_id"] != row["contact_id"] for r in results):
                results.append(_contact_view(kernel, row, "联系人说明"))
    if not results and phone:
        entry = db.execute("SELECT * FROM phone_directory WHERE phone=?", (phone.group(0),)).fetchone()
        if entry:
            results.append({"contact_id": None, "name": entry["masked_name"], "display": entry["masked_name"],
                            "relation": "非联系人", "masked_phone": phone.group(0)[:3] + "****" + phone.group(0)[-4:],
                            "account_id": entry["account_id"], "via_phone": phone.group(0), "match": "手机号目录",
                            "is_contact": False})
    return results


def _contact_view(kernel, row, reason):
    aliases = json.loads(row["aliases"])
    display = row["name"] + (f"（{aliases[0]}）" if aliases else "")
    last = kernel.db.execute("""SELECT amount_cents, memo, time FROM transactions WHERE user_id=? AND counterparty=? AND amount_cents<0
        ORDER BY time DESC LIMIT 1""", (row["user_id"], row["name"])).fetchone()
    return {"contact_id": row["contact_id"], "name": row["name"], "display": display, "relation": row["relation"],
            "aliases": aliases, "masked_phone": row["phone"][:3] + "****" + row["phone"][-4:],
            "account_id": row["account_id"], "via_phone": None, "match": reason, "is_contact": True,
            "last_transfer": ({"amount_cents": -last["amount_cents"], "memo": last["memo"], "time": last["time"]} if last else None)}


def contacts_mentioned(kernel, user_id, texts):
    """用户原话里提到的联系人：姓名、称呼、关系，或该联系人历史转账备注里的用途词（如“房租”“生活费”）。
    返回 {contact_id: 命中的词}。"""
    joined = "\n".join(t for t in texts if isinstance(t, str))
    found = {}
    for row in kernel.db.execute("SELECT * FROM contacts WHERE user_id=?", (user_id,)).fetchall():
        words = [row["name"], row["relation"]] + json.loads(row["aliases"])
        for word in words:
            if word and len(word) >= 1 and word in joined and not (len(word) == 1 and word != "妈"):
                found[row["contact_id"]] = word
                break
        if row["contact_id"] in found:
            continue
        for memo in kernel.db.execute("""SELECT DISTINCT memo FROM transactions WHERE user_id=? AND counterparty=? AND memo IS NOT NULL
                AND amount_cents<0""", (user_id, row["name"])):
            if memo[0] and len(memo[0]) >= 2 and memo[0] in joined:
                found[row["contact_id"]] = memo[0]
                break
    for phone in PHONE_PATTERN.findall(joined):
        found["phone:" + phone] = phone
    return found
