"""卡片、订阅、理财、预算/订单处理器（PLAN 场景二到六）。

风险对称原则：降低风险的操作低摩擦（冻结、下调限额 = 黄档），增加风险的操作强验证（解冻、上调限额、挂失、解挂 = 红档）。
"""

import json
import secrets
from datetime import datetime, timedelta

from .kernel import SMALL_LIMIT_CENTS, RuleError
from .ops import Handler
from .seed import PRODUCT_DISCLAIMER
from .util import SHANGHAI, add_months, human_date, iso, new_id, parse_iso, plain_yuan, yuan

CARD_STATUS = {"active": "正常", "frozen": "临时冻结", "lost": "已挂失"}
RISK_LABELS = {"C1": "保守型", "C2": "稳健型", "C3": "平衡型", "C4": "成长型", "C5": "进取型"}

QUESTIONNAIRE = [
    ("Q1", "你的投资经验有多久？", ["无", "1 年以内", "1–3 年", "3–5 年", "5 年以上"]),
    ("Q2", "你能接受的最大亏损是多少？", ["不能亏", "5% 以内", "10% 以内", "20% 以内", "20% 以上"]),
    ("Q3", "这笔钱计划投资多久？", ["3 个月内", "3–6 个月", "6–12 个月", "1–3 年", "3 年以上"]),
    ("Q4", "你的收入稳定吗？", ["无稳定收入", "不太稳定", "一般", "稳定", "很稳定"]),
    ("Q5", "你的投资目的是？", ["保本", "稳定增值", "平衡", "较高收益", "高收益"]),
    ("Q6", "理财资金占你总资产的比例？", ["70% 以上", "50–70%", "30–50%", "10–30%", "10% 以下"]),
]


def risk_level_for(score):
    if score <= 9:
        return "C1"
    if score <= 14:
        return "C2"
    if score <= 20:
        return "C3"
    if score <= 25:
        return "C4"
    return "C5"


def questionnaire_block(questionnaire_id):
    return {"type": "risk_questionnaire", "data": {"questionnaire_id": questionnaire_id, "questions": [
        {"id": qid, "text": text, "options": [{"value": i + 1, "label": label} for i, label in enumerate(options)]}
        for qid, text, options in QUESTIONNAIRE]}}


# ---------------------------------------------------------------------------------------------- 卡片
class CardHandler(Handler):
    allowed_from = ()
    target = None

    def subject(self, p):
        return "card:" + p.get("card_id", "")

    def card(self, user_id, p):
        row = self.db.execute("SELECT * FROM cards WHERE card_id=? AND user_id=?", (p.get("card_id"), user_id)).fetchone()
        if row is None:
            raise RuleError("forbidden", "只能操作你本人名下的卡。")
        return row

    def prepare(self, user_id, p, recheck=False):
        row = self.card(user_id, p)
        if self.allowed_from and row["status"] not in self.allowed_from:
            raise RuleError("invalid_request", f"这张卡当前是“{CARD_STATUS[row['status']]}”状态，不能{self.verb}。")
        return p

    def card_label(self, row):
        return f"{row['name']} **** {row['tail']}"

    def sms_text(self, user_id, p):
        return f"{self.verb}{self.card_label(self.card(user_id, p))}"

    def view(self, user_id, p, tier):
        row = self.card(user_id, p)
        return {"title": f"{self.verb} · {self.card_label(row)}",
                "lines": [{"label": "卡片", "value": self.card_label(row)},
                          {"label": "当前状态", "value": CARD_STATUS[row["status"]]},
                          {"label": "办理后", "value": CARD_STATUS[self.target], "emphasis": True}],
                "impact": self.impact}

    def execute(self, user_id, p, request_row):
        row = self.card(user_id, p)
        self.db.execute("UPDATE cards SET status=? WHERE card_id=?", (self.target, row["card_id"]))
        return {"status": "success", "title": f"{self.verb}成功",
                "lines": [{"label": "卡片", "value": self.card_label(row)}, {"label": "状态", "value": CARD_STATUS[self.target]}],
                "summary": f"{self.card_label(row)} 已{self.done}"}


