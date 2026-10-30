"""v2 安全内核主体。

模型提议，代码裁决：
- 所有写操作只能经 propose() 生成待确认单；档位、累计、风险由代码计算。
- 黄档凭 confirm()（确认码绑定参数哈希、5 分钟、一次性）；红档凭 verify_strong()（交易密码 + 模拟短信动态码）。
- 业务修改与审计在同一事务；审计写失败即回滚。审计带哈希链。
- 失败熔断与可疑行为熔断写在库里，重启不清零。
"""

import hashlib
import hmac
import json
import os
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timedelta

from . import schema, seed as seed_module
from .util import (SHANGHAI, canonical, check_salted, human_datetime, iso, mask_phone, new_id,
                   numeric_code, parse_iso, plain_yuan, salted_hash, sha256_hex, yuan)

PENDING_TTL = timedelta(minutes=5)
LOCK_DURATION = timedelta(minutes=10)
MAX_FAILURES = 3
OTP_RESEND_SECONDS = 60
SMALL_LIMIT_CENTS = 100000  # 小额额度 ¥1,000：当日累计超过即红档
GENESIS_HASH = "0" * 64


class RuleError(Exception):
    """代码规则拒绝。message 给用户看；code 给前端/评测。"""

    def __init__(self, code, message, *, tier="refused", detail=None):
        super().__init__(message)
        self.code, self.message, self.tier, self.detail = code, message, tier, detail or {}


class NeedChoice(Exception):
    """参数有歧义：由代码给出选项，用户点选后继续。"""

    def __init__(self, prompt, field, items):
        super().__init__(prompt)
        self.prompt, self.field, self.items = prompt, field, items


class AuditFailure(Exception):
    pass


