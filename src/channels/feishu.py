"""飞书机器人渠道（PLAN 11.2）。

- 只处理私聊（p2p），群聊消息一律忽略。
- 未绑定的飞书账号只收到使用说明；发“绑定 123456”用 App 里生成的绑定码完成绑定。
- 渠道分级风控：绿档、黄档可以在飞书里办；黄档用卡片按钮确认（按钮里只有随机卡片令牌，确认码留在服务端）；
  红档只生成待办，提示“请在 App 内完成强验证”，动态码绝不发到飞书。聊天里打“确认”仍然无效。
- 主动推送：调度器产生的通知（定时任务结果、续费/生日提醒、AA 收款请求）推给已绑定的本人。

FeishuBridge 不依赖飞书 SDK（单测用假客户端）；LarkTransport / start_feishu 用官方 SDK lark-oapi 的长连接模式，
凭据只从环境变量 FEISHU_APP_ID、FEISHU_APP_SECRET 读取，不进仓库、不进日志。
"""

import json
import os
import re
import secrets
import threading
import time
import traceback

from ..core.kernel import RuleError
from ..core.util import yuan
from . import binding

CHANNEL = "feishu"
TOKEN_TTL = 300
HELP_TEXT = ("你好，我是模拟银行 AI 助手「小安」（演示环境，全部数据为模拟）。\n"
             "使用前请先绑定：打开小安 App → 我的 → 绑定飞书，拿到 6 位绑定码后在这里发送“绑定 123456”。\n"
             "绑定后可以在飞书里查账单、办小额转账、管理卡片和订阅；大额操作需要回到 App 完成交易密码 + 短信动态码。")


def _summary(block):
    from ..agent.orchestrator import block_summary
    try:
        return block_summary(block)
    except Exception:
        return None


