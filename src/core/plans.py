"""计划引擎（PLAN X1–X5）：DAG 计划、整体确认、定时节点、暂停/继续/回退/转人工，全部持久化在库里。

- 计划的档位 = 节点档位的最高值（代码计算）；一次确认绑定全部节点参数的哈希；任一红档节点 → 整体一次强验证。
- 定时节点由调度器到点执行，执行前按执行日重新判档；超出授权档位 → 节点失败并通知，不偷偷执行。
- 回退：取消未执行的节点、释放预算（补偿动作）；已执行的订单保留并如实标注。
"""

import json
from datetime import datetime, timedelta

from .kernel import SMALL_LIMIT_CENTS, RuleError
from .ops import Handler
from .ops_cards import create_budget, pay_order_from_budget, release_budget
from .util import SHANGHAI, canonical, human_datetime, iso, new_id, parse_iso, sha256_hex, yuan

TIER_ORDER = {"green": 0, "yellow": 1, "red": 2}
TERMINAL = {"success", "failed", "skipped", "rolled_back"}
NODE_TIER_LABEL = {"green": "绿", "yellow": "黄", "red": "红"}


def load(k, user_id, plan_id):
    row = k.db.execute("SELECT * FROM plans WHERE plan_id=? AND user_id=?", (plan_id, user_id)).fetchone()
    if row is None:
        raise RuleError("not_found", "没有找到这个计划。")
    plan = json.loads(row["plan_json"])
    plan["status"] = row["status"]
    return plan


def save(k, user_id, plan):
    k.db.execute("UPDATE plans SET status=?, plan_json=?, updated_at=? WHERE plan_id=? AND user_id=?",
                 (plan["status"], canonical(plan), iso(k.now()), plan["plan_id"], user_id))


def actions_for(status):
    return {"awaiting_confirmation": ["takeover"], "running": ["pause", "rollback", "takeover"],
            "paused": ["resume", "rollback", "takeover"], "draft": ["takeover"]}.get(status, [])


def view(plan):
    return {"plan_id": plan["plan_id"], "title": plan["title"], "status": plan["status"], "created_at": plan["created_at"],
            "nodes": [{k: n.get(k) for k in ("id", "title", "intent", "tier", "status", "depends_on", "run_at", "result_summary",
                                             "compensation")} for n in plan["nodes"]],
            "actions": actions_for(plan["status"]), "budget_id": plan.get("budget_id")}


def summary(plan):
    return {"plan_id": plan["plan_id"], "title": plan["title"], "status": plan["status"], "created_at": plan["created_at"],
            "node_count": len(plan["nodes"]), "done_count": sum(1 for n in plan["nodes"] if n["status"] == "success")}


def node_tiers(k, user_id, plan):
    """代码判档：预算锁定黄档；订单按执行日累计判档；提醒绿档。"""
    by_day = {}
    for node in plan["nodes"]:
        if node["status"] == "skipped":
            node["tier"] = "green"
            continue
        if node["intent"] == "place_order":
            day = parse_iso(node["run_at"]).date().isoformat()
            by_day.setdefault(day, k.ops.daily_outgoing(user_id, day) + k.ops.scheduled_outgoing(user_id, day))
            by_day[day] += node["params"]["price_cents"]
            node["tier"] = "red" if by_day[day] > SMALL_LIMIT_CENTS else "yellow"
        elif node["intent"] == "reserve_budget":
            node["tier"] = "yellow"
        else:
            node["tier"] = "green"
    return max((n["tier"] for n in plan["nodes"]), key=lambda t: TIER_ORDER[t])


