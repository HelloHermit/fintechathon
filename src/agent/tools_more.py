"""账单、卡片、订阅、理财工具。参数溯源：卡、产品、订阅必须由用户原话提到（名称/别名/尾号）、用户点选，或名下唯一。"""

import json
import re

from ..core import views
from ..core.kernel import NeedChoice, RuleError
from ..core.ops_cards import (CARD_STATUS, QUESTIONNAIRE, RISK_LABELS, questionnaire_block, subscription_items, valid_profile)
from ..core.seed import PRODUCT_DISCLAIMER
from ..core.util import iso, new_id, yuan
from .guard import wrap_external
from .tools import (ToolOutcome, _check_amount, cents_from, pending_for_model, provenance_step, step, tool)


def _propose(ctx, intent, params, trace, provenance=None):
    result = ctx.kernel.propose(ctx.user_id, intent, params, turn_id=ctx.turn_id, provenance=provenance or {})
    trace.append(step("tier", result["tier_reason"], "pending", {"tier": result["tier"]}))
    return ToolOutcome(pending_for_model(result["pending"]), pending=result["pending"], trace=trace)


# ---------------------------------------------------------------------------------------------- 账单
@tool("detect_anomalies", "识别近期异常交易：凌晨境外大额、重复扣款、小额试探（盗刷前兆）、订阅涨价、可疑来账。")
def detect_anomalies(ctx):
    findings = ctx.kernel.analytics.anomalies(ctx.user_id, ctx.now)
    sev = {"high": "高风险", "medium": "中风险", "low": "低风险"}
    return ToolOutcome({"count": len(findings), "findings": [
        {"severity": sev[f["severity"]], "time": f["time"][:16].replace("T", " "), "merchant": wrap_external(f["merchant"], 40),
         "amount": yuan(abs(f["amount_cents"])), "rule": f["rule"], "explanation": f["explanation"]} for f in findings],
        "note": "每条发现在界面上带有“冻结这张卡”“这笔是我本人的”按钮。"},
        blocks=[{"type": "anomaly_list", "data": {"items": findings}}],
        trace=[step("tool", f"异常识别（代码规则）：{len(findings)} 处发现", "success")])


@tool("monthly_report", "生成某个月的账单报告（KPI、分类、趋势、异常、订阅支出）。",
      {"month": {"type": "string", "description": "YYYY-MM；用户说“10月”“这个月”“上个月”时换算后填写"}})
def monthly_report(ctx, month=None):
    if not month or not re.fullmatch(r"[0-9]{4}-[0-9]{2}", month):
        start, _, _ = ctx.kernel.analytics.resolve_period(month or "本月", ctx.now)
        month = f"{start.year}-{start.month:02d}"
    report = ctx.kernel.analytics.monthly_report(ctx.user_id, month)
    return ToolOutcome({"period": report["period"]["label"], "kpis": {k["label"]: k["value"] + (f"（{k['delta']}）" if k["delta"] else "") for k in report["kpis"]},
                        "sections": report["sections"]}, blocks=[{"type": "report", "data": report}])


@tool("annual_report", "生成年度消费报告：月度趋势、分类占比、要点。",
      {"year": {"type": "integer", "description": "年份；用户说“过去一年/最近12个月”时不填，并把 last12 设为 true"},
       "last12": {"type": "boolean"}})
def annual_report(ctx, year=None, last12=False):
    report = ctx.kernel.analytics.annual_report(ctx.user_id, None if last12 or not year else int(year))
    return ToolOutcome({"period": report["period"]["label"], "kpis": {k["label"]: k["value"] for k in report["kpis"]},
                        "sections": report["sections"]}, blocks=[{"type": "report", "data": report}])


@tool("cashflow_forecast", "预测未来一段时间的资金情况：当前可用余额、已排定的转账（如房租）、即将续费的订阅总额、预计工资。用于“下个月房租交得起吗”。",
      {"days": {"type": "integer", "description": "向后看多少天，默认 35"}})
