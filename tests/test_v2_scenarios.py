"""v2 场景处理器测试：卡片（风险对称）、订阅（识别/标记/取消）、理财（测评/适当性/申购/赎回）、AA、撤回、账户互转。"""

import unittest

from src.agent.tools import TaskContext, run_tool
from src.core.kernel import RuleError
from src.core.ops_cards import subscription_items
from tests.test_v2_engine import new_kernel, otp_from_sms


def tool(k, tool_name, text, user="alice", selections=None, **args):
    return run_tool(tool_name, args, TaskContext(k, user, [text], selections=selections))


def strong(k, pending, user="alice"):
    k.send_otp(user, pending["request_id"])
    return k.verify_strong(user, pending["request_id"], "135790", otp_from_sms(k, user))


class CardTests(unittest.TestCase):
    def test_risk_symmetry(self):
        k, _ = new_kernel()
        freeze = tool(k, "card_action", "先把储蓄卡冻上", action="freeze").pending
        self.assertEqual(freeze["tier"], "yellow")
        k.confirm("alice", freeze["request_id"], freeze["confirmation_code"])
        self.assertEqual(k.db.execute("SELECT status FROM cards WHERE card_id='card-6621'").fetchone()[0], "frozen")
        unfreeze = tool(k, "card_action", "储蓄卡解冻", action="unfreeze").pending
        self.assertEqual(unfreeze["tier"], "red")
        strong(k, unfreeze)
        down = tool(k, "set_card_limit", "储蓄卡每天限额降到2000", daily_limit=2000).pending
        self.assertEqual(down["tier"], "yellow")
        up = tool(k, "set_card_limit", "储蓄卡限额提到2万", daily_limit=20000).pending
        self.assertEqual(up["tier"], "red")

    def test_lost_card_offers_freeze_or_report(self):
        k, _ = new_kernel()
        out = tool(k, "card_action", "我卡丢了", action="lost")
        values = [i["value"] for i in out.choice["data"]["items"]]
        self.assertEqual(values, ["freeze", "report_lost"])
        lost = tool(k, "card_action", "储蓄卡正式挂失", action="report_lost").pending
        self.assertEqual(lost["tier"], "red")
        strong(k, lost)
        restore = tool(k, "card_action", "卡找到了，解挂", action="restore").pending
        self.assertEqual(restore["tier"], "red")

    def test_virtual_card_is_yellow(self):
        k, _ = new_kernel()
        p = tool(k, "apply_virtual_card", "帮我开张网购用的虚拟卡", purpose="网购").pending
        self.assertEqual(p["tier"], "yellow")
        result = k.confirm("alice", p["request_id"], p["confirmation_code"])
        self.assertTrue(k.db.execute("SELECT 1 FROM cards WHERE card_id=?", (result["card_id"],)).fetchone())

    def test_cannot_touch_other_users_card(self):
        k, _ = new_kernel()
        with self.assertRaises(RuleError):
            k.propose("alice", "freeze_card", {"card_id": "card-1234"})


class SubscriptionTests(unittest.TestCase):
    def test_detection_and_flags(self):
        k, _ = new_kernel()
        items = {i["name"]: i for i in subscription_items(k, "alice")}
        self.assertEqual(items["读书App"]["source"], "detected")
        self.assertIn("price_up", items["视频会员"]["flags"])
        self.assertIn("idle", items["健身App会员"]["flags"])
        self.assertIn("renew_soon", items["健身App会员"]["flags"])
        self.assertIn("renew_soon", items["音乐会员"]["flags"])
        self.assertEqual(len(items), 5)

    def test_query_is_yellow_and_cancel_stops_future_charges(self):
        k, _ = new_kernel()
        q = tool(k, "query_subscriptions", "我有哪些自动扣费").pending
        self.assertEqual(q["tier"], "yellow")
        result = k.confirm("alice", q["request_id"], q["confirmation_code"])
        self.assertEqual(result["blocks"][0]["type"], "subscription_list")
        c = tool(k, "cancel_subscription", "健身会员不要了", name="健身会员").pending
        k.confirm("alice", c["request_id"], c["confirmation_code"])
        before = k.db.execute("SELECT COUNT(*) FROM transactions WHERE merchant LIKE '健身App%'").fetchone()[0]
        k.advance_clock(to="2026-11-02T09:00:00+08:00")
        after = k.db.execute("SELECT COUNT(*) FROM transactions WHERE merchant LIKE '健身App%'").fetchone()[0]
        self.assertEqual(before, after)
        music = k.db.execute("SELECT COUNT(*) FROM transactions WHERE merchant LIKE '音乐会员%' AND time>'2026-11-01'").fetchone()[0]
        self.assertEqual(music, 0)  # 11-03 才续费
        k.advance_clock(to="2026-11-03T09:00:00+08:00")
        music = k.db.execute("SELECT COUNT(*) FROM transactions WHERE merchant LIKE '音乐会员%' AND time>'2026-11-01'").fetchone()[0]
        self.assertEqual(music, 1)