class FreezeCard(CardHandler):
    intent, verb, done, target, allowed_from = "freeze_card", "临时冻结", "临时冻结", "frozen", ("active",)
    impact = "冻结后这张卡不能消费和扣费（自动续费也会失败），随时可以解冻（解冻需要强验证）。"

    def tier(self, user_id, p):
        return "yellow", "代码判档：黄档（冻结卡片降低风险，风险对称原则：低摩擦）"


class UnfreezeCard(CardHandler):
    intent, verb, done, target, allowed_from = "unfreeze_card", "解冻", "解冻", "active", ("frozen",)
    impact = "解冻后卡片恢复消费。"

    def tier(self, user_id, p):
        return "red", "代码判档：红档（解冻增加风险，风险对称原则：需要强验证）"


class ReportLost(CardHandler):
    intent, verb, done, target, allowed_from = "report_card_lost", "正式挂失", "挂失", "lost", ("active", "frozen")
    impact = "挂失后卡片永久停用，可以说“卡找到了，解挂”恢复（需要强验证）。"

    def tier(self, user_id, p):
        return "red", "代码判档：红档（挂失是卡片状态的重大变更，需要强验证）"


class RestoreCard(CardHandler):
    intent, verb, done, target, allowed_from = "restore_card", "解挂", "解除挂失", "active", ("lost",)
    impact = "解挂后卡片恢复正常使用。"

    def tier(self, user_id, p):
        return "red", "代码判档：红档（解挂增加风险，需要强验证）"


class SetCardLimit(CardHandler):
    intent, verb, done = "set_card_limit", "调整每日限额", "调整每日限额"

    def prepare(self, user_id, p, recheck=False):
        row = self.card(user_id, p)
        new = p.get("daily_limit_cents")
        if type(new) is not int or not 10000 <= new <= 5000000:
            raise RuleError("invalid_amount", "每日限额需要在 ¥100.00 到 ¥50,000.00 之间。")
        if new == row["daily_limit_cents"] and not recheck:
            raise RuleError("invalid_request", f"这张卡的每日限额已经是 {yuan(new)} 了。")
        if row["status"] == "lost":
            raise RuleError("invalid_request", "已挂失的卡不能调整限额。")
        p["from_cents"] = row["daily_limit_cents"]
        return p

    def tier(self, user_id, p):
        if p["daily_limit_cents"] > p["from_cents"]:
            return "red", "代码判档：红档（上调限额增加风险，需要强验证）"
        return "yellow", "代码判档：黄档（下调限额降低风险）"

    def view(self, user_id, p, tier):
        row = self.card(user_id, p)
        return {"title": f"{'上调' if tier == 'red' else '下调'}每日限额 · {self.card_label(row)}",
                "lines": [{"label": "卡片", "value": self.card_label(row)},
                          {"label": "当前每日限额", "value": yuan(row["daily_limit_cents"])},
                          {"label": "调整为", "value": yuan(p["daily_limit_cents"]), "emphasis": True}],
                "impact": "确认后立即生效。"}

    def sms_text(self, user_id, p):
        return f"将{self.card_label(self.card(user_id, p))}每日限额调整为 {plain_yuan(p['daily_limit_cents'])} 元"

    def execute(self, user_id, p, request_row):
        row = self.card(user_id, p)
        self.db.execute("UPDATE cards SET daily_limit_cents=? WHERE card_id=?", (p["daily_limit_cents"], row["card_id"]))
        return {"status": "success", "title": "限额已调整",
                "lines": [{"label": "卡片", "value": self.card_label(row)}, {"label": "每日限额", "value": yuan(p["daily_limit_cents"])}],
                "summary": f"{self.card_label(row)} 每日限额已调整为 {yuan(p['daily_limit_cents'])}"}