def cashflow_forecast(ctx, days=35):
    from datetime import timedelta
    days = max(1, min(90, int(days or 35)))
    k, end = ctx.kernel, ctx.now + timedelta(days=days)
    account = k.db.execute("SELECT * FROM accounts WHERE account_id=?", (ctx.user_id + "-main",)).fetchone()
    available = account["balance_cents"] - account["reserved_cents"]
    scheduled = [s for s in views.scheduled(k, ctx.user_id) if s["status"] == "scheduled" and s["run_at"] <= iso(end) and s.get("kind") in ("transfer", "order")]
    subs = [s for s in subscription_items(k, ctx.user_id) if s["status"] == "active" and s.get("next_charge_date") and s["next_charge_date"] <= end.date().isoformat()]
    salary = k.db.execute("""SELECT amount_cents FROM transactions WHERE user_id=? AND category='工资' ORDER BY time DESC LIMIT 1""", (ctx.user_id,)).fetchone()
    salary_days = []
    if salary:
        d = ctx.now.replace(day=10, hour=9, minute=30)
        for _ in range(3):
            if ctx.now < d <= end:
                salary_days.append(d.date().isoformat())
            d = (d.replace(day=1) + timedelta(days=32)).replace(day=10)
    out_sched = sum(s["amount_cents"] for s in scheduled if not s.get("revocable"))
    out_subs = sum(s["amount_cents"] for s in subs)
    income = (salary["amount_cents"] if salary else 0) * len(salary_days)
    lines = [{"label": "当前活期可用", "value": yuan(available)},
             {"label": f"{days} 天内已排定转出", "value": yuan(out_sched) + (f"（{'、'.join(s['title'] for s in scheduled[:3])}）" if scheduled else "")},
             {"label": f"{days} 天内订阅续费", "value": f"{yuan(out_subs)}（{len(subs)} 项）"},
             {"label": "预计工资入账", "value": yuan(income) + (f"（{'、'.join(salary_days)}）" if salary_days else "")},
             {"label": "预计期末可用", "value": yuan(available - out_sched - out_subs + income), "emphasis": True}]
    return ToolOutcome({"available": yuan(available), "scheduled_out": yuan(out_sched), "scheduled_items": [f"{s['title']} {yuan(s['amount_cents'])} {s['run_at'][:10]}" for s in scheduled],
                        "subscriptions_out": yuan(out_subs), "subscription_count": len(subs), "expected_salary": yuan(income),
                        "salary_dates": salary_days, "projected_available": yuan(available - out_sched - out_subs + income),
                        "enough": available - out_sched - out_subs >= 0},
                       blocks=[{"type": "receipt", "data": {"title": f"未来 {days} 天资金预估", "status": "success", "lines": lines, "request_id": "", "audit_hash": ""}}])


# ---------------------------------------------------------------------------------------------- 卡片
def _resolve_card(ctx, card, statuses=None, physical_only=False):
    rows = ctx.kernel.db.execute("SELECT * FROM cards WHERE user_id=? ORDER BY created_at, card_id", (ctx.user_id,)).fetchall()
    selected = ctx.selections.get("card_id")
    if selected:
        row = next((r for r in rows if r["card_id"] == selected), None)
        if row:
            return row, "user_selected"
    pool = [r for r in rows if (statuses is None or r["status"] in statuses) and (not physical_only or r["kind"] == "debit")]
    # 先看这一句话（避免上一件事里的“虚拟卡”影响这次的“卡丢了”），再看本次任务的上下文
    text = ctx.current + " " + (card if card and ctx.mentions(card) else "")
    tails = re.findall(r"(?<![0-9])([0-9]{4})(?![0-9])", text)
    candidates = [r for r in pool if r["tail"] in tails] if tails else []
    source = "用户说的尾号"
    if not candidates:
        if re.search(r"虚拟|网购", text):
            candidates, source = [r for r in pool if r["kind"] == "virtual"], "用户说的“虚拟卡/网购卡”"
        elif re.search(r"储蓄|借记|实体|银行卡|工资卡", text):
            candidates, source = [r for r in pool if r["kind"] == "debit"], "用户说的“储蓄卡”"
        else:
            candidates, source = pool, "名下唯一符合条件的卡"
    if len(candidates) == 1:
        return candidates[0], source
    if not candidates:
        raise RuleError("not_found", "没有找到符合条件的卡。" + ("" if statuses is None else f"（需要状态：{'/'.join(CARD_STATUS[s] for s in statuses)}）"))
    raise NeedChoice("是哪一张卡？", "card_id", [{"label": f"{r['name']} **** {r['tail']}", "value": r["card_id"],
                                                 "hint": CARD_STATUS[r["status"]]} for r in candidates])