def create_birthday_plan(k, user_id, contact_id, event_date=None, budget_cents=100000, source="insight"):
    contact = k.db.execute("SELECT * FROM contacts WHERE contact_id=? AND user_id=?", (contact_id, user_id)).fetchone()
    if contact is None:
        raise RuleError("forbidden", "只能为你的联系人创建生日计划。")
    now = k.now()
    if event_date is None:
        if not contact["birthday"]:
            raise RuleError("need_info", f"不知道{contact['name']}的生日是哪天，请告诉我日期。")
        month, day = map(int, contact["birthday"].split("-"))
        event = datetime(now.year, month, day, 9, 0, tzinfo=SHANGHAI)
        if event.date() < now.date():
            event = event.replace(year=now.year + 1)
    else:
        event = event_date.replace(hour=9, minute=0, second=0, microsecond=0)
    if event.date() <= now.date() + timedelta(days=2):
        raise RuleError("invalid_date", "离生日不到 3 天，来不及按计划提前 2 天订花和蛋糕了。可以直接说“帮我订鲜花”。")
    existing = k.db.execute("""SELECT plan_id FROM plans WHERE user_id=? AND status IN ('awaiting_confirmation','running','paused')
        AND plan_json LIKE ?""", (user_id, '%"contact_id":"' + contact_id + '"%')).fetchone()
    if existing:
        plan = load(k, user_id, existing[0])
        if plan["status"] == "awaiting_confirmation":
            plan["status"] = "draft"
            with k.tx():
                save(k, user_id, plan)
        else:
            raise RuleError("duplicate", f"已经有一个进行中的“{plan['title']}”计划了。", detail={"plan_id": plan["plan_id"]})
    order_at = event - timedelta(days=2)
    services = {r["service_id"]: r for r in k.db.execute("SELECT * FROM services")}
    relation = "爱人" if contact["relation"] == "配偶" else contact["relation"]
    plan_id = new_id("plan")
    plan = {"plan_id": plan_id, "title": f"{contact['name']}生日筹备", "template": "birthday", "contact_id": contact_id,
            "event_date": event.date().isoformat(), "created_at": iso(now), "status": "awaiting_confirmation", "source": source,
            "nodes": [
                {"id": "n1", "title": f"锁定生日预算 {yuan(budget_cents)}", "intent": "reserve_budget", "status": "pending",
                 "depends_on": [], "run_at": None, "result_summary": None, "compensation": "release_budget",
                 "params": {"amount_cents": budget_cents, "name": f"{contact['name']}生日"}},
                {"id": "n2", "title": f"{order_at:%m-%d} 订{services['flower-basic']['name']}", "intent": "place_order", "status": "pending",
                 "depends_on": ["n1"], "run_at": iso(order_at), "result_summary": None, "compensation": "cancel_order",
                 "params": {"service_id": "flower-basic", "price_cents": services["flower-basic"]["price_cents"], "deliver_date": event.date().isoformat()}},
                {"id": "n3", "title": f"{order_at:%m-%d} 订{services['cake-basic']['name']}", "intent": "place_order", "status": "pending",
                 "depends_on": ["n1"], "run_at": iso(order_at), "result_summary": None, "compensation": "cancel_order",
                 "params": {"service_id": "cake-basic", "price_cents": services["cake-basic"]["price_cents"], "deliver_date": event.date().isoformat()}},
                {"id": "n4", "title": f"{event:%m-%d} 当天提醒：{contact['name']}（{relation}）生日", "intent": "reminder", "status": "pending",
                 "depends_on": ["n2", "n3"], "run_at": iso(event), "result_summary": None, "compensation": None,
                 "params": {"text": f"今天是{contact['name']}（{relation}）的生日，鲜花和蛋糕已按计划下单。"}},
            ]}
    tier = node_tiers(k, user_id, plan)
    plan["tier"] = tier
    with k.tx():
        k.db.execute("INSERT INTO plans VALUES(?,?,?,?,?,?,?)", (plan_id, user_id, plan["title"], plan["status"], canonical(plan), iso(now), iso(now)))
        k.audit(user_id, "plan", tier, "plan_created", "pending", f"生成计划“{plan['title']}”（{len(plan['nodes'])} 个节点）",
                actor="agent" if source == "chat" else "user", params={"plan_id": plan_id, "template": "birthday"})
    return plan