class FeishuBridge:
    def __init__(self, kernel, agent, transport, app_url=None):
        self.kernel, self.agent, self.transport = kernel, agent, transport
        self.app_url = app_url or os.environ.get("FINTECH_PUBLIC_URL", "http://127.0.0.1:8765")
        self.tokens = {}          # 卡片令牌 → {user_id, kind, request_id, code, ref, value, expires}
        self.seen_messages = []   # 飞书可能重投同一条消息，按 message_id 去重
        self.lock = threading.Lock()
        with kernel.lock:
            row = kernel.db.execute("SELECT MAX(rowid) FROM notifications").fetchone()
        self.last_notification = row[0] or 0

    # ------------------------------------------------------------------ 收消息
    def on_message(self, open_id, chat_type, message_type, text, message_id=None):
        """返回本次处理的结果标签（单测用）：ignored / help / bound / bind_failed / handled。"""
        if chat_type != "p2p":
            return "ignored"  # 只处理私聊：群聊里的消息可能来自别人，不作为本人指令
        if message_id:
            with self.lock:
                if message_id in self.seen_messages:
                    return "ignored"
                self.seen_messages = (self.seen_messages + [message_id])[-200:]
        if message_type != "text" or not isinstance(text, str) or not text.strip():
            self.transport.send_text(open_id, "目前只支持文字消息。")
            return "help"
        text = text.strip()[:500]
        m = re.fullmatch(r"绑定\s*([0-9]{6})", text)
        if m:
            try:
                user_id = binding.consume_code(self.kernel, CHANNEL, open_id, m.group(1))
            except RuleError as error:
                self.transport.send_text(open_id, error.message)
                return "bind_failed"
            name = self.kernel.user(user_id)["display_name"]
            self.transport.send_text(open_id, f"绑定成功：{name}（模拟账户）。现在可以直接跟我说，比如“这个月花了多少钱”“给小王转200”。")
            return "bound"
        user_id = binding.user_for(self.kernel, CHANNEL, open_id)
        if user_id is None:
            self.transport.send_text(open_id, HELP_TEXT)
            return "help"
        resp = self.agent.chat(user_id, text, channel=CHANNEL)
        self.render(open_id, user_id, resp)
        return "handled"

    # ------------------------------------------------------------------ 卡片按钮
    def on_card_action(self, open_id, value):
        """飞书卡片按钮回调。返回 toast {type, content}。只认绑定本人点的、未过期的令牌。"""
        if not isinstance(value, dict) or type(value.get("t")) is not str:
            return {"type": "error", "content": "按钮已失效"}
        user_id = binding.user_for(self.kernel, CHANNEL, open_id)
        with self.lock:
            entry = self.tokens.get(value["t"])
            if entry is None or entry["expires"] < time.time():
                self.tokens.pop(value["t"], None)
                return {"type": "error", "content": "按钮已失效，请重新发起"}
            if user_id is None or user_id != entry["user_id"]:
                return {"type": "error", "content": "只有本人可以操作"}  # 不消耗令牌
            self.tokens.pop(value["t"], None)  # 一次性
        if entry["kind"] == "confirm":
            resp = self.agent.kernel_call(user_id, self.kernel.confirm, entry["request_id"], entry["code"],
                                          risk_acknowledged=entry.get("ack", False))
        elif entry["kind"] == "cancel":
            resp = self.agent.kernel_call(user_id, self.kernel.cancel, entry["request_id"])
        elif entry["kind"] == "option":
            resp = self.agent.action(user_id, "option_select", entry["ref"], entry["value"])
            if resp.get("pending"):
                self.kernel.mark_channel(resp["pending"]["request_id"], CHANNEL)
                resp["pending"]["channel"] = CHANNEL
        else:
            return {"type": "error", "content": "按钮已失效"}
        self.render(open_id, user_id, resp)
        if resp.get("error"):
            return {"type": "warning", "content": resp["error"]["message"][:40]}
        return {"type": "success", "content": "已处理"}

    def _token(self, user_id, **entry):
        token = secrets.token_urlsafe(16)
        with self.lock:
            now = time.time()
            self.tokens = {k: v for k, v in self.tokens.items() if v["expires"] > now}
            self.tokens[token] = dict(entry, user_id=user_id, expires=now + TOKEN_TTL)
        return token

    # ------------------------------------------------------------------ 渲染 TurnResponse
    def render(self, open_id, user_id, resp):
        lines = [resp["assistant"]["text"]]
        option_cards = []
        for block in resp["assistant"]["blocks"]:
            if block["type"] == "options":
                option_cards.append(block)
            elif block["type"] == "receipt":
                d = block["data"]
                lines.append("【" + d.get("title", "回执") + "】" + "；".join(f"{l['label']} {l['value']}" for l in d.get("lines", [])))
            elif block["type"] == "note":
                if block["data"]["text"] not in lines[0]:
                    lines.append(block["data"]["text"])
            else:
                text = _summary(block)
                if text and text not in lines[0]:
                    lines.append(text)
        pending = resp.get("pending")
        if pending and pending["tier"] == "red":
            lines.append(f"这是红档操作（{pending['title']}），为了安全，飞书里不能完成。请打开小安 App（{self.app_url}）在“待办”里输入交易密码和短信动态码。")
        self.transport.send_text(open_id, "\n".join(l for l in lines if l))
        for block in option_cards:
            self.transport.send_card(open_id, self.options_card(user_id, block))
        if pending and pending["tier"] == "yellow" and pending.get("confirmation_code"):
            self.transport.send_card(open_id, self.pending_card(user_id, pending))

    def pending_card(self, user_id, pending):
        risk = pending.get("risk")
        ack = bool(risk and risk.get("require_ack"))
        confirm = self._token(user_id, kind="confirm", request_id=pending["request_id"], code=pending["confirmation_code"], ack=ack)
        cancel = self._token(user_id, kind="cancel", request_id=pending["request_id"])
        body = "\n".join(f"**{l['label']}**：{l['value']}" for l in pending["lines"])
        elements = [{"tag": "div", "text": {"tag": "lark_md", "content": body}}]
        if risk:
            elements.append({"tag": "div", "text": {"tag": "lark_md", "content": "⚠️ **风险提示**：" + "；".join(risk["reasons"]) + "\n" + risk["advice"]}})
        elements.append({"tag": "note", "elements": [{"tag": "plain_text", "content": (pending.get("impact") or "") + " 5 分钟内有效。模拟数据。"}]})
        elements.append({"tag": "action", "actions": [
            {"tag": "button", "type": "primary", "text": {"tag": "plain_text", "content": "我已了解风险，确认" if ack else "确认"},
             "value": {"t": confirm}},
            {"tag": "button", "type": "default", "text": {"tag": "plain_text", "content": "取消"}, "value": {"t": cancel}}]})
        return {"config": {"wide_screen_mode": True},
                "header": {"template": "orange" if risk else "blue", "title": {"tag": "plain_text", "content": "待确认 · " + pending["title"]}},
                "elements": elements}

    def options_card(self, user_id, block):
        d = block["data"]
        actions = [{"tag": "button", "type": "default", "text": {"tag": "plain_text", "content": item["label"][:30]},
                    "value": {"t": self._token(user_id, kind="option", ref=d["ref"], value=item["value"])}} for item in d["items"][:5]]
        return {"config": {"wide_screen_mode": True}, "header": {"template": "blue", "title": {"tag": "plain_text", "content": d["prompt"][:60]}},
                "elements": [{"tag": "action", "actions": actions}]}

    # ------------------------------------------------------------------ 主动推送
    def push_new_notifications(self):
        """把新产生的通知推给已绑定的本人。返回推送条数。"""
        with self.kernel.lock:
            latest = self.kernel.db.execute("SELECT MAX(rowid) FROM notifications").fetchone()[0] or 0
            if latest < self.last_notification:  # 演示库被重置过
                self.last_notification = latest
                return 0
            rows = self.kernel.db.execute("""SELECT n.rowid AS rid, n.*, b.external_id FROM notifications n
                JOIN im_bindings b ON b.user_id=n.user_id AND b.channel=? WHERE n.rowid>? ORDER BY n.rowid""",
                                          (CHANNEL, self.last_notification)).fetchall()
        for row in rows:
            self.transport.send_text(row["external_id"], f"【小安通知 · 模拟】{row['title']}\n{row['body']}")
        self.last_notification = max(self.last_notification, latest)
        return len(rows)

    def start_pusher(self, stop_event, interval=5):
        def loop():
            while not stop_event.wait(interval):
                try:
                    self.push_new_notifications()
                except Exception:
                    traceback.print_exc()
        thread = threading.Thread(target=loop, name="feishu-push", daemon=True)
        thread.start()
        return thread