@tool("list_cards", "查询本人的银行卡和虚拟卡：状态、每日限额、今日已用。")
def list_cards(ctx):
    cards = views.cards(ctx.kernel, ctx.user_id)
    return ToolOutcome({"cards": [{"name": c["name"], "tail": c["masked_no"][-4:], "status": CARD_STATUS[c["status"]],
                                   "daily_limit": yuan(c["daily_limit_cents"]), "today_spent": yuan(c["today_spent_cents"])} for c in cards]},
                       blocks=[{"type": "card_list", "data": {"items": cards}}])


CARD_ACTIONS = {"freeze": ("freeze_card", ("active",)), "unfreeze": ("unfreeze_card", ("frozen",)),
                "report_lost": ("report_card_lost", ("active", "frozen")), "restore": ("restore_card", ("lost",))}


@tool("card_action", "卡片状态操作：freeze=临时冻结、unfreeze=解冻、report_lost=正式挂失、restore=解挂（卡找到了）、"
      "lost=用户说卡丢了但没说要冻结还是挂失（系统会给两个选项）。只生成待确认单。",
      {"action": {"type": "string", "enum": ["freeze", "unfreeze", "report_lost", "restore", "lost"]},
       "card": {"type": "string", "description": "用户说的卡：尾号、“储蓄卡”“虚拟卡”等；没说就不填"}}, ["action"], write=True)
def card_action(ctx, action="", card=None):
    trace = []
    if action == "lost":
        row, source = _resolve_card(ctx, card, statuses=("active", "frozen"), physical_only=True)
        options = []
        if row["status"] == "active":
            options.append({"label": "立即临时冻结（推荐先做）", "value": "freeze", "hint": "黄档：点确认即可，找到后可解冻",
                            "tool": "card_action", "args": {"action": "freeze", "card": card or ""}, "selections": {"card_id": row["card_id"]}})
        options.append({"label": "正式挂失", "value": "report_lost", "hint": "红档：需要交易密码 + 动态码，卡片永久停用",
                        "tool": "card_action", "args": {"action": "report_lost", "card": card or ""}, "selections": {"card_id": row["card_id"]}})
        raise NeedChoice(f"别着急。{row['name']} **** {row['tail']} 要怎么处理？", "lost_choice", options)
    if action not in CARD_ACTIONS:
        raise RuleError("invalid_request", "不支持的卡片操作。")
    intent, statuses = CARD_ACTIONS[action]
    row, source = _resolve_card(ctx, card, statuses=statuses, physical_only=action in ("report_lost", "restore"))
    trace.append(provenance_step("卡片", True, f"{source} → **** {row['tail']}"))
    return _propose(ctx, intent, {"card_id": row["card_id"]}, trace)


@tool("set_card_limit", "调整卡片每日交易限额。下调为黄档，上调为红档（系统判定）。只生成待确认单。",
      {"card": {"type": "string", "description": "用户说的卡"}, "daily_limit": {"type": "number", "description": "新的每日限额（元），用户说出的数"}},
      ["daily_limit"], write=True)
def set_card_limit(ctx, card=None, daily_limit=None):
    trace = []
    row, source = _resolve_card(ctx, card, statuses=("active", "frozen"))
    trace.append(provenance_step("卡片", True, f"{source} → **** {row['tail']}"))
    cents = _check_amount(ctx, daily_limit, trace, field="限额")
    return _propose(ctx, "set_card_limit", {"card_id": row["card_id"], "daily_limit_cents": cents}, trace)


@tool("apply_virtual_card", "申请一张虚拟卡（网购、订阅专用等）。只生成待确认单。",
      {"purpose": {"type": "string", "description": "用途，如“网购”“订阅”"}, "daily_limit": {"type": "number", "description": "可选：用户说的每日限额（元）"}},
      write=True)
def apply_virtual_card(ctx, purpose=None, daily_limit=None):
    trace = []
    params = {"purpose": (purpose or "网购")[:10] if purpose and ctx.mentions(purpose[:2]) else "网购"}
    if daily_limit is not None:
        params["daily_limit_cents"] = _check_amount(ctx, daily_limit, trace, field="限额")
    return _propose(ctx, "apply_virtual_card", params, trace)


# ---------------------------------------------------------------------------------------------- 订阅
@tool("query_subscriptions", "查询订阅和自动扣费（含从流水自动识别的、涨价、闲置、即将续费标记）。按规定这是黄档：生成待确认单，用户确认后展示名单。",
      write=True)
def query_subscriptions(ctx):
    return _propose(ctx, "query_subscriptions", {}, [])


SUB_WORDS = {"健身": "健身", "视频": "视频", "音乐": "音乐", "云存储": "云存储", "云盘": "云存储", "读书": "读书", "网盘": "云存储"}