class ApplyVirtualCard(Handler):
    intent = "apply_virtual_card"

    def subject(self, p):
        return "vcard"

    def prepare(self, user_id, p, recheck=False):
        count = self.db.execute("SELECT COUNT(*) FROM cards WHERE user_id=? AND kind='virtual' AND status!='lost'", (user_id,)).fetchone()[0]
        if count >= 5:
            raise RuleError("invalid_request", "虚拟卡最多 5 张。")
        limit = p.get("daily_limit_cents", 100000)
        if type(limit) is not int or not 10000 <= limit <= 500000:
            raise RuleError("invalid_amount", "虚拟卡每日限额需要在 ¥100.00 到 ¥5,000.00 之间。")
        p["daily_limit_cents"] = limit
        p["purpose"] = (p.get("purpose") or "网购")[:10]
        return p

    def tier(self, user_id, p):
        return "yellow", "代码判档：黄档（申请虚拟卡，绑定本人活期账户，默认限额较低）"

    def view(self, user_id, p, tier):
        return {"title": f"申请虚拟卡 · {p['purpose']}",
                "lines": [{"label": "用途", "value": p["purpose"]}, {"label": "绑定账户", "value": "储蓄卡（活期）"},
                          {"label": "每日限额", "value": yuan(p["daily_limit_cents"]), "emphasis": True}],
                "impact": "虚拟卡只能线上使用，卡号只在 App 内显示后四位（模拟）。"}

    def execute(self, user_id, p, request_row):
        tail = f"{secrets.randbelow(9000) + 1000}"
        card_id = "card-" + tail
        while self.db.execute("SELECT 1 FROM cards WHERE card_id=?", (card_id,)).fetchone():
            tail = f"{secrets.randbelow(9000) + 1000}"
            card_id = "card-" + tail
        self.db.execute("INSERT INTO cards VALUES(?,?,?,?,?,?,?,?,?,?)",
                        (card_id, user_id, p["purpose"] + "虚拟卡", "virtual", tail, user_id + "-main", "active",
                         p["daily_limit_cents"], p["purpose"], iso(self.k.now())))
        return {"status": "success", "title": "虚拟卡已开通",
                "lines": [{"label": "卡片", "value": f"{p['purpose']}虚拟卡 **** {tail}"}, {"label": "每日限额", "value": yuan(p["daily_limit_cents"])}],
                "summary": f"{p['purpose']}虚拟卡（尾号{tail}）已开通，每日限额 {yuan(p['daily_limit_cents'])}", "card_id": card_id}


# ---------------------------------------------------------------------------------------------- 订阅
def detect_subscriptions(k, user_id):
    """从流水自动识别订阅：登记的订阅 + 流水里连续 ≥3 个月、同商户、带“自动续费”或金额固定的扣费。"""
    now = k.now()
    registered = {r["merchant"]: r for r in k.db.execute("SELECT * FROM subscriptions WHERE user_id=?", (user_id,))}
    since = iso(now - timedelta(days=200))
    rows = k.db.execute("""SELECT merchant, amount_cents, time FROM transactions WHERE user_id=? AND time>=? AND amount_cents<0
        AND status='success' AND card_id IS NOT NULL ORDER BY time""", (user_id, since)).fetchall()
    by_merchant = {}
    for r in rows:
        by_merchant.setdefault(r["merchant"], []).append(r)
    items = []
    for merchant, charges in by_merchant.items():
        months = {c["time"][:7] for c in charges}
        recurring = "自动续费" in merchant or (len(months) >= 4 and len({c["amount_cents"] for c in charges}) <= 2 and len(charges) <= len(months) + 1)
        if merchant in registered or not recurring or len(months) < 3:
            continue
        last = charges[-1]
        last_time = parse_iso(last["time"])
        y, m = add_months(last_time.year, last_time.month, 1)
        next_date = last_time.replace(year=y, month=m).date().isoformat()
        items.append({"subscription_id": "det-" + merchant.split(" ")[0], "name": merchant.replace(" 自动续费", ""), "merchant": merchant,
                      "amount_cents": -last["amount_cents"], "cycle": "monthly", "next_charge_date": next_date, "status": "active",
                      "source": "detected", "months_seen": len(months)})
    return items


