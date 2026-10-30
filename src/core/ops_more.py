"""其余写操作处理器。每个处理器：prepare（校验 + 归属）→ tier（代码判档）→ view（确认单）→ execute（执行）。"""

import json
from datetime import timedelta

from .kernel import SMALL_LIMIT_CENTS, RuleError
from .ops import Handler
from .util import human_datetime, iso, mask_name, new_id, parse_iso, plain_yuan, yuan


def _account(db, account_id):
    return db.execute("SELECT * FROM accounts WHERE account_id=?", (account_id,)).fetchone()


# ---------------------------------------------------------------------------------------------- 本人账户互转
class MoveFundsHandler(Handler):
    """本人名下账户之间转账（例如从储蓄账户转入活期）。本人资金，不计入当日对外累计；黄档确认。"""
    intent = "move_funds"

    def subject(self, p):
        return "move:" + p.get("source_account_id", "") + ">" + p.get("target_account_id", "")

    def prepare(self, user_id, p, recheck=False):
        source, target = _account(self.db, p.get("source_account_id")), _account(self.db, p.get("target_account_id"))
        if source is None or target is None or source["user_id"] != user_id or target["user_id"] != user_id:
            raise RuleError("forbidden", "账户互转只能在你本人名下的账户之间进行。")
        if source["account_id"] == target["account_id"]:
            raise RuleError("invalid_request", "转出和转入账户不能相同。")
        amount = p.get("amount_cents")
        if type(amount) is not int or amount <= 0:
            raise RuleError("invalid_amount", "金额必须大于 0。")
        if source["balance_cents"] - source["reserved_cents"] < amount:
            raise RuleError("insufficient_funds", f"{source['name']}可用余额不足（可用 {yuan(source['balance_cents'] - source['reserved_cents'])}）。")
        return p

    def tier(self, user_id, p):
        return "yellow", "代码判档：黄档（本人账户互转，不计入当日对外转账累计）"

    def view(self, user_id, p, tier):
        s, t = _account(self.db, p["source_account_id"]), _account(self.db, p["target_account_id"])
        return {"title": f"从{s['name']}转入{t['name']}",
                "lines": [{"label": "转出账户", "value": f"{s['name']} 尾号{s['tail']}（可用 {yuan(s['balance_cents'] - s['reserved_cents'])}）"},
                          {"label": "转入账户", "value": f"{t['name']} 尾号{t['tail']}"},
                          {"label": "金额", "value": yuan(p["amount_cents"]), "emphasis": True}],
                "impact": "本人账户之间转账，确认后实时到账。" + (f" 之后可以继续：{p['then']}" if p.get("then") else "")}

    def execute(self, user_id, p, request_row):
        db, now = self.db, self.k.now()
        s, t = _account(db, p["source_account_id"]), _account(db, p["target_account_id"])
        db.execute("UPDATE accounts SET balance_cents=balance_cents-? WHERE account_id=?", (p["amount_cents"], s["account_id"]))
        db.execute("UPDATE accounts SET balance_cents=balance_cents+? WHERE account_id=?", (p["amount_cents"], t["account_id"]))
        ref = new_id("mv")
        for account, amount, merchant in ((s, -p["amount_cents"], "转出至" + t["name"]), (t, p["amount_cents"], "转入自" + s["name"])):
            db.execute("INSERT INTO transactions VALUES(?,?,?,?,?,?,?,?,?,?,?,0,?)",
                       (new_id("txn"), user_id, account["account_id"], iso(now), merchant, "账户互转", amount, "success",
                        None, None, None, ref))
        balance = _account(db, t["account_id"])["balance_cents"]
        return {"status": "success", "title": "账户互转成功",
                "lines": [{"label": "金额", "value": yuan(p["amount_cents"])},
                          {"label": t["name"] + "余额", "value": yuan(balance)}],
                "summary": f"已从{s['name']}转入{t['name']} {yuan(p['amount_cents'])}" + (f"，现在可以继续：{p['then']}" if p.get("then") else "")}