class WealthTests(unittest.TestCase):
    def assess(self, k, answers):
        p = k.propose("alice", "submit_risk_assessment", {"answers": answers})["pending"]
        return k.confirm("alice", p["request_id"], p["confirmation_code"])

    def test_purchase_requires_assessment_then_red(self):
        k, _ = new_kernel()
        out = tool(k, "purchase_product", "买一万稳健季享", product="稳健季享", amount=10000)
        self.assertEqual(out.model_result["status"], "need_assessment")
        self.assertTrue(any(b["type"] == "risk_questionnaire" for b in out.blocks))
        self.assess(k, {"Q1": 2, "Q2": 2, "Q3": 3, "Q4": 3, "Q5": 2, "Q6": 3})  # 15 分 → C3
        self.assertEqual(k.user("alice")["risk_level"], "C3")
        p = tool(k, "purchase_product", "买一万稳健季享", product="稳健季享", amount=10000).pending
        self.assertEqual(p["tier"], "red")
        strong(k, p)
        self.assertEqual(k.db.execute("SELECT COUNT(*) FROM holdings WHERE user_id='alice' AND product_id='prd-steady'").fetchone()[0], 2)

    def test_suitability_blocks_high_risk(self):
        k, _ = new_kernel()
        self.assess(k, {"Q1": 1, "Q2": 2, "Q3": 2, "Q4": 2, "Q5": 2, "Q6": 3})  # 12 分 → C2
        out = tool(k, "purchase_product", "买两万科技先锋", product="科技先锋", amount=20000)
        self.assertEqual(out.model_result["code"], "unsuitable")
        self.assertIsNone(out.pending)

    def test_redeem_is_yellow_and_returns_money(self):
        k, _ = new_kernel()
        p = tool(k, "redeem_product", "稳健季享赎回五千", product="稳健季享", amount=5000).pending
        self.assertEqual(p["tier"], "yellow")
        result = k.confirm("alice", p["request_id"], p["confirmation_code"])
        self.assertEqual(k.db.execute("SELECT balance_cents FROM accounts WHERE account_id='alice-main'").fetchone()[0], 2658000 + 500000 + 2950)
        self.assertEqual(result["status"], "success")

    def test_injected_product_description_is_wrapped(self):
        k, _ = new_kernel()
        out = tool(k, "list_products", "有哪些理财")
        tech = next(p for p in out.model_result["products"] if p["name"] == "科技先锋")
        self.assertTrue(tech["description"].startswith("<external_data>"))