def subscription_items(k, user_id):
    now = k.now()
    items = []
    for s in k.db.execute("SELECT * FROM subscriptions WHERE user_id=? ORDER BY next_charge_date", (user_id,)):
        items.append({"subscription_id": s["subscription_id"], "name": s["name"], "merchant": s["merchant"], "amount_cents": s["amount_cents"],
                      "cycle": s["cycle"], "next_charge_date": s["next_charge_date"] if s["status"] == "active" else None,
                      "status": s["status"], "source": "registered", "last_used_at": s["last_used_at"]})
    items += detect_subscriptions(k, user_id)
    for item in items:
        flags = []
        charges = k.db.execute("""SELECT amount_cents, time FROM transactions WHERE user_id=? AND merchant=? AND amount_cents<0
            ORDER BY time""", (user_id, item["merchant"])).fetchall()
        for prev, cur in zip(charges, charges[1:]):
            if cur["amount_cents"] < prev["amount_cents"] and parse_iso(cur["time"]) >= now - timedelta(days=90):
                flags.append("price_up")
                item["price_change"] = {"from_cents": -prev["amount_cents"], "to_cents": -cur["amount_cents"], "since": cur["time"][:10]}
                break
        if item.get("last_used_at") and parse_iso(item["last_used_at"]) < now - timedelta(days=90):
            flags.append("idle")
            item["idle_days"] = (now - parse_iso(item["last_used_at"])).days
        if item["status"] == "active" and item.get("next_charge_date") and \
                datetime.fromisoformat(item["next_charge_date"]).date() <= (now + timedelta(days=7)).date():
            flags.append("renew_soon")
        item["flags"] = flags
    return items


def subscription_block(k, user_id):
    items = subscription_items(k, user_id)
    active = [i for i in items if i["status"] == "active"]
    return {"type": "subscription_list", "data": {"items": items, "monthly_total_cents": sum(i["amount_cents"] for i in active)}}


class QuerySubscriptions(Handler):
    """赛题权限表把“订阅查询”列为黄档：确认后才返回名单。"""
    intent = "query_subscriptions"

    def subject(self, p):
        return "subs-query"

    def prepare(self, user_id, p, recheck=False):
        return {}

    def tier(self, user_id, p):
        return "yellow", "代码判档：黄档（订阅查询按赛题权限表需要确认）"

    def view(self, user_id, p, tier):
        return {"title": "查询订阅与自动扣费", "lines": [{"label": "查询内容", "value": "登记的订阅 + 从流水自动识别的扣费"},
                                                     {"label": "范围", "value": "本人名下全部卡片"}],
                "impact": "确认后展示订阅名单，并标出涨价、闲置、即将续费。"}

    def execute(self, user_id, p, request_row):
        block = subscription_block(self.k, user_id)
        data = block["data"]
        active = [i for i in data["items"] if i["status"] == "active"]
        detected = [i for i in active if i["source"] == "detected"]
        return {"status": "success", "title": "订阅查询完成",
                "lines": [{"label": "生效中的订阅", "value": f"{len(active)} 项"},
                          {"label": "每月合计", "value": yuan(data["monthly_total_cents"])},
                          {"label": "自动识别", "value": "、".join(i["name"] for i in detected) or "无"}],
                "blocks": [block],
                "summary": f"你有 {len(active)} 项生效中的订阅，每月合计 {yuan(data['monthly_total_cents'])}" +
                           (f"，其中 {'、'.join(i['name'] for i in detected)} 是从流水里自动识别出来的" if detected else "")}


class CancelSubscription(Handler):
    intent = "cancel_subscription"

    def subject(self, p):
        return "sub:" + p.get("subscription_id", "")

    def _item(self, user_id, p):
        item = next((i for i in subscription_items(self.k, user_id) if i["subscription_id"] == p.get("subscription_id")), None)
        if item is None:
            raise RuleError("not_found", "没有找到这项订阅。")
        if item["status"] != "active":
            raise RuleError("invalid_request", "这项订阅已经取消了。")
        return item

    def prepare(self, user_id, p, recheck=False):
        self._item(user_id, p)
        return p

    def tier(self, user_id, p):
        return "yellow", "代码判档：黄档（取消订阅）"

    def view(self, user_id, p, tier):
        item = self._item(user_id, p)
        lines = [{"label": "订阅", "value": item["name"]}, {"label": "每期金额", "value": yuan(item["amount_cents"])},
                 {"label": "下次扣费", "value": item.get("next_charge_date") or "-"}]
        if "idle" in item["flags"]:
            lines.append({"label": "使用情况", "value": f"已 {item['idle_days']} 天没用"})
        return {"title": f"取消订阅 · {item['name']}", "lines": lines,
                "impact": "取消后不再自动扣费，历史扣费记录保留。"}

    def execute(self, user_id, p, request_row):
        item = self._item(user_id, p)
        now = iso(self.k.now())
        if item["source"] == "registered":
            self.db.execute("UPDATE subscriptions SET status='cancelled', cancelled_at=?, next_charge_date=NULL WHERE subscription_id=?",
                            (now, item["subscription_id"]))
        else:
            self.db.execute("INSERT INTO subscriptions VALUES(?,?,?,?,?,?,?,NULL,'cancelled',NULL,NULL,?)",
                            ("sub-" + new_id("d")[2:], user_id, item["name"], item["merchant"], item["amount_cents"], "monthly",
                             int(item["next_charge_date"][-2:]), now))
        return {"status": "success", "title": "订阅已取消",
                "lines": [{"label": "订阅", "value": item["name"]}, {"label": "每月节省", "value": yuan(item["amount_cents"])}],
                "summary": f"{item['name']}已取消，以后不再扣费，每月省 {yuan(item['amount_cents'])}"}


