"""写操作处理器：参数校验（prepare）、代码判档（tier）、确认单展示（view）、执行（execute）。

每个处理器只接受代码解析后的规范化参数；所有归属、余额、累计都在这里复查。
"""

import json
from datetime import datetime, timedelta

from .kernel import SMALL_LIMIT_CENTS, NeedChoice, RuleError
from .util import (SHANGHAI, add_months, human_date, human_datetime, iso, mask_phone, new_id, parse_iso,
                   plain_yuan, yuan)

FRAUD_TERMS = ["安全账户", "公检法", "公安", "检察院", "法院", "涉嫌洗钱", "洗钱", "冻结", "解冻", "保证金", "刷单",
               "返利", "中奖", "客服退款", "退款客服", "理赔", "验证码给", "把验证码", "屏幕共享", "共享屏幕",
               "投资导师", "导师", "内幕", "高回报", "稳赚", "贷款手续费", "解冻费", "注销校园贷", "校园贷", "清空征信",
               "征信", "网上认识", "网友", "杀猪盘", "带单", "荐股"]
URGENCY_TERMS = ["马上", "立刻", "立即", "赶紧", "赶快", "快点", "不然就", "否则", "来不及", "今天之内", "十分钟内"]


def fraud_signals(texts):
    """从本次任务里的用户原话提取诈骗话术与催促用语（代码规则，不依赖模型）。"""
    joined = "\n".join(t for t in texts if isinstance(t, str))
    terms = [t for t in FRAUD_TERMS if t in joined]
    # “冻结/解冻”在卡片业务里是正常用语，只有和转账一起出现才计入
    urgent = [t for t in URGENCY_TERMS if t in joined]
    return {"fraud_terms": terms[:6], "urgency_terms": urgent[:4]}


class Handler:
    intent = ""

    def __init__(self, ops):
        self.ops, self.k = ops, ops.k

    @property
    def db(self):
        return self.k.db

    def sms_text(self, user_id, params):
        return self.view(user_id, params, "red")["title"]

    def subject(self, params):
        return self.intent