@tool("cancel_subscription", "取消一项订阅/自动续费（如“健身会员不要了”）。只生成待确认单。",
      {"name": {"type": "string", "description": "用户说的订阅名称或关键词"}}, ["name"], write=True)
def cancel_subscription(ctx, name="", subscription_id=None):
    trace = []
    items = [i for i in subscription_items(ctx.kernel, ctx.user_id) if i["status"] == "active"]
    if subscription_id or ctx.selections.get("subscription_id"):
        sid = subscription_id or ctx.selections.get("subscription_id")
        matches = [i for i in items if i["subscription_id"] == sid]
        source = "用户点选"
    else:
        keys = [w for w in list(SUB_WORDS) + [i["name"] for i in items] if w in ctx.joined]
        matches = [i for i in items if any(SUB_WORDS.get(k, k) in i["name"] for k in keys)]
        source = "用户原话“" + "、".join(keys) + "”" if keys else ""
    if not matches:
        raise NeedChoice("要取消哪一项订阅？", "subscription_id", [
            {"label": f"{i['name']} {yuan(i['amount_cents'])}/月", "value": i["subscription_id"], "hint": "、".join(
                {"price_up": "涨价", "idle": "闲置", "renew_soon": "即将续费"}[f] for f in i["flags"])} for i in items])
    if len(matches) > 1:
        raise NeedChoice("是哪一项？", "subscription_id", [{"label": i["name"], "value": i["subscription_id"], "hint": ""} for i in matches])
    trace.append(provenance_step("订阅", True, f"{source} → {matches[0]['name']}"))
    return _propose(ctx, "cancel_subscription", {"subscription_id": matches[0]["subscription_id"]}, trace)


# ---------------------------------------------------------------------------------------------- 理财
def _product_rows(ctx):
    return ctx.kernel.db.execute("SELECT * FROM products ORDER BY risk_level, term_days").fetchall()


def _product_for_model(row, suitable=None):
    data = {"name": row["name"], "type": row["type"], "risk": row["risk_level"],
            "term": "随时可取" if row["term_days"] == 0 else f"{row['term_days']}天", "yield": row["yield_text"],
            "min": yuan(row["min_amount_cents"]), "description": wrap_external(row["description"], 80)}
    if suitable is not None:
        data["suitable_for_user"] = suitable
    return data


def _match_products(ctx, names=None):
    """只认用户原话里出现的产品名或别名（模型给的名字不能作为来源）。先看这一句，没有再看本次任务上下文。"""
    rows = _product_rows(ctx)
    for text in (ctx.current, ctx.joined):
        found = [row for row in rows if any(w and w in text for w in [row["name"]] + json.loads(row["aliases"]))]
        if found:
            return found
    return []


def _suitability(ctx):
    level = valid_profile(ctx.kernel, ctx.user_id)
    return level, (lambda row: None if level is None else int(row["risk_level"][1:]) <= int(level[1:]))


@tool("list_products", "查询理财产品列表（含风险等级、期限、收益说明）。")
def list_products(ctx):
    level, ok = _suitability(ctx)
    rows = _product_rows(ctx)
    items = [dict(views.product(r), suitable=ok(r)) for r in rows]
    return ToolOutcome({"risk_profile": level and f"{level} {RISK_LABELS[level]}", "products": [_product_for_model(r, ok(r)) for r in rows],
                        "disclaimer": PRODUCT_DISCLAIMER}, blocks=[{"type": "product_list", "data": {"items": items, "disclaimer": PRODUCT_DISCLAIMER}}])


@tool("compare_products", "对比 2–4 个理财产品。", {"names": {"type": "array", "items": {"type": "string"}, "description": "用户说的产品名称"}}, ["names"])
def compare_products(ctx, names=None):
    rows = _match_products(ctx, names or [])
    if len(rows) < 2:
        raise RuleError("need_info", "请告诉我要对比哪几个产品（至少两个），例如“活钱宝和稳健季享”。")
    rows = rows[:4]
    level, ok = _suitability(ctx)
    table = [{"label": "类型", "values": [r["type"] for r in rows]}, {"label": "风险等级", "values": [r["risk_level"] for r in rows]},
             {"label": "期限", "values": ["随时可取" if r["term_days"] == 0 else f"{r['term_days']} 天" for r in rows]},
             {"label": "流动性", "values": [r["liquidity"] for r in rows]}, {"label": "收益说明", "values": [r["yield_text"] for r in rows]},
             {"label": "起购", "values": [yuan(r["min_amount_cents"]) for r in rows]},
             {"label": "适合你", "values": ["需先测评" if ok(r) is None else ("适合" if ok(r) else "不适合") for r in rows]}]
    return ToolOutcome({"products": [_product_for_model(r, ok(r)) for r in rows], "disclaimer": PRODUCT_DISCLAIMER},
                       blocks=[{"type": "product_compare", "data": {"products": [views.product(r) for r in rows], "rows": table,
                                                                     "disclaimer": PRODUCT_DISCLAIMER}}])


