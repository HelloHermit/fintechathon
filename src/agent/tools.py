"""工具白名单：模型能调用的全部工具、严格参数、代码溯源校验，以及给模型看的结果（不含任何确认码）。

每个工具返回 ToolOutcome：
- model_result：交给模型的数据（外部文本已包进 <external_data>，不含确认码/动态码/密码）
- blocks：界面卡片（代码根据账本生成）
- pending：待确认单（含黄档确认码，只给前端）
- trace：决策链步骤
"""

import json
import re
from decimal import Decimal, InvalidOperation

from ..core.kernel import NeedChoice, RuleError
from ..core.ops import fraud_signals
from ..core.util import SIMULATION_NOTICE, human_date, human_datetime, iso, new_id, parse_iso, yuan
from . import resolvers
from .guard import wrap_external

TOOLS = {}


def tool(name, description, properties=None, required=None, write=False):
    def decorator(fn):
        TOOLS[name] = {"fn": fn, "write": write, "schema": {
            "type": "function", "function": {"name": name, "description": description, "parameters": {
                "type": "object", "properties": properties or {}, "required": required or [],
                "additionalProperties": False}}}}
        return fn
    return decorator


class ToolOutcome:
    def __init__(self, model_result=None, blocks=None, pending=None, trace=None, choice=None, receipt=None, plan=None):
        self.plan = plan
        self.model_result = model_result or {}
        self.blocks = blocks or []
        self.pending = pending
        self.trace = trace or []
        self.choice = choice
        self.receipt = receipt


def step(kind, label, status="pass", detail=None, ms=0):
    return {"kind": kind, "label": label, "status": status, "detail": detail or {}, "ms": ms}


class TaskContext:
    """本次任务的上下文：用户原话（参数溯源依据）、用户点选的值、当前时间。"""

    def __init__(self, kernel, user_id, texts, selections=None, turn_id=None):
        self.kernel, self.user_id, self.texts = kernel, user_id, [t for t in texts if t]
        self.selections = selections or {}
        self.turn_id = turn_id
        self.now = kernel.now()

    @property
    def joined(self):
        return "\n".join(self.texts)

    @property
    def current(self):
        return self.texts[-1] if self.texts else ""

    def mentions(self, word):
        if not word:
            return False
        compact = re.sub(r"\s", "", self.joined)
        return re.sub(r"\s", "", word) in compact


def tool_specs(names=None):
    return [TOOLS[n]["schema"] for n in (names or TOOLS)]


def run_tool(name, args, ctx, internal=None):
    """internal：代码内部（点选、页面按钮）附加的参数，不经过模型，也不在模型可见的 schema 里。"""
    entry = TOOLS.get(name)
    if entry is None:
        return ToolOutcome({"status": "error", "message": f"没有名为 {name} 的工具"},
                           trace=[step("tool", f"拒绝：未知工具 {name}", "blocked")])
    if not isinstance(args, dict):
        return ToolOutcome({"status": "error", "message": "参数必须是对象"}, trace=[step("tool", f"{name} 参数非法", "blocked")])
    allowed = set(entry["schema"]["function"]["parameters"]["properties"])
    extra = set(args) - allowed
    if extra:
        args = {k: v for k, v in args.items() if k in allowed}
    if internal:
        args = dict(args, **internal)
    try:
        outcome = entry["fn"](ctx, **args)
    except NeedChoice as choice:
        ref = new_id("opt")
        ctx.kernel.option_sets[ref] = {"user_id": ctx.user_id, "tool": name, "args": args, "field": choice.field,
                                       "items": choice.items, "texts": ctx.texts}
        block = {"type": "options", "data": {"prompt": choice.prompt, "ref": ref,
                                              "items": [{"label": i["label"], "value": i["value"], "hint": i.get("hint", "")} for i in choice.items]}}
        return ToolOutcome({"status": "need_user_choice", "prompt": choice.prompt,
                            "options": [i["label"] for i in choice.items],
                            "note": "界面已经给用户展示了这些选项按钮，请用一句话请用户点选，不要替用户选择。"},
                           blocks=[block], trace=[step("resolver", choice.prompt, "pending")], choice=block)
    except RuleError as error:
        blocks = [{"type": "note", "data": {"text": error.message + (" " + error.detail["advice"] if error.detail.get("advice") else ""),
                                            "tone": "danger" if error.code in ("risk_listed", "forbidden", "locked", "unsuitable") else "warning"}}]
        return ToolOutcome({"status": "rejected", "code": error.code, "message": error.message, **({"advice": error.detail["advice"]} if error.detail.get("advice") else {}),
                            **({k: v for k, v in error.detail.items() if k in ("available_cents", "shortfall_cents")})},
                           blocks=blocks, trace=[step("tier" if error.code in ("risk_listed", "forbidden", "unsuitable") else "tool",
                                                      f"代码拒绝：{error.message}", "blocked", {"code": error.code})])
    if entry["write"] is False and outcome.trace == []:
        outcome.trace.append(step("tool", f"绿档工具 {name}", "success"))
    return outcome