class TransferExtrasTests(unittest.TestCase):
    def test_aa_split_and_bob_pays(self):
        k, _ = new_kernel()
        p = tool(k, "aa_collect", "昨晚和小王、小张吃饭花了360，AA一下", total_amount=360, participants=["小王", "小张"]).pending
        self.assertIn("¥120.00", p["title"])
        k.confirm("alice", p["request_id"], p["confirmation_code"])
        pay = tool(k, "pay_aa", "付一下AA", user="bob").pending
        k.confirm("bob", pay["request_id"], pay["confirmation_code"])
        self.assertEqual(k.db.execute("SELECT balance_cents FROM accounts WHERE account_id='alice-main'").fetchone()[0], 2658000 + 12000)
        self.assertEqual(k.db.execute("SELECT status FROM aa_requests WHERE payer_user='bob'").fetchone()[0], "paid")

    def test_aa_participant_must_be_said(self):
        k, _ = new_kernel()
        out = tool(k, "aa_collect", "昨晚吃饭花了360，AA一下", total_amount=360, participants=["小王"])
        self.assertEqual(out.model_result["code"], "provenance")

    def test_scheduled_needs_reauth_when_cumulative_grows(self):
        k, _ = new_kernel()
        p = run_tool("transfer", {"payee": "小王", "amount": 800, "when": "明天"}, TaskContext(k, "alice", ["明天给小王转800"])).pending
        self.assertEqual(p["tier"], "yellow")
        k.confirm("alice", p["request_id"], p["confirmation_code"])
        k.advance_clock(to="2026-10-31T08:00:00+08:00")
        q = run_tool("transfer", {"payee": "小张", "amount": 500}, TaskContext(k, "alice", ["给小张转500"])).pending
        k.confirm("alice", q["request_id"], q["confirmation_code"])
        k.advance_clock(to="2026-10-31T09:01:00+08:00")
        status = k.db.execute("SELECT status FROM schedules WHERE amount_cents=80000").fetchone()[0]
        self.assertEqual(status, "needs_reauth")

    def test_move_funds_not_counted_as_spending(self):
        k, _ = new_kernel()
        p = k.propose("alice", "move_funds", {"source_account_id": "alice-savings", "target_account_id": "alice-main", "amount_cents": 100000})["pending"]
        k.confirm("alice", p["request_id"], p["confirmation_code"])
        start, end, _ = k.analytics.resolve_period("今天", k.now())
        self.assertEqual(k.analytics.breakdown("alice", start, end)["total_cents"], 0)


if __name__ == "__main__":
    unittest.main()


class PlanTests(unittest.TestCase):
    def setUp(self):
        from src.agent.orchestrator import Agent
        from tests.test_v2_engine import FakeLLM
        self.k, _ = new_kernel()
        self.agent = Agent(self.k, FakeLLM([]))
        resp = self.agent.action("alice", "insight_accept", "ins-birthday-c-spouse", None)
        self.pending, self.plan_id = resp["pending"], resp["plan"]["plan_id"]

    def balances(self):
        return tuple(self.k.db.execute("SELECT balance_cents, reserved_cents FROM accounts WHERE account_id='alice-main'").fetchone())

    def test_one_confirmation_runs_whole_plan(self):
        self.assertEqual(self.pending["tier"], "yellow")
        self.assertEqual(len(self.pending["lines"]), 5)
        self.agent.kernel_call("alice", self.k.confirm, self.pending["request_id"], self.pending["confirmation_code"])
        self.assertEqual(self.balances(), (2658000, 100000))
        self.k.advance_clock(to="2026-11-12T09:00:00+08:00")
        plan = self.k.ops.plan_view("alice", self.plan_id)
        self.assertEqual(plan["status"], "completed")
        self.assertEqual([n["status"] for n in plan["nodes"]], ["success"] * 4)
        orders = self.k.db.execute("SELECT service_id, amount_cents, shanghai_date FROM orders ORDER BY service_id").fetchall()
        self.assertEqual([tuple(o) for o in orders], [("cake-basic", 9900, "2026-11-10"), ("flower-basic", 12900, "2026-11-10")])
        self.assertEqual(self.balances()[1], 0)  # 剩余预算已释放

    def test_cancel_node_and_rollback(self):
        from src.core import plans
        self.agent.kernel_call("alice", self.k.confirm, self.pending["request_id"], self.pending["confirmation_code"])
        plans.control(self.k, "alice", self.plan_id, "cancel_node", ["蛋糕"])
        resp = self.agent.plan_control("alice", self.plan_id, "rollback")
        self.assertEqual(resp["plan"]["status"], "rolled_back")
        self.assertEqual(self.balances(), (2658000, 0))
        self.k.advance_clock(to="2026-11-11T09:00:00+08:00")
        self.assertEqual(self.k.db.execute("SELECT COUNT(*) FROM orders").fetchone()[0], 0)

    def test_pause_blocks_execution_and_takeover(self):
        self.agent.kernel_call("alice", self.k.confirm, self.pending["request_id"], self.pending["confirmation_code"])
        self.agent.plan_control("alice", self.plan_id, "pause")
        self.k.advance_clock(to="2026-11-10T10:00:00+08:00")
        self.assertEqual(self.k.db.execute("SELECT COUNT(*) FROM orders").fetchone()[0], 0)
        self.agent.plan_control("alice", self.plan_id, "resume")
        self.assertEqual(self.k.db.execute("SELECT COUNT(*) FROM orders").fetchone()[0], 2)
        resp = self.agent.plan_control("alice", self.plan_id, "takeover")  # 提醒节点还没到，计划未结束，可以转人工
        self.assertIsNone(resp["error"])
        self.assertEqual(resp["plan"]["status"], "handed_over")
        self.assertTrue(self.k.db.execute("SELECT 1 FROM handovers WHERE plan_id=?", (self.plan_id,)).fetchone())