@tool("recommend_products", "按用户的风险测评等级、投资期限和偏好推荐理财产品（代码过滤，标注是否适合）。没有有效测评时会提示先测评。",
      {"horizon_days": {"type": "integer", "description": "用户说的投资期限换算成天数，如“半年”=180；没说不填"},
       "preference": {"type": "string", "enum": ["stable", "balanced", "growth", "liquid"], "description": "stable=稳一点，liquid=随时要用"}})
def recommend_products(ctx, horizon_days=None, preference="stable"):
    level, ok = _suitability(ctx)
    rows = _product_rows(ctx)
    if horizon_days:
        rows = [r for r in rows if r["term_days"] <= int(horizon_days)]
    if preference == "liquid":
        rows = [r for r in rows if r["term_days"] <= 30]
    if preference == "stable":
        rows = [r for r in rows if r["risk_level"] in ("R1", "R2")]
    items = [dict(views.product(r), suitable=ok(r)) for r in rows]
    blocks = [{"type": "product_list", "data": {"items": items, "disclaimer": PRODUCT_DISCLAIMER}}]
    result = {"risk_profile": level and f"{level} {RISK_LABELS[level]}", "products": [_product_for_model(r, ok(r)) for r in rows],
              "disclaimer": PRODUCT_DISCLAIMER}
    if level is None:
        qid = new_id("q")
        ctx.kernel.questionnaires[qid] = ctx.user_id
        blocks.append(questionnaire_block(qid))
        result["note"] = "用户没有有效的风险测评，界面已展示测评问卷；购买前必须先完成测评。"
    return ToolOutcome(result, blocks=blocks)


@tool("start_risk_assessment", "给用户展示风险测评问卷（6 道题）。用户提交后由系统计分定级。")
def start_risk_assessment(ctx):
    qid = new_id("q")
    ctx.kernel.questionnaires[qid] = ctx.user_id
    level = valid_profile(ctx.kernel, ctx.user_id)
    return ToolOutcome({"status": "questionnaire_shown", "current_profile": level and f"{level} {RISK_LABELS[level]}",
                        "note": "界面已展示问卷，请用户逐题选择后提交。"}, blocks=[questionnaire_block(qid)])


@tool("get_holdings", "查询本人理财持仓、收益、可赎回金额和风险测评结果。")
def get_holdings(ctx):
    items = views.holdings(ctx.kernel, ctx.user_id)
    profile = views.risk_profile(ctx.kernel, ctx.user_id)
    return ToolOutcome({"holdings": [{"name": h["name"], "amount": yuan(h["amount_cents"]), "profit": yuan(h["profit_cents"]),
                                      "redeemable": yuan(h["redeemable_cents"]), "matures_at": h["matures_at"][:10]} for h in items],
                        "total_profit": yuan(sum(h["profit_cents"] for h in items)),
                        "risk_profile": (f"{profile['level']} {profile['label']}" + ("" if profile["valid"] else "（已过期）")) if profile else None},
                       blocks=[{"type": "holding_list", "data": {"items": items}}])


def _resolve_product(ctx, product, rows=None):
    rows = rows if rows is not None else _product_rows(ctx)
    selected = ctx.selections.get("product_id")
    if selected:
        row = next((r for r in rows if r["product_id"] == selected), None)
        if row:
            return row, "用户点选"
    found = _match_products(ctx, [product or ""])
    found = [r for r in found if r in rows] if rows is not None else found
    if len(found) == 1:
        return found[0], f"用户原话提到“{found[0]['name']}”"
    if len(rows) == 1 and not found:
        return rows[0], "名下唯一持有"
    candidates = found or rows
    raise NeedChoice("是哪个产品？", "product_id", [{"label": r["name"], "value": r["product_id"], "hint": f"{r['risk_level']} · {r['yield_text']}"} for r in candidates])