# ---------------------------------------------------------------------------------------------- 真实飞书（lark-oapi）
class LarkTransport:
    """用飞书开放平台发消息。真机联调等队长建好应用后再做（真机未验证）。"""

    def __init__(self, app_id, app_secret):
        import lark_oapi as lark
        self.lark = lark
        self.client = lark.Client.builder().app_id(app_id).app_secret(app_secret).log_level(lark.LogLevel.WARNING).build()

    def _send(self, open_id, msg_type, content):
        from lark_oapi.api.im.v1 import CreateMessageRequest, CreateMessageRequestBody
        request = (CreateMessageRequest.builder().receive_id_type("open_id")
                   .request_body(CreateMessageRequestBody.builder().receive_id(open_id).msg_type(msg_type)
                                 .content(json.dumps(content, ensure_ascii=False)).build()).build())
        response = self.client.im.v1.message.create(request)
        if not response.success():
            print(f"飞书消息发送失败：code={response.code}", flush=True)  # 不打印正文和凭据

    def send_text(self, open_id, text):
        self._send(open_id, "text", {"text": text})

    def send_card(self, open_id, card):
        self._send(open_id, "interactive", card)


def start_feishu(kernel, agent, stop_event):
    """`python run.py --feishu`：长连接模式启动机器人（不需要公网地址）。返回 bridge，失败返回 None。"""
    app_id, app_secret = os.environ.get("FEISHU_APP_ID", ""), os.environ.get("FEISHU_APP_SECRET", "")
    if not app_id or not app_secret:
        print(" 飞书：没有设置 FEISHU_APP_ID / FEISHU_APP_SECRET，机器人未启动。")
        return None
    try:
        import lark_oapi as lark
        from lark_oapi.event.callback.model.p2_card_action_trigger import P2CardActionTriggerResponse
    except ImportError:
        print(" 飞书：没有安装 lark-oapi（pip install -r requirements-feishu.txt），机器人未启动。")
        return None
    bridge = FeishuBridge(kernel, agent, LarkTransport(app_id, app_secret))

    def on_message(data):
        try:
            message, sender = data.event.message, data.event.sender
            text = json.loads(message.content or "{}").get("text", "") if message.message_type == "text" else ""
            text = re.sub(r"@_user_[0-9]+\s*", "", text)
            open_id = sender.sender_id.open_id
            # 模型调用需要几秒，放到线程里，避免阻塞长连接
            threading.Thread(target=bridge.on_message, args=(open_id, message.chat_type, message.message_type, text, message.message_id),
                             daemon=True).start()
        except Exception:
            traceback.print_exc()

    def on_card(data):
        try:
            toast = bridge.on_card_action(data.event.operator.open_id, data.event.action.value or {})
        except Exception:
            traceback.print_exc()
            toast = {"type": "error", "content": "处理失败"}
        return P2CardActionTriggerResponse({"toast": toast})

    handler = (lark.EventDispatcherHandler.builder("", "")
               .register_p2_im_message_receive_v1(on_message)
               .register_p2_card_action_trigger(on_card).build())
    client = lark.ws.Client(app_id, app_secret, event_handler=handler, log_level=lark.LogLevel.WARNING)
    threading.Thread(target=client.start, name="feishu-ws", daemon=True).start()
    bridge.start_pusher(stop_event)
    print(" 飞书：机器人已通过长连接启动（只处理私聊；红档需回到 App 完成强验证）。")
    return bridge