# ---------------------------------------------------------------------------------------------- 公共
def cents_from(value):
    """模型给出的金额（元，数字或字符串）→ 整数分；非法返回 None。"""
    if value is None or isinstance(value, bool):
        return None
    try:
        amount = Decimal(str(value).replace(",", "").replace("¥", "").replace("元", "").strip())
    except InvalidOperation:
        parsed = resolvers.parse_amounts(str(value))
        return parsed[0] if len(parsed) == 1 else None
    if amount <= 0 or amount.as_tuple().exponent < -2:
        return None
    return int(amount * 100)


def pending_for_model(pending):
    """给模型看的待确认单：没有确认码。"""
    return {"status": "awaiting_user_confirmation", "tier": pending["tier"], "title": pending["title"],
            "lines": {l["label"]: l["value"] for l in pending["lines"]},
            "risk": ({"level": pending["risk"]["level"], "reasons": pending["risk"]["reasons"]} if pending.get("risk") else None),
            "how_to_confirm": "用户需点击确认单上的确认按钮" if pending["tier"] == "yellow" else "用户需在强验证面板输入交易密码和短信动态码",
            "note": "尚未执行。不要说已完成；请用一两句话请用户核对确认单。"}


def account_view(row):
    return {"account_id": row["account_id"], "name": row["name"], "masked_no": "**** " + row["tail"],
            "balance_cents": row["balance_cents"], "reserved_cents": row["reserved_cents"],
            "available_cents": row["balance_cents"] - row["reserved_cents"]}


def provenance_step(field, ok, source):
    return step("provenance", f"参数溯源 · {field}：{source}", "pass" if ok else "blocked", {"field": field, "source": source})


# ---------------------------------------------------------------------------------------------- 绿档：账户与流水
@tool("get_accounts", "查询本人账户余额与可用余额。")
def get_accounts(ctx):
    rows = ctx.kernel.db.execute("SELECT * FROM accounts WHERE user_id=? ORDER BY account_id", (ctx.user_id,)).fetchall()
    accounts = [account_view(r) for r in rows]
    total = sum(a["balance_cents"] for a in accounts)
    return ToolOutcome({"accounts": [{"name": a["name"], "tail": a["masked_no"][-4:], "balance": yuan(a["balance_cents"]),
                                      "available": yuan(a["available_cents"])} for a in accounts], "total": yuan(total)},
                       blocks=[{"type": "account_list", "data": {"accounts": accounts}}])


@tool("search_transactions", "查询本人交易流水。可按时间范围、分类、商户/对方关键词、收支方向筛选，按时间或金额排序。",
      {"period": {"type": "string", "description": "用户说的时间范围原话，如“本月”“上个月”“最近7天”“今年”“2026-10”；不填表示最近30天"},
       "category": {"type": "string", "description": "分类，如 餐饮外卖、超市日用、交通出行、购物、住房缴费、娱乐、订阅会员、医疗健康、学习教育、旅行、转账给他人、人情红包、其他、工资、转入、理财收益、退款"},
       "keyword": {"type": "string", "description": "商户或对方名称关键词"},
       "direction": {"type": "string", "enum": ["expense", "income", "all"]},
       "order_by": {"type": "string", "enum": ["time", "amount"]},
       "limit": {"type": "integer", "description": "返回条数，默认10，最多50"}})
