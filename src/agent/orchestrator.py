"""编排循环：输入守卫 → 模型工具调用（≤6 步）→ 代码执行工具 → 事实校验 → TurnResponse。

所有聊天、确认、强验证、取消、点选都返回 API_V2 的 TurnResponse。
"""

import json
import threading
import time
from datetime import timedelta

from ..core.kernel import NeedChoice, RuleError
from ..core.util import iso, new_id, parse_iso, redact_text, yuan
from . import factcheck, guard, tools
from .llm import ModelUnavailable
from .prompts import build_system

MAX_STEPS = 6
HISTORY_LIMIT = 12
TASK_TEXT_LIMIT = 4
DEFAULT_SUGGESTIONS = ["这个月花了多少钱？", "帮我看看有没有异常扣款", "我有哪些卡", "给小王转200"]


class Agent:
    def __init__(self, kernel, llm):
        self.kernel = kernel
        self.llm = llm
        self.memory = {}
        self.user_locks = {}
        self._guard = threading.Lock()

    def user_lock(self, user_id):
        with self._guard:
            return self.user_locks.setdefault(user_id, threading.Lock())

    def reset_memory(self):
        self.memory.clear()

    def _mem(self, user_id):
        return self.memory.setdefault(user_id, {"history": [], "task": []})

    def _task_texts(self, user_id, text=None):
        mem = self._mem(user_id)
        now = self.kernel.now()
        mem["task"] = [(t, at) for t, at in mem["task"] if now - at <= timedelta(minutes=15)][-TASK_TEXT_LIMIT:]
        if text is not None:
            mem["task"].append((text, now))
            mem["task"] = mem["task"][-TASK_TEXT_LIMIT:]
        return [t for t, _ in mem["task"]]

    def end_task(self, user_id):
        self._mem(user_id)["task"] = []

    def _remember(self, user_id, text, reply, note=""):
        mem = self._mem(user_id)
        mem["history"].append({"role": "user", "content": text})
        mem["history"].append({"role": "assistant", "content": reply + (f"\n（系统记录：{note}）" if note else "")})
        mem["history"] = mem["history"][-HISTORY_LIMIT:]

    # ------------------------------------------------------------------ 响应
    def response(self, turn_id, text, blocks=None, pending=None, plan=None, suggestions=None, trace=None,
                 guard_input="pass", fact_check="pass", error=None, user_id=None):
        locked = None
        if user_id:
            until = self.kernel.read_only_until(user_id) or self.kernel.locked_until(user_id, "strong")
            locked = iso(until) if until else None
        return {"turn_id": turn_id, "assistant": {"text": text, "blocks": blocks or []}, "pending": pending, "plan": plan,
                "suggestions": suggestions if suggestions is not None else [], "trace": trace or [],
                "guard": {"input": guard_input, "fact_check": fact_check, "locked_until": locked}, "error": error}

    def _finish(self, user_id, turn_id, text_in, resp):
        try:
            self.kernel.save_turn(user_id, turn_id, text_in, resp["trace"])
        except Exception:
            pass
        return resp

    # ------------------------------------------------------------------ 聊天
    def chat(self, user_id, text):
        with self.user_lock(user_id):
            return self._chat(user_id, text)

    def _chat(self, user_id, text):
        turn_id = new_id("t")
        started = time.monotonic()
        self.kernel.tick()
        trace = []
        verdict = guard.check_input(text)
        if verdict["verdict"] == "blocked":
            count, locked = self.kernel.record_suspicious(user_id, verdict["category"] + ":" + verdict["rule"], turn_id)
            trace.append(tools.step("guard", f"输入守卫拦截：{verdict['rule']}（不调用模型；10 分钟内第 {count} 次）", "blocked",
                                    {"category": verdict["category"], "rule": verdict["rule"]}))
            reply = verdict["reply"]
            blocks = []
            if locked:
                reply += " 由于 10 分钟内多次出现可疑指令，本会话已切换为只读保护 10 分钟。"
                blocks.append({"type": "note", "data": {"text": "已切换为只读保护：10 分钟内只能查询，不能办理转账等操作。", "tone": "danger"}})
            self._remember(user_id, text, reply, "输入守卫拦截")
            return self._finish(user_id, turn_id, text, self.response(turn_id, reply, blocks, trace=trace, guard_input="blocked",
                                                                      suggestions=["查询余额", "这个月花了多少钱？"], user_id=user_id))
        trace.append(tools.step("guard", "输入守卫：未发现注入或信息套取", "pass"))
        pendings = self.kernel.open_pendings(user_id)
        if guard.is_text_confirmation(text):
            reply = ("聊天里的文字不能当作确认。为了安全，请在确认单上点“确认”按钮" +
                     ("；大额操作还需要输入交易密码和短信动态码。" if pendings else "。") if pendings else
                     "现在没有等待确认的操作。需要办理什么可以直接告诉我。")
            trace.append(tools.step("auth", "文字“确认”不作为授权：只认确认按钮 / 强验证", "blocked"))
            self._remember(user_id, text, reply)
            return self._finish(user_id, turn_id, text, self.response(turn_id, reply, pending=pendings[-1] if pendings else None,
                                                                      trace=trace, user_id=user_id))
        if guard.is_cancel(text) and pendings:
            result = self.kernel.cancel(user_id, pendings[-1]["request_id"], turn_id)
            self.end_task(user_id)
            reply = f"好的，已取消：{result['title']}。"
            trace.append(tools.step("tool", f"取消待确认单：{result['title']}", "success"))
            self._remember(user_id, text, reply)
            return self._finish(user_id, turn_id, text, self.response(turn_id, reply, trace=trace, user_id=user_id,
                                                                      suggestions=DEFAULT_SUGGESTIONS[:3]))
        texts = self._task_texts(user_id, text)
        ctx = tools.TaskContext(self.kernel, user_id, texts, turn_id=turn_id)
        return self._finish(user_id, turn_id, text, self._model_loop(user_id, text, ctx, trace, started))

    def _model_loop(self, user_id, text, ctx, trace, started):
        kernel = self.kernel
        user = kernel.user(user_id)
        system = build_system(user["display_name"], ctx.now, kernel.open_pendings(user_id))
        messages = [{"role": "system", "content": system}] + self._mem(user_id)["history"] + [{"role": "user", "content": text}]
        specs = tools.tool_specs()
        blocks, evidence, pending, choice, receipts, tool_notes = [], [text], None, None, [], []
        cancelled = False
        reply = ""
        for step_index in range(MAX_STEPS):
            final_call = pending is not None or choice is not None
            try:
                result = self.llm.chat(messages, None if final_call else specs)
            except ModelUnavailable as error:
                trace.append(tools.step("llm", f"模型调用失败：{error.message}", "failed", {"code": error.code}))
                if pending or choice or blocks:
                    reply = "请看下面的结果。" if not pending else "请核对确认单，确认后才会执行。"
                    break
                resp = self.response(ctx.turn_id, "抱歉，智能助手暂时连不上（已自动重试一次）。你可以点下面的快捷操作，或稍后再试。",
                                     [{"type": "note", "data": {"text": "模型服务暂不可用。查询类功能可以在首页、账单、卡片页直接查看。", "tone": "warning"}}],
                                     trace=trace, suggestions=["查询余额", "这个月花了多少钱？", "我有哪些卡"], user_id=user_id,
                                     error={"code": error.code, "message": error.message})
                self._remember(user_id, text, "（模型不可用）")
                return resp
            calls = result["tool_calls"]
            trace.append(tools.step("llm", f"模型第 {step_index + 1} 步：" + ("提出工具调用 " + "、".join(c["name"] for c in calls) if calls else "生成回复"),
                                    "pass", {"model": result.get("model"), "tokens": result["usage"],
                                             "proposed": [{"name": c["name"], "arguments": _safe_args(c["arguments"])} for c in calls]},
                                    result.get("ms", 0)))
            if not calls:
                reply = (result["content"] or "").strip()
                break
            messages.append({"role": "assistant", "content": result["content"] or "",
                             "tool_calls": [{"id": c["id"], "type": "function", "function": {"name": c["name"], "arguments": c["arguments"]}} for c in calls]})
            for call in calls:
                try:
                    args = json.loads(call["arguments"] or "{}")
                except ValueError:
                    args = None
                t0 = time.monotonic()
                outcome = tools.run_tool(call["name"], args, ctx)
                for item in outcome.trace:
                    item["ms"] = item.get("ms") or int((time.monotonic() - t0) * 1000)
                trace.extend(outcome.trace)
                blocks.extend(outcome.blocks)
                if outcome.pending:
                    pending = outcome.pending
                if outcome.choice:
                    choice = outcome.choice
                if outcome.receipt:
                    receipts.append(outcome.receipt)
                if outcome.model_result.get("status") == "cancelled":
                    cancelled = True
                content = json.dumps(outcome.model_result, ensure_ascii=False)
                evidence.append(content)
                tool_notes.append(f"{call['name']}→{outcome.model_result.get('status', 'ok')}")
                messages.append({"role": "tool", "tool_call_id": call["id"], "content": content[:6000]})
            if time.monotonic() - started > 20:
                break
        if pending:
            evidence.append(json.dumps(pending["lines"], ensure_ascii=False) + pending["title"])
        for block in blocks:
            evidence.append(json.dumps(block, ensure_ascii=False))
        ok, problems = factcheck.check(reply, evidence, completed=bool(receipts), cancelled=cancelled)
        fact = "pass"
        if not reply or not ok:
            fact = "corrected" if reply else "pass"
            if reply:
                trace.append(tools.step("fact_check", "事实校验：" + "；".join(problems[:3]) + " → 已用代码模板重写回复", "warned",
                                        {"problems": problems[:5]}))
                with kernel.tx():
                    kernel.audit(user_id, "fact_check", "none", "fact_check", "corrected", "；".join(problems[:3]),
                                 actor="agent", turn_id=ctx.turn_id)
            reply = self._template_reply(pending, choice, blocks)
        else:
            trace.append(tools.step("fact_check", "事实校验：回复中的数字均来自工具结果", "pass"))
        if pending is None and choice is None and not any(b["type"] == "note" for b in blocks):
            pass
        note = "；".join(tool_notes)
        self._remember(user_id, text, reply, note)
        return self.response(ctx.turn_id, reply, blocks, pending=pending, trace=trace, fact_check=fact,
                             suggestions=self._suggest(blocks, pending), user_id=user_id)

    def _template_reply(self, pending, choice, blocks):
        if pending:
            if pending["tier"] == "red":
                return f"已为你生成“{pending['title']}”的待确认单。这是红档操作，请核对后输入交易密码和短信动态码完成验证。"
            return f"已为你生成“{pending['title']}”的待确认单，请核对后点确认。"
        if choice:
            return choice["data"]["prompt"]
        for block in blocks:
            if block["type"] == "note":
                return block["data"]["text"]
        if blocks:
            return "结果在下方卡片里。"
        return "我可以帮你办理转账、查账单、理财、卡片和订阅等业务，请问需要什么？"

    def _suggest(self, blocks, pending):
        types = {b["type"] for b in blocks}
        if pending:
            return []
        if "spending_breakdown" in types:
            return ["上个月外卖花了多少", "帮我看看有没有异常扣款", "生成本月账单报告"]
        if "account_list" in types:
            return ["这个月花了多少钱？", "最近三笔大额支出"]
        if "transaction_list" in types:
            return ["这个月都花哪了", "帮我看看有没有异常扣款"]
        return DEFAULT_SUGGESTIONS[:3]

    # ------------------------------------------------------------------ 确认、强验证、取消、点选
    def kernel_call(self, user_id, fn, *args, **kwargs):
        """把内核确认/验证/取消包装成 TurnResponse。"""
        turn_id = new_id("t")
        trace = []
        with self.user_lock(user_id):
            try:
                result = fn(user_id, *args, **kwargs)
            except RuleError as error:
                tone = "danger" if error.code in ("locked", "auth_failed") else "warning"
                trace.append(tools.step("auth", error.message, "failed" if error.code != "locked" else "blocked", {"code": error.code}))
                pending = None
                if error.code in ("auth_failed", "risk_ack_required", "cooling_off", "confirm_failed"):
                    pending = next((p for p in self.kernel.open_pendings(user_id) if p["request_id"] == args[0]), None) if args else None
                resp = self.response(turn_id, error.message, [{"type": "note", "data": {"text": error.message, "tone": tone}}],
                                     pending=pending, trace=trace, user_id=user_id,
                                     error={"code": error.code if error.code in ("locked", "rate_limited") else "invalid_request",
                                            "message": error.message, "reason": error.code, **({"detail": error.detail} if error.detail else {})})
                return self._finish(user_id, turn_id, "[确认操作]", resp)
            if result.get("status") == "pending":
                pending = result["pending"]
                return self._finish(user_id, turn_id, "[修改到账方式]", self.response(
                    turn_id, "已按新的到账方式重新生成待确认单，请核对后确认。", pending=pending,
                    trace=[tools.step("tier", result["tier_reason"], "pending")], user_id=user_id))
            if result.get("status") == "cancelled":
                self.end_task(user_id)
                self._mem(user_id)["history"].append({"role": "assistant", "content": f"（用户在界面上取消了：{result['title']}）"})
                return self._finish(user_id, turn_id, "[取消]", self.response(
                    turn_id, f"好的，已取消：{result['title']}。", trace=[tools.step("tool", "用户取消待确认单", "success")],
                    suggestions=DEFAULT_SUGGESTIONS[:3], user_id=user_id))
            self.end_task(user_id)
            receipt = {"type": "receipt", "data": {"title": result.get("title", "办理成功"),
                                                    "status": "success" if result["status"] == "success" else result["status"],
                                                    "lines": result.get("lines", []), "request_id": result["request_id"],
                                                    "audit_hash": result.get("audit_hash", "")}}
            blocks = [receipt] + result.get("blocks", [])
            via = "交易密码 + 动态码验证通过" if result.get("tier") == "red" else "确认按钮校验通过（确认码绑定参数哈希、一次性）"
            trace = [tools.step("auth", via, "success"),
                     tools.step("tool", "执行前复查余额、归属、累计、重复请求：通过", "success"),
                     tools.step("audit", f"成功审计已写入（与业务修改同一事务），哈希 {result.get('audit_hash', '')[:12]}…", "success")]
            text = result.get("summary", "办理成功。")
            self._mem(user_id)["history"].append({"role": "assistant", "content": f"（系统记录：用户已确认并执行成功：{text}）"})
            plan = result.get("plan")
            return self._finish(user_id, turn_id, "[确认]", self.response(turn_id, text + "。" if not text.endswith("。") else text,
                                                                           blocks, plan=plan, trace=trace, user_id=user_id,
                                                                           suggestions=["查询余额", "看看最近的交易"]))

    def action(self, user_id, kind, ref, value):
        if kind == "option_select":
            return self.select_option(user_id, ref, value)
        handler = getattr(self, "_action_" + kind, None)
        if handler is None:
            return _not_ready(self, user_id, "这个操作")
        with self.user_lock(user_id):
            return handler(user_id, ref, value)

    def quick_intent(self, user_id, intent, params):
        handler = getattr(self, "_quick_intent", None)
        if handler is None:
            return _not_ready(self, user_id, "快捷办理")
        with self.user_lock(user_id):
            return handler(user_id, intent, params)

    def plan_control(self, user_id, plan_id, action):
        handler = getattr(self, "_plan_control", None)
        if handler is None:
            return _not_ready(self, user_id, "计划控制")
        with self.user_lock(user_id):
            return handler(user_id, plan_id, action)

    def select_option(self, user_id, ref, value):
        turn_id = new_id("t")
        with self.user_lock(user_id):
            entry = self.kernel.option_sets.get(ref)
            if entry is None or entry["user_id"] != user_id:
                return self.response(turn_id, "这个选项已失效，请重新说一下要办什么。", error={"code": "invalid_request", "message": "选项已失效"})
            item = next((i for i in entry["items"] if i["value"] == value), None)
            if item is None:
                return self.response(turn_id, "请从给出的选项里选择。", error={"code": "invalid_request", "message": "选项无效"})
            self.kernel.option_sets.pop(ref, None)
            selections = dict(entry.get("selections") or {})
            selections[entry["field"]] = value
            ctx = tools.TaskContext(self.kernel, user_id, entry["texts"], selections=selections, turn_id=turn_id)
            outcome = tools.run_tool(entry["tool"], entry["args"], ctx)
            if outcome.choice:
                self.kernel.option_sets[outcome.choice["data"]["ref"]]["selections"] = selections
            trace = [tools.step("provenance", f"用户点选：{item['label']}", "pass")] + outcome.trace
            reply = self._template_reply(outcome.pending, outcome.choice, outcome.blocks)
            self._mem(user_id)["history"].append({"role": "assistant", "content": f"（用户点选了“{item['label']}”）{reply}"})
            return self._finish(user_id, turn_id, "[点选]", self.response(turn_id, reply, outcome.blocks, pending=outcome.pending,
                                                                          trace=trace, user_id=user_id))


def _not_ready(agent, user_id, what):
    turn_id = new_id("t")
    return agent.response(turn_id, f"{what}功能正在开发中。", error={"code": "invalid_request", "message": f"{what}暂不可用"}, user_id=user_id)


def _safe_args(arguments):
    """决策链里记录模型提出的参数，去掉可能的 6 位数字（密码/验证码）。"""
    try:
        args = json.loads(arguments or "{}")
    except ValueError:
        return {"raw": redact_text(arguments, 80)}
    if not isinstance(args, dict):
        return {}
    return {k: (redact_text(v, 80) if isinstance(v, str) else v) for k, v in args.items()}