class TransferHandler(Handler):
    intent = "transfer"

    def subject(self, p):
        return "transfer:" + p.get("target_account_id", "")

    def prepare(self, user_id, p, recheck=False):
        db = self.db
        for key in ("source_account_id", "target_account_id", "payee_name", "amount_cents"):
            if key not in p:
                raise RuleError("invalid_request", "转账参数不完整。")
        amount = p["amount_cents"]
        if type(amount) is not int or amount <= 0:
            raise RuleError("invalid_amount", "转账金额必须是大于 0 的金额。")
        if amount > 20000000:
            raise RuleError("invalid_amount", "单笔转账超过 ¥200,000.00 的模拟上限，请分笔或到柜台办理。")
        source = db.execute("SELECT * FROM accounts WHERE account_id=?", (p["source_account_id"],)).fetchone()
        if source is None or source["user_id"] != user_id:
            raise RuleError("forbidden", "只能从你本人名下的账户转出。")
        target = p["target_account_id"]
        if target == p["source_account_id"]:
            raise RuleError("invalid_request", "收款账户和付款账户不能相同。")
        if db.execute("SELECT 1 FROM risk_list WHERE account_id=?", (target,)).fetchone():
            raise RuleError("risk_listed", "收款方在涉诈风险名单上，这笔转账已被拒绝。",
                            detail={"advice": "公检法和银行客服不会要求你把钱转到“安全账户”。如果有人这样要求，请立即挂断并拨打 96110 反诈专线（模拟提示）。"})
        own = db.execute("SELECT 1 FROM accounts WHERE account_id=? AND user_id=?", (target, user_id)).fetchone()
        if own:
            raise RuleError("invalid_request", "转给自己的账户请用“账户互转”。")
        contact = None
        if p.get("payee_contact_id"):
            contact = db.execute("SELECT * FROM contacts WHERE contact_id=? AND user_id=?",
                                 (p["payee_contact_id"], user_id)).fetchone()
            if contact is None or contact["account_id"] != target:
                raise RuleError("forbidden", "收款人不在你的联系人里。")
        elif p.get("via_phone"):
            entry = db.execute("SELECT * FROM phone_directory WHERE phone=?", (p["via_phone"],)).fetchone()
            if entry is None or entry["account_id"] != target:
                raise RuleError("not_found", "按这个手机号没有查到收款人。")
        else:
            raise RuleError("forbidden", "收款人必须是你的联系人或按手机号查到的收款人。")
        if p.get("arrival", "instant") not in ("instant", "delayed_2h", "delayed_24h"):
            raise RuleError("invalid_request", "到账方式无效。")
        if p.get("repeat", "none") not in ("none", "monthly"):
            raise RuleError("invalid_request", "周期只支持每月。")
        memo = p.get("memo") or ""
        if type(memo) is not str or len(memo) > 30:
            raise RuleError("invalid_request", "备注最多 30 个字。")
        if p.get("run_at"):
            run_at = parse_iso(p["run_at"])
            if not recheck and run_at <= self.k.now():
                raise RuleError("invalid_date", "定时转账的执行时间必须晚于现在。")
            if run_at > self.k.now() + timedelta(days=366):
                raise RuleError("invalid_date", "定时转账最多提前一年设置。")
        else:
            available = source["balance_cents"] - source["reserved_cents"]
            if amount > available:
                raise RuleError("insufficient_funds", f"余额不足：{source['name']}可用 {yuan(available)}，这笔需要 {yuan(amount)}。",
                                detail={"available_cents": available, "shortfall_cents": amount - available})
        return p

    def _day_total(self, user_id, day):
        return self.ops.daily_outgoing(user_id, day)

    def tier(self, user_id, p):
        amount = p["amount_cents"]
        if p.get("run_at"):
            day = parse_iso(p["run_at"]).date().isoformat()
            used = self._day_total(user_id, day) + self.ops.scheduled_outgoing(user_id, day, exclude=p.get("_schedule_id"))
            label = f"执行日 {day} 已排定 {yuan(used)} + 本笔 {yuan(amount)}"
        else:
            day = self.k.now().date().isoformat()
            used = self._day_total(user_id, day)
            label = f"今日累计 {yuan(used)} + 本笔 {yuan(amount)}"
        if used + amount > SMALL_LIMIT_CENTS:
            return "red", f"代码判档：红档（{label} > 小额额度 {yuan(SMALL_LIMIT_CENTS)}）"
        return "yellow", f"代码判档：黄档（{label} ≤ 小额额度 {yuan(SMALL_LIMIT_CENTS)}）"

    def risk(self, user_id, p):
        """反诈评分 0–100（PLAN 3.4）。收款方在风险名单已在 prepare 里直接拒绝。"""
        db, now = self.db, self.k.now()
        score, reasons = 0, []
        target, name = p["target_account_id"], p["payee_name"]
        previous = db.execute("SELECT COUNT(*) FROM transfers WHERE user_id=? AND target_account_id=? AND status!='revoked'",
                              (user_id, target)).fetchone()[0]
        history = db.execute("SELECT COUNT(*) FROM transactions WHERE user_id=? AND counterparty=? AND amount_cents<0",
                             (user_id, name)).fetchone()[0]
        if previous == 0 and history == 0:
            score += 25
            reasons.append("首次向该收款人转账")
        if p.get("via_phone") and not p.get("payee_contact_id"):
            score += 15
            reasons.append("通过手机号转给非联系人")
        since = iso(now - timedelta(days=90))
        amounts = sorted(-r[0] for r in db.execute(
            "SELECT amount_cents FROM transactions WHERE user_id=? AND time>? AND amount_cents<0 AND category IN ('转账给他人','住房缴费','人情红包') AND counterparty IS NOT NULL",
            (user_id, since)))
        if amounts:
            mid = len(amounts) // 2
            median = amounts[mid] if len(amounts) % 2 else (amounts[mid - 1] + amounts[mid]) // 2
            if p["amount_cents"] > 3 * median and p["amount_cents"] > 50000:
                score += 20
                reasons.append(f"金额高于你近 90 天转账中位数（{yuan(median)}）的 3 倍")
        signals = p.get("signals") or {}
        if signals.get("fraud_terms"):
            score += 30
            reasons.append("对话中出现“" + "”“".join(signals["fraud_terms"][:3]) + "”等诈骗常见话术")
        if signals.get("urgency_terms"):
            score += 10
            reasons.append("对话中有催促用语（“" + signals["urgency_terms"][0] + "”）")
        if 0 <= now.hour < 6:
            score += 10
            reasons.append("凌晨 00:00–05:59 发起")
        recent = db.execute("SELECT COUNT(*) FROM transfers WHERE user_id=? AND created_at>? AND status!='revoked'",
                            (user_id, iso(now - timedelta(minutes=10)))).fetchone()[0]
        if recent >= 2:
            score += 15
            reasons.append("10 分钟内第 3 笔及以上转账")
        score = min(100, score)
        p["risk_score"] = score
        if score < 30:
            return None
        level = "high" if score >= 60 else "medium"
        if signals.get("fraud_terms"):
            advice = "公检法和银行客服不会要求你转账到“安全账户”，网上的“导师”“刷单返利”多为诈骗。转账前请先打电话向本人核实。"
        else:
            advice = "请确认你认识这位收款人，并通过电话等方式核实过对方身份。"
        risk = {"level": level, "score": score, "reasons": reasons, "advice": advice, "require_ack": True,
                "not_before": None, "arrival_options": [] if p.get("run_at") else ["instant", "delayed_2h", "delayed_24h"]}
        if level == "high" and not p.get("run_at") and not p.get("arrival_chosen"):
            p["arrival"] = "delayed_24h"
        return risk

    def view(self, user_id, p, tier):
        db, now = self.db, self.k.now()
        source = db.execute("SELECT * FROM accounts WHERE account_id=?", (p["source_account_id"],)).fetchone()
        target = db.execute("SELECT * FROM accounts WHERE account_id=?", (p["target_account_id"],)).fetchone()
        display = p.get("payee_display") or p["payee_name"]
        lines = [{"label": "收款人", "value": f"{display} · 尾号{target['tail'] if target else '----'}"}]
        if p.get("via_phone"):
            lines.append({"label": "收款手机号", "value": mask_phone(p["via_phone"])})
        lines.append({"label": "金额", "value": yuan(p["amount_cents"]), "emphasis": True})
        available = source["balance_cents"] - source["reserved_cents"]
        lines.append({"label": "付款账户", "value": f"{source['name']} 尾号{source['tail']}（可用 {yuan(available)}）"})
        if p.get("run_at"):
            run_at = parse_iso(p["run_at"])
            when = human_datetime(run_at, now)
            if p.get("repeat") == "monthly":
                when = f"每月 {run_at.day} 日 {run_at:%H:%M}，首次 {when}"
            lines.append({"label": "执行时间", "value": when})
            day = run_at.date().isoformat()
            used = self._day_total(user_id, day) + self.ops.scheduled_outgoing(user_id, day)
            lines.append({"label": "执行日已排定转出", "value": f"{yuan(used)} + 本笔 / 小额额度 {yuan(SMALL_LIMIT_CENTS)}"})
            impact = f"确认后将于 {when} 执行，执行前会再次检查余额和限额。"
        else:
            arrival = p.get("arrival", "instant")
            arrival_text = {"instant": "实时到账", "delayed_2h": "2 小时后到账（到账前可撤回）",
                            "delayed_24h": "24 小时后到账（到账前可撤回）"}[arrival]
            lines.append({"label": "到账方式", "value": arrival_text})
            used = self._day_total(user_id, now.date().isoformat())
            lines.append({"label": "今日累计转出", "value": f"{yuan(used + p['amount_cents'])} / 小额额度 {yuan(SMALL_LIMIT_CENTS)}"})
            impact = "确认后立即转出。" if arrival == "instant" else "确认后资金先扣出进入“在途”，到账前你可以说“撤回刚才那笔”全额退回。"
        if p.get("memo"):
            lines.insert(-1, {"label": "备注", "value": p["memo"]})
        if tier == "red":
            impact += " 需要交易密码 + 短信动态码。"
        title = ("定时转账给 " if p.get("run_at") else "转账给 ") + display
        return {"title": title, "lines": lines, "impact": impact}

    def sms_text(self, user_id, p):
        prefix = "定时转账" if p.get("run_at") else "转账"
        return f"向 {p['payee_name']} {prefix} {plain_yuan(p['amount_cents'])} 元"

    def execute(self, user_id, p, request_row, actor="user"):
        if p.get("run_at"):
            schedule_id = new_id("sch")
            run_at = parse_iso(p["run_at"])
            title = f"{'每月' if p.get('repeat') == 'monthly' else '定时'}转账 · {p['payee_name']}"
            stored = {k: v for k, v in p.items() if k not in ("run_at",)}
            stored["day_of_month"] = run_at.day
            self.db.execute("INSERT INTO schedules VALUES(?,?,?,?,?,?,?,?,?,'scheduled',?,?,?,?,NULL)",
                            (schedule_id, user_id, "transfer", title, "transfer", json.dumps(stored, ensure_ascii=False),
                             p["amount_cents"], iso(run_at), p.get("repeat", "none"), request_row["tier"],
                             request_row["plan_id"], None, iso(self.k.now())))
            return {"status": "scheduled", "schedule_id": schedule_id,
                    "title": "定时转账已设置",
                    "lines": [{"label": "收款人", "value": p.get("payee_display") or p["payee_name"]},
                              {"label": "金额", "value": yuan(p["amount_cents"])},
                              {"label": "执行时间", "value": human_datetime(run_at, self.k.now())}] +
                             ([{"label": "备注", "value": p["memo"]}] if p.get("memo") else []),
                    "summary": f"已设置定时转账：{human_datetime(run_at)} 向 {p['payee_name']} 转 {yuan(p['amount_cents'])}"}
        return self.ops.move_money(user_id, p, request_id=request_row["request_id"], risk_score=p.get("risk_score", 0))