def search_transactions(ctx, period=None, category=None, keyword=None, direction="all", order_by="time", limit=10):
    analytics = ctx.kernel.analytics
    start, end, label = analytics.resolve_period(period or "最近30天", ctx.now)
    result = analytics.search(ctx.user_id, start, end, category=category, keyword=keyword, direction=direction,
                              order_by=order_by, limit=max(1, min(50, int(limit or 10))))
    title = f"{label}" + (f" · {category}" if category else "") + (f" · {keyword}" if keyword else "")
    block = {"type": "transaction_list", "data": {"items": result["items"], "total_count": result["count"], "title": title}}
    model_items = [{"time": i["time"][:16].replace("T", " "), "merchant": wrap_external(i["merchant"], 40), "category": i["category"],
                    "amount": yuan(i["amount_cents"]), **({"memo": wrap_external(i["memo"], 60)} if i.get("memo") else {})}
                   for i in result["items"][:15]]
    return ToolOutcome({"period": f"{start:%Y-%m-%d} 至 {end:%Y-%m-%d}", "count": result["count"],
                        "expense_total": yuan(result["expense_cents"]), "income_total": yuan(result["income_cents"]),
                        "items": model_items}, blocks=[block])


@tool("spending_summary", "消费分类统计：某段时间总支出、各分类金额占比、与上一周期对比。用于“这个月花了多少/都花哪了”。",
      {"period": {"type": "string", "description": "用户说的时间范围原话，如“本月”“上个月”“10月”“今年”；默认本月"}})
def spending_summary(ctx, period=None):
    analytics = ctx.kernel.analytics
    start, end, label = analytics.resolve_period(period or "本月", ctx.now)
    data = analytics.breakdown(ctx.user_id, start, end)
    block = {"type": "spending_breakdown", "data": data}
    return ToolOutcome({"period": f"{label}（{start:%Y-%m-%d} 至 {end:%Y-%m-%d}）", "total_expense": yuan(data["total_cents"]),
                        "categories": [{"name": c["name"], "amount": yuan(c["amount_cents"]), "share": f"{round(c['share'] * 100)}%", "count": c["count"]}
                                       for c in data["categories"][:8]],
                        "previous_period_total": yuan(data["compare"]["prev_total_cents"]),
                        "change_pct": data["compare"]["change_pct"]}, blocks=[block])


@tool("find_contacts", "按姓名、称呼（如小王、妈妈、房东）、手机号或转账用途（如房租）查找本人联系人或按手机号查收款人。",
      {"query": {"type": "string", "description": "用户原话里的称呼/姓名/手机号/用途词"}}, ["query"])
def find_contacts(ctx, query=""):
    matches = resolvers.contact_matches(ctx.kernel, ctx.user_id, query)
    return ToolOutcome({"note": "如果用户是要转账/交房租，请直接调用 transfer（payee 用用户原话里的词；没说金额就不填 amount，系统会给建议金额选项）。",
                        "query": query, "matches": [{"name": m["display"], "relation": m["relation"], "phone": m["masked_phone"],
                                                     "matched_by": m["match"],
                                                     **({"last_transfer": yuan(m["last_transfer"]["amount_cents"]) + (f"（备注 {m['last_transfer']['memo']}）" if m["last_transfer"].get("memo") else "")}
                                                        if m.get("last_transfer") else {})} for m in matches]},
                       trace=[step("resolver", f"联系人解析：“{query}” → {len(matches)} 个结果", "pass")])


@tool("resolve_date", "把用户说的日期表达（明天、下周五、月底、11月10日、下个月12号）换算成具体日期。",
      {"expression": {"type": "string"}}, ["expression"])