# ---------------------------------------------------------------------------------------------- 理财
class SubmitRiskAssessment(Handler):
    intent = "submit_risk_assessment"

    def subject(self, p):
        return "risk-assessment"

    def prepare(self, user_id, p, recheck=False):
        answers = p.get("answers")
        if not isinstance(answers, dict) or set(answers) != {q[0] for q in QUESTIONNAIRE}:
            raise RuleError("invalid_request", "请完成全部 6 道题。")
        for value in answers.values():
            if type(value) is not int or not 1 <= value <= 5:
                raise RuleError("invalid_request", "答案无效。")
        p["score"] = sum(answers.values())
        p["level"] = risk_level_for(p["score"])
        return p

    def tier(self, user_id, p):
        return "yellow", "代码判档：黄档（提交风险测评）"

    def view(self, user_id, p, tier):
        return {"title": "提交风险测评", "lines": [{"label": "得分", "value": f"{p['score']} 分（6–30）"},
                                                {"label": "测评结果", "value": f"{p['level']} {RISK_LABELS[p['level']]}", "emphasis": True},
                                                {"label": "可购买", "value": f"风险等级 R{p['level'][1:]} 及以下的产品"},
                                                {"label": "有效期", "value": "1 年"}],
                "impact": "确认后测评结果生效，作为理财适当性管理的依据。"}

    def execute(self, user_id, p, request_row):
        now = self.k.now()
        self.db.execute("UPDATE users SET risk_level=?, risk_score=?, risk_assessed_at=?, risk_valid_until=? WHERE user_id=?",
                        (p["level"], p["score"], iso(now), iso(now.replace(year=now.year + 1)), user_id))
        profile = {"level": p["level"], "label": RISK_LABELS[p["level"]], "score": p["score"],
                   "valid_until": iso(now.replace(year=now.year + 1)), "max_product_risk": "R" + p["level"][1:]}
        return {"status": "success", "title": "风险测评已生效", "lines": [{"label": "测评结果", "value": f"{p['level']} {RISK_LABELS[p['level']]}"}],
                "blocks": [{"type": "risk_profile", "data": profile}],
                "summary": f"测评结果：{p['level']} {RISK_LABELS[p['level']]}，可以购买 R{p['level'][1:]} 及以下的产品"}


def valid_profile(k, user_id):
    user = k.user(user_id)
    if not user["risk_level"] or not user["risk_valid_until"] or parse_iso(user["risk_valid_until"]) <= k.now():
        return None
    return user["risk_level"]