class SandboxTests(unittest.TestCase):
    def test_good_code_runs_and_bad_code_is_rejected(self):
        from src.core import sandbox
        k, _ = new_kernel()
        data = sandbox.snapshot(k, "alice")
        ok = sandbox.run("from statistics import mean\ndef analyze(transactions):\n    return {'n': len(transactions)}", data)
        self.assertEqual(ok["status"], "ok")
        self.assertEqual(ok["result"]["value"]["n"], len(data))
        for bad in ["import os\ndef analyze(t): return 1", "def analyze(t): return open('/etc/passwd').read()",
                    "def analyze(t): return ().__class__.__bases__", "from socket import socket\ndef analyze(t): return 1",
                    "def analyze(t): return eval('1')", "x = 1"]:
            self.assertEqual(sandbox.run(bad, data)["status"], "rejected", bad)
        loop = sandbox.run("def analyze(t):\n    while True:\n        pass", data)
        self.assertEqual(loop["status"], "error")

    def test_tool_audits_code_hash(self):
        k, _ = new_kernel()
        out = tool(k, "run_analysis", "统计笔数", question="统计笔数", code="def analyze(transactions):\n    return len(transactions)")
        self.assertEqual(out.blocks[0]["data"]["status"], "ok")
        row = k.db.execute("SELECT params_redacted FROM audit WHERE event='sandbox_run'").fetchone()
        self.assertIn("code_hash", row[0])