class Operations:
    def __init__(self, kernel):
        self.k = kernel
        self.handlers = {}
        for cls in [TransferHandler]:
            self.register(cls(self))
        from . import ops_more
        ops_more.register_all(self)

    def register(self, handler):
        self.handlers[handler.intent] = handler

    def handler(self, intent):
        handler = self.handlers.get(intent)
        if handler is None:
            raise RuleError("unknown_intent", "不支持的操作。")
        return handler

    @property
    def db(self):
        return self.k.db

    # ------------------------------------------------------------------ 累计
    def daily_outgoing(self, user_id, day):
        transfers = self.db.execute("""SELECT COALESCE(SUM(amount_cents),0) FROM transfers WHERE user_id=? AND shanghai_date=?
            AND status!='revoked'""", (user_id, day)).fetchone()[0]
        orders = self.db.execute("""SELECT COALESCE(SUM(amount_cents),0) FROM orders WHERE user_id=? AND shanghai_date=?
            AND status='paid'""", (user_id, day)).fetchone()[0]
        return transfers + orders

    def scheduled_outgoing(self, user_id, day, exclude=None):
        total = 0
        for row in self.db.execute("SELECT * FROM schedules WHERE user_id=? AND status='scheduled' AND kind IN ('transfer','order')",
                                   (user_id,)):
            if row["schedule_id"] == exclude:
                continue
            if parse_iso(row["run_at"]).date().isoformat() == day:
                total += row["amount_cents"]
        return total

    # ------------------------------------------------------------------ 资金移动
    def move_money(self, user_id, p, *, request_id=None, risk_score=0, actor="user", kind="transfer"):
        db, now = self.db, self.k.now()
        source = db.execute("SELECT * FROM accounts WHERE account_id=?", (p["source_account_id"],)).fetchone()
        amount = p["amount_cents"]
        if source["balance_cents"] - source["reserved_cents"] < amount:
            raise RuleError("insufficient_funds", f"余额不足：可用 {yuan(source['balance_cents'] - source['reserved_cents'])}。")
        arrival = p.get("arrival", "instant")
        arrive_at = now + {"instant": timedelta(0), "delayed_2h": timedelta(hours=2), "delayed_24h": timedelta(hours=24)}[arrival]
        status = "completed" if arrival == "instant" else "in_transit"
        transfer_id = new_id("tr")
        db.execute("UPDATE accounts SET balance_cents=balance_cents-? WHERE account_id=?", (amount, source["account_id"]))
        db.execute("INSERT INTO transfers VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   (transfer_id, user_id, source["account_id"], p["target_account_id"], p["payee_name"], amount,
                    p.get("memo") or "", kind, status, iso(now), iso(arrive_at), now.date().isoformat(), request_id, risk_score))
        db.execute("INSERT INTO transactions VALUES(?,?,?,?,?,?,?,?,?,?,?,0,?)",
                   (new_id("txn"), user_id, source["account_id"], iso(now), "转账给 " + p["payee_name"],
                    "转账给他人", -amount, "success" if status == "completed" else "in_transit", None,
                    p.get("memo") or None, p["payee_name"], transfer_id))
        if status == "completed":
            self._credit(transfer_id)
        balance = db.execute("SELECT balance_cents FROM accounts WHERE account_id=?", (source["account_id"],)).fetchone()[0]
        lines = [{"label": "收款人", "value": p.get("payee_display") or p["payee_name"]},
                 {"label": "金额", "value": yuan(amount)},
                 {"label": "付款账户余额", "value": yuan(balance)}]
        if p.get("memo"):
            lines.append({"label": "备注", "value": p["memo"]})
        if status == "in_transit":
            lines.append({"label": "预计到账", "value": human_datetime(arrive_at, now) + "（到账前可撤回）"})
        return {"status": "success" if status == "completed" else "scheduled", "transfer_id": transfer_id,
                "title": "转账成功" if status == "completed" else "已转出，等待延时到账",
                "lines": lines, "balance_cents": balance,
                "summary": (f"已向 {p['payee_name']} 转账 {yuan(amount)}" if status == "completed"
                            else f"{yuan(amount)} 已转出，将于 {arrive_at:%m-%d %H:%M} 到账 {p['payee_name']}，到账前可撤回")}

    def _credit(self, transfer_id):
        db, now = self.db, self.k.now()
        tr = db.execute("SELECT * FROM transfers WHERE transfer_id=?", (transfer_id,)).fetchone()
        target = db.execute("SELECT * FROM accounts WHERE account_id=?", (tr["target_account_id"],)).fetchone()
        db.execute("UPDATE transfers SET status='completed' WHERE transfer_id=?", (transfer_id,))
        db.execute("UPDATE transactions SET status='success' WHERE ref_id=? AND user_id=?", (transfer_id, tr["user_id"]))
        if target is not None and target["kind"] == "internal":
            sender = db.execute("SELECT display_name FROM users WHERE user_id=?", (tr["user_id"],)).fetchone()[0]
            db.execute("UPDATE accounts SET balance_cents=balance_cents+? WHERE account_id=?", (tr["amount_cents"], target["account_id"]))
            db.execute("INSERT INTO transactions VALUES(?,?,?,?,?,?,?,?,?,?,?,0,?)",
                       (new_id("txn"), target["user_id"], target["account_id"], iso(now), "收到转账 · " + sender, "转入",
                        tr["amount_cents"], "success", None, tr["memo"] or None, sender, transfer_id))
            self.k.notify(target["user_id"], "scheduled_executed", "收到转账",
                          f"{sender} 向你转账 {yuan(tr['amount_cents'])}" + (f"，备注“{tr['memo']}”" if tr["memo"] else ""))

    # ------------------------------------------------------------------ 调度器
    def next_event_time(self, after, until):
        """(after, until] 之间最早的一个到期事件时间；没有则 None。"""
        candidates = []
        row = self.db.execute("""SELECT MIN(run_at) FROM schedules WHERE status='scheduled' AND run_at>? AND run_at<=? AND (plan_id IS NULL OR
            plan_id NOT IN (SELECT plan_id FROM plans WHERE status IN ('paused','handed_over')))""", (iso(after), iso(until))).fetchone()
        if row[0]:
            candidates.append(parse_iso(row[0]))
        row = self.db.execute("SELECT MIN(arrive_at) FROM transfers WHERE status='in_transit' AND arrive_at>? AND arrive_at<=?",
                              (iso(after), iso(until))).fetchone()
        if row[0]:
            candidates.append(parse_iso(row[0]))
        for sub in self.db.execute("SELECT next_charge_date FROM subscriptions WHERE status='active' AND next_charge_date IS NOT NULL"):
            when = datetime.fromisoformat(sub[0]).replace(hour=6, minute=30, tzinfo=SHANGHAI)
            if after < when <= until:
                candidates.append(when)
        return min(candidates) if candidates else None

    def run_due(self):
        produced = []
        now = self.k.now()
        for _ in range(200):  # 防止异常数据导致死循环
            due = self.db.execute("""SELECT * FROM schedules WHERE status='scheduled' AND run_at<=? AND (plan_id IS NULL OR
                plan_id NOT IN (SELECT plan_id FROM plans WHERE status IN ('paused','handed_over'))) ORDER BY run_at LIMIT 1""",
                                  (iso(now),)).fetchone()
            if due is None:
                break
            produced.extend(self._run_schedule(due))
        for tr in self.db.execute("SELECT transfer_id,user_id,payee_name,amount_cents FROM transfers WHERE status='in_transit' AND arrive_at<=?",
                                  (iso(now),)).fetchall():
            with self.k.tx():
                self._credit(tr["transfer_id"])
                self.k.notify(tr["user_id"], "scheduled_executed", "延时转账已到账",
                              f"向 {tr['payee_name']} 转账的 {yuan(tr['amount_cents'])} 已到账。")
                self.k.audit(tr["user_id"], "transfer", "yellow", "delayed_arrival", "success", "延时到账完成",
                             actor="scheduler", params={"transfer_id": tr["transfer_id"]})
            produced.append(self.k.notifications(tr["user_id"], 1)[0])
        produced.extend(self._charge_subscriptions(now))
        for hook in getattr(self, "tick_hooks", []):
            produced.extend(hook(now))
        return produced

    def _run_schedule(self, row):
        user_id = row["user_id"]
        params = json.loads(row["params_json"])
        run_at = parse_iso(row["run_at"])
        produced = []
        if row["intent"] != "transfer":
            handler = self.handlers.get(row["intent"])
            if handler is not None and hasattr(handler, "run_scheduled"):
                return handler.run_scheduled(row, params)
            with self.k.tx():
                self.db.execute("UPDATE schedules SET status='failed', last_result='unsupported' WHERE schedule_id=?", (row["schedule_id"],))
            return produced
        handler = self.handlers["transfer"]
        p = dict(params)
        p.pop("day_of_month", None)
        day = run_at.date().isoformat()
        used = self.daily_outgoing(user_id, day)
        needs_red = used + row["amount_cents"] > SMALL_LIMIT_CENTS
        try:
            with self.k.tx():
                if needs_red and row["authorized_tier"] != "red":
                    self.db.execute("UPDATE schedules SET status='needs_reauth', last_result=? WHERE schedule_id=?",
                                    ("执行日累计超过小额额度，需重新授权", row["schedule_id"]))
                    self.k.notify(user_id, "scheduled_failed", "定时转账需要重新授权",
                                  f"{row['title']} {yuan(row['amount_cents'])}：执行日累计超过小额额度，为安全起见没有执行，请重新发起并完成强验证。")
                    self.k.audit(user_id, "transfer", row["authorized_tier"], "scheduled_needs_reauth", "blocked",
                                 "执行时重新判档为红档，超出授权档位", actor="scheduler", params={"schedule_id": row["schedule_id"]})
                else:
                    handler.prepare(user_id, dict(p), recheck=True)
                    result = self.move_money(user_id, dict(p, arrival="instant"), request_id=row["schedule_id"], actor="scheduler")
                    self.k.notify(user_id, "scheduled_executed", "定时转账已执行",
                                  f"{row['title']}：已转出 {yuan(row['amount_cents'])}，账户余额 {yuan(result['balance_cents'])}。")
                    self.k.audit(user_id, "transfer", row["authorized_tier"], "scheduled_executed", "success",
                                 "调度器到点执行（执行前复查余额与累计）", actor="scheduler",
                                 params={"schedule_id": row["schedule_id"], "amount_cents": row["amount_cents"]})
                    self._advance_or_finish(row, run_at)
        except RuleError as error:
            with self.k.tx():
                self.db.execute("UPDATE schedules SET status='failed', last_result=? WHERE schedule_id=?", (error.message, row["schedule_id"]))
                self.k.notify(user_id, "scheduled_failed", "定时转账执行失败", f"{row['title']}：{error.message}")
                self.k.audit(user_id, "transfer", row["authorized_tier"], "scheduled_failed", "failed", error.message,
                             actor="scheduler", params={"schedule_id": row["schedule_id"]})
                if row["repeat"] == "monthly":
                    self._advance_or_finish(row, run_at, keep_failed=True)
        produced.append(self.k.notifications(user_id, 1)[0])
        return produced

    def _advance_or_finish(self, row, run_at, keep_failed=False):
        if row["repeat"] == "monthly":
            params = json.loads(row["params_json"])
            y, m = add_months(run_at.year, run_at.month, 1)
            day = min(params.get("day_of_month", run_at.day), 28 if m == 2 else 30 if m in (4, 6, 9, 11) else 31)
            nxt = run_at.replace(year=y, month=m, day=day)
            if keep_failed:
                new_id_ = new_id("sch")
                self.db.execute("""INSERT INTO schedules SELECT ?,user_id,kind,title,intent,params_json,amount_cents,?,repeat,
                    'scheduled',authorized_tier,plan_id,node_id,created_at,NULL FROM schedules WHERE schedule_id=?""",
                                (new_id_, iso(nxt), row["schedule_id"]))
            else:
                self.db.execute("UPDATE schedules SET run_at=?, last_result='上次执行成功' WHERE schedule_id=?", (iso(nxt), row["schedule_id"]))
        else:
            self.db.execute("UPDATE schedules SET status='executed', last_result='执行成功' WHERE schedule_id=?", (row["schedule_id"],))

    def _charge_subscriptions(self, now):
        produced = []
        today = now.date().isoformat()
        rows = self.db.execute("SELECT * FROM subscriptions WHERE status='active' AND next_charge_date<=?", (today,)).fetchall()
        for sub in rows:
            charge_day = datetime.fromisoformat(sub["next_charge_date"]).replace(hour=6, minute=30, tzinfo=SHANGHAI)
            if charge_day > now:
                continue
            card = self.db.execute("SELECT * FROM cards WHERE card_id=?", (sub["card_id"],)).fetchone()
            account = self.db.execute("SELECT * FROM accounts WHERE account_id=?", (card["account_id"],)).fetchone()
            y, m = add_months(charge_day.year, charge_day.month, 1)
            nxt = charge_day.replace(year=y, month=m, day=min(sub["charge_day"], 28)).date().isoformat()
            with self.k.tx():
                if card["status"] != "active" or account["balance_cents"] - account["reserved_cents"] < sub["amount_cents"]:
                    self.k.notify(sub["user_id"], "scheduled_failed", f"{sub['name']} 扣费失败",
                                  "卡片不可用或余额不足，本期未扣费。")
                else:
                    self.db.execute("UPDATE accounts SET balance_cents=balance_cents-? WHERE account_id=?",
                                    (sub["amount_cents"], account["account_id"]))
                    self.db.execute("INSERT INTO transactions VALUES(?,?,?,?,?,?,?,?,?,?,?,0,?)",
                                    (new_id("txn"), sub["user_id"], account["account_id"], iso(charge_day), sub["merchant"],
                                     "订阅会员", -sub["amount_cents"], "success", card["card_id"], None, None, sub["subscription_id"]))
                    self.k.notify(sub["user_id"], "scheduled_executed", f"{sub['name']} 已自动续费",
                                  f"扣费 {yuan(sub['amount_cents'])}，下次扣费 {nxt}。")
                self.db.execute("UPDATE subscriptions SET next_charge_date=? WHERE subscription_id=?", (nxt, sub["subscription_id"]))
                self.k.audit(sub["user_id"], "subscription_charge", "none", "subscription_charge", "success",
                             sub["name"], actor="scheduler")
            produced.append(self.k.notifications(sub["user_id"], 1)[0])
        return produced

    # 计划引擎钩子（A8 实现）
    def plan_confirmed(self, user_id, plan_id, result):
        pass

    def plan_cancelled(self, user_id, plan_id):
        pass
