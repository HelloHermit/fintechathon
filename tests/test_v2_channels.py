"""飞书渠道与流式输出测试（假飞书客户端，不联网）。"""

import json
import re
import threading
import unittest
import urllib.request

from src.agent.orchestrator import Agent
from src.channels import binding
from src.channels.feishu import FeishuBridge
from tests.test_v2_engine import FakeLLM, new_kernel


class FakeFeishu:
    def __init__(self):
        self.sent = []

    def send_text(self, open_id, text):
        self.sent.append(("text", open_id, text))

    def send_card(self, open_id, card):
        self.sent.append(("card", open_id, card))

    def texts(self):
        return [m[2] for m in self.sent if m[0] == "text"]

    def cards(self):
        return [m[2] for m in self.sent if m[0] == "card"]


def card_buttons(card):
    return [a for e in card["elements"] if e["tag"] == "action" for a in e["actions"]]


class FeishuTests(unittest.TestCase):
    def setUp(self):
        self.k, self.clock = new_kernel()
        self.llm = FakeLLM([])
        self.agent = Agent(self.k, self.llm)
        self.im = FakeFeishu()
        self.bridge = FeishuBridge(self.k, self.agent, self.im, app_url="http://127.0.0.1:8765")

    def bind(self, open_id="ou_alice_0001"):
        code = binding.create_code(self.k, "alice")["code"]
        self.assertEqual(self.bridge.on_message(open_id, "p2p", "text", f"绑定 {code}", "m-bind"), "bound")
        return open_id

    def test_unbound_user_only_gets_help(self):
        self.assertEqual(self.bridge.on_message("ou_stranger", "p2p", "text", "给小王转200", "m1"), "help")
        self.assertIn("绑定", self.im.texts()[-1])
        self.assertEqual(self.llm.seen, [])  # 没有调用模型，更没有业务

    def test_group_chat_ignored(self):
        open_id = self.bind()
        self.assertEqual(self.bridge.on_message(open_id, "group", "text", "给小王转200", "m2"), "ignored")
        self.assertEqual(len(self.im.sent), 1)

    def test_bind_code_one_time_and_expires(self):
        code = binding.create_code(self.k, "alice")["code"]
        self.assertEqual(self.bridge.on_message("ou_a", "p2p", "text", f"绑定 {code}", "m3"), "bound")
        self.assertEqual(self.bridge.on_message("ou_b", "p2p", "text", f"绑定 {code}", "m4"), "bind_failed")
        code2 = binding.create_code(self.k, "alice")["code"]
        self.clock.t += 301
        self.assertEqual(self.bridge.on_message("ou_c", "p2p", "text", f"绑定 {code2}", "m5"), "bind_failed")

    def test_duplicate_message_ignored(self):
        open_id = self.bind()
        self.llm.script = [{"content": "你好"}]
        self.assertEqual(self.bridge.on_message(open_id, "p2p", "text", "你好", "dup"), "handled")
        self.assertEqual(self.bridge.on_message(open_id, "p2p", "text", "你好", "dup"), "ignored")

    def test_yellow_confirmed_by_card_button_not_text(self):
        open_id = self.bind()
        self.llm.script = [{"calls": [("transfer", {"payee": "小王", "amount": 200})]}, {"content": "请核对确认单。"}]
        self.bridge.on_message(open_id, "p2p", "text", "给小王转200", "m6")
        card = self.im.cards()[-1]
        dump = json.dumps(card, ensure_ascii=False)
        pending = self.k.open_pendings("alice")[-1]
        self.assertEqual(pending["channel"], "feishu")
        # 卡片里没有确认码，只有随机令牌
        code_row = self.k.db.execute("SELECT code_hash FROM requests WHERE request_id=?", (pending["request_id"],)).fetchone()
        self.assertIsNotNone(code_row)
        self.assertNotIn("confirmation_code", dump)
        # 文字“确认”无效
        self.bridge.on_message(open_id, "p2p", "text", "确认", "m7")
        self.assertEqual(self.k.db.execute("SELECT balance_cents FROM accounts WHERE account_id='bob-main'").fetchone()[0], 820000)
        confirm = card_buttons(card)[0]["value"]
        # 别人点按钮无效
        self.assertEqual(self.bridge.on_card_action("ou_other", confirm)["type"], "error")
        self.assertEqual(self.bridge.on_card_action(open_id, confirm)["type"], "success")
        self.assertEqual(self.k.db.execute("SELECT balance_cents FROM accounts WHERE account_id='bob-main'").fetchone()[0], 820000 + 20000)
        self.assertIn("转账成功", self.im.texts()[-1])
        # 同一个按钮不能重复使用
        self.assertEqual(self.bridge.on_card_action(open_id, confirm)["type"], "error")

    def test_red_goes_back_to_app_and_otp_never_sent_to_im(self):
        open_id = self.bind()
        self.llm.script = [{"calls": [("transfer", {"payee": "妈妈", "amount": 2000})]}, {"content": "这是大额转账。"}]
        self.bridge.on_message(open_id, "p2p", "text", "给妈妈转2000", "m9")
        self.assertIn("请打开小安 App", self.im.texts()[-1])
        self.assertEqual(self.im.cards(), [])  # 红档没有确认按钮
        pending = self.k.open_pendings("alice")[-1]
        self.assertEqual((pending["tier"], pending["channel"]), ("red", "feishu"))
        # 网页上完成强验证
        self.k.send_otp("alice", pending["request_id"])
        otp = re.search(r"验证码 ([0-9]{6})", self.k.sms_inbox("alice")[-1]["text"]).group(1)
        self.k.verify_strong("alice", pending["request_id"], "135790", otp)
        self.bridge.push_new_notifications()
        self.assertTrue(all(otp not in json.dumps(m, ensure_ascii=False) for m in self.im.sent))

    def test_options_become_card_buttons(self):
        open_id = self.bind()
        self.llm.script = [{"calls": [("transfer", {"payee": "小李", "amount": 200})]}, {"content": "是哪位小李？"}]
        self.bridge.on_message(open_id, "p2p", "text", "给小李转200", "m10")
        buttons = card_buttons(self.im.cards()[-1])
        self.assertEqual(len(buttons), 2)
        self.assertEqual(self.bridge.on_card_action(open_id, buttons[1]["value"])["type"], "success")
        pending = self.k.open_pendings("alice")[-1]
        self.assertEqual((pending["title"], pending["channel"]), ("转账给 李娜（小李）", "feishu"))
        self.assertTrue(card_buttons(self.im.cards()[-1]))  # 新单的确认卡片

    def test_push_notifications_to_bound_user_only(self):
        open_id = self.bind()
        before = len(self.im.sent)
        self.k.advance_clock(to="2026-11-01T09:30:00+08:00")  # 健身会员续费 + 房租定时转账
        pushed = self.bridge.push_new_notifications()
        self.assertGreaterEqual(pushed, 2)
        texts = [m[2] for m in self.im.sent[before:]]
        self.assertTrue(any("定时转账已执行" in t for t in texts))
        self.assertTrue(all(m[1] == open_id for m in self.im.sent[before:]))
        self.assertEqual(self.bridge.push_new_notifications(), 0)

    def test_binding_survives_demo_reset(self):
        self.bind()
        self.k.reset()
        self.assertEqual(binding.user_for(self.k, "feishu", "ou_alice_0001"), "alice")