class PlanHandler(Handler):
    """整体确认：一次确认绑定全部节点参数的哈希。"""
    intent = "plan"

    def subject(self, p):
        return "plan:" + p.get("plan_id", "")

    def prepare(self, user_id, p, recheck=False):
        plan = load(self.k, user_id, p.get("plan_id"))
        if plan["status"] != "awaiting_confirmation":
            raise RuleError("expired", "这个计划已经不在待确认状态了。")
        digest = sha256_hex(canonical([{k: n[k] for k in ("id", "intent", "params", "run_at", "depends_on", "status")} for n in plan["nodes"]]))
        if p.get("nodes_hash") and p["nodes_hash"] != digest:
            raise RuleError("expired", "计划内容有变化，请重新确认。")
        p["nodes_hash"] = digest
        if plan["nodes"][0]["intent"] == "reserve_budget":
            account = self.db.execute("SELECT * FROM accounts WHERE account_id=?", (user_id + "-main",)).fetchone()
            if account["balance_cents"] - account["reserved_cents"] < plan["nodes"][0]["params"]["amount_cents"]:
                raise RuleError("insufficient_funds", "活期可用余额不足，无法锁定预算。")
        return p

    def tier(self, user_id, p):
        plan = load(self.k, user_id, p["plan_id"])
        tier = node_tiers(self.k, user_id, plan)
        tier = "yellow" if tier == "green" else tier
        nodes = "、".join(f"{n['id']}{NODE_TIER_LABEL[n['tier']]}" for n in plan["nodes"])
        return tier, f"代码判档：计划整体{NODE_TIER_LABEL[tier]}档（节点：{nodes}；取最高档）"

    def view(self, user_id, p, tier):
        plan = load(self.k, user_id, p["plan_id"])
        node_tiers(self.k, user_id, plan)
        lines = [{"label": f"步骤 {i}", "value": f"{n['title']}（{NODE_TIER_LABEL[n['tier']]}档）" if n["status"] != "skipped" else f"{n['title']}（已去掉）"}
                 for i, n in enumerate(plan["nodes"], 1)]
        total = sum(n["params"].get("price_cents", 0) for n in plan["nodes"] if n["status"] != "skipped")
        lines.append({"label": "预计花费", "value": f"{yuan(total)}（从预算支付，剩余自动释放）", "emphasis": True})
        return {"title": f"确认整个计划：{plan['title']}", "lines": lines,
                "impact": "一次确认整个计划：现在锁定预算，到点自动下单并通知你；执行前会再次检查余额和限额，随时可以暂停、回退或转人工。"}

    def sms_text(self, user_id, p):
        return f"确认计划“{load(self.k, user_id, p['plan_id'])['title']}”"

    def execute(self, user_id, p, request_row):
        k = self.k
        plan = load(k, user_id, p["plan_id"])
        tier = request_row["tier"]
        for node in plan["nodes"]:
            if node["status"] == "skipped":
                continue
            if node["intent"] == "reserve_budget":
                budget_id = create_budget(k, user_id, node["params"]["name"], node["params"]["amount_cents"],
                                          iso(parse_iso(plan["nodes"][-1]["run_at"]) + timedelta(days=1)), plan["plan_id"])
                plan["budget_id"] = budget_id
                node["status"], node["result_summary"] = "success", f"已锁定 {yuan(node['params']['amount_cents'])}"
            else:
                node["status"] = "scheduled"
                kind = "order" if node["intent"] == "place_order" else "reminder"
                k.db.execute("INSERT INTO schedules VALUES(?,?,?,?,?,?,?,?,'none','scheduled',?,?,?,?,NULL)",
                             (new_id("sch"), user_id, kind, f"{plan['title']} · {node['title']}", "plan_node",
                              canonical({"plan_id": plan["plan_id"], "node_id": node["id"]}), node["params"].get("price_cents", 0),
                              node["run_at"], tier, plan["plan_id"], node["id"], iso(k.now())))
        plan["status"] = "running"
        plan["authorized_tier"] = tier
        save(k, user_id, plan)
        return {"status": "success", "title": "计划已启动", "plan": view(plan),
                "lines": [{"label": "计划", "value": plan["title"]}, {"label": "预算", "value": plan["nodes"][0]["result_summary"]},
                          {"label": "下一步", "value": human_datetime(parse_iso(plan["nodes"][1]["run_at"]), k.now()) + " 自动下单"}],
                "blocks": [{"type": "plan", "data": view(plan)}],
                "summary": f"计划“{plan['title']}”已启动：预算已锁定，{parse_iso(plan['nodes'][1]['run_at']):%m-%d %H:%M} 自动订花和蛋糕"}


