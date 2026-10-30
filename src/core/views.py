"""只读视图：首页、账户、卡片、产品、持仓、定时任务等（API_V2 第 3 节对象）。"""

import json
from datetime import datetime, timedelta

from .ops_more import aa_requests_for
from .seed import PRODUCT_DISCLAIMER
from .util import SHANGHAI, iso, parse_iso, yuan


def account(row):
    return {"account_id": row["account_id"], "name": row["name"], "masked_no": "**** " + row["tail"],
            "balance_cents": row["balance_cents"], "reserved_cents": row["reserved_cents"],
            "available_cents": row["balance_cents"] - row["reserved_cents"]}


def accounts(k, user_id):
    return [account(r) for r in k.db.execute("SELECT * FROM accounts WHERE user_id=? ORDER BY account_id", (user_id,))]


def card(k, row):
    today = k.now().date().isoformat()
    spent = -k.db.execute("""SELECT COALESCE(SUM(amount_cents),0) FROM transactions WHERE card_id=? AND amount_cents<0
        AND substr(time,1,10)=?""", (row["card_id"], today)).fetchone()[0]
    return {"card_id": row["card_id"], "name": row["name"], "kind": row["kind"], "masked_no": "**** " + row["tail"],
            "account_id": row["account_id"], "status": row["status"], "daily_limit_cents": row["daily_limit_cents"],
            "today_spent_cents": spent}


def cards(k, user_id):
    return [card(k, r) for r in k.db.execute("SELECT * FROM cards WHERE user_id=? ORDER BY created_at, card_id", (user_id,))]


def product(row, risk_level=None):
    data = {"product_id": row["product_id"], "name": row["name"], "type": row["type"], "risk_level": row["risk_level"],
            "term_days": row["term_days"], "liquidity": row["liquidity"], "yield_text": row["yield_text"],
            "min_amount_cents": row["min_amount_cents"], "description": row["description"]}
    return data


def products(k):
    return [product(r) for r in k.db.execute("SELECT * FROM products ORDER BY risk_level, term_days")], PRODUCT_DISCLAIMER


def risk_profile(k, user_id):
    user = k.user(user_id)
    if not user["risk_level"]:
        return None
    valid = parse_iso(user["risk_valid_until"]) > k.now()
    labels = {"C1": "保守型", "C2": "稳健型", "C3": "平衡型", "C4": "成长型", "C5": "进取型"}
    return {"level": user["risk_level"], "label": labels.get(user["risk_level"], ""), "score": user["risk_score"],
            "valid_until": user["risk_valid_until"], "max_product_risk": "R" + user["risk_level"][1:], "valid": valid,
            "assessed_at": user["risk_assessed_at"]}


def holdings(k, user_id):
    now = k.now()
    result = []
    for r in k.db.execute("""SELECT h.*, p.name FROM holdings h JOIN products p ON p.product_id=h.product_id
            WHERE h.user_id=? AND h.amount_cents>0 ORDER BY h.purchased_at""", (user_id,)):
        redeemable = r["amount_cents"] if parse_iso(r["matures_at"]) <= now else 0
        result.append({"holding_id": r["holding_id"], "product_id": r["product_id"], "name": r["name"],
                       "amount_cents": r["amount_cents"], "profit_cents": r["profit_cents"], "purchased_at": r["purchased_at"],
                       "matures_at": r["matures_at"], "redeemable_cents": redeemable})
    return result


def scheduled(k, user_id):
    items = []
    for r in k.db.execute("SELECT * FROM schedules WHERE user_id=? ORDER BY run_at", (user_id,)):
        items.append({"schedule_id": r["schedule_id"], "kind": r["kind"], "title": r["title"], "amount_cents": r["amount_cents"],
                      "run_at": r["run_at"], "repeat": r["repeat"], "status": r["status"], "plan_id": r["plan_id"]})
    for r in k.db.execute("SELECT * FROM transfers WHERE user_id=? AND status='in_transit' ORDER BY arrive_at", (user_id,)):
        items.append({"schedule_id": r["transfer_id"], "kind": "transfer", "title": f"延时到账 · {r['payee_name']}",
                      "amount_cents": r["amount_cents"], "run_at": r["arrive_at"], "repeat": "none", "status": "scheduled",
                      "revocable": True})
    return items