class PermissionTableTests(unittest.TestCase):
    """权限表 v5 中前面没有单独覆盖的行。"""

    def test_revoke_is_yellow(self):
        k, clock = new_kernel()
        p = k.propose("alice", "transfer", {"source_account_id": "alice-main", "target_account_id": "bob-main", "payee_contact_id": "c-wang",
                                            "payee_name": "王磊", "amount_cents": 50000, "arrival": "delayed_2h"})["pending"]
        k.confirm("alice", p["request_id"], p["confirmation_code"])
        revoke = tool(k, "revoke_transfer", "撤回刚才那笔").pending
        self.assertEqual(revoke["tier"], "yellow")
        k.confirm("alice", revoke["request_id"], revoke["confirmation_code"])
        self.assertEqual(k.db.execute("SELECT balance_cents FROM accounts WHERE account_id='alice-main'").fetchone()[0], 2658000)
        self.assertEqual(k.db.execute("SELECT balance_cents FROM accounts WHERE account_id='bob-main'").fetchone()[0], 820000)

    def test_cancel_scheduled_is_yellow(self):
        k, _ = new_kernel()
        p = tool(k, "cancel_scheduled", "下个月房租先别自动转了", keyword="房租").pending
        self.assertEqual(p["tier"], "yellow")
        k.confirm("alice", p["request_id"], p["confirmation_code"])
        k.advance_clock(to="2026-11-01T10:00:00+08:00")
        self.assertEqual(k.db.execute("SELECT COUNT(*) FROM transfers WHERE payee_name='李建国'").fetchone()[0], 0)

    def test_unknown_tool_and_unknown_intent_refused(self):
        k, _ = new_kernel()
        out = run_tool("drop_all_tables", {}, TaskContext(k, "alice", ["x"]))
        self.assertEqual(out.model_result["status"], "error")
        with self.assertRaises(RuleError):
            k.propose("alice", "set_tier_green", {})

    def test_aa_payment_red_when_cumulative_over_limit(self):
        k, _ = new_kernel()
        p = tool(k, "aa_collect", "和小王吃饭花了2400，AA一下", total_amount=2400, participants=["小王"]).pending
        k.confirm("alice", p["request_id"], p["confirmation_code"])
        pay = tool(k, "pay_aa", "付一下AA", user="bob").pending
        self.assertEqual(pay["tier"], "red")  # 人均 ¥1,200 > 小额额度

    def test_plan_with_red_node_needs_strong_auth(self):
        from src.core import plans
        k, _ = new_kernel()
        ctx = TaskContext(k, "alice", ["11月10日给小王转900"])
        p = run_tool("transfer", {"payee": "小王", "amount": 900, "when": "11月10日"}, ctx).pending
        k.confirm("alice", p["request_id"], p["confirmation_code"])
        plan = plans.create_birthday_plan(k, "alice", "c-spouse")
        result = k.propose("alice", "plan", {"plan_id": plan["plan_id"]}, plan_id=plan["plan_id"])
        self.assertEqual(result["pending"]["tier"], "red")
        self.assertEqual(result["pending"]["kind"], "strong_auth")

    def test_read_only_lock_blocks_writes_but_not_reads(self):
        k, _ = new_kernel()
        for _ in range(3):
            k.record_suspicious("alice", "injection:test")
        with self.assertRaises(RuleError):
            k.propose("alice", "freeze_card", {"card_id": "card-6621"})
        self.assertEqual(tool(k, "get_accounts", "余额").model_result["accounts"][0]["tail"], "6621")


class TravelTests(unittest.TestCase):
    def test_foreign_toggle_risk_symmetry(self):
        k, _ = new_kernel()
        on = tool(k, "card_action", "下周去日本，储蓄卡开通境外交易", action="enable_foreign").pending
        self.assertEqual(on["tier"], "red")
        strong(k, on)
        self.assertEqual(k.db.execute("SELECT foreign_enabled FROM cards WHERE card_id='card-6621'").fetchone()[0], 1)
        off = tool(k, "card_action", "回来了，储蓄卡关闭境外交易", action="disable_foreign").pending
        self.assertEqual(off["tier"], "yellow")

    def test_exchange_and_budget(self):
        k, _ = new_kernel()
        p = tool(k, "exchange_currency", "换5万日元", currency="JPY", foreign_amount=50000).pending
        self.assertEqual(p["tier"], "yellow")
        k.confirm("alice", p["request_id"], p["confirmation_code"])
        self.assertEqual(k.db.execute("SELECT amount_minor FROM fx_wallets WHERE currency='JPY'").fetchone()[0], 50000)
        self.assertEqual(k.db.execute("SELECT balance_cents FROM accounts WHERE account_id='alice-main'").fetchone()[0], 2658000 - 250000)
        start, end, _ = k.analytics.resolve_period("今天", k.now())
        self.assertEqual(k.analytics.breakdown("alice", start, end)["total_cents"], 0)  # 换汇不算消费
        b = tool(k, "travel_budget", "去日本玩，锁8000旅行预算", amount=8000, destination="日本").pending
        self.assertEqual(b["tier"], "yellow")
        self.assertIn("日本", b["title"])

    def test_fx_rates_green(self):
        k, _ = new_kernel()
        out = tool(k, "fx_rates", "日元汇率多少")
        self.assertIn("模拟", out.model_result["note"])