class Kernel:
    def __init__(self, db_path, *, real_clock=time.time, audit_fail_hook=None):
        self.db_path = str(db_path)
        self.real_clock = real_clock
        self.lock = threading.RLock()
        self.audit_fail_hook = audit_fail_hook  # 测试用：模拟审计写失败
        self.option_sets = {}  # ref -> {"user_id","intent","params","field","items","created"}
        self.questionnaires = {}
        self._open()
        from .ops import Operations  # 延迟导入，避免循环
        from .analytics import Analytics
        self.ops = Operations(self)
        self.analytics = Analytics(self)

    # ------------------------------------------------------------------ 库与时钟
    def _open(self):
        self.db = schema.connect(self.db_path)
        if self.db.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
            self.db.execute("BEGIN IMMEDIATE")
            try:
                seed_module.seed(self.db)
                self.db.execute("UPDATE meta SET value=? WHERE key='clock_anchor_real'", (repr(self.real_clock()),))
                self._audit_raw("system", None, None, "system", "none", "seed", "success", "按 rich 种子建库", "system", {})
                self.db.execute("COMMIT")
            except Exception:
                self.db.execute("ROLLBACK")
                raise

    def reset(self):
        """按 rich 种子重建演示库（仅演示模式）。"""
        with self.lock:
            self.db.close()
            if self.db_path != ":memory:":
                for suffix in ("", "-wal", "-shm"):
                    try:
                        os.remove(self.db_path + suffix)
                    except FileNotFoundError:
                        pass
            self.option_sets.clear()
            self.questionnaires.clear()
            self._open()

    def close(self):
        try:
            self.db.close()
        except Exception:
            pass

    def __del__(self):
        self.close()

    def _meta(self, key):
        row = self.db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row[0] if row else None

    def now(self):
        """模拟时间 = 锚点模拟时间 + 真实流逝时间。"""
        anchor_sim = parse_iso(self._meta("clock_anchor_sim"))
        anchor_real = float(self._meta("clock_anchor_real") or self.real_clock())
        elapsed = max(0.0, self.real_clock() - anchor_real)
        return (anchor_sim + timedelta(seconds=int(elapsed))).astimezone(SHANGHAI)

    def advance_clock(self, minutes=None, to=None):
        with self.lock:
            current = self.now()
            if to is not None:
                target = parse_iso(to)
                if target <= current:
                    raise RuleError("invalid_request", "只能把模拟时间往后调。")
            else:
                if type(minutes) is not int or not 0 < minutes <= 60 * 24 * 60:
                    raise RuleError("invalid_request", "快进分钟数需在 1 到 86400 之间。")
                target = current + timedelta(minutes=minutes)
            executed = []
            # 逐个事件推进：每个到期任务都在它自己的计划时间执行（例如 11-01 的房租不会被算到 11-10）
            for _ in range(500):
                nxt = self.ops.next_event_time(self.now(), target)
                if nxt is None:
                    break
                self._set_clock(nxt)
                executed.extend(self.tick())
            self._set_clock(target)
            with self.tx():
                self.audit("system", "demo_clock", "none", "advance_clock", "success",
                           f"模拟时间 {iso(current)} → {iso(target)}", actor="system")
            executed.extend(self.tick())
            return {"now": iso(self.now()), "executed": executed}

    def _set_clock(self, when):
        with self.tx():
            self.db.execute("UPDATE meta SET value=? WHERE key='clock_anchor_sim'", (iso(when),))
            self.db.execute("UPDATE meta SET value=? WHERE key='clock_anchor_real'", (repr(self.real_clock()),))

    @contextmanager
    def tx(self):
        """一次提交包含业务修改和审计；任何异常（含审计失败）整体回滚。"""
        with self.lock:
            if self.db.in_transaction:
                yield
                return
            self.db.execute("BEGIN IMMEDIATE")
            try:
                yield
                self.db.execute("COMMIT")
            except Exception:
                self.db.execute("ROLLBACK")
                raise

    # ------------------------------------------------------------------ 审计（只追加 + 哈希链）
    def audit(self, user_id, intent, tier, event, result, reason="", *, actor="user", params=None,
              turn_id=None, request_id=None):
        if not self.db.in_transaction:
            raise AuditFailure("审计必须与业务修改在同一事务")
        self._audit_raw(user_id, turn_id, request_id, intent, tier, event, result, reason, actor, params or {})

    def _audit_raw(self, user_id, turn_id, request_id, intent, tier, event, result, reason, actor, params):
        if self.audit_fail_hook is not None and self.audit_fail_hook(event):
            raise AuditFailure("模拟审计写入失败")
        safe = redact_params(params)
        prev = self.db.execute("SELECT hash FROM audit ORDER BY id DESC LIMIT 1").fetchone()
        prev_hash = prev[0] if prev else GENESIS_HASH
        record = {"time": iso(self.now()) if self._meta("clock_anchor_sim") else "", "user_id": user_id,
                  "turn_id": turn_id, "request_id": request_id, "intent": intent, "tier": tier,
                  "event": event, "result": result, "reason": reason, "actor": actor,
                  "params_redacted": canonical(safe)}
        digest = sha256_hex(prev_hash + canonical(record))
        try:
            self.db.execute("""INSERT INTO audit(time,user_id,turn_id,request_id,intent,tier,event,result,reason,
                actor,params_redacted,prev_hash,hash) VALUES(:time,:user_id,:turn_id,:request_id,:intent,:tier,
                :event,:result,:reason,:actor,:params_redacted,:prev_hash,:hash)""",
                            dict(record, prev_hash=prev_hash, hash=digest))
        except Exception as error:
            raise AuditFailure("审计写入失败") from error
        return digest

    def verify_chain(self):
        prev_hash, length, broken_at = GENESIS_HASH, 0, None
        for row in self.db.execute("SELECT * FROM audit ORDER BY id"):
            record = {k: row[k] for k in ("time", "user_id", "turn_id", "request_id", "intent", "tier", "event",
                                          "result", "reason", "actor", "params_redacted")}
            expected = sha256_hex(prev_hash + canonical(record))
            if row["prev_hash"] != prev_hash or row["hash"] != expected:
                broken_at = row["id"]
                break
            prev_hash, length = row["hash"], length + 1
        return {"verified": broken_at is None, "length": length, "head_hash": prev_hash, "broken_at": broken_at}

    def audit_events(self, user_id, limit=50):
        rows = self.db.execute("SELECT * FROM audit WHERE user_id=? ORDER BY id DESC LIMIT ?",
                               (user_id, max(1, min(200, limit)))).fetchall()
        events = [{"id": r["id"], "time": r["time"], "turn_id": r["turn_id"], "request_id": r["request_id"],
                   "intent": r["intent"], "tier": r["tier"], "event": r["event"], "result": r["result"],
                   "reason": r["reason"], "actor": r["actor"], "hash": r["hash"]} for r in rows]
        return {"events": events, "chain": self.verify_chain()}

    # ------------------------------------------------------------------ 熔断（持久化）
    def lock_state(self, user_id, scope):
        row = self.db.execute("SELECT failures,locked_until FROM lockouts WHERE user_id=? AND scope=?",
                              (user_id, scope)).fetchone()
        if not row:
            return 0, None
        until = parse_iso(row["locked_until"]) if row["locked_until"] else None
        if until is not None and until <= self.now():
            return 0, None
        return row["failures"], until

    def locked_until(self, user_id, scope):
        return self.lock_state(user_id, scope)[1]

    def _record_failure(self, user_id, scope):
        failures, until = self.lock_state(user_id, scope)
        if until is not None:
            return failures, until
        failures += 1
        locked = iso(self.now() + LOCK_DURATION) if failures >= MAX_FAILURES else None
        self.db.execute("""INSERT INTO lockouts(user_id,scope,failures,locked_until) VALUES(?,?,?,?)
            ON CONFLICT(user_id,scope) DO UPDATE SET failures=excluded.failures, locked_until=excluded.locked_until""",
                        (user_id, scope, 0 if locked else failures, locked))
        return failures, parse_iso(locked) if locked else None

    def _clear_failures(self, user_id, scope):
        self.db.execute("DELETE FROM lockouts WHERE user_id=? AND scope=?", (user_id, scope))

    def record_suspicious(self, user_id, kind, turn_id=None):
        """可疑行为熔断：10 分钟内 3 次被拦截的注入或套取 → 只读 10 分钟。"""
        with self.tx():
            now = self.now()
            self.db.execute("INSERT INTO suspicious_events(user_id,time,kind) VALUES(?,?,?)", (user_id, iso(now), kind))
            since = iso(now - timedelta(minutes=10))
            count = self.db.execute("SELECT COUNT(*) FROM suspicious_events WHERE user_id=? AND time>?",
                                    (user_id, since)).fetchone()[0]
            locked = None
            if count >= MAX_FAILURES and self.locked_until(user_id, "suspicious") is None:
                locked = now + LOCK_DURATION
                self.db.execute("""INSERT INTO lockouts(user_id,scope,failures,locked_until) VALUES(?,?,0,?)
                    ON CONFLICT(user_id,scope) DO UPDATE SET locked_until=excluded.locked_until""",
                                (user_id, "suspicious", iso(locked)))
                self._cancel_open_requests(user_id, "可疑行为熔断")
                self.notify(user_id, "risk_alert", "已切换为只读保护",
                            "10 分钟内多次出现可疑指令，本会话 10 分钟内只能查询。")
            self.audit(user_id, "guard", "none", "suspicious_input", "blocked", kind, turn_id=turn_id,
                       params={"count_10min": count, "read_only_until": iso(locked) if locked else None})
            return count, locked

    def read_only_until(self, user_id):
        return self.locked_until(user_id, "suspicious")

    # ------------------------------------------------------------------ 通知与模拟短信
    def notify(self, user_id, kind, title, body, ref=None):
        self.db.execute("INSERT INTO notifications VALUES(?,?,?,?,?,?,0,?)",
                        (new_id("n"), user_id, iso(self.now()), kind, title, body, ref))

    def notifications(self, user_id, limit=50):
        rows = self.db.execute("SELECT * FROM notifications WHERE user_id=? ORDER BY time DESC, rowid DESC LIMIT ?",
                               (user_id, limit)).fetchall()
        return [{"id": r["notification_id"], "time": r["time"], "kind": r["kind"], "title": r["title"],
                 "body": r["body"], "read": bool(r["read"]), "ref": r["ref"]} for r in rows]

    def sms_inbox(self, user_id):
        rows = self.db.execute("SELECT * FROM sms WHERE user_id=? ORDER BY received_at DESC, rowid DESC LIMIT 30",
                               (user_id,)).fetchall()
        return [{"id": r["sms_id"], "from": r["sender"], "text": r["text"], "received_at": r["received_at"]} for r in rows]

    # ------------------------------------------------------------------ 用户
    def user(self, user_id):
        row = self.db.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
        if row is None:
            raise RuleError("invalid_request", "未知的模拟用户。")
        return row

    def user_public(self, user_id):
        row = self.user(user_id)
        return {"user_id": row["user_id"], "display_name": row["display_name"], "masked_phone": mask_phone(row["phone"])}

    def users_public(self):
        return [{"user_id": r["user_id"], "display_name": r["display_name"]}
                for r in self.db.execute("SELECT user_id,display_name FROM users ORDER BY user_id")]

    # ------------------------------------------------------------------ 待确认单
    def _params_hash(self, user_id, intent, params):
        return sha256_hex(canonical({"user": user_id, "intent": intent, "params": params}))

    def _cancel_open_requests(self, user_id, reason, except_id=None):
        rows = self.db.execute("SELECT request_id,intent,tier FROM requests WHERE user_id=? AND status='pending'",
                               (user_id,)).fetchall()
        for row in rows:
            if row["request_id"] == except_id:
                continue
            self.db.execute("UPDATE requests SET status='voided' WHERE request_id=?", (row["request_id"],))
            self.audit(user_id, row["intent"], row["tier"], "pending_voided", "cancelled", reason,
                       request_id=row["request_id"])

    def _void_same_subject(self, user_id, intent, subject):
        """同一对象（如同一收款人）的旧待确认单作废：用户“改成300”时旧单失效。不同对象的单可以并存。"""
        for row in self.db.execute("SELECT * FROM requests WHERE user_id=? AND status='pending'", (user_id,)).fetchall():
            if row["intent"] != intent and not (row["plan_id"] and intent == "plan"):
                continue
            if self.ops.handler(row["intent"]).subject(json.loads(row["params_json"])) != subject:
                continue
            self.db.execute("UPDATE requests SET status='voided' WHERE request_id=?", (row["request_id"],))
            self.audit(user_id, row["intent"], row["tier"], "pending_voided", "cancelled", "同一对象生成了新的待确认单，旧单作废",
                       request_id=row["request_id"])

    def open_pendings(self, user_id):
        now = self.now()
        rows = self.db.execute("SELECT * FROM requests WHERE user_id=? AND status='pending' ORDER BY created_at", (user_id,)).fetchall()
        return [self._pending_view(r) for r in rows if parse_iso(r["expires_at"]) > now]

    def propose(self, user_id, intent, params, *, turn_id=None, provenance=None, actor="agent", plan_id=None):
        """生成待确认单。返回 {"status": "pending", "pending": view} 或抛 RuleError / NeedChoice。"""
        with self.lock:
            handler = self.ops.handler(intent)
            if self.read_only_until(user_id) is not None:
                raise RuleError("locked", "检测到多次可疑指令，本会话暂时只能查询（10 分钟后恢复）。")
            prepared = handler.prepare(user_id, dict(params))
            tier, tier_reason = handler.tier(user_id, prepared)
            risk = handler.risk(user_id, prepared) if hasattr(handler, "risk") else None
            if risk and risk.get("level") == "high" and tier == "yellow":
                tier, tier_reason = "red", tier_reason + "；反诈评分 ≥60，升为红档"
            if tier == "red":
                until = self.locked_until(user_id, "strong")
                if until is not None:
                    raise RuleError("locked", f"交易密码或动态码连续错误 3 次，红档操作已锁定至 {until:%H:%M}。")
            elif self.locked_until(user_id, "confirm") is not None:
                raise RuleError("locked", "确认码连续错误 3 次，确认操作暂时锁定 10 分钟。")
            view = handler.view(user_id, prepared, tier)
            now = self.now()
            request_id = new_id("req")
            params_hash = self._params_hash(user_id, intent, prepared)
            code = numeric_code(6) if tier == "yellow" else None
            code_hash, code_salt = salted_hash(code) if code else (None, None)
            not_before = None
            if risk and risk.get("level") == "high":
                not_before = iso(now + timedelta(seconds=30))
                risk["not_before"] = not_before
            with self.tx():
                self._void_same_subject(user_id, intent, handler.subject(prepared))
                self.db.execute("""INSERT INTO requests(request_id,user_id,intent,params_json,params_hash,tier,kind,
                    code_hash,code_salt,status,created_at,expires_at,view_json,risk_json,not_before,plan_id,turn_id,
                    provenance_json) VALUES(?,?,?,?,?,?,?,?,?,'pending',?,?,?,?,?,?,?,?)""",
                                (request_id, user_id, intent, canonical(prepared), params_hash, tier,
                                 "confirm" if tier == "yellow" else "strong_auth", code_hash, code_salt,
                                 iso(now), iso(now + PENDING_TTL), canonical(view), canonical(risk) if risk else None,
                                 not_before, plan_id, turn_id, canonical(provenance or {})))
                self.audit(user_id, intent, tier, "pending_created", "pending", tier_reason, actor=actor,
                           params=prepared, turn_id=turn_id, request_id=request_id)
            pending = self._pending_view(self.db.execute("SELECT * FROM requests WHERE request_id=?", (request_id,)).fetchone())
            if code:
                pending["confirmation_code"] = code
            return {"status": "pending", "pending": pending, "tier": tier, "tier_reason": tier_reason, "risk": risk}

    def _pending_view(self, row):
        view = json.loads(row["view_json"])
        risk = json.loads(row["risk_json"]) if row["risk_json"] else None
        result = {"request_id": row["request_id"], "kind": row["kind"], "tier": row["tier"], "intent": row["intent"],
                  "title": view["title"], "lines": view["lines"], "impact": view.get("impact", ""),
                  "risk": risk, "factors": ["pin", "sms_otp"] if row["tier"] == "red" else [],
                  "expires_at": row["expires_at"], "plan_id": row["plan_id"]}
        return result

    def pending_for(self, user_id):
        row = self.db.execute("SELECT * FROM requests WHERE user_id=? AND status='pending' ORDER BY created_at DESC LIMIT 1",
                              (user_id,)).fetchone()
        if row is None or parse_iso(row["expires_at"]) <= self.now():
            return None
        return self._pending_view(row)

    def _load_pending(self, user_id, request_id, kind):
        if type(request_id) is not str or not 1 <= len(request_id) <= 64:
            raise RuleError("invalid_request", "待确认单编号无效。")
        row = self.db.execute("SELECT * FROM requests WHERE request_id=? AND user_id=?", (request_id, user_id)).fetchone()
        if row is None:
            raise RuleError("invalid_request", "没有找到这张待确认单。")
        if row["status"] == "success":
            raise RuleError("duplicate", "这笔操作已经执行过了，不会重复执行。")
        if row["status"] != "pending":
            raise RuleError("expired", "这张待确认单已失效（已取消、已作废或已执行），请重新发起。")
        if parse_iso(row["expires_at"]) <= self.now():
            with self.tx():
                self.db.execute("UPDATE requests SET status='expired' WHERE request_id=?", (request_id,))
                self.audit(user_id, row["intent"], row["tier"], "pending_expired", "expired", "超过 5 分钟有效期",
                           request_id=request_id)
            raise RuleError("expired", "待确认单已超过 5 分钟有效期，请重新发起。")
        if row["kind"] != kind:
            raise RuleError("invalid_request", "这张单需要" + ("交易密码 + 动态码强验证" if row["kind"] == "strong_auth" else "点确认按钮") + "。")
        if row["params_hash"] != self._params_hash(user_id, row["intent"], json.loads(row["params_json"])):
            raise RuleError("invalid_request", "待确认单参数校验失败，已作废。")
        return row

    def _check_risk_gate(self, row, risk_acknowledged):
        if row["risk_json"]:
            risk = json.loads(row["risk_json"])
            if risk.get("require_ack") and risk_acknowledged is not True:
                raise RuleError("risk_ack_required", "这笔操作有风险提示，请先勾选“我已了解风险”。")
        if row["not_before"] and self.now() < parse_iso(row["not_before"]):
            raise RuleError("cooling_off", "冷静期还没结束，请稍等片刻再确认。", detail={"not_before": row["not_before"]})

    def confirm(self, user_id, request_id, confirmation_code, risk_acknowledged=None, turn_id=None):
        """黄档确认。确认码一次性、绑定参数哈希；连续 3 次错误锁 10 分钟（持久化）。"""
        with self.lock:
            until = self.locked_until(user_id, "confirm")
            if until is not None:
                raise RuleError("locked", f"确认码连续错误 3 次，已锁定至 {until:%H:%M}。")
            row = self._load_pending(user_id, request_id, "confirm")
            if type(confirmation_code) is not str or not check_salted(confirmation_code, row["code_hash"], row["code_salt"]):
                with self.tx():
                    failures, locked = self._record_failure(user_id, "confirm")
                    self.audit(user_id, row["intent"], row["tier"], "confirm_failed", "failed", "确认码不匹配",
                               request_id=request_id, turn_id=turn_id)
                if locked:
                    raise RuleError("locked", f"确认码连续错误 3 次，已锁定至 {locked:%H:%M}。")
                raise RuleError("confirm_failed", "确认码不匹配，未执行。请直接点确认按钮。")
            self._check_risk_gate(row, risk_acknowledged)
            return self._execute(user_id, row, "confirm", turn_id)

    def send_otp(self, user_id, request_id):
        with self.lock:
            row = self._load_pending(user_id, request_id, "strong_auth")
            now = self.now()
            if row["otp_sent_at"] and (now - parse_iso(row["otp_sent_at"])).total_seconds() < OTP_RESEND_SECONDS:
                wait = OTP_RESEND_SECONDS - int((now - parse_iso(row["otp_sent_at"])).total_seconds())
                raise RuleError("rate_limited", f"动态码已发送，{wait} 秒后才能重发。", detail={"resend_after_seconds": wait})
            user = self.user(user_id)
            code = numeric_code(6)
            code_hash, salt = salted_hash(code)
            handler = self.ops.handler(row["intent"])
            what = handler.sms_text(user_id, json.loads(row["params_json"]))
            with self.tx():
                self.db.execute("UPDATE otps SET used=1 WHERE request_id=? AND used=0", (request_id,))
                self.db.execute("INSERT INTO otps VALUES(?,?,?,?,?,?,?,?,0)",
                                (new_id("otp"), request_id, user_id, row["params_hash"], code_hash, salt,
                                 iso(now), iso(now + PENDING_TTL)))
                self.db.execute("UPDATE requests SET otp_sent_at=? WHERE request_id=?", (iso(now), request_id))
                # 动态码只进模拟手机收件箱，不进聊天、不给模型、不进日志。
                self.db.execute("INSERT INTO sms VALUES(?,?,?,?,?)",
                                (new_id("sms"), user_id, "模拟银行",
                                 f"【模拟银行】验证码 {code}，用于{what}，5 分钟内有效。请勿告诉任何人，银行不会索要验证码。",
                                 iso(now)))
                self.audit(user_id, row["intent"], row["tier"], "otp_sent", "success", "模拟短信已发送到绑定手机",
                           request_id=request_id, params={"masked_phone": mask_phone(user["phone"])})
            return {"status": "sent", "channel": "sim_sms", "masked_phone": mask_phone(user["phone"]),
                    "expires_at": iso(now + PENDING_TTL), "resend_after_seconds": OTP_RESEND_SECONDS}

    def verify_strong(self, user_id, request_id, pin, otp, risk_acknowledged=None, turn_id=None):
        """红档强验证：交易密码 + 动态码。任一错误计一次；连续 3 次锁 10 分钟；不提示哪一项错。"""
        with self.lock:
            until = self.locked_until(user_id, "strong")
            if until is not None:
                raise RuleError("locked", f"验证连续失败 3 次，红档操作已锁定至 {until:%H:%M}。")
            row = self._load_pending(user_id, request_id, "strong_auth")
            self._check_risk_gate(row, risk_acknowledged)
            user = self.user(user_id)
            pin_ok = (type(pin) is str and pin.isdigit() and len(pin) == 6 and hmac.compare_digest(
                hashlib.pbkdf2_hmac("sha256", pin.encode(), bytes.fromhex(user["pin_salt"]), user["pin_iterations"]).hex(),
                user["pin_hash"]))
            otp_row = self.db.execute("""SELECT * FROM otps WHERE request_id=? AND user_id=? AND used=0
                ORDER BY created_at DESC LIMIT 1""", (request_id, user_id)).fetchone()
            otp_ok = (otp_row is not None and type(otp) is str and otp.isdigit() and len(otp) == 6
                      and parse_iso(otp_row["expires_at"]) > self.now()
                      and otp_row["params_hash"] == row["params_hash"]
                      and check_salted(otp, otp_row["code_hash"], otp_row["code_salt"]))
            if not (pin_ok and otp_ok):
                with self.tx():
                    failures, locked = self._record_failure(user_id, "strong")
                    self.audit(user_id, row["intent"], row["tier"], "strong_auth_failed", "failed",
                               "交易密码或动态码不正确", request_id=request_id, turn_id=turn_id,
                               params={"consecutive_failures": failures if not locked else MAX_FAILURES})
                if locked:
                    raise RuleError("locked", f"验证连续失败 3 次，红档操作已锁定至 {locked:%H:%M}（10 分钟）。")
                if otp_row is None:
                    raise RuleError("auth_failed", "验证未通过：请先获取动态码，再输入交易密码和动态码。",
                                    detail={"remaining_attempts": MAX_FAILURES - failures})
                raise RuleError("auth_failed", f"交易密码或动态码不正确，未执行。还可以再试 {MAX_FAILURES - failures} 次。",
                                detail={"remaining_attempts": MAX_FAILURES - failures})
            with self.tx():
                self.db.execute("UPDATE otps SET used=1 WHERE otp_id=?", (otp_row["otp_id"],))
                self._clear_failures(user_id, "strong")
            return self._execute(user_id, row, "strong_auth", turn_id)

    def cancel(self, user_id, request_id, turn_id=None):
        with self.lock:
            row = self.db.execute("SELECT * FROM requests WHERE request_id=? AND user_id=?", (request_id, user_id)).fetchone()
            if row is None or row["status"] != "pending":
                raise RuleError("expired", "这张待确认单已失效，无需取消。")
            with self.tx():
                self.db.execute("UPDATE requests SET status='cancelled' WHERE request_id=?", (request_id,))
                self.audit(user_id, row["intent"], row["tier"], "pending_cancelled", "cancelled", "用户取消",
                           request_id=request_id, turn_id=turn_id, actor="user")
            if row["plan_id"]:
                self.ops.plan_cancelled(user_id, row["plan_id"])
            return {"status": "cancelled", "intent": row["intent"], "title": json.loads(row["view_json"])["title"]}

    def cancel_open(self, user_id, turn_id=None):
        """聊天里说“算了/不要了”：取消当前待确认单（降低风险的操作，直接生效）。"""
        pending = self.pending_for(user_id)
        if pending is None:
            return None
        return self.cancel(user_id, pending["request_id"], turn_id)

    def revise_arrival(self, user_id, request_id, arrival):
        with self.lock:
            if arrival not in ("instant", "delayed_2h", "delayed_24h"):
                raise RuleError("invalid_request", "到账方式只能是实时、2 小时后或 24 小时后。")
            row = self.db.execute("SELECT * FROM requests WHERE request_id=? AND user_id=?", (request_id, user_id)).fetchone()
            if row is None or row["status"] != "pending" or row["intent"] != "transfer":
                raise RuleError("expired", "这张待确认单已失效，请重新发起。")
            params = json.loads(row["params_json"])
            if params.get("run_at"):
                raise RuleError("invalid_request", "定时转账不支持修改到账方式。")
            params["arrival"] = arrival
            params["arrival_chosen"] = True
            provenance = json.loads(row["provenance_json"] or "{}")
            return self.propose(user_id, "transfer", params, turn_id=row["turn_id"], provenance=provenance, actor="user")

    def _execute(self, user_id, row, via, turn_id):
        """执行前复查（余额、归属、累计、授权、重复）；业务修改 + 成功审计同一事务。"""
        handler = self.ops.handler(row["intent"])
        params = json.loads(row["params_json"])
        try:
            with self.tx():
                current = self.db.execute("SELECT status FROM requests WHERE request_id=?", (row["request_id"],)).fetchone()
                if current["status"] != "pending":
                    raise RuleError("duplicate", "这笔操作已经处理过了，不会重复执行。")
                handler.prepare(user_id, dict(params), recheck=True)
                tier_now, reason_now = handler.tier(user_id, params)
                if row["tier"] == "yellow" and tier_now == "red":
                    raise RuleError("reauth_required", "执行前复查发现今日累计已超过小额额度，需要重新发起并完成强验证。")
                result = handler.execute(user_id, params, row)
                self.db.execute("UPDATE requests SET status='success', result_json=? WHERE request_id=?",
                                (canonical(result), row["request_id"]))
                digest = self._audit_raw(user_id, turn_id, row["request_id"], row["intent"], row["tier"], "executed",
                                         "success", result.get("audit_reason", "执行成功（" + ("确认按钮" if via == "confirm" else "交易密码 + 动态码") + "）"),
                                         "user", params)
                result["audit_hash"] = digest
        except RuleError as error:
            with self.tx():
                self.db.execute("UPDATE requests SET status='failed' WHERE request_id=? AND status='pending'", (row["request_id"],))
                self.audit(user_id, row["intent"], row["tier"], "execute_refused", "failed", error.message,
                           request_id=row["request_id"], turn_id=turn_id)
            raise
        result["request_id"] = row["request_id"]
        result["intent"] = row["intent"]
        result["tier"] = row["tier"]
        if row["plan_id"]:
            self.ops.plan_confirmed(user_id, row["plan_id"], result)
            self.tick()
        return result

    # ------------------------------------------------------------------ 绿档只读工具的审计
    def audit_read(self, user_id, intent, reason, turn_id=None, params=None):
        with self.tx():
            self.audit(user_id, intent, "green", "read", "success", reason, actor="agent", turn_id=turn_id, params=params)

    # ------------------------------------------------------------------ 调度器
    def tick(self):
        """执行到期的定时任务、延时到账、订阅扣费。返回本次产生的通知。"""
        with self.lock:
            return self.ops.run_due()

    # ------------------------------------------------------------------ 决策链
    def save_turn(self, user_id, turn_id, text, trace):
        with self.tx():
            from .util import redact_text
            self.db.execute("INSERT OR REPLACE INTO turns VALUES(?,?,?,?,?)",
                            (turn_id, user_id, iso(self.now()), redact_text(text), canonical(trace)))

    def turn(self, user_id, turn_id):
        row = self.db.execute("SELECT * FROM turns WHERE turn_id=? AND user_id=?", (turn_id, user_id)).fetchone()
        if row is None:
            raise RuleError("not_found", "没有找到这一轮对话的决策链。")
        return {"turn_id": turn_id, "time": row["time"], "trace": json.loads(row["trace_json"])}


SECRET_KEYS = {"pin", "otp", "confirmation_code", "code", "password", "api_key", "secret"}


def redact_params(params):
    """审计参数脱敏：去掉秘密字段、完整手机号、外部长文本截断。"""
    import re
    def clean(value, key=""):
        if key in SECRET_KEYS:
            return "[已隐藏]"
        if isinstance(value, dict):
            return {k: clean(v, k) for k, v in value.items() if k not in SECRET_KEYS}
        if isinstance(value, list):
            return [clean(v) for v in value[:30]]
        if isinstance(value, str):
            text = re.sub(r"1[3-9][0-9]{9}", lambda m: mask_phone(m.group(0)), value)
            return text[:120]
        return value
    return clean(params if isinstance(params, dict) else {})