def insights(k, user_id):
    """首页主动提醒（SEED 第 12 节）。只给数量和提示，具体订阅名单仍需黄档确认。"""
    now = k.now()
    result = []
    for c in k.db.execute("SELECT * FROM contacts WHERE user_id=? AND birthday IS NOT NULL", (user_id,)):
        month, day = map(int, c["birthday"].split("-"))
        bday = datetime(now.year, month, day, tzinfo=SHANGHAI)
        if bday.date() < now.date():
            bday = bday.replace(year=now.year + 1)
        days = (bday.date() - now.date()).days
        if 0 <= days <= 30:
            aliases = json.loads(c["aliases"])
            planned = k.db.execute("SELECT 1 FROM plans WHERE user_id=? AND plan_json LIKE ? AND status NOT IN ('rolled_back','failed')",
                                   (user_id, '%' + c["contact_id"] + '%')).fetchone()
            result.append({"insight_id": f"ins-birthday-{c['contact_id']}", "kind": "birthday",
                           "title": f"{c['name']}（{c['relation'] if c['relation'] != '配偶' else '爱人'}）{month}-{day:02d} 生日，还有 {days} 天",
                           "body": "要不要帮你准备？锁定 ¥1,000.00 生日预算，生日前 2 天订好鲜花和蛋糕，一次确认整个计划。" if not planned else "生日筹备计划已创建，可以在计划里查看进度。",
                           "cta_label": "帮我准备" if not planned else "查看计划", "contact_id": c["contact_id"], "days_left": days})
    soon = k.db.execute("SELECT COUNT(*) FROM subscriptions WHERE user_id=? AND status='active' AND next_charge_date<=?",
                        (user_id, (now + timedelta(days=7)).date().isoformat())).fetchone()[0]
    if soon:
        result.append({"insight_id": "ins-renewal", "kind": "renewal", "title": f"有 {soon} 项订阅将在 7 天内续费",
                       "body": "查看具体名单需要你确认（订阅查询属于黄档）。", "cta_label": "查看订阅", "count": soon})
    findings = [f for f in k.analytics.anomalies(user_id, now) if f["severity"] in ("high", "medium")]
    if findings:
        high = sum(1 for f in findings if f["severity"] == "high")
        result.append({"insight_id": "ins-anomaly", "kind": "anomaly",
                       "title": f"发现 {len(findings)} 处可疑交易" + (f"（{high} 处高风险）" if high else ""),
                       "body": "包括凌晨境外大额消费、疑似重复扣款、小额试探扣款和可疑来账，建议尽快查看。", "cta_label": "查看异常",
                       "count": len(findings)})
    for s in k.db.execute("SELECT * FROM schedules WHERE user_id=? AND status='scheduled' AND kind='transfer' AND run_at<=?",
                          (user_id, iso(now + timedelta(days=3)))):
        params = json.loads(s["params_json"])
        if params.get("memo") == "房租":
            run_at = parse_iso(s["run_at"])
            result.append({"insight_id": "ins-rent-" + s["schedule_id"], "kind": "rent",
                           "title": f"{run_at.month:02d}-{run_at.day:02d} 将自动转出房租 {yuan(s['amount_cents'])}",
                           "body": f"收款人 {params.get('payee_name')}，执行前会再次检查余额。", "cta_label": "查看定时任务"})
    return result


def home(k, user_id):
    accts = accounts(k, user_id)
    total = sum(a["balance_cents"] for a in accts) + sum(h["amount_cents"] + h["profit_cents"] for h in holdings(k, user_id))
    return {"now": iso(k.now()), "total_assets_cents": total, "accounts": accts, "insights": insights(k, user_id),
            "quick_actions": [{"label": "本月账单", "prompt": "这个月花了多少钱？"},
                              {"label": "转账", "prompt": "给小王转200"},
                              {"label": "异常扣款", "prompt": "帮我看看有没有异常扣款"},
                              {"label": "我的卡", "prompt": "我有哪些卡"},
                              {"label": "理财", "prompt": "推荐点稳一点的理财，放半年"},
                              {"label": "自动扣费", "prompt": "我有哪些自动扣费"}],
            "notifications": k.notifications(user_id, 10),
            "aa_requests": [i for i in aa_requests_for(k, user_id) if i["direction"] == "incoming" and i["status"] == "open"]}