def resolve_date_tool(ctx, expression=""):
    value, note = resolvers.resolve_date(expression, ctx.now)
    if value is None:
        return ToolOutcome({"status": "unknown", "message": note})
    return ToolOutcome({"date": f"{value:%Y-%m-%d}", "weekday": "周" + "一二三四五六日"[value.weekday()], "time": f"{value:%H:%M}"},
                       trace=[step("resolver", f"日期解析：{note}", "pass")])


# ---------------------------------------------------------------------------------------------- 写操作：转账
def _resolve_payee(ctx, payee, trace):
    selection = ctx.selections.get("payee")
    if selection:
        row = ctx.kernel.db.execute("SELECT * FROM contacts WHERE contact_id=? AND user_id=?", (selection, ctx.user_id)).fetchone()
        if row is not None:
            trace.append(provenance_step("收款人", True, f"用户点选 {row['name']}"))
            return resolvers._contact_view(ctx.kernel, row, "用户点选"), "user_selected"
    if not payee:
        raise RuleError("need_info", "请告诉我要转给谁（姓名、称呼或手机号）。")
    phone = resolvers.PHONE_PATTERN.search(payee)
    matches = resolvers.contact_matches(ctx.kernel, ctx.user_id, payee)
    if not (ctx.mentions(payee) or (phone and ctx.mentions(phone.group(0)))):
        # 允许：模型用 find_contacts 按用户原话里的词（如“房租”）查到的唯一联系人
        mentioned = resolvers.contacts_mentioned(ctx.kernel, ctx.user_id, ctx.texts)
        hit = [m for m in matches if m["contact_id"] and m["contact_id"] in mentioned]
        if len(hit) == 1:
            trace.append(provenance_step("收款人", True, f"用户原话“{mentioned[hit[0]['contact_id']]}” → {hit[0]['display']}"))
            return hit[0], "user_text_keyword"
        trace.append(provenance_step("收款人", False, f"“{payee}”不在用户原话里"))
        raise RuleError("provenance", f"收款人必须来自你本人说的话。请直接告诉我要转给谁。")
    if not matches:
        raise RuleError("not_found", f"没有找到“{payee}”。可以告诉我对方的全名，或者直接说对方手机号。")
    if len(matches) > 1:
        raise NeedChoice(f"“{payee}”对应 {len(matches)} 位联系人，要转给哪一位？", "payee",
                         [{"label": m["display"], "value": m["contact_id"] or m["via_phone"],
                           "hint": f"{m['relation']} · {m['masked_phone']}"} for m in matches])
    if ctx.kernel.db.execute("SELECT 1 FROM risk_list WHERE account_id=?", (matches[0]["account_id"],)).fetchone():
        trace.append(step("tier", "收款方在模拟涉诈风险名单上：直接拒绝", "blocked"))
        raise RuleError("risk_listed", "收款方在涉诈风险名单上，这笔转账已被拒绝。",
                        detail={"advice": "公检法和银行客服不会要求你把钱转到“安全账户”。如果有人这样要求，请立即挂断并拨打 96110 反诈专线（模拟提示）。"})
    trace.append(provenance_step("收款人", True, f"用户原话“{payee}” → {matches[0]['display']}（{matches[0]['match']}）"))
    return matches[0], "user_text"


def _check_amount(ctx, amount, trace, field="金额"):
    selected = ctx.selections.get("amount_cents")
    if selected:
        trace.append(provenance_step(field, True, f"用户点选建议金额 {yuan(selected)}"))
        return selected
    cents = cents_from(amount)
    if cents is None:
        raise RuleError("need_info", "请告诉我具体金额。")
    said = set()
    for text in ctx.texts:
        said.update(resolvers.parse_amounts(text))
    if cents not in said:
        trace.append(provenance_step(field, False, f"{yuan(cents)} 不在用户原话里"))
        raise RuleError("provenance", f"金额必须是你本人说出的数。你说的是多少钱？")
    trace.append(provenance_step(field, True, f"用户原话中的金额 {yuan(cents)}"))
    return cents