class PurchaseProduct(Handler):
    """理财申购：适当性（测评等级 ≥ 产品风险）由代码判断；一律红档强验证。本人资金，不计入对外转账累计。"""
    intent = "purchase_product"

    def subject(self, p):
        return "buy:" + p.get("product_id", "")

    def prepare(self, user_id, p, recheck=False):
        product = self.db.execute("SELECT * FROM products WHERE product_id=?", (p.get("product_id"),)).fetchone()
        if product is None:
            raise RuleError("not_found", "没有这个理财产品。")
        level = valid_profile(self.k, user_id)
        if level is None:
            raise RuleError("need_assessment", "购买理财前需要先完成风险测评（你还没有有效的测评结果）。")
        if int(product["risk_level"][1:]) > int(level[1:]):
            raise RuleError("unsuitable", f"{product['name']}的风险等级是 {product['risk_level']}，高于你的测评结果 {level} {RISK_LABELS[level]}"
                                          f"（最高可买 R{level[1:]}）。按理财适当性管理规定，不能为你办理申购。",
                            detail={"advice": "可以看看风险等级更低的产品，或者在情况变化后重新做风险测评。"})
        amount = p.get("amount_cents")
        if type(amount) is not int or amount < product["min_amount_cents"]:
            raise RuleError("invalid_amount", f"{product['name']}起购金额是 {yuan(product['min_amount_cents'])}。")
        account = self.db.execute("SELECT * FROM accounts WHERE account_id=?", (user_id + "-main",)).fetchone()
        if account["balance_cents"] - account["reserved_cents"] < amount:
            raise RuleError("insufficient_funds", f"活期可用余额不足（可用 {yuan(account['balance_cents'] - account['reserved_cents'])}）。")
        p["risk_level"], p["profile_level"] = product["risk_level"], level
        return p

    def tier(self, user_id, p):
        return "red", f"代码判档：红档（理财申购一律强验证；适当性 {p['profile_level']} ≥ {p['risk_level']}，通过）"

    def view(self, user_id, p, tier):
        product = self.db.execute("SELECT * FROM products WHERE product_id=?", (p["product_id"],)).fetchone()
        term = "随时可取" if product["term_days"] == 0 else f"{product['term_days']} 天，到期可取"
        return {"title": f"申购 {product['name']}",
                "lines": [{"label": "产品", "value": f"{product['name']}（{product['type']} · {product['risk_level']}）"},
                          {"label": "金额", "value": yuan(p["amount_cents"]), "emphasis": True},
                          {"label": "期限", "value": term}, {"label": "收益说明", "value": product["yield_text"]},
                          {"label": "适当性", "value": f"你的测评 {p['profile_level']} {RISK_LABELS[p['profile_level']]}，可购买"},
                          {"label": "付款账户", "value": "储蓄卡（活期）"}],
                "impact": PRODUCT_DISCLAIMER}

    def sms_text(self, user_id, p):
        name = self.db.execute("SELECT name FROM products WHERE product_id=?", (p["product_id"],)).fetchone()[0]
        return f"申购 {name} {plain_yuan(p['amount_cents'])} 元"

    def execute(self, user_id, p, request_row):
        db, now = self.db, self.k.now()
        product = db.execute("SELECT * FROM products WHERE product_id=?", (p["product_id"],)).fetchone()
        db.execute("UPDATE accounts SET balance_cents=balance_cents-? WHERE account_id=?", (p["amount_cents"], user_id + "-main"))
        db.execute("INSERT INTO holdings VALUES(?,?,?,?,0,?,?,?)",
                   (new_id("hold"), user_id, product["product_id"], p["amount_cents"], iso(now),
                    iso(now + timedelta(days=product["term_days"])), user_id + "-main"))
        db.execute("INSERT INTO transactions VALUES(?,?,?,?,?,?,?,?,?,?,?,0,?)",
                   (new_id("txn"), user_id, user_id + "-main", iso(now), "申购 " + product["name"], "理财申购", -p["amount_cents"],
                    "success", None, None, None, product["product_id"]))
        return {"status": "success", "title": "申购成功",
                "lines": [{"label": "产品", "value": product["name"]}, {"label": "金额", "value": yuan(p["amount_cents"])},
                          {"label": "到期日", "value": (now + timedelta(days=product["term_days"])).date().isoformat()}],
                "summary": f"已申购{product['name']} {yuan(p['amount_cents'])}"}