class PlanNodeRunner(Handler):
    """调度器到点执行计划节点。"""
    intent = "plan_node"

    def run_scheduled(self, row, params):
        k, user_id = self.k, row["user_id"]
        produced = []
        with k.tx():
            plan = load(k, user_id, params["plan_id"])
            node = next(n for n in plan["nodes"] if n["id"] == params["node_id"])
            if plan["status"] != "running" or node["status"] in TERMINAL:
                k.db.execute("UPDATE schedules SET status='cancelled', last_result='计划不在运行中' WHERE schedule_id=?", (row["schedule_id"],))
                return produced
            if node["intent"] == "place_order":
                day = k.now().date().isoformat()
                used = k.ops.daily_outgoing(user_id, day)
                price = node["params"]["price_cents"]
                if used + price > SMALL_LIMIT_CENTS and plan.get("authorized_tier") != "red":
                    node["status"], node["result_summary"] = "failed", "执行日累计超过小额额度，需要重新授权，未下单"
                    k.notify(user_id, "scheduled_failed", f"{plan['title']}：{node['title']} 未执行", node["result_summary"] + "。")
                    k.audit(user_id, "plan", plan.get("authorized_tier", "yellow"), "plan_node_needs_reauth", "blocked", node["result_summary"],
                            actor="scheduler", params={"plan_id": plan["plan_id"], "node_id": node["id"]})
                else:
                    try:
                        order_id, name, price = pay_order_from_budget(k, user_id, plan["budget_id"], node["params"]["service_id"],
                                                                      node["params"]["deliver_date"], plan["plan_id"])
                        node["status"], node["result_summary"] = "success", f"已下单 {name} {yuan(price)}（预算支付，{node['params']['deliver_date']} 送达）"
                        node["order_id"] = order_id
                        k.notify(user_id, "scheduled_executed", f"{plan['title']}：已下单", node["result_summary"])
                        k.audit(user_id, "plan", plan.get("authorized_tier", "yellow"), "plan_node_executed", "success", node["result_summary"],
                                actor="scheduler", params={"plan_id": plan["plan_id"], "node_id": node["id"], "amount_cents": price})
                    except RuleError as error:
                        node["status"], node["result_summary"] = "failed", error.message
                        k.notify(user_id, "scheduled_failed", f"{plan['title']}：{node['title']} 失败", error.message)
                        k.audit(user_id, "plan", plan.get("authorized_tier", "yellow"), "plan_node_failed", "failed", error.message,
                                actor="scheduler", params={"plan_id": plan["plan_id"], "node_id": node["id"]})
            else:
                node["status"], node["result_summary"] = "success", "已提醒"
                k.notify(user_id, "reminder", plan["title"], node["params"]["text"])
                k.audit(user_id, "plan", "green", "plan_reminder", "success", node["params"]["text"][:60], actor="scheduler",
                        params={"plan_id": plan["plan_id"], "node_id": node["id"]})
            k.db.execute("UPDATE schedules SET status='executed', last_result=? WHERE schedule_id=?", (node["result_summary"], row["schedule_id"]))
            if all(n["status"] in TERMINAL for n in plan["nodes"]):
                released = release_budget(k, user_id, plan.get("budget_id"))
                plan["status"] = "completed" if all(n["status"] in ("success", "skipped") for n in plan["nodes"]) else "failed"
                if released:
                    k.notify(user_id, "settlement", f"{plan['title']} 已完成", f"预算剩余 {yuan(released)} 已自动释放。")
            save(k, user_id, plan)
        produced.append(k.notifications(user_id, 1)[0])
        return produced