class StreamTests(unittest.TestCase):
    def test_chat_stream_sends_steps_then_final(self):
        from src.server_v2 import App, create_server
        k, _ = new_kernel()
        llm = FakeLLM([{"calls": [("get_accounts", {})]}, {"content": "你的余额见卡片。"}])
        app = App(k, Agent(k, llm))
        server = create_server(app, "127.0.0.1", 0)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            req = urllib.request.Request(f"http://127.0.0.1:{server.server_address[1]}/api/v2/chat/stream",
                                         data=json.dumps({"text": "我还有多少钱"}).encode(), method="POST",
                                         headers={"Content-Type": "application/json", "X-CSRF-Token": app.csrf})
            with urllib.request.urlopen(req, timeout=10) as resp:
                self.assertTrue(resp.headers["Content-Type"].startswith("text/event-stream"))
                raw = resp.read().decode()
            events = re.findall(r"event: (\w+)\ndata: (.*)\n\n", raw)
            kinds = [e for e, _ in events]
            self.assertGreaterEqual(kinds.count("step"), 3)
            self.assertEqual(kinds[-1], "final")
            final = json.loads(events[-1][1])
            self.assertEqual(final["assistant"]["blocks"][0]["type"], "account_list")
            self.assertEqual(len(final["trace"]), kinds.count("step"))
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main()
