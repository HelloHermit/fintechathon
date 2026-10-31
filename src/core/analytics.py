"""账单分析（绿档、只读）：时间范围解析、流水搜索、分类统计、异常识别、月报/年报。"""

import json
import re
import statistics
from collections import defaultdict
from datetime import datetime, timedelta

from .util import SHANGHAI, add_months, iso, month_bounds, parse_iso, yuan

EXPENSE_CATEGORIES = ["餐饮外卖", "超市日用", "交通出行", "购物", "住房缴费", "娱乐", "订阅会员", "医疗健康", "学习教育",
                      "旅行", "转账给他人", "人情红包", "其他"]
INCOME_CATEGORIES = ["工资", "转入", "理财收益", "退款"]
CATEGORY_ALIASES = {"外卖": "餐饮外卖", "吃饭": "餐饮外卖", "餐饮": "餐饮外卖", "超市": "超市日用", "日用": "超市日用",
                    "交通": "交通出行", "打车": "交通出行", "出行": "交通出行", "网购": "购物", "房租": "住房缴费", "水电": "住房缴费",
                    "缴费": "住房缴费", "订阅": "订阅会员", "会员": "订阅会员", "医疗": "医疗健康", "看病": "医疗健康",
                    "学习": "学习教育", "教育": "学习教育", "转账": "转账给他人", "红包": "人情红包", "收入": None}
CN_NUM = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10, "十一": 11, "十二": 12}


def _n(token):
    if token is None:
        return None
    return int(token) if token.isdigit() else CN_NUM.get(token)