# ---------------------------------------------------------------------------------------------- 撤回延时到账
class RevokeTransferHandler(Handler):
    intent = "revoke_transfer"

    def subject(self, p):
        return "revoke:" + p.get("transfer_id", "")

    def _row(self, user_id, p):
        row = self.db.execute("SELECT * FROM transfers WHERE transfer_id=? AND user_id=?", (p.get("transfer_id"), user_id)).fetchone()
        if row is None:
            raise RuleError("not_found", "没有找到这笔转账。")
        if row["status"] != "in_transit":
            raise RuleError("invalid_request", "这笔转账已经到账（或已撤回），不能再撤回。")
        if parse_iso(row["arrive_at"]) <= self.k.now():
            raise RuleError("invalid_request", "这笔转账已经到了到账时间，不能再撤回。")
        return row

    def prepare(self, user_id, p, recheck=False):
        self._row(user_id, p)
        return p

    def tier(self, user_id, p):
        return "yellow", "代码判档：黄档（撤回在途转账，资金退回本人账户）"

    def view(self, user_id, p, tier):
        row = self._row(user_id, p)
        return {"title": f"撤回给 {row['payee_name']} 的延时转账",
                "lines": [{"label": "收款人", "value": row["payee_name"]},
                          {"label": "金额", "value": yuan(row["amount_cents"]), "emphasis": True},
                          {"label": "原定到账", "value": human_datetime(parse_iso(row["arrive_at"]), self.k.now())}],
                "impact": "确认后全额退回付款账户，对方不会收到这笔钱。"}

    def execute(self, user_id, p, request_row):
        row = self._row(user_id, p)
        db = self.db
        db.execute("UPDATE transfers SET status='revoked' WHERE transfer_id=?", (row["transfer_id"],))
        db.execute("UPDATE accounts SET balance_cents=balance_cents+? WHERE account_id=?", (row["amount_cents"], row["source_account_id"]))
        db.execute("UPDATE transactions SET status='revoked' WHERE ref_id=? AND user_id=?", (row["transfer_id"], user_id))
        balance = _account(db, row["source_account_id"])["balance_cents"]
        return {"status": "success", "title": "已撤回，资金已退回",
                "lines": [{"label": "退回金额", "value": yuan(row["amount_cents"])}, {"label": "账户余额", "value": yuan(balance)}],
                "summary": f"已撤回给 {row['payee_name']} 的 {yuan(row['amount_cents'])}，资金已全额退回"}


# ---------------------------------------------------------------------------------------------- AA 收款
class AACollectHandler(Handler):
    """发起 AA 收款：只是向对方发收款请求，不动资金；黄档确认。人均金额由代码计算。"""
    intent = "aa_collect"

    def subject(self, p):
        return "aa:" + str(p.get("total_cents"))

    def prepare(self, user_id, p, recheck=False):
        total, ids = p.get("total_cents"), p.get("contact_ids") or []
        if type(total) is not int or total <= 0 or total > 10000000:
            raise RuleError("invalid_amount", "AA 总金额需要在 ¥0.01 到 ¥100,000.00 之间。")
        if not 1 <= len(ids) <= 10 or len(set(ids)) != len(ids):
            raise RuleError("invalid_request", "请告诉我和谁 AA（1 到 10 人）。")
        for cid in ids:
            if not self.db.execute("SELECT 1 FROM contacts WHERE contact_id=? AND user_id=?", (cid, user_id)).fetchone():
                raise RuleError("forbidden", "AA 对象必须是你的联系人。")
        people = len(ids) + (1 if p.get("include_self", True) else 0)
        p["per_person_cents"] = total // people
        if p["per_person_cents"] <= 0:
            raise RuleError("invalid_amount", "人均金额太小了。")
        return p

    def tier(self, user_id, p):
        return "yellow", "代码判档：黄档（发起 AA 收款，不动资金）"

    def _names(self, user_id, ids):
        return [self.db.execute("SELECT name FROM contacts WHERE contact_id=?", (cid,)).fetchone()[0] for cid in ids]

    def view(self, user_id, p, tier):
        names = self._names(user_id, p["contact_ids"])
        people = len(names) + (1 if p.get("include_self", True) else 0)
        remainder = p["total_cents"] - p["per_person_cents"] * people
        lines = [{"label": "总金额", "value": yuan(p["total_cents"])},
                 {"label": "人数", "value": f"{people} 人（含你自己）" if p.get("include_self", True) else f"{people} 人"},
                 {"label": "每人应付", "value": yuan(p["per_person_cents"]), "emphasis": True},
                 {"label": "向谁收款", "value": "、".join(names)}]
        if p.get("memo"):
            lines.append({"label": "备注", "value": p["memo"]})
        if remainder:
            lines.append({"label": "零头", "value": f"{yuan(remainder)} 由你承担"})
        return {"title": f"发起 AA 收款 · 每人 {yuan(p['per_person_cents'])}", "lines": lines,
                "impact": "确认后会给对方发收款请求，对方同意后才付款；不会从任何人账户直接扣钱。"}

    def execute(self, user_id, p, request_row):
        db, now = self.db, self.k.now()
        batch = new_id("aa")
        sender = self.k.user(user_id)["display_name"]
        items = []
        for cid in p["contact_ids"]:
            contact = db.execute("SELECT * FROM contacts WHERE contact_id=?", (cid,)).fetchone()
            target = _account(db, contact["account_id"])
            payer_user = target["user_id"] if target and target["kind"] == "internal" else None
            aa_id = new_id("aar")
            db.execute("INSERT INTO aa_requests VALUES(?,?,?,?,?,?,?,?,'open',?,NULL)",
                       (aa_id, batch, user_id, cid, contact["name"], payer_user, p["per_person_cents"], p.get("memo") or "AA",
                        iso(now)))
            if payer_user:
                self.k.notify(payer_user, "aa_request", f"{sender} 向你发起 AA 收款",
                              f"{p.get('memo') or 'AA'}：每人 {yuan(p['per_person_cents'])}。在“小安”里说“付一下AA”或点通知即可付款。", ref=aa_id)
            items.append({"request_id": aa_id, "from_name": sender, "payer_name": contact["name"], "amount_cents": p["per_person_cents"],
                          "memo": p.get("memo") or "AA", "status": "open"})
        return {"status": "success", "title": "AA 收款已发起",
                "lines": [{"label": "每人应付", "value": yuan(p["per_person_cents"])},
                          {"label": "已通知", "value": "、".join(i["payer_name"] for i in items)}],
                "blocks": [{"type": "aa_request", "data": i} for i in items],
                "summary": f"已向 {'、'.join(i['payer_name'] for i in items)} 发起 AA 收款，每人 {yuan(p['per_person_cents'])}"}