class RedeemProduct(Handler):
    intent = "redeem_product"

    def subject(self, p):
        return "redeem:" + p.get("product_id", "")

    def _holdings(self, user_id, product_id):
        now = self.k.now()
        rows = self.db.execute("SELECT * FROM holdings WHERE user_id=? AND product_id=? AND amount_cents>0 ORDER BY purchased_at",
                               (user_id, product_id)).fetchall()
        return [r for r in rows if parse_iso(r["matures_at"]) <= now], rows

    def prepare(self, user_id, p, recheck=False):
        product = self.db.execute("SELECT * FROM products WHERE product_id=?", (p.get("product_id"),)).fetchone()
        if product is None:
            raise RuleError("not_found", "没有这个理财产品。")
        redeemable, all_rows = self._holdings(user_id, p["product_id"])
        if not all_rows:
            raise RuleError("not_found", f"你没有持有{product['name']}。")
        available = sum(r["amount_cents"] for r in redeemable)
        if available == 0:
            raise RuleError("invalid_request", f"{product['name']}还没到期，暂时不能赎回（到期日 {all_rows[0]['matures_at'][:10]}）。")
        amount = p.get("amount_cents")
        if amount == "all":
            p["amount_cents"] = amount = available
        if type(amount) is not int or amount <= 0 or amount > available:
            raise RuleError("invalid_amount", f"可赎回金额是 {yuan(available)}。")
        return p

    def tier(self, user_id, p):
        return "yellow", "代码判档：黄档（赎回到本人活期账户）"

    def view(self, user_id, p, tier):
        product = self.db.execute("SELECT * FROM products WHERE product_id=?", (p["product_id"],)).fetchone()
        redeemable, _ = self._holdings(user_id, p["product_id"])
        return {"title": f"赎回 {product['name']}",
                "lines": [{"label": "产品", "value": product["name"]},
                          {"label": "赎回金额", "value": yuan(p["amount_cents"]), "emphasis": True},
                          {"label": "可赎回", "value": yuan(sum(r["amount_cents"] for r in redeemable))},
                          {"label": "到账账户", "value": "储蓄卡（活期）"}],
                "impact": "确认后本金和对应的收益回到活期账户（模拟实时到账）。"}

    def execute(self, user_id, p, request_row):
        db, now = self.db, self.k.now()
        product = db.execute("SELECT * FROM products WHERE product_id=?", (p["product_id"],)).fetchone()
        redeemable, _ = self._holdings(user_id, p["product_id"])
        remaining, credited, profit_total = p["amount_cents"], 0, 0
        for row in redeemable:
            if remaining <= 0:
                break
            take = min(remaining, row["amount_cents"])
            profit = row["profit_cents"] * take // row["amount_cents"]
            db.execute("UPDATE holdings SET amount_cents=amount_cents-?, profit_cents=profit_cents-? WHERE holding_id=?",
                       (take, profit, row["holding_id"]))
            remaining -= take
            credited += take + profit
            profit_total += profit
        db.execute("UPDATE accounts SET balance_cents=balance_cents+? WHERE account_id=?", (credited, user_id + "-main"))
        db.execute("INSERT INTO transactions VALUES(?,?,?,?,?,?,?,?,?,?,?,0,?)",
                   (new_id("txn"), user_id, user_id + "-main", iso(now), "赎回 " + product["name"], "理财赎回", credited,
                    "success", None, None, None, product["product_id"]))
        balance = db.execute("SELECT balance_cents FROM accounts WHERE account_id=?", (user_id + "-main",)).fetchone()[0]
        return {"status": "success", "title": "赎回成功",
                "lines": [{"label": "本金", "value": yuan(p["amount_cents"])}, {"label": "收益", "value": yuan(profit_total)},
                          {"label": "到账", "value": yuan(credited)}, {"label": "活期余额", "value": yuan(balance)}],
                "summary": f"已赎回{product['name']} {yuan(p['amount_cents'])}，连同收益 {yuan(profit_total)} 共 {yuan(credited)} 已回到活期"}


# ---------------------------------------------------------------------------------------------- 预算与订单（生活联动）
class ReserveBudget(Handler):
    intent = "reserve_budget"

    def subject(self, p):
        return "budget:" + p.get("name", "")

    def prepare(self, user_id, p, recheck=False):
        amount = p.get("amount_cents")
        if type(amount) is not int or not 100 <= amount <= 2000000:
            raise RuleError("invalid_amount", "预算金额需要在 ¥1.00 到 ¥20,000.00 之间。")
        account = self.db.execute("SELECT * FROM accounts WHERE account_id=? AND user_id=?", (user_id + "-main", user_id)).fetchone()
        if not recheck and account["balance_cents"] - account["reserved_cents"] < amount:
            raise RuleError("insufficient_funds", "活期可用余额不足，无法锁定预算。")
        p["name"] = (p.get("name") or "预算")[:20]
        p["until"] = p.get("until") or iso(self.k.now() + timedelta(days=30))
        return p

    def tier(self, user_id, p):
        return "yellow", "代码判档：黄档（锁定本人资金作为预算，不计入对外累计）"

    def view(self, user_id, p, tier):
        return {"title": f"锁定预算 · {p['name']}", "lines": [{"label": "金额", "value": yuan(p["amount_cents"]), "emphasis": True},
                                                           {"label": "有效至", "value": p["until"][:10]}],
                "impact": "锁定的钱仍在你的账户里，只是不能用于其他支出；没用完的会自动释放。"}

    def execute(self, user_id, p, request_row):
        return {"status": "success", "summary": f"已锁定预算 {yuan(p['amount_cents'])}", "title": "预算已锁定",
                "budget_id": create_budget(self.k, user_id, p["name"], p["amount_cents"], p["until"], p.get("plan_id")), "lines": []}