@tool("purchase_product", "申购理财产品。系统会检查风险测评与适当性（不匹配直接拒绝），通过后为红档强验证。只生成待确认单。",
      {"product": {"type": "string", "description": "用户说的产品名称"}, "amount": {"type": "number", "description": "金额（元），用户说出的数"}},
      ["product", "amount"], write=True)
def purchase_product(ctx, product="", amount=None):
    trace = []
    row, source = _resolve_product(ctx, product)
    trace.append(provenance_step("产品", True, f"{source}"))
    cents = _check_amount(ctx, amount, trace)
    try:
        return _propose(ctx, "purchase_product", {"product_id": row["product_id"], "amount_cents": cents}, trace)
    except RuleError as error:
        if error.code == "need_assessment":
            qid = new_id("q")
            ctx.kernel.questionnaires[qid] = ctx.user_id
            return ToolOutcome({"status": "need_assessment", "message": error.message, "note": "界面已展示风险测评问卷。"},
                               blocks=[{"type": "note", "data": {"text": error.message, "tone": "warning"}}, questionnaire_block(qid)],
                               trace=trace + [step("tier", "适当性：没有有效风险测评，先测评", "blocked")])
        if error.code == "unsuitable":
            trace.append(step("tier", "适当性拦截：" + error.message, "blocked"))
        raise


@tool("redeem_product", "赎回已到期（或随时可取）的理财持仓到活期。只生成待确认单。",
      {"product": {"type": "string", "description": "用户说的产品名称"}, "amount": {"type": "number", "description": "金额（元）；用户说“全部”时不填并设 all=true"},
       "all": {"type": "boolean"}}, ["product"], write=True)
def redeem_product(ctx, product="", amount=None, all=False):
    trace = []
    held = [r for r in _product_rows(ctx) if any(h["product_id"] == r["product_id"] for h in views.holdings(ctx.kernel, ctx.user_id))]
    if not held:
        raise RuleError("not_found", "你目前没有理财持仓。")
    row, source = _resolve_product(ctx, product, held)
    trace.append(provenance_step("产品", True, source))
    if all or (amount is None and re.search(r"全部|都赎|全赎", ctx.joined)):
        cents = "all"
    else:
        cents = _check_amount(ctx, amount, trace)
    return _propose(ctx, "redeem_product", {"product_id": row["product_id"], "amount_cents": cents}, trace)


# ---------------------------------------------------------------------------------------------- 定时任务
@tool("list_scheduled", "查询本人的定时任务（定时/每月转账、计划里的订单）和延时到账中的转账。")
def list_scheduled(ctx):
    items = [s for s in views.scheduled(ctx.kernel, ctx.user_id) if s["status"] in ("scheduled", "needs_reauth")]
    return ToolOutcome({"items": [{"title": s["title"], "amount": yuan(s["amount_cents"]), "run_at": s["run_at"][:16].replace("T", " "),
                                   "repeat": s["repeat"], "status": s["status"]} for s in items]},
                       blocks=[{"type": "scheduled_list", "data": {"items": items}}])


@tool("cancel_scheduled", "取消一个定时任务（如“下个月房租先别自动转了”）。只生成待确认单。",
      {"keyword": {"type": "string", "description": "用户说的任务关键词，如收款人或用途"}}, ["keyword"], write=True)
def cancel_scheduled(ctx, keyword="", schedule_id=None):
    rows = ctx.kernel.db.execute("SELECT * FROM schedules WHERE user_id=? AND status IN ('scheduled','needs_reauth') ORDER BY run_at",
                                 (ctx.user_id,)).fetchall()
    if schedule_id or ctx.selections.get("schedule_id"):
        sid = schedule_id or ctx.selections.get("schedule_id")
        rows = [r for r in rows if r["schedule_id"] == sid]
    else:
        rows = [r for r in rows if any(w and w in ctx.joined and (w in r["title"] or w in r["params_json"]) for w in
                                       re.findall(r"[\u4e00-\u9fa5]{2,}", r["title"] + " " + r["params_json"]))] or rows
    if not rows:
        raise RuleError("not_found", "没有可以取消的定时任务。")
    if len(rows) > 1:
        raise NeedChoice("要取消哪一个定时任务？", "schedule_id", [{"label": f"{r['title']} {yuan(r['amount_cents'])}", "value": r["schedule_id"],
                                                                  "hint": r["run_at"][:10]} for r in rows])
    return _propose(ctx, "cancel_scheduled", {"schedule_id": rows[0]["schedule_id"]}, [])