class AAPayHandler(Handler):
    """支付别人发起的 AA：本质是一笔转账，计入当日累计，按累计判档。"""
    intent = "aa_pay"

    def subject(self, p):
        return "aapay:" + p.get("aa_id", "")

    def _row(self, user_id, p):
        row = self.db.execute("SELECT * FROM aa_requests WHERE aa_id=? AND payer_user=?", (p.get("aa_id"), user_id)).fetchone()
        if row is None:
            raise RuleError("not_found", "没有找到发给你的这笔 AA 收款。")
        if row["status"] != "open":
            raise RuleError("invalid_request", "这笔 AA 已经处理过了。")
        return row

    def prepare(self, user_id, p, recheck=False):
        row = self._row(user_id, p)
        source = _account(self.db, user_id + "-main")
        if source["balance_cents"] - source["reserved_cents"] < row["amount_cents"]:
            raise RuleError("insufficient_funds", "余额不足，无法支付这笔 AA。")
        return p

    def tier(self, user_id, p):
        row = self._row(user_id, p)
        used = self.ops.daily_outgoing(user_id, self.k.now().date().isoformat())
        if used + row["amount_cents"] > SMALL_LIMIT_CENTS:
            return "red", f"代码判档：红档（今日累计 {yuan(used)} + 本笔 {yuan(row['amount_cents'])} > 小额额度）"
        return "yellow", f"代码判档：黄档（今日累计 {yuan(used)} + 本笔 {yuan(row['amount_cents'])} ≤ 小额额度）"

    def view(self, user_id, p, tier):
        row = self._row(user_id, p)
        initiator = self.k.user(row["from_user"])["display_name"]
        return {"title": f"支付 {initiator} 的 AA", "lines": [
            {"label": "收款人", "value": initiator}, {"label": "金额", "value": yuan(row["amount_cents"]), "emphasis": True},
            {"label": "备注", "value": row["memo"]}], "impact": "确认后立即转给对方。"}

    def sms_text(self, user_id, p):
        row = self._row(user_id, p)
        return f"向 {self.k.user(row['from_user'])['display_name']} 支付 AA {plain_yuan(row['amount_cents'])} 元"

    def execute(self, user_id, p, request_row):
        row = self._row(user_id, p)
        initiator = self.k.user(row["from_user"])
        params = {"source_account_id": user_id + "-main", "target_account_id": row["from_user"] + "-main",
                  "payee_name": initiator["display_name"], "amount_cents": row["amount_cents"], "memo": "AA·" + row["memo"][:20]}
        result = self.ops.move_money(user_id, params, request_id=request_row["request_id"], kind="aa_pay")
        self.db.execute("UPDATE aa_requests SET status='paid', paid_at=? WHERE aa_id=?", (iso(self.k.now()), row["aa_id"]))
        self.k.notify(row["from_user"], "aa_request", "AA 已收到", f"{self.k.user(user_id)['display_name']} 已支付 {yuan(row['amount_cents'])}（{row['memo']}）")
        result["title"] = "AA 已支付"
        result["summary"] = f"已向 {initiator['display_name']} 支付 AA {yuan(row['amount_cents'])}"
        return result