def create_budget(k, user_id, name, amount, until, plan_id=None):
    budget_id = new_id("bud")
    account_id = user_id + "-main"
    account = k.db.execute("SELECT * FROM accounts WHERE account_id=?", (account_id,)).fetchone()
    if account["balance_cents"] - account["reserved_cents"] < amount:
        raise RuleError("insufficient_funds", "活期可用余额不足，无法锁定预算。")
    k.db.execute("UPDATE accounts SET reserved_cents=reserved_cents+? WHERE account_id=?", (amount, account_id))
    k.db.execute("INSERT INTO budgets VALUES(?,?,?,?,?,?,0,0,?,'active',?,?)",
                 (budget_id, user_id, name, account_id, amount, amount, until, plan_id, iso(k.now())))
    return budget_id


def release_budget(k, user_id, budget_id):
    row = k.db.execute("SELECT * FROM budgets WHERE budget_id=? AND user_id=?", (budget_id, user_id)).fetchone()
    if row is None or row["status"] != "active" or row["remaining_cents"] == 0:
        return 0
    k.db.execute("UPDATE accounts SET reserved_cents=reserved_cents-? WHERE account_id=?", (row["remaining_cents"], row["account_id"]))
    k.db.execute("""UPDATE budgets SET released_cents=released_cents+remaining_cents, remaining_cents=0, status='released'
        WHERE budget_id=?""", (budget_id,))
    return row["remaining_cents"]


def pay_order_from_budget(k, user_id, budget_id, service_id, deliver_date, plan_id=None):
    """从预算付款下单。价格只由代码读取服务目录。"""
    service = k.db.execute("SELECT * FROM services WHERE service_id=?", (service_id,)).fetchone()
    budget = k.db.execute("SELECT * FROM budgets WHERE budget_id=? AND user_id=?", (budget_id, user_id)).fetchone()
    if service is None:
        raise RuleError("not_found", "没有这个服务。")
    if budget is None or budget["status"] != "active" or budget["remaining_cents"] < service["price_cents"]:
        raise RuleError("insufficient_funds", "预算余额不足。")
    price = service["price_cents"]
    now = k.now()
    k.db.execute("""UPDATE budgets SET remaining_cents=remaining_cents-?, spent_cents=spent_cents+?,
        status=CASE WHEN remaining_cents-?=0 THEN 'exhausted' ELSE status END WHERE budget_id=?""", (price, price, price, budget_id))
    k.db.execute("UPDATE accounts SET reserved_cents=reserved_cents-?, balance_cents=balance_cents-? WHERE account_id=?",
                 (price, price, budget["account_id"]))
    order_id = new_id("ord")
    k.db.execute("INSERT INTO orders VALUES(?,?,?,?,?,?,?,?,'paid',?,?,?)",
                 (order_id, user_id, service_id, service["name"], price, budget_id, budget["account_id"], deliver_date,
                  iso(now), now.date().isoformat(), plan_id))
    k.db.execute("INSERT INTO transactions VALUES(?,?,?,?,?,?,?,?,?,?,?,0,?)",
                 (new_id("txn"), user_id, budget["account_id"], iso(now), service["name"], "购物", -price, "success",
                  None, "预算：" + budget["name"], None, order_id))
    return order_id, service["name"], price


def register(ops):
    for cls in (FreezeCard, UnfreezeCard, ReportLost, RestoreCard, SetCardLimit, ApplyVirtualCard, QuerySubscriptions,
                CancelSubscription, SubmitRiskAssessment, PurchaseProduct, RedeemProduct, ReserveBudget):
        ops.register(cls(ops))