# ---------------------------------------------------------------------------------------------- 计划（跨场景联动）
from ..core import plans as plan_engine  # noqa: E402
from . import resolvers  # noqa: E402


@tool("create_plan", "为家人朋友的生日生成筹备计划：锁定预算 → 生日前 2 天订鲜花和蛋糕 → 当天提醒；用户一次确认整个计划。"
      "用于“我老婆下个月12号生日，帮我准备一下”。",
      {"person": {"type": "string", "description": "用户说的人（称呼或姓名，如“老婆”“妈妈”）"},
       "date": {"type": "string", "description": "用户说的生日日期原话；没说就不填（用联系人登记的生日）"},
       "budget": {"type": "number", "description": "用户说的预算（元）；没说不填，默认 1000"}}, ["person"], write=True)
def create_plan(ctx, person="", date=None, budget=None):
    trace = []
    if not person or not ctx.mentions(person):
        raise RuleError("provenance", "要给谁准备？请告诉我对方的称呼或名字。")
    matches = [m for m in resolvers.contact_matches(ctx.kernel, ctx.user_id, person) if m["is_contact"]]
    if len(matches) != 1:
        raise RuleError("not_found", f"联系人里没有找到唯一的“{person}”。")
    contact = matches[0]
    trace.append(provenance_step("对象", True, f"用户原话“{person}” → {contact['display']}"))
    event = None
    if date:
        value, note = resolvers.resolve_date(date, ctx.now)
        if value is None or value.date().isoformat() not in resolvers.scan_dates(ctx.texts, ctx.now):
            raise RuleError("provenance", "生日日期请以你说的为准，能再说一下是哪天吗？")
        event = value
        trace.append(provenance_step("日期", True, f"用户原话“{date}” → {value:%Y-%m-%d}"))
    cents = 100000
    if budget is not None:
        cents = _check_amount(ctx, budget, trace, field="预算")
    plan = plan_engine.create_birthday_plan(ctx.kernel, ctx.user_id, contact["contact_id"], event, cents, source="chat")
    trace.append(step("plan", f"计划模板：生日筹备（{len(plan['nodes'])} 个节点，依赖关系 n1→n2/n3→n4）", "pass"))
    result = ctx.kernel.propose(ctx.user_id, "plan", {"plan_id": plan["plan_id"]}, turn_id=ctx.turn_id, plan_id=plan["plan_id"],
                                provenance={"person": "user_text", "date": "user_text" if date else "联系人登记的生日"})
    trace.append(step("tier", result["tier_reason"], "pending"))
    out = ToolOutcome(dict(pending_for_model(result["pending"]), plan_nodes=[n["title"] for n in plan["nodes"]]),
                      blocks=[{"type": "plan", "data": plan_engine.view(plan_engine.load(ctx.kernel, ctx.user_id, plan["plan_id"]))}],
                      pending=result["pending"], trace=trace)
    out.plan = plan_engine.view(plan_engine.load(ctx.kernel, ctx.user_id, plan["plan_id"]))
    return out


def _active_plan(ctx):
    row = ctx.kernel.db.execute("""SELECT plan_id FROM plans WHERE user_id=? AND status IN ('running','paused','awaiting_confirmation','failed')
        ORDER BY created_at DESC LIMIT 1""", (ctx.user_id,)).fetchone()
    if row is None:
        raise RuleError("not_found", "你现在没有进行中的计划。")
    return row[0]


@tool("plan_control", "控制进行中的计划：pause=暂停、resume=继续、rollback=全部取消并回退（释放预算）、takeover=转人工、"
      "cancel_node=只取消其中一步（如“先别订蛋糕了”，node 填“蛋糕”）。",
      {"action": {"type": "string", "enum": ["pause", "resume", "rollback", "takeover", "cancel_node"]},
       "node": {"type": "string", "description": "cancel_node 时用户说的那一步，如“蛋糕”“鲜花”"}}, ["action"])