class CancelScheduledHandler(Handler):
    intent = "cancel_scheduled"

    def subject(self, p):
        return "sched:" + p.get("schedule_id", "")

    def _row(self, user_id, p):
        row = self.db.execute("SELECT * FROM schedules WHERE schedule_id=? AND user_id=?", (p.get("schedule_id"), user_id)).fetchone()
        if row is None or row["status"] not in ("scheduled", "needs_reauth"):
            raise RuleError("not_found", "没有找到可以取消的定时任务。")
        return row

    def prepare(self, user_id, p, recheck=False):
        self._row(user_id, p)
        return p

    def tier(self, user_id, p):
        return "yellow", "代码判档：黄档（取消定时任务）"

    def view(self, user_id, p, tier):
        row = self._row(user_id, p)
        return {"title": f"取消定时任务 · {row['title']}",
                "lines": [{"label": "任务", "value": row["title"]}, {"label": "金额", "value": yuan(row["amount_cents"])},
                          {"label": "下次执行", "value": human_datetime(parse_iso(row["run_at"]), self.k.now())},
                          {"label": "周期", "value": {"none": "一次", "monthly": "每月", "weekly": "每周"}[row["repeat"]]}],
                "impact": "确认后这个定时任务不再执行（之前已执行的不受影响）。"}

    def execute(self, user_id, p, request_row):
        row = self._row(user_id, p)
        self.db.execute("UPDATE schedules SET status='cancelled', last_result='用户取消' WHERE schedule_id=?", (row["schedule_id"],))
        return {"status": "success", "title": "定时任务已取消", "lines": [{"label": "任务", "value": row["title"]}],
                "summary": f"已取消定时任务：{row['title']}"}


def decline_aa(kernel, user_id, aa_id, turn_id=None):
    """拒绝别人发来的 AA：不动资金，直接生效并审计。"""
    with kernel.tx():
        row = kernel.db.execute("SELECT * FROM aa_requests WHERE aa_id=? AND payer_user=? AND status='open'", (aa_id, user_id)).fetchone()
        if row is None:
            raise RuleError("not_found", "没有找到待处理的这笔 AA。")
        kernel.db.execute("UPDATE aa_requests SET status='declined' WHERE aa_id=?", (aa_id,))
        kernel.notify(row["from_user"], "aa_request", "AA 被婉拒", f"{kernel.user(user_id)['display_name']} 婉拒了 {yuan(row['amount_cents'])} 的 AA（{row['memo']}）", ref=aa_id)
        kernel.audit(user_id, "aa_decline", "green", "aa_declined", "success", "用户婉拒 AA（不动资金）", turn_id=turn_id, params={"aa_id": aa_id})
    return row


def aa_requests_for(kernel, user_id):
    rows = kernel.db.execute("""SELECT * FROM aa_requests WHERE from_user=? OR payer_user=? ORDER BY created_at DESC LIMIT 30""",
                             (user_id, user_id)).fetchall()
    result = []
    for r in rows:
        initiator = kernel.user(r["from_user"])["display_name"]
        result.append({"request_id": r["aa_id"], "from_name": initiator, "payer_name": r["payer_name"],
                       "amount_cents": r["amount_cents"], "memo": r["memo"], "status": r["status"],
                       "direction": "incoming" if r["payer_user"] == user_id else "outgoing"})
    return result


def register_all(ops):
    ops.tick_hooks = []
    for cls in (MoveFundsHandler, RevokeTransferHandler, AACollectHandler, AAPayHandler, CancelScheduledHandler):
        ops.register(cls(ops))
    from . import ops_cards
    ops_cards.register(ops)