class Analytics:
    def __init__(self, kernel):
        self.k = kernel

    @property
    def db(self):
        return self.k.db

    # ------------------------------------------------------------------ 时间范围
    def resolve_period(self, text, now):
        """返回 (start, end, label)，end 为开区间上界（不超过现在）。"""
        text = (text or "").strip()
        cap = now + timedelta(seconds=1)

        def month(y, m, label=None):
            s, e = month_bounds(y, m)
            return s, min(e, cap), label or f"{y}年{m}月"

        m = re.search(r"([0-9]{4})[-/年]([0-9]{1,2})", text)
        if m:
            return month(int(m.group(1)), int(m.group(2)))
        if re.search(r"上上个?月", text):
            y, mo = add_months(now.year, now.month, -2)
            return month(y, mo)
        if re.search(r"上个?月|上月", text):
            y, mo = add_months(now.year, now.month, -1)
            return month(y, mo, f"上个月（{y}年{mo}月）")
        if re.search(r"(这|本|当)个?月", text):
            return month(now.year, now.month, f"本月（{now.year}年{now.month}月）")
        m = re.search(r"(去年|今年)?\s*([0-9]{1,2}|十一|十二|[一二三四五六七八九十])\s*月(份)?", text)
        if m and _n(m.group(2)) and 1 <= _n(m.group(2)) <= 12:
            mo = _n(m.group(2))
            y = now.year - 1 if m.group(1) == "去年" else now.year
            if not m.group(1) and (y, mo) > (now.year, now.month):
                y -= 1
            return month(y, mo)
        m = re.search(r"(最近|过去|近)\s*([0-9]+|[一二两三四五六七八九十]+)\s*(天|周|个月|年)", text)
        if m:
            count = _n(m.group(2)) or 1
            unit = m.group(3)
            days = {"天": 1, "周": 7, "个月": 30, "年": 365}[unit] * count
            return now - timedelta(days=days), cap, f"最近{m.group(2)}{unit}"
        if "过去一年" in text or "近一年" in text or "最近一年" in text:
            return now - timedelta(days=365), cap, "最近一年"
        if "今年" in text:
            return datetime(now.year, 1, 1, tzinfo=SHANGHAI), cap, f"{now.year}年"
        if "去年" in text:
            return datetime(now.year - 1, 1, 1, tzinfo=SHANGHAI), datetime(now.year, 1, 1, tzinfo=SHANGHAI), f"{now.year - 1}年"
        if "本周" in text or "这周" in text:
            start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
            return start, cap, "本周"
        if "上周" in text:
            start = (now - timedelta(days=now.weekday() + 7)).replace(hour=0, minute=0, second=0, microsecond=0)
            return start, start + timedelta(days=7), "上周"
        if "昨天" in text:
            start = (now - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
            return start, start + timedelta(days=1), "昨天"
        if "今天" in text:
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            return start, cap, "今天"
        return now - timedelta(days=30), cap, "最近30天"

    def normalize_category(self, category):
        if not category:
            return None
        category = category.strip()
        if category in EXPENSE_CATEGORIES or category in INCOME_CATEGORIES:
            return category
        for key, value in CATEGORY_ALIASES.items():
            if key in category:
                return value
        return None

    # ------------------------------------------------------------------ 流水
    def txn_view(self, row):
        return {"id": row["txn_id"], "time": row["time"], "merchant": row["merchant"], "category": row["category"],
                "amount_cents": row["amount_cents"], "status": row["status"], "card_id": row["card_id"],
                "memo": row["memo"], "flags": ["foreign"] if row["foreign_flag"] else []}

    def search(self, user_id, start, end, category=None, keyword=None, direction="all", order_by="time", limit=20, cursor=None):
        sql = "SELECT * FROM transactions WHERE user_id=? AND time>=? AND time<? AND status IN ('success','in_transit')"
        args = [user_id, iso(start), iso(end)]
        cat = self.normalize_category(category)
        if category and cat:
            sql += " AND category=?"
            args.append(cat)
        if keyword:
            sql += " AND (merchant LIKE ? OR counterparty LIKE ?)"
            args += ["%" + keyword + "%", "%" + keyword + "%"]
        if direction == "expense":
            sql += " AND amount_cents<0"
        elif direction == "income":
            sql += " AND amount_cents>0"
        rows = self.db.execute(sql, args).fetchall()
        expense = -sum(r["amount_cents"] for r in rows if r["amount_cents"] < 0)
        income = sum(r["amount_cents"] for r in rows if r["amount_cents"] > 0)
        if order_by == "amount":
            rows = sorted(rows, key=lambda r: abs(r["amount_cents"]), reverse=True)
        else:
            rows = sorted(rows, key=lambda r: r["time"], reverse=True)
        offset = int(cursor) if cursor and str(cursor).isdigit() else 0
        page = rows[offset:offset + limit]
        next_cursor = str(offset + limit) if offset + limit < len(rows) else None
        return {"items": [self.txn_view(r) for r in page], "count": len(rows), "expense_cents": expense,
                "income_cents": income, "next_cursor": next_cursor}

    # ------------------------------------------------------------------ 分类统计
    def _expenses(self, user_id, start, end):
        return self.db.execute("""SELECT category, amount_cents FROM transactions WHERE user_id=? AND time>=? AND time<?
            AND status IN ('success','in_transit') AND amount_cents<0 AND category NOT IN ('账户互转','理财申购','理财赎回','换汇')""", (user_id, iso(start), iso(end))).fetchall()

    def breakdown(self, user_id, start, end):
        rows = self._expenses(user_id, start, end)
        sums, counts = defaultdict(int), defaultdict(int)
        for r in rows:
            sums[r["category"]] += -r["amount_cents"]
            counts[r["category"]] += 1
        total = sum(sums.values())
        categories = [{"name": name, "amount_cents": cents, "share": round(cents / total, 4) if total else 0, "count": counts[name],
                       "avg_cents": cents // counts[name] if counts[name] else 0}
                      for name, cents in sorted(sums.items(), key=lambda kv: kv[1], reverse=True)]
        span = end - start
        if start.day == 1 and start.hour == 0 and span <= timedelta(days=31):
            # 按自然月比较：本月 1 日至今 对比 上月 1 日至同一天（环比）
            py, pm = add_months(start.year, start.month, -1)
            prev_start, prev_month_end = month_bounds(py, pm)
            prev_end = min(prev_start + span, prev_month_end)
        else:
            prev_start, prev_end = start - span, start
        prev_rows = self._expenses(user_id, prev_start, prev_end)
        prev_total = -sum(r["amount_cents"] for r in prev_rows)
        change = round((total - prev_total) * 100 / prev_total, 1) if prev_total else None
        return {"period": {"from": iso(start), "to": iso(end)}, "total_cents": total, "categories": categories,
                "compare": {"prev_total_cents": prev_total, "change_pct": change}}

    # ------------------------------------------------------------------ 异常交易识别（PLAN L3）
    def anomalies(self, user_id, now, days=60):
        """规则引擎（代码）：凌晨/境外/新商户/金额异常组合、重复扣款、小额试探、订阅涨价、可疑来账。"""
        since = iso(now - timedelta(days=days))
        history_start = iso(now - timedelta(days=400))
        rows = self.db.execute("""SELECT * FROM transactions WHERE user_id=? AND time>=? AND status='success' ORDER BY time""",
                               (user_id, history_start)).fetchall()
        recent = [r for r in rows if r["time"] >= since]
        marks = {r["finding_id"]: r["mark"] for r in self.db.execute("SELECT * FROM anomaly_marks WHERE user_id=?", (user_id,))}
        card_spend = [r for r in rows if r["amount_cents"] < 0 and r["card_id"]]
        amounts = sorted(-r["amount_cents"] for r in card_spend)
        median = statistics.median(amounts) if amounts else 0
        findings = []
        first_seen = {}
        for r in rows:
            first_seen.setdefault(r["merchant"], r["time"])

        def add(fid, txns, rule, severity, explanation, card_id=None):
            if marks.get(fid) == "normal":
                return
            actions = []
            if card_id:
                card = self.db.execute("SELECT status,tail FROM cards WHERE card_id=?", (card_id,)).fetchone()
                if card and card["status"] == "active":
                    actions.append({"label": f"冻结尾号{card['tail']}的卡", "intent": "freeze_card", "params": {"card_id": card_id}})
            actions.append({"label": "这笔是我本人的", "intent": "mark_normal", "params": {"finding_id": fid}})
            first = txns[0]
            findings.append({"finding_id": fid, "transaction_ids": [t["txn_id"] for t in txns], "time": first["time"],
                             "merchant": first["merchant"], "amount_cents": sum(t["amount_cents"] for t in txns),
                             "rule": rule, "severity": severity, "explanation": explanation, "actions": actions,
                             "card_id": card_id})

        for r in recent:
            if r["amount_cents"] >= 0 or not r["card_id"]:
                continue
            t = parse_iso(r["time"])
            factors = []
            if 0 <= t.hour < 6:
                factors.append("凌晨交易")
            if r["foreign_flag"]:
                factors.append("境外商户")
            if first_seen.get(r["merchant"]) == r["time"]:
                factors.append("首次出现的商户")
            if -r["amount_cents"] > 3 * median and -r["amount_cents"] > 50000:
                factors.append(f"金额远高于你平时的单笔消费（中位数 {yuan(int(median))}）")
            if len(factors) >= 3 or (len(factors) == 2 and ("凌晨交易" in factors or "境外商户" in factors)):
                severity = "high" if len(factors) >= 3 else "medium"
                add("f-" + r["txn_id"], [r], "unusual_card_spend", severity,
                    "，".join(factors) + "。如果不是你本人消费，建议立即冻结这张卡。", r["card_id"])
        # 重复扣款：同卡同商户同金额 2 分钟内
        for i, r in enumerate(recent):
            if r["amount_cents"] >= 0 or not r["card_id"]:
                continue
            for s in recent[i + 1:i + 6]:
                if (s["merchant"] == r["merchant"] and s["amount_cents"] == r["amount_cents"] and s["card_id"] == r["card_id"]
                        and (parse_iso(s["time"]) - parse_iso(r["time"])).total_seconds() <= 120):
                    gap = int((parse_iso(s["time"]) - parse_iso(r["time"])).total_seconds())
                    add("f-dup-" + r["txn_id"], [r, s], "duplicate_charge", "medium",
                        f"同一商户、同一金额 {yuan(-r['amount_cents'])} 在 {gap} 秒内扣了两次，疑似重复扣款，可以联系商户退款。", None)
                    break
        # 小额试探：同卡同商户 10 分钟内 ≥3 笔 ≤ ¥5
        used = set()
        for i, r in enumerate(recent):
            if r["txn_id"] in used or r["amount_cents"] >= 0 or -r["amount_cents"] > 500 or not r["card_id"]:
                continue
            group = [s for s in recent[i:] if s["merchant"] == r["merchant"] and s["card_id"] == r["card_id"]
                     and 0 < -s["amount_cents"] <= 500 and (parse_iso(s["time"]) - parse_iso(r["time"])).total_seconds() <= 600]
            if len(group) >= 3:
                used.update(g["txn_id"] for g in group)
                add("f-probe-" + r["txn_id"], group, "small_probe", "high",
                    f"{len(group)} 笔 ¥5 以内的小额扣款在 10 分钟内连续发生，常见于盗刷前的“试卡”，建议立即冻结这张卡。", r["card_id"])
        # 订阅涨价
        for sub in self.db.execute("SELECT * FROM subscriptions WHERE user_id=?", (user_id,)).fetchall():
            charges = [r for r in rows if r["merchant"] == sub["merchant"] and r["amount_cents"] < 0]
            for prev, cur in zip(charges, charges[1:]):
                if cur["amount_cents"] < prev["amount_cents"] and cur["time"] >= iso(now - timedelta(days=90)):
                    add("f-price-" + sub["subscription_id"], [cur], "price_increase", "low",
                        f"{sub['name']}从 {yuan(-prev['amount_cents'])} 涨到 {yuan(-cur['amount_cents'])}（{cur['time'][:10]} 起）。", None)
                    break
        # 可疑来账：极小金额来账，或备注里有指令性文字
        for r in recent:
            if r["amount_cents"] > 0 and (r["amount_cents"] < 100 or (r["memo"] and re.search(r"转到|安全账户|忽略|立即|验证码", r["memo"] or ""))):
                add("f-in-" + r["txn_id"], [r], "suspicious_incoming", "medium",
                    f"收到来自“{r['counterparty'] or '未知'}”的 {yuan(r['amount_cents'])} 小额来账，备注里有要求转账的文字。"
                    "这类“打一分钱+备注引导”常见于诈骗，不要按备注操作。", None)
        order = {"high": 0, "medium": 1, "low": 2}
        findings.sort(key=lambda f: (order[f["severity"]], f["time"]), reverse=False)
        return findings

    # ------------------------------------------------------------------ 月报 / 年报（PLAN L4、L5）
    def _income(self, user_id, start, end):
        return self.db.execute("""SELECT COALESCE(SUM(amount_cents),0) FROM transactions WHERE user_id=? AND time>=? AND time<?
            AND status='success' AND amount_cents>0 AND category NOT IN ('账户互转','理财申购','理财赎回','换汇')""", (user_id, iso(start), iso(end))).fetchone()[0]

    def monthly_report(self, user_id, month):
        now = self.k.now()
        y, m = map(int, month.split("-"))
        start, end = month_bounds(y, m)
        end = min(end, now + timedelta(seconds=1))
        data = self.breakdown(user_id, start, end)
        py, pm = add_months(y, m, -1)
        ps, pe = month_bounds(py, pm)
        prev = self.breakdown(user_id, ps, pe)
        income = self._income(user_id, start, end)
        expense = data["total_cents"]
        change = data["compare"]["change_pct"]  # 与 spending_breakdown 同一口径：上月同期
        subs = -self.db.execute("""SELECT COALESCE(SUM(amount_cents),0) FROM transactions WHERE user_id=? AND time>=? AND time<?
            AND category='订阅会员' AND amount_cents<0""", (user_id, iso(start), iso(end))).fetchone()[0]
        findings = [f for f in self.anomalies(user_id, now, days=400) if start <= parse_iso(f["time"]) < end]
        trend = []
        for i in range(5, -1, -1):
            ty, tm = add_months(y, m, -i)
            ts, te = month_bounds(ty, tm)
            trend.append({"label": f"{tm}月", "value_cents": -sum(r["amount_cents"] for r in self._expenses(user_id, ts, min(te, end)))})
        top = data["categories"][:3]
        bullets = [f"{c['name']} {yuan(c['amount_cents'])}，占 {round(c['share'] * 100)}%（{c['count']} 笔）" for c in top]
        prev_map = {c["name"]: c["amount_cents"] for c in prev["categories"]}
        movers = sorted(((c["name"], c["amount_cents"] - prev_map.get(c["name"], 0)) for c in data["categories"]), key=lambda x: -abs(x[1]))[:2]
        changes = [f"{name}{'增加' if delta > 0 else '减少'} {yuan(abs(delta))}" for name, delta in movers if delta]
        sections = [{"title": "支出构成", "bullets": bullets},
                    {"title": "和上月比", "bullets": changes or ["和上月基本持平"]},
                    {"title": "异常与风险", "bullets": [f"{ {'high': '高', 'medium': '中', 'low': '低'}[f['severity']] }风险：{f['merchant']} {yuan(abs(f['amount_cents']))}（{f['time'][5:16].replace('T', ' ')}）" for f in findings[:5]] or ["本月未发现异常交易"]},
                    {"title": "订阅支出", "bullets": [f"本月订阅会员合计 {yuan(subs)}"]}]
        return {"kind": "monthly", "period": {"from": iso(start), "to": iso(end), "label": f"{y}年{m}月"},
                "kpis": [{"label": "总支出", "value": yuan(expense), "value_cents": expense,
                          "delta": (f"{'+' if change > 0 else ''}{change}% 环比（上月同期）" if change is not None else "")},
                         {"label": "总收入", "value": yuan(income), "value_cents": income, "delta": ""},
                         {"label": "结余", "value": yuan(income - expense), "value_cents": income - expense, "delta": ""},
                         {"label": "异常交易", "value": f"{len(findings)} 处", "value_cents": None, "delta": ""}],
                "sections": sections,
                "charts": [{"type": "spending_breakdown", "data": data},
                           {"type": "trend_chart", "data": {"title": "近 6 个月支出", "metric": "expense", "series": trend}}]}

    def annual_report(self, user_id, year=None):
        now = self.k.now()
        if year is None:
            sy, sm = add_months(now.year, now.month, -11)
            start, label = datetime(sy, sm, 1, tzinfo=SHANGHAI), "过去 12 个月"
        else:
            start, label = datetime(year, 1, 1, tzinfo=SHANGHAI), f"{year}年"
        end = min(datetime((year or now.year) + 1, 1, 1, tzinfo=SHANGHAI) if year else now + timedelta(seconds=1), now + timedelta(seconds=1))
        data = self.breakdown(user_id, start, end)
        income = self._income(user_id, start, end)
        series, y, m = [], start.year, start.month
        while datetime(y, m, 1, tzinfo=SHANGHAI) < end:
            ms, me = month_bounds(y, m)
            series.append({"label": f"{y % 100:02d}-{m:02d}", "value_cents": -sum(r["amount_cents"] for r in self._expenses(user_id, ms, min(me, end)))})
            y, m = add_months(y, m, 1)
        peak = max(series, key=lambda s: s["value_cents"]) if series else None
        low = min(series, key=lambda s: s["value_cents"]) if series else None
        avg = data["total_cents"] // max(1, len(series))
        bullets = [f"月均支出 {yuan(avg)}"]
        if peak:
            bullets.append(f"支出最高的月份：{peak['label']}（{yuan(peak['value_cents'])}）")
        if low:
            bullets.append(f"支出最低的月份：{low['label']}（{yuan(low['value_cents'])}）")
        top = data["categories"][:3]
        return {"kind": "annual", "period": {"from": iso(start), "to": iso(end), "label": label},
                "kpis": [{"label": "总支出", "value": yuan(data["total_cents"]), "value_cents": data["total_cents"], "delta": ""},
                         {"label": "总收入", "value": yuan(income), "value_cents": income, "delta": ""},
                         {"label": "结余", "value": yuan(income - data["total_cents"]), "value_cents": income - data["total_cents"], "delta": ""},
                         {"label": "月均支出", "value": yuan(avg), "value_cents": avg, "delta": ""}],
                "sections": [{"title": "要点", "bullets": bullets},
                             {"title": "最大的三类支出", "bullets": [f"{c['name']} {yuan(c['amount_cents'])}（{round(c['share'] * 100)}%）" for c in top]}],
                "charts": [{"type": "trend_chart", "data": {"title": "月度支出趋势", "metric": "expense", "series": series}},
                           {"type": "spending_breakdown", "data": data}]}