def _check_date(ctx, when, trace):
    """返回 (run_at_iso 或 None)。今天 → 立即执行。"""
    if not when:
        return None
    value, note = resolvers.resolve_date(when, ctx.now)
    if value is None:
        raise RuleError("need_info", f"没能理解“{when}”是哪一天，请说具体日期，比如“11月5日”。")
    said = resolvers.scan_dates(ctx.texts, ctx.now)
    if value.date().isoformat() not in said:
        trace.append(provenance_step("日期", False, f"{value:%Y-%m-%d} 不在用户原话里"))
        raise RuleError("provenance", "执行日期必须来自你本人说的话，请告诉我哪天转。")
    trace.append(step("resolver", f"日期解析：{note}", "pass"))
    trace.append(provenance_step("日期", True, f"用户原话“{when}”"))
    if value.date() == ctx.now.date() and value <= ctx.now.replace(second=59):
        return None
    if value.date() == ctx.now.date() and not re.search(r"[点时:：]", when):
        return None
    return iso(value)


@tool("transfer", "给联系人或手机号转账（含定时、每月周期转账）。只会生成待确认单，必须由用户在界面上确认；档位、风险由系统判定。"
      "payee/amount/when 请原样使用用户的说法。",
      {"payee": {"type": "string", "description": "用户说的收款人：姓名、称呼（小王/妈妈/房东）、手机号，或用途词（如“房租”“生活费”，系统按历史备注找人）"},
       "amount": {"type": "number", "description": "金额（元），必须是用户说出的数"},
       "when": {"type": "string", "description": "用户说的执行日期原话（如“明天”“11月5号”“下周五下午3点”）；立即转账不填"},
       "repeat": {"type": "string", "enum": ["none", "monthly"], "description": "用户明确说“每月”时为 monthly"},
       "memo": {"type": "string", "description": "用户说的备注/用途，原样填写，最多30字"},
       "from_account": {"type": "string", "enum": ["main", "savings"], "description": "付款账户，默认 main（储蓄卡活期）；用户说从储蓄账户时为 savings"}},
      ["payee"], write=True)
