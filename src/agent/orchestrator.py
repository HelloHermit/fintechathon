"""编排循环：输入守卫 → 模型工具调用（≤6 步）→ 代码执行工具 → 事实校验 → TurnResponse。

所有聊天、确认、强验证、取消、点选都返回 API_V2 的 TurnResponse。
"""

import json
import re
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
BUSINESS_HINT = re.compile(r"转账|转[0-9一二两三四五六七八九十百千万]|AA|冻|挂失|解挂|限额|虚拟卡|订阅|自动扣费|续费|会员|申购|买|赎回|理财|持仓|"
                          r"账单|花了|花在|支出|收入|余额|流水|我的卡|哪些卡|异常|报告|年报|月报|撤回|房租|工资|测评|定时")
DEFAULT_SUGGESTIONS = ["这个月花了多少钱？", "帮我看看有没有异常扣款", "我有哪些卡", "给小王转200"]


class StepList(list):
    """决策链列表：每追加一步就回调一次（流式输出用）。"""

    def __init__(self, on_step=None):
        super().__init__()
        self.on_step = on_step

    def append(self, item):
        super().append(item)
        if self.on_step:
            try:
                self.on_step(item)
            except Exception:
                self.on_step = None  # 客户端断开时不影响本轮处理

    def extend(self, items):
        for item in items:
            self.append(item)


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
        if text is not None and not mem.get("keep_task", False):
            mem["task"] = []
        mem["task"] = [(t, at) for t, at in mem["task"] if now - at <= timedelta(minutes=15)][-TASK_TEXT_LIMIT:]
        if text is not None:
            mem["task"].append((text, now))
            mem["task"] = mem["task"][-TASK_TEXT_LIMIT:]
        return [t for t, _ in mem["task"]]

    def end_task(self, user_id):
        self._mem(user_id)["task"] = []

    def _remember(self, user_id, text, reply, note="", keep_task=False):
        """历史只存用户原话和助手回复（不存系统记录，避免模型模仿“已生成确认单”之类的文字）。
        keep_task：本轮留下了待确认单、选项或追问，下一句可能是补充，保留任务上下文；否则任务结束。"""
        mem = self._mem(user_id)
        mem["history"].append({"role": "user", "content": text})
        mem["history"].append({"role": "assistant", "content": reply})
        mem["history"] = mem["history"][-HISTORY_LIMIT:]
        mem["keep_task"] = keep_task

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
    def chat(self, user_id, text, channel="app", on_step=None):
        """channel：app（网页）或 feishu（IM）。on_step：每产生一步决策链就回调（流式接口用）。"""
        with self.user_lock(user_id):
            resp = self._chat(user_id, text, on_step)
            if channel != "app" and resp.get("pending"):
                self.kernel.mark_channel(resp["pending"]["request_id"], channel)
                resp["pending"]["channel"] = channel
            return resp

    def _chat(self, user_id, text, on_step=None):
        turn_id = new_id("t")
        started = time.monotonic()
        self.kernel.tick()
        trace = StepList(on_step)
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
        pre_blocks = self._risk_prescan(user_id, text, trace)
        resp = self._model_loop(user_id, text, ctx, trace, started)
        if pre_blocks:
            resp["assistant"]["blocks"] = pre_blocks + resp["assistant"]["blocks"]
            resp["guard"]["input"] = "warned"
        return self._finish(user_id, turn_id, text, resp)

    def _risk_prescan(self, user_id, text, trace):
        """代码反诈预检：用户原话里出现的手机号如果在模拟涉诈风险名单上，直接标出（不依赖模型判断）。"""
        from ..core.ops import fraud_signals
        blocks = []
        for phone in set(re.findall(r"(?<![0-9])1[3-9][0-9]{9}(?![0-9])", text)):
            entry = self.kernel.db.execute("""SELECT d.masked_name, r.reason FROM phone_directory d JOIN risk_list r
                ON r.account_id=d.account_id WHERE d.phone=?""", (phone,)).fetchone()
            if entry:
                masked = phone[:3] + "****" + phone[-4:]
                trace.append(tools.step("risk", f"反诈预检：{masked}（{entry['masked_name']}）在模拟涉诈风险名单上，任何转账都会被代码拒绝",
                                        "blocked", {"reason": entry["reason"]}))
                blocks.append({"type": "note", "data": {"tone": "danger", "text":
                               f"风险提示：{masked} 在涉诈风险名单上（{entry['reason']}）。向它的任何转账都会被系统拒绝。"
                               "公检法和银行客服不会要求你把钱转到“安全账户”，请挂断电话，可拨打 96110 反诈专线（模拟提示）。"}})
        signals = fraud_signals([text])
        if signals["fraud_terms"] and not blocks:
            trace.append(tools.step("risk", "反诈预检：出现“" + "”“".join(signals["fraud_terms"][:3]) + "”等诈骗常见话术，转账将计入反诈评分",
                                    "warned", signals))
        return blocks

    def _model_loop(self, user_id, text, ctx, trace, started):
        kernel = self.kernel
        user = kernel.user(user_id)
        system = build_system(user["display_name"], ctx.now, kernel.open_pendings(user_id))
        messages = [{"role": "system", "content": system}] + self._mem(user_id)["history"] + [{"role": "user", "content": text}]
        specs = tools.tool_specs()
        blocks, evidence, pending, choice, receipts, tool_notes = [], [text], None, None, [], []
        plan = None
        cancelled = False
        nudged = False
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
                if not tool_notes and not nudged and step_index + 1 < MAX_STEPS:
                    ok_first, problems_first = factcheck.check(reply, evidence, completed=False, pending_created=False)
                    if ok_first and BUSINESS_HINT.search(text) and not reply.rstrip().endswith(("？", "?")):
                        ok_first, problems_first = False, ["业务请求没有调用工具"]
                    if not ok_first:
                        # 模型没调用任何工具就给出了事实性内容或“已生成确认单”：提醒一次，让它调用工具
                        nudged = True
                        trace.append(tools.step("fact_check", "模型未调用工具就回答了事实性内容，要求其调用工具后重答", "warned",
                                                {"problems": problems_first[:3]}))
                        messages.append({"role": "assistant", "content": reply})
                        messages.append({"role": "user", "content": "（系统提示：你刚才没有调用任何工具，回复里的数字或“确认单已生成”没有依据。请调用合适的工具后再回答我上一句话。）"})
                        reply = ""
                        continue
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
                if outcome.plan:
                    plan = outcome.plan
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
        ok, problems = factcheck.check(reply, evidence, completed=bool(receipts), cancelled=cancelled,
                                       pending_created=pending is not None)
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
            waiting = [p for p in kernel.open_pendings(user_id) if not pending or p["request_id"] != pending["request_id"]]
            if not pending and not choice and waiting:
                how = "点确认" if waiting[-1]["tier"] == "yellow" else "完成交易密码 + 动态码验证"
                reply = f"还没有执行：“{waiting[-1]['title']}”还在等你{how}。" + ("" if reply.startswith("这个问题需要先查数据") else reply)
        else:
            trace.append(tools.step("fact_check", "事实校验：回复中的数字均来自工具结果", "pass"))
        if pending is None and choice is None and not any(b["type"] == "note" for b in blocks):
            pass
        note = "；".join(tool_notes)
        asked = reply.rstrip().endswith(("？", "?"))
        self._remember(user_id, text, reply, note, keep_task=bool(pending or choice or asked or any(
            '"need_info"' in e or '"provenance"' in e for e in evidence)))
        try:
            with kernel.tx():
                kernel.audit(user_id, "chat_turn", "none", "agent_turn", "success",
                             f"工具：{'、'.join(n.split('→')[0] for n in tool_notes) or '无'}；事实校验：{fact}",
                             actor="agent", turn_id=ctx.turn_id,
                             params={"tools": tool_notes[:10], "pending": pending["request_id"] if pending else None,
                                     "fact_check": fact})
            trace.append(tools.step("audit", "本轮决策链已保存，审计已追加（哈希链）", "success"))
        except Exception:
            trace.append(tools.step("audit", "审计写入失败：本轮只返回查询结果", "failed"))
        if plan and any(b["type"] == "plan" for b in blocks):
            blocks = [b for b in blocks if b["type"] != "plan"]  # 计划放在 TurnResponse.plan，避免重复
        return self.response(ctx.turn_id, reply, blocks, pending=pending, plan=plan, trace=trace, fact_check=fact,
                             suggestions=self._suggest(blocks, pending), user_id=user_id)

    def _template_reply(self, pending, choice, blocks):
        """事实校验不通过时的代码模板：内容只来自本轮的卡片和确认单。"""
        if pending:
            if pending["tier"] == "red":
                return f"已为你生成“{pending['title']}”的待确认单。这是红档操作，请核对后输入交易密码和短信动态码完成验证。"
            return f"已为你生成“{pending['title']}”的待确认单，请核对后点确认。"
        if choice:
            return choice["data"]["prompt"]
        for block in blocks:
            text = block_summary(block)
            if text:
                return text
        if blocks:
            return "结果在下方卡片里。"
        return "这个问题需要先查数据才能准确回答，我不展示没有核实过的数字。你可以换个说法再问一次，比如“这个月花了多少钱”“查一下余额”。"

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
                                     error={"code": error.code if error.code in ("locked", "rate_limited") else
                                            "expired" if error.code in ("expired", "duplicate", "not_found") else "invalid_request",
                                            "message": error.message, "reason": error.code, **({"detail": error.detail} if error.detail else {})})
                return self._finish(user_id, turn_id, "[确认操作]", resp)
            if result.get("status") == "pending":
                pending = result["pending"]
                return self._finish(user_id, turn_id, "[修改到账方式]", self.response(
                    turn_id, "已按新的到账方式重新生成待确认单，请核对后确认。", pending=pending,
                    trace=[tools.step("tier", result["tier_reason"], "pending")], user_id=user_id))
            if result.get("status") == "cancelled":
                self.end_task(user_id)
                self._mem(user_id)["history"].append({"role": "assistant", "content": f"好的，已取消：{result['title']}。"})
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
            self._mem(user_id)["history"].append({"role": "assistant", "content": text})
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

    # ------------------------------------------------------------------ 页面按钮
    def _quick_intent(self, user_id, intent, params, turn_id=None, label=None):
        turn_id = turn_id or new_id("t")
        trace = [tools.step("guard", f"页面按钮发起：{label or intent}（不经过模型）", "pass")]
        if intent == "mark_normal":
            fid = params.get("finding_id")
            if type(fid) is not str or len(fid) > 80:
                return self.response(turn_id, "参数无效。", error={"code": "invalid_request", "message": "参数无效"}, user_id=user_id)
            with self.kernel.tx():
                self.kernel.db.execute("INSERT OR REPLACE INTO anomaly_marks VALUES(?,?,?,?)", (user_id, fid, "normal", iso(self.kernel.now())))
                self.kernel.audit(user_id, "mark_normal", "green", "anomaly_marked", "success", "用户标记为本人交易", turn_id=turn_id,
                                  params={"finding_id": fid})
            return self.response(turn_id, "好的，已标记为你本人的交易，之后不再提醒。", trace=trace, user_id=user_id)
        if intent == "decline_aa_request":
            from ..core.ops_more import decline_aa
            try:
                row = decline_aa(self.kernel, user_id, str(params.get("request_id") or params.get("aa_id") or "")[:80], turn_id)
            except RuleError as error:
                return self.response(turn_id, error.message, error={"code": "expired", "message": error.message}, user_id=user_id)
            return self.response(turn_id, f"好的，已婉拒这笔 {yuan(row['amount_cents'])} 的 AA，没有动用资金。", trace=trace, user_id=user_id)
        if intent == "start_risk_assessment":
            outcome = tools.run_tool("start_risk_assessment", {}, tools.TaskContext(self.kernel, user_id, [], turn_id=turn_id))
            return self.response(turn_id, "请完成下面 6 道题，提交后系统计分定级。", outcome.blocks, trace=trace + outcome.trace, user_id=user_id)
        if intent == "detect_anomalies":
            outcome = tools.run_tool("detect_anomalies", {}, tools.TaskContext(self.kernel, user_id, [], turn_id=turn_id))
            return self.response(turn_id, f"发现 {outcome.model_result['count']} 处需要留意的交易，详见下方。", outcome.blocks,
                                 trace=trace + outcome.trace, user_id=user_id)
        spec = QUICK_INTENTS.get(intent)
        if spec is None:
            return self.response(turn_id, "不支持的快捷操作。", error={"code": "invalid_request", "message": "未知操作"}, user_id=user_id)
        kernel_intent, build = spec
        try:
            params_built = build(params)
            result = self.kernel.propose(user_id, kernel_intent, params_built, turn_id=turn_id, actor="user",
                                         provenance={"source": "用户在界面上点击"})
        except (KeyError, TypeError):
            return self.response(turn_id, "参数不完整。", error={"code": "invalid_request", "message": "参数不完整"}, user_id=user_id)
        except RuleError as error:
            trace.append(tools.step("tier", f"代码拒绝：{error.message}", "blocked", {"code": error.code}))
            return self.response(turn_id, error.message, [{"type": "note", "data": {"text": error.message, "tone": "warning"}}],
                                 trace=trace, user_id=user_id)
        trace.append(tools.step("tier", result["tier_reason"], "pending", {"tier": result["tier"]}))
        reply = self._template_reply(result["pending"], None, [])
        return self._finish(user_id, turn_id, "[按钮]" + intent, self.response(turn_id, reply, pending=result["pending"], trace=trace, user_id=user_id))

    def _action_block_action(self, user_id, ref, value):
        if not isinstance(value, dict) or type(value.get("intent")) is not str or not isinstance(value.get("params", {}), dict):
            return self.response(new_id("t"), "参数无效。", error={"code": "invalid_request", "message": "参数无效"}, user_id=user_id)
        return self._quick_intent(user_id, value["intent"], value.get("params", {}), label=ref)

    def _action_form_submit(self, user_id, ref, value):
        turn_id = new_id("t")
        owner = self.kernel.questionnaires.get(ref)
        if owner != user_id or not isinstance(value, dict):
            return self.response(turn_id, "问卷已失效，请重新开始测评。", error={"code": "invalid_request", "message": "问卷已失效"}, user_id=user_id)
        try:
            result = self.kernel.propose(user_id, "submit_risk_assessment", {"answers": value}, turn_id=turn_id, actor="user",
                                         provenance={"answers": "用户在问卷上逐题选择"})
        except RuleError as error:
            return self.response(turn_id, error.message, [{"type": "note", "data": {"text": error.message, "tone": "warning"}}], user_id=user_id)
        self.kernel.questionnaires.pop(ref, None)
        trace = [tools.step("resolver", "问卷计分由代码完成：6 题各 1–5 分", "pass"), tools.step("tier", result["tier_reason"], "pending")]
        return self._finish(user_id, turn_id, "[问卷]", self.response(turn_id, "测评结果已算好，请核对后点确认提交。", pending=result["pending"],
                                                                      trace=trace, user_id=user_id))

    def _accept_birthday(self, user_id, ref):
        from ..core import plans as plan_engine
        turn_id = new_id("t")
        contact_id = ref[len("ins-birthday-"):]
        trace = [tools.step("guard", "用户点击首页提醒“帮我准备”（不经过模型）", "pass")]
        existing = self.kernel.db.execute("""SELECT plan_id FROM plans WHERE user_id=? AND status IN ('running','paused')
            AND plan_json LIKE ?""", (user_id, '%"contact_id":"' + contact_id + '"%')).fetchone()
        if existing:
            plan = plan_engine.view(plan_engine.load(self.kernel, user_id, existing[0]))
            return self.response(turn_id, "这个生日计划已经在进行中了，进度见下方。", plan=plan, trace=trace, user_id=user_id)
        try:
            created = plan_engine.create_birthday_plan(self.kernel, user_id, contact_id, source="insight")
            result = self.kernel.propose(user_id, "plan", {"plan_id": created["plan_id"]}, turn_id=turn_id, plan_id=created["plan_id"],
                                         actor="user", provenance={"source": "用户点击首页生日提醒"})
        except RuleError as error:
            return self.response(turn_id, error.message, [{"type": "note", "data": {"text": error.message, "tone": "warning"}}],
                                 trace=trace, user_id=user_id)
        trace += [tools.step("plan", f"计划模板：生日筹备（{len(created['nodes'])} 个节点：锁预算 → 订花、订蛋糕 → 当天提醒）", "pass"),
                  tools.step("tier", result["tier_reason"], "pending")]
        plan = plan_engine.view(plan_engine.load(self.kernel, user_id, created["plan_id"]))
        text = f"已为你生成“{created['title']}”计划，共 {len(created['nodes'])} 步。核对后点一次确认，整个计划就会按时自动执行。"
        return self._finish(user_id, turn_id, "[生日提醒]", self.response(turn_id, text, pending=result["pending"], plan=plan,
                                                                        trace=trace, user_id=user_id))

    def _plan_control(self, user_id, plan_id, action):
        from ..core import plans as plan_engine
        turn_id = new_id("t")
        try:
            plan, note = plan_engine.control(self.kernel, user_id, plan_id, action, turn_id=turn_id)
        except RuleError as error:
            return self.response(turn_id, error.message, error={"code": "expired" if error.code == "not_found" else "invalid_request",
                                                                 "message": error.message}, user_id=user_id)
        trace = [tools.step("plan", f"计划控制（页面按钮）：{action} → {plan['status']}", "success"),
                 tools.step("audit", "已写入审计", "success")]
        self.kernel.tick()
        raw = plan_engine.load(self.kernel, user_id, plan_id)
        plan = plan_engine.view(raw)
        blocks = [{"type": "plan", "data": plan}]
        if action == "takeover" and raw.get("handover_ticket"):
            blocks.insert(0, {"type": "handover", "data": {"ticket_id": raw["handover_ticket"],
                                                           "summary": f"计划“{raw['title']}”转人工处理", "status": "waiting"}})
        return self._finish(user_id, turn_id, "[计划控制]", self.response(turn_id, note, blocks, plan=plan, trace=trace, user_id=user_id))

    def _action_insight_accept(self, user_id, ref, value):
        kind = ref.split("-")[1] if ref.startswith("ins-") else ""
        if kind == "birthday" and hasattr(self, "_accept_birthday"):
            return self._accept_birthday(user_id, ref)
        if kind == "renewal":
            return self._quick_intent(user_id, "query_subscriptions", {}, label="查看订阅")
        if kind == "anomaly":
            return self._quick_intent(user_id, "detect_anomalies", {}, label="查看异常")
        if kind == "rent":
            from ..core import views
            items = [s for s in views.scheduled(self.kernel, user_id) if s["status"] == "scheduled"]
            return self.response(new_id("t"), "这是你已排定的定时任务。", [{"type": "scheduled_list", "data": {"items": items}}], user_id=user_id)
        return _not_ready(self, user_id, "这个提醒")

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
            if value == "cancel":
                self.end_task(user_id)
                return self.response(turn_id, "好的，先不办了。", suggestions=DEFAULT_SUGGESTIONS[:3], user_id=user_id)
            selections = dict(entry.get("selections") or {})
            selections[entry["field"]] = value
            selections.update(item.get("selections") or {})
            ctx = tools.TaskContext(self.kernel, user_id, entry["texts"], selections=selections, turn_id=turn_id)
            tool_name, args = item.get("tool") or entry["tool"], dict(item.get("args") or entry["args"])
            outcome = tools.run_tool(tool_name, args, ctx, internal={"then": item["then"]} if item.get("then") else None)
            if outcome.choice:
                self.kernel.option_sets[outcome.choice["data"]["ref"]]["selections"] = selections
            trace = [tools.step("provenance", f"用户点选：{item['label']}", "pass")] + outcome.trace
            reply = self._template_reply(outcome.pending, outcome.choice, outcome.blocks)
            self._mem(user_id)["history"].append({"role": "assistant", "content": reply})
            self._mem(user_id)["keep_task"] = True
            return self._finish(user_id, turn_id, "[点选]", self.response(turn_id, reply, outcome.blocks, pending=outcome.pending,
                                                                          trace=trace, user_id=user_id))