def plan_control(ctx, action="", node=None):
    plan_id = _active_plan(ctx)
    hint = None
    if action == "cancel_node":
        hint = [w for w in ("蛋糕", "鲜花", "花") if w in ctx.current or (node and w in node and ctx.mentions(w))]
        if not hint:
            raise RuleError("need_info", "要取消计划里的哪一步？鲜花还是蛋糕？")
    plan, note = plan_engine.control(ctx.kernel, ctx.user_id, plan_id, action, hint, ctx.turn_id, actor="user")
    if plan["status"] == "awaiting_confirmation":
        # 确认前修改计划：旧确认单作废，按新节点重新生成一张整体确认单
        result = ctx.kernel.propose(ctx.user_id, "plan", {"plan_id": plan_id}, turn_id=ctx.turn_id, plan_id=plan_id,
                                    provenance={"change": "用户要求去掉一步"})
        out = ToolOutcome(dict(pending_for_model(result["pending"]), message=note),
                          pending=result["pending"], trace=[step("plan", note, "success"), step("tier", result["tier_reason"], "pending")])
        out.plan = plan_engine.view(plan_engine.load(ctx.kernel, ctx.user_id, plan_id))
        return out
    extra_blocks = []
    if action == "takeover" and plan.get("handover_ticket"):
        extra_blocks.append({"type": "handover", "data": {"ticket_id": plan["handover_ticket"], "summary": f"计划“{plan['title']}”转人工处理",
                                                          "status": "waiting"}})
    out = ToolOutcome({"status": "done", "plan_status": plan["status"], "message": note},
                      blocks=extra_blocks + [{"type": "plan", "data": plan_engine.view(plan)}, {"type": "note", "data": {"text": note, "tone": "info"}}],
                      trace=[step("plan", f"计划控制：{action} → {plan['status']}", "success")])
    out.plan = plan_engine.view(plan)
    return out


@tool("list_plans", "查看我的计划及进度。")
def list_plans(ctx):
    items = ctx.kernel.ops.plan_summaries(ctx.user_id)
    blocks = [{"type": "plan", "data": ctx.kernel.ops.plan_view(ctx.user_id, i["plan_id"])} for i in items[:3]]
    return ToolOutcome({"plans": [{"title": i["title"], "status": i["status"], "progress": f"{i['done_count']}/{i['node_count']}"} for i in items]},
                       blocks=blocks)


# ---------------------------------------------------------------------------------------------- 沙箱分析
from ..core import sandbox  # noqa: E402


@tool("run_analysis", "固定报表回答不了的长尾分析（如“周末和工作日外卖平均各花多少”“哪个月打车最多”）：你写一段 Python，"
      "系统在受限沙箱里运行。代码必须定义 def analyze(transactions)，返回可 JSON 序列化的结果（dict/list/数字）。"
      "transactions 是本人近 13 个月交易列表，每项字段：time(ISO), date(YYYY-MM-DD), weekday(0=周一…6=周日), hour, merchant, category, "
      "amount(元，支出为负), amount_cents。只能 from math/statistics/collections/datetime/itertools import …；不能读写文件、联网。",
      {"question": {"type": "string", "description": "用户的问题"}, "code": {"type": "string", "description": "Python 代码，≤2000 字符"}},
      ["question", "code"])
def run_analysis(ctx, question="", code=""):
    data = sandbox.snapshot(ctx.kernel, ctx.user_id)
    result = sandbox.run(code, data)
    block = {"type": "code_analysis", "data": {"question": question[:100], "code": code[:2000], "engine": result["engine"],
                                                "limits": result["limits"], "duration_ms": result["duration_ms"],
                                                "status": result["status"], "result": result["result"],
                                                **({"reason": result["reason"]} if result.get("reason") else {})}}
    with ctx.kernel.tx():
        ctx.kernel.audit(ctx.user_id, "run_analysis", "green", "sandbox_run", result["status"], (result.get("reason") or "运行完成")[:100],
                         actor="agent", turn_id=ctx.turn_id,
                         params={"code_hash": result["code_hash"], "engine": result["engine"], "duration_ms": result["duration_ms"],
                                 "exit": result.get("exit"), "limits": result["limits"]})
    label = {"ok": "success", "rejected": "blocked", "error": "failed"}[result["status"]]
    trace = [step("tool", f"沙箱分析（{result['engine']}）：AST 白名单{'通过' if result['status'] != 'rejected' else '拒绝：' + result['reason']}；"
                          f"{result['duration_ms']} 毫秒", label, {"code_hash": result["code_hash"][:16], "engine": result["engine"]})]
    first = data[0]["date"] if data else ""
    model_result = {"status": result["status"], "result": result["result"],
                    "data_range": f"近 13 个月（{first} 至 {ctx.now:%Y-%m-%d}，共 {len(data)} 笔）"}
    if result.get("reason"):
        model_result["reason"] = result["reason"]
        model_result["note"] = "可以修正代码后再调用一次。"
    return ToolOutcome(model_result, blocks=[block], trace=trace)
