"""外部 IM 账号 ↔ 演示用户的绑定。绑定码 6 位、一次性、5 分钟有效，库里只存加盐哈希。"""

from datetime import timedelta

from ..core.kernel import RuleError
from ..core.util import check_salted, iso, numeric_code, parse_iso, salted_hash

BIND_TTL = timedelta(minutes=5)


def mask_external(external_id):
    if not external_id:
        return None
    return external_id[:3] + "****" + external_id[-4:] if len(external_id) > 8 else "****"


def create_code(kernel, user_id, channel="feishu"):
    """生成绑定码（旧码作废）。明文只返回这一次。"""
    code = numeric_code(6)
    digest, salt = salted_hash(code)
    expires = kernel.now() + BIND_TTL
    with kernel.tx():
        kernel.db.execute("INSERT OR REPLACE INTO bind_codes VALUES(?,?,?,?,?,0)", (user_id, channel, digest, salt, iso(expires)))
        kernel.audit(user_id, "im_bind", "green", "bind_code_created", "success", f"生成{channel}绑定码（5 分钟有效）", actor="user")
    return {"code": code, "expires_at": iso(expires), "instructions": f"在飞书里私聊机器人发送：绑定 {code}"}


def consume_code(kernel, channel, external_id, code):
    """IM 用户发“绑定 123456”。成功返回 user_id；失败抛 RuleError。同一个 IM 账号只能绑定一个演示用户。"""
    if not (isinstance(code, str) and code.isdigit() and len(code) == 6):
        raise RuleError("invalid_request", "绑定码是 6 位数字。")
    now = kernel.now()
    with kernel.tx():
        rows = kernel.db.execute("SELECT * FROM bind_codes WHERE channel=? AND used=0", (channel,)).fetchall()
        match = next((r for r in rows if parse_iso(r["expires_at"]) > now and check_salted(code, r["code_hash"], r["code_salt"])), None)
        if match is None:
            raise RuleError("invalid_request", "绑定码不正确或已过期，请在 App“我的 → 绑定飞书”里重新生成。")
        kernel.db.execute("UPDATE bind_codes SET used=1 WHERE user_id=? AND channel=?", (match["user_id"], channel))
        kernel.db.execute("DELETE FROM im_bindings WHERE channel=? AND (external_id=? OR user_id=?)", (channel, external_id, match["user_id"]))
        kernel.db.execute("INSERT INTO im_bindings VALUES(?,?,?,?)", (channel, external_id, match["user_id"], iso(now)))
        kernel.audit(match["user_id"], "im_bind", "green", "im_bound", "success", f"{channel}账号 {mask_external(external_id)} 完成绑定",
                     actor="user")
    return match["user_id"]


def user_for(kernel, channel, external_id):
    with kernel.lock:
        row = kernel.db.execute("SELECT user_id FROM im_bindings WHERE channel=? AND external_id=?", (channel, external_id)).fetchone()
    return row[0] if row else None


def external_for(kernel, channel, user_id):
    with kernel.lock:
        row = kernel.db.execute("SELECT external_id, bound_at FROM im_bindings WHERE channel=? AND user_id=?", (channel, user_id)).fetchone()
    return (row[0], row[1]) if row else (None, None)


def unbind(kernel, channel, user_id):
    with kernel.tx():
        kernel.db.execute("DELETE FROM im_bindings WHERE channel=? AND user_id=?", (channel, user_id))
        kernel.audit(user_id, "im_bind", "green", "im_unbound", "success", f"解除{channel}绑定", actor="user")


def status(kernel, user_id, bot_running):
    external, bound_at = external_for(kernel, "feishu", user_id)
    return {"feishu": {"enabled": bool(bot_running), "bot_running": bool(bot_running), "bound": external is not None,
                       "bound_at": bound_at, "masked_account": mask_external(external),
                       "display_name": kernel.user(user_id)["display_name"] if external else None}}