QUICK_INTENTS = {
    # 页面按钮直接发起：参数来自用户本人在界面上的点击，不经过模型；照样走代码判档与确认。
    "query_subscriptions": ("query_subscriptions", lambda p: {}),
    "cancel_subscription": ("cancel_subscription", lambda p: {"subscription_id": p["subscription_id"]}),
    "freeze_card": ("freeze_card", lambda p: {"card_id": p["card_id"]}),
    "unfreeze_card": ("unfreeze_card", lambda p: {"card_id": p["card_id"]}),
    "report_card_lost": ("report_card_lost", lambda p: {"card_id": p["card_id"]}),
    "restore_card": ("restore_card", lambda p: {"card_id": p["card_id"]}),
    "set_card_limit": ("set_card_limit", lambda p: {"card_id": p["card_id"], "daily_limit_cents": p["daily_limit_cents"]}),
    "apply_virtual_card": ("apply_virtual_card", lambda p: {k: v for k, v in p.items() if k in ("purpose", "daily_limit_cents")}),
    "redeem_product": ("redeem_product", lambda p: {"product_id": p["product_id"], "amount_cents": p["amount_cents"]}),
    "purchase_product": ("purchase_product", lambda p: {"product_id": p["product_id"], "amount_cents": p["amount_cents"]}),
    "revoke_transfer": ("revoke_transfer", lambda p: {"transfer_id": p["transfer_id"]}),
    "pay_aa": ("aa_pay", lambda p: {"aa_id": p.get("aa_id") or p["request_id"]}),
    "pay_aa_request": ("aa_pay", lambda p: {"aa_id": p.get("request_id") or p["aa_id"]}),
    "cancel_card_lost": ("restore_card", lambda p: {"card_id": p["card_id"]}),
    "cancel_scheduled": ("cancel_scheduled", lambda p: {"schedule_id": p["schedule_id"]}),
}