def transfer(ctx, payee="", amount=None, when=None, repeat="none", memo=None, from_account="main"):
    trace = []
    contact, payee_source = _resolve_payee(ctx, payee, trace)
    if amount is None and not ctx.selections.get("amount_cents"):
        last = contact.get("last_transfer")
        if last:
            raise NeedChoice(f"要给{contact['name']}转多少钱？", "amount_cents",
                             [{"label": f"按上次 {yuan(last['amount_cents'])}" + (f"（{last['memo']}）" if last.get("memo") else ""),
                               "value": last["amount_cents"], "hint": f"上次转账 {last['time'][:10]}"}])
        raise RuleError("need_info", f"要给{contact['name']}转多少钱？")
    cents = _check_amount(ctx, amount, trace)
    run_at = _check_date(ctx, when, trace)
    if repeat == "monthly" and not re.search(r"每个?月|每月", ctx.joined):
        repeat = "none"
    if repeat == "monthly" and not run_at:
        raise RuleError("need_info", "每月几号转？")
    memo_text = None
    if memo:
        memo_text = memo.strip()[:30]
        if not ctx.mentions(memo_text):
            trace.append(provenance_step("备注", False, "备注不在用户原话里，已忽略"))
            memo_text = None
    source_id = ctx.user_id + ("-savings" if from_account == "savings" else "-main")
    signals = fraud_signals(ctx.texts)
    params = {"source_account_id": source_id, "target_account_id": contact["account_id"],
              "payee_contact_id": contact["contact_id"], "payee_name": contact["name"] if contact["is_contact"] else contact["name"],
              "payee_display": contact["display"], "via_phone": contact.get("via_phone"), "amount_cents": cents,
              "memo": memo_text, "run_at": run_at, "repeat": repeat if run_at else "none", "arrival": "instant",
              "signals": signals}
    params = {k: v for k, v in params.items() if v not in (None, "")}
    try:
        result = ctx.kernel.propose(ctx.user_id, "transfer", params, turn_id=ctx.turn_id,
                                provenance={"payee": payee_source, "amount": "user_text" if not ctx.selections.get("amount_cents") else "user_selected",
                                            "date": "user_text" if run_at else None})
    except RuleError as error:
        if error.code != "insufficient_funds" or from_account == "savings":
            raise
        shortfall = error.detail.get("shortfall_cents", 0)
        savings = ctx.kernel.db.execute("SELECT * FROM accounts WHERE account_id=?", (ctx.user_id + "-savings",)).fetchone()
        if not savings or savings["balance_cents"] - savings["reserved_cents"] < shortfall:
            raise
        top_up = -(-shortfall // 10000) * 10000  # 向上取整到百元
        top_up = min(top_up, savings["balance_cents"] - savings["reserved_cents"])
        trace.append(step("tool", f"余额不足：差 {yuan(shortfall)}，储蓄账户可用 {yuan(savings['balance_cents'] - savings['reserved_cents'])}", "warned"))
        raise NeedChoice(f"{error.message} 可以先从储蓄账户（尾号{savings['tail']}）转入，再完成这笔转账。", "recovery", [
            {"label": f"先从储蓄账户转入 {yuan(top_up)}", "value": "top_up", "hint": "两步：① 账户互转（黄档）② 再转账",
             "tool": "move_funds", "args": {"amount": top_up / 100, "direction": "savings_to_main"},
             "then": f"给{contact['name']}转{yuan(cents)}", "selections": {"amount_cents": top_up}},
            {"label": f"直接从储蓄账户付这 {yuan(cents)}", "value": "pay_from_savings", "hint": "付款账户改为储蓄账户",
             "tool": "transfer", "args": dict(payee=payee, amount=amount, when=when, repeat=repeat, memo=memo, from_account="savings")},
            {"label": "先不转了", "value": "cancel", "hint": ""}])
    pending = result["pending"]
    trace.append(step("tier", result["tier_reason"], "pending", {"tier": result["tier"]}))
    if result.get("risk"):
        r = result["risk"]
        trace.append(step("risk", f"反诈评分 {r['score']}（{ {'medium': '中风险', 'high': '高风险'}[r['level']] }）：" + "；".join(r["reasons"]),
                          "warned", {"score": r["score"], "level": r["level"]}))
    else:
        trace.append(step("risk", "反诈评分 < 30（低风险）", "pass"))
    return ToolOutcome(pending_for_model(pending), pending=pending, trace=trace)


@tool("cancel_pending", "取消一张还没确认的待确认单（用户说“算了”“第二笔不要了”时）。",
      {"ref": {"type": "string", "description": "待确认单编号，如 P1、P2；不填表示最近一张"}})
def cancel_pending(ctx, ref=None):
    rows = ctx.kernel.db.execute("SELECT request_id, view_json FROM requests WHERE user_id=? AND status='pending' ORDER BY created_at",
                                 (ctx.user_id,)).fetchall()
    rows = [r for r in rows if parse_iso(ctx.kernel.db.execute("SELECT expires_at FROM requests WHERE request_id=?", (r["request_id"],)).fetchone()[0]) > ctx.now]
    if not rows:
        return ToolOutcome({"status": "nothing_to_cancel", "message": "当前没有待确认的操作。"})
    target = rows[-1]
    if ref:
        m = re.search(r"([0-9]+)", ref)
        if m and 1 <= int(m.group(1)) <= len(rows):
            target = rows[int(m.group(1)) - 1]
    result = ctx.kernel.cancel(ctx.user_id, target["request_id"], ctx.turn_id)
    extra = {"note": "这张单还没确认，没有执行过任何操作，也没有锁定或扣过钱"}
    return ToolOutcome({"status": "cancelled", "title": result["title"], **extra},
                       blocks=[{"type": "note", "data": {"text": f"已取消：{result['title']}", "tone": "info"}}],
                       trace=[step("tool", f"取消待确认单：{result['title']}", "success")])


@tool("transfer_to_human", "用户要求转人工、或问题超出能力需要人工处理时，生成人工接管单。",
      {"summary": {"type": "string", "description": "一句话概括用户的问题"}}, ["summary"])
def transfer_to_human(ctx, summary=""):
    ticket = new_id("hd")
    with ctx.kernel.tx():
        ctx.kernel.db.execute("INSERT INTO handovers VALUES(?,?,?,?,?,NULL)",
                              (ticket, ctx.user_id, (summary or "用户请求人工服务")[:100], "waiting", iso(ctx.now)))
        ctx.kernel.audit(ctx.user_id, "handover", "green", "handover_created", "success", (summary or "")[:100],
                         actor="agent", turn_id=ctx.turn_id)
    return ToolOutcome({"status": "created", "ticket_id": ticket, "note": "模拟人工客服会在工作时间联系用户"},
                       blocks=[{"type": "handover", "data": {"ticket_id": ticket, "summary": (summary or "用户请求人工服务")[:100], "status": "waiting"}}])


# ---------------------------------------------------------------------------------------------- 写操作：账户互转、撤回、AA
@tool("move_funds", "本人账户之间转账，例如“从储蓄账户转5000到活期”。只生成待确认单。",
      {"amount": {"type": "number", "description": "金额（元），用户说出的数"},
       "direction": {"type": "string", "enum": ["savings_to_main", "main_to_savings"], "description": "savings_to_main=储蓄账户转入活期储蓄卡"}},
      ["amount", "direction"], write=True)
def move_funds(ctx, amount=None, direction="savings_to_main", then=None):
    trace = []
    cents = _check_amount(ctx, amount, trace)
    src, dst = ("-savings", "-main") if direction == "savings_to_main" else ("-main", "-savings")
    params = {"source_account_id": ctx.user_id + src, "target_account_id": ctx.user_id + dst, "amount_cents": cents}
    if then:
        params["then"] = then[:40]
    result = ctx.kernel.propose(ctx.user_id, "move_funds", params, turn_id=ctx.turn_id, provenance={"amount": "user_text"})
    trace.append(step("tier", result["tier_reason"], "pending"))
    return ToolOutcome(pending_for_model(result["pending"]), pending=result["pending"], trace=trace)


@tool("revoke_transfer", "撤回一笔还没到账的延时到账转账（用户说“撤回刚才那笔”）。只生成待确认单。",
      {"payee": {"type": "string", "description": "可选：用户说的收款人，用于区分多笔在途转账"}}, write=True)
def revoke_transfer(ctx, payee=None, transfer_id=None):
    rows = ctx.kernel.db.execute("SELECT * FROM transfers WHERE user_id=? AND status='in_transit' ORDER BY created_at DESC",
                                 (ctx.user_id,)).fetchall()
    if transfer_id:
        rows = [r for r in rows if r["transfer_id"] == transfer_id]
    elif payee:
        named = [r for r in rows if payee in r["payee_name"] or r["payee_name"] in payee]
        rows = named or rows
    if not rows:
        raise RuleError("not_found", "现在没有可以撤回的在途转账（只有选择了延时到账、还没到账的转账才能撤回）。")
    row = rows[0]
    result = ctx.kernel.propose(ctx.user_id, "revoke_transfer", {"transfer_id": row["transfer_id"]}, turn_id=ctx.turn_id)
    return ToolOutcome(pending_for_model(result["pending"]), pending=result["pending"],
                       trace=[step("tier", result["tier_reason"], "pending")])


@tool("aa_collect", "发起 AA 收款：用户说一起吃饭/活动花了多少钱、和谁 AA。人均由系统计算，只生成待确认单。",
      {"total_amount": {"type": "number", "description": "总金额（元），用户说出的数"},
       "participants": {"type": "array", "items": {"type": "string"}, "description": "用户说的一起分摊的人（称呼/姓名），不含用户自己"},
       "include_self": {"type": "boolean", "description": "用户自己是否也分摊一份，默认 true"},
       "memo": {"type": "string", "description": "用途，如“昨晚聚餐”"}},
      ["total_amount", "participants"], write=True)
def aa_collect(ctx, total_amount=None, participants=None, include_self=True, memo=None):
    trace = []
    total = _check_amount(ctx, total_amount, trace, field="总金额")
    ids, names = [], []
    for who in (participants or [])[:10]:
        if not ctx.mentions(who):
            trace.append(provenance_step("AA 对象", False, f"“{who}”不在用户原话里"))
            raise RuleError("provenance", "AA 的对象必须是你本人说的人，请告诉我和谁一起分摊。")
        matches = [m for m in resolvers.contact_matches(ctx.kernel, ctx.user_id, who) if m["is_contact"]]
        if not matches:
            raise RuleError("not_found", f"联系人里没有“{who}”。")
        if len(matches) > 1:
            chosen = ctx.selections.get("aa:" + who)
            match = next((m for m in matches if m["contact_id"] == chosen), None)
            if match is None:
                raise NeedChoice(f"“{who}”有 {len(matches)} 位，是哪一位？", "aa:" + who,
                                 [{"label": m["display"], "value": m["contact_id"], "hint": m["relation"]} for m in matches])
            matches = [match]
        ids.append(matches[0]["contact_id"])
        names.append(matches[0]["name"])
    if not ids:
        raise RuleError("need_info", "和谁一起 AA？")
    trace.append(provenance_step("AA 对象", True, "、".join(names)))
    memo_text = memo.strip()[:20] if memo and ctx.mentions(memo.strip()[:20]) else None
    params = {"total_cents": total, "contact_ids": ids, "include_self": include_self is not False}
    if memo_text:
        params["memo"] = memo_text
    result = ctx.kernel.propose(ctx.user_id, "aa_collect", params, turn_id=ctx.turn_id,
                                provenance={"total": "user_text", "per_person": "代码计算（总额 ÷ 人数）"})
    trace.append(step("resolver", f"人均由代码计算：{yuan(total)} ÷ {len(ids) + (1 if include_self is not False else 0)} 人", "pass"))
    trace.append(step("tier", result["tier_reason"], "pending"))
    return ToolOutcome(pending_for_model(result["pending"]), pending=result["pending"], trace=trace)


@tool("list_aa_requests", "查看 AA 收款：我发起的和别人发给我的。")
def list_aa_requests(ctx):
    from ..core.ops_more import aa_requests_for
    items = aa_requests_for(ctx.kernel, ctx.user_id)
    return ToolOutcome({"items": [{"from": i["from_name"], "payer": i["payer_name"], "amount": yuan(i["amount_cents"]), "memo": i["memo"],
                                   "status": i["status"], "direction": i["direction"]} for i in items[:10]]},
                       blocks=[{"type": "aa_request", "data": i} for i in items[:6]])


@tool("pay_aa", "支付别人发给我的 AA 收款请求（用户说“付一下AA”）。只生成待确认单。",
      {"from_name": {"type": "string", "description": "可选：发起人姓名"}}, write=True)
def pay_aa(ctx, from_name=None, aa_id=None):
    from ..core.ops_more import aa_requests_for
    items = [i for i in aa_requests_for(ctx.kernel, ctx.user_id) if i["direction"] == "incoming" and i["status"] == "open"]
    if aa_id:
        items = [i for i in items if i["request_id"] == aa_id]
    elif from_name:
        items = [i for i in items if from_name in i["from_name"]] or items
    if not items:
        raise RuleError("not_found", "现在没有待你支付的 AA 收款。")
    result = ctx.kernel.propose(ctx.user_id, "aa_pay", {"aa_id": items[0]["request_id"]}, turn_id=ctx.turn_id)
    return ToolOutcome(pending_for_model(result["pending"]), pending=result["pending"],
                       trace=[step("tier", result["tier_reason"], "pending")])


from . import tools_more  # noqa: E402,F401  注册其余工具