def control(k, user_id, plan_id, action, node_hint=None, turn_id=None, actor="user"):
    """暂停/继续/回退/转人工/取消单个节点。都是降低风险的操作，直接生效并审计。"""
    with k.tx():
        plan = load(k, user_id, plan_id)
        status = plan["status"]
        note = ""
        if action == "pause":
            if status != "running":
                raise RuleError("invalid_request", "只有进行中的计划才能暂停。")
            plan["status"], note = "paused", "计划已暂停，到点的步骤不会执行，说“继续”即可恢复。"
        elif action == "resume":
            if status != "paused":
                raise RuleError("invalid_request", "计划没有暂停。")
            plan["status"], note = "running", "计划已继续；暂停期间到点的步骤会马上补执行（执行前同样复查）。"
        elif action == "cancel_node":
            if status not in ("running", "paused", "awaiting_confirmation"):
                raise RuleError("invalid_request", "计划不在进行中。")
            node = next((n for n in plan["nodes"] if n["intent"] == "place_order" and n["status"] not in TERMINAL
                         and node_hint and any(w in n["title"] for w in node_hint)), None)
            if node is None:
                raise RuleError("not_found", "没有找到可以取消的步骤（可能已经执行了）。")
            node["status"], node["result_summary"] = "skipped", "用户取消了这一步"
            k.db.execute("UPDATE schedules SET status='cancelled', last_result='用户取消' WHERE plan_id=? AND node_id=? AND status='scheduled'",
                         (plan_id, node["id"]))
            note = f"已去掉“{node['title']}”，其他步骤照常。" + ("请重新确认整个计划。" if status == "awaiting_confirmation" else "")
        elif action == "rollback":
            if status not in ("running", "paused", "failed"):
                raise RuleError("invalid_request", "这个计划不需要回退。")
            undone = []
            for node in plan["nodes"]:
                if node["status"] not in TERMINAL:
                    node["status"], node["result_summary"] = "rolled_back", "已回退（未执行）"
                    undone.append(node["title"])
                elif node["status"] == "success" and node["intent"] == "place_order":
                    node["result_summary"] += "（已执行的订单不自动退，如需退款请转人工）"
            k.db.execute("UPDATE schedules SET status='cancelled', last_result='计划回退' WHERE plan_id=? AND status='scheduled'", (plan_id,))
            released = release_budget(k, user_id, plan.get("budget_id"))
            if plan["nodes"][0]["status"] == "success" and released:
                plan["nodes"][0]["result_summary"] = f"已释放预算 {yuan(released)}（补偿动作）"
                plan["nodes"][0]["status"] = "rolled_back"
            plan["status"] = "rolled_back"
            note = f"计划已回退：取消了 {len(undone)} 个未执行步骤" + (f"，释放预算 {yuan(released)}" if released else "") + "。"
        elif action == "takeover":
            if status in ("completed", "rolled_back", "handed_over"):
                raise RuleError("invalid_request", "这个计划已经结束了。")
            ticket = new_id("hd")
            k.db.execute("INSERT INTO handovers VALUES(?,?,?,?,?,?)", (ticket, user_id, f"计划“{plan['title']}”转人工处理",
                                                                       "waiting", iso(k.now()), plan_id))
            plan["status"], plan["handover_ticket"] = "handed_over", ticket
            note = f"已转人工处理（工单 {ticket}），计划暂停自动执行，人工客服会联系你。"
        else:
            raise RuleError("invalid_request", "不支持的计划操作。")
        save(k, user_id, plan)
        k.audit(user_id, "plan", "none", "plan_" + action, "success", note[:100], actor=actor, turn_id=turn_id,
                params={"plan_id": plan_id})
    return plan, note


def register(ops):
    ops.register(PlanHandler(ops))
    ops.register(PlanNodeRunner(ops))

    def summaries(user_id):
        return [summary(load(ops.k, user_id, r[0])) for r in
                ops.k.db.execute("SELECT plan_id FROM plans WHERE user_id=? ORDER BY created_at DESC", (user_id,))]

    def plan_view(user_id, plan_id):
        try:
            return view(load(ops.k, user_id, plan_id))
        except RuleError:
            return None

    def plan_cancelled(user_id, plan_id):
        with ops.k.tx():
            plan = load(ops.k, user_id, plan_id)
            if plan["status"] == "awaiting_confirmation":
                plan["status"] = "draft"
                save(ops.k, user_id, plan)

    ops.plan_summaries = summaries
    ops.plan_view = plan_view
    ops.plan_cancelled = plan_cancelled