def block_summary(block):
    """由代码根据卡片内容生成一句话（不经过模型）。"""
    t, d = block["type"], block.get("data", {})
    if t == "note":
        return d.get("text")
    if t == "spending_breakdown":
        top = d["categories"][0] if d.get("categories") else None
        return f"这段时间总支出 {yuan(d['total_cents'])}" + (f"，最多的是{top['name']} {yuan(top['amount_cents'])}" if top else "") + "。"
    if t == "account_list":
        return f"你名下 {len(d['accounts'])} 个账户，合计余额 {yuan(sum(a['balance_cents'] for a in d['accounts']))}。"
    if t == "transaction_list":
        return f"{d.get('title', '')}共 {d['total_count']} 笔，明细见下方。"
    if t == "anomaly_list":
        high = sum(1 for i in d["items"] if i["severity"] == "high")
        return f"发现 {len(d['items'])} 处需要留意的交易" + (f"，其中 {high} 处高风险" if high else "") + "，详见下方。"
    if t == "report":
        kpi = d["kpis"][0]
        return f"{d['period'].get('label', '')}账单报告已生成：{kpi['label']} {kpi['value']}。"
    if t == "card_list":
        return f"你名下有 {len(d['items'])} 张卡，详见下方。"
    if t in ("product_list", "product_compare"):
        return "产品信息见下方。理财非存款，产品有风险，投资须谨慎。"
    if t == "holding_list":
        return f"你有 {len(d['items'])} 笔理财持仓，累计收益 {yuan(sum(i['profit_cents'] for i in d['items']))}。"
    if t == "risk_questionnaire":
        return "请先完成下方 6 道风险测评题。"
    if t == "code_analysis":
        if d["status"] != "ok":
            return f"分析代码没有通过沙箱检查（{d.get('reason', '')}），没有运行。"
        return "分析结果见下方卡片（代码在受限沙箱中运行，结果来自你的流水）。"
    return None


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
