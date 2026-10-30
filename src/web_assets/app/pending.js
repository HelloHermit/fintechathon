// 待确认单：底部弹出面板（黄档确认 / 红档强验证）+ 对话里的简要卡片。
// 安全要点：confirmation_code 只在点“确认”时原样回传，不显示、不存进对话；交易密码只存在局部变量里，提交后立即清空。
import { h, icon, yuan, fmtTime, isoMs } from "./util.js";
import { api } from "./api.js";
import { state, on, emit, simNowMs, setPendingStatus } from "./store.js";
import { runTurn } from "./turn.js";
import { openSheet, closeSheet } from "./sheet.js";
import { renderPlan } from "./plan.js";
import { toast } from "./toast.js";

const ARRIVAL = {
  instant: ["实时到账", "确认后立即转出"],
  delayed_2h: ["2 小时后到账", "到账前可以撤回"],
  delayed_24h: ["24 小时后到账", "推荐：到账前可以撤回，给自己留出核实时间"],
};
function arrivalOf(op) {
  const line = (op.lines || []).find((l) => /到账/.test(l.label));
  const v = line ? String(line.value) : "";
  if (/24/.test(v)) return "delayed_24h";
  if (/2\s*小时/.test(v)) return "delayed_2h";
  return "instant";
}
const STATUS_TEXT = { open: "待确认", done: "已处理", cancelled: "已取消", invalid: "已失效", expired: "已过期" };

/** 对话里的待确认简要卡片 */
export function pendingSummary(op) {
  const entry = state.pendings.get(op.request_id);
  const status = entry?.status || "open";
  const amountLine = (op.lines || []).find((l) => l.emphasis) || (op.lines || [])[0];
  const el = h(`div.pending-card.${op.tier}`, { dataset: { requestId: op.request_id } },
    h("div.pc-head", null, h(`span.tier-tag.${op.tier}`, { text: op.tier === "red" ? "红档 · 需强验证" : "黄档 · 需确认" }),
      h(`span.pc-status.${status}`, { text: STATUS_TEXT[status] || status })),
    h("div.pc-title", { text: op.title || "待确认操作" }),
    amountLine ? h("div.pc-amount", null, h("span.muted.small", { text: amountLine.label }), h("span", { text: amountLine.value })) : null,
    op.risk ? h(`div.pc-risk.${op.risk.level}`, null, icon("alert"), h("span", { text: `${op.risk.level === "high" ? "高风险" : "中风险"}：${(op.risk.reasons || [])[0] || ""}` })) : null,
    status === "open" ? h("button.btn.primary.block", { type: "button", onclick: () => openPending(op.request_id) }, op.tier === "red" ? "查看并验证" : "查看并确认") : null);
  return el;
}

/** 打开某张单的面板 */
export function openPending(requestId) {
  const entry = state.pendings.get(requestId);
  if (!entry || entry.status !== "open") return;
  state.activePendingId = requestId;
  const view = new PendingView(entry.op);
  openSheet(view.el, { onClose: () => view.destroy(), label: entry.op.title });
}

class PendingView {
  constructor(op) {
    this.op = op;
    this.ack = false;
    this.timers = [];
    this.el = h("div.pending-sheet");
    const offP = on("pendings", () => {
      const e = state.pendings.get(this.op.request_id);
      if (!e || e.status !== "open") closeSheet();
    });
    const offB = on("busy", () => (this.verifyBtn?.isConnected ? this.paintFields() : this.updateClocks()));
    this.unsub = () => { offP(); offB(); };
    this.renderConfirm();
    this.tick = setInterval(() => this.updateClocks(), 500);
  }
  destroy() { clearInterval(this.tick); this.unsub?.(); this.timers.forEach(clearTimeout); this.pin = ""; this.otp = ""; }

  header() {
    const op = this.op;
    return h("div.ps-head", null,
      h(`span.tier-tag.${op.tier}`, { text: op.tier === "red" ? "红档 · 交易密码 + 短信动态码" : "黄档 · 需要你确认" }),
      h("button.icon-btn", { type: "button", "aria-label": "稍后处理", onclick: () => closeSheet() }, icon("x")));
  }

  renderConfirm() {
    const op = this.op;
    const risk = op.risk;
    const lines = h("div.ps-lines", null, (op.lines || []).map((l) => h(`div.ps-line${l.emphasis ? ".emph" : ""}`, null, h("span.k", { text: l.label }), h("span.v", { text: l.value }))));
    const children = [
      this.header(),
      h("h2.ps-title", { text: op.title || "请确认" }),
      lines,
      op.impact ? h("div.ps-impact", null, icon("sparkle"), h("span", { text: op.impact })) : null,
    ];
    if (op.plan_id && state.lastTurn?.plan && state.lastTurn.plan.plan_id === op.plan_id) {
      children.push(h("div.ps-plan", null, renderPlan({ ...state.lastTurn.plan, actions: [] })));
    }
    if (risk) children.push(this.riskBox(risk));
    this.expiryEl = h("div.ps-expiry.muted.small");
    this.cooldownEl = h("div.ps-cooldown");
    this.mainBtn = h("button.btn.primary.block.lg", { type: "button", onclick: () => this.primary() }, op.tier === "red" ? "下一步：强验证" : "确认办理");
    children.push(this.cooldownEl,
      h("div.ps-actions", null,
        h("button.btn.ghost", { type: "button", onclick: () => this.cancel() }, "取消"),
        this.mainBtn),
      this.expiryEl,
      h("div.ps-foot.muted.small", { text: op.tier === "red" ? "红档操作只认交易密码 + 动态码；在聊天里说“我确认”不算确认。" : "只有点击“确认办理”才会执行；在聊天里说“我确认”不算确认。" }));
    this.el.replaceChildren(...children.filter(Boolean));
    this.updateClocks();
  }

  riskBox(risk) {
    const box = h(`div.risk-box.${risk.level}`, null,
      h("div.risk-head", null, icon("shield"), h("span", { text: risk.level === "high" ? "高风险交易" : "请注意风险" }),
        risk.score != null ? h("span.risk-score", { text: `风险分 ${risk.score}` }) : null),
      h("ul.risk-reasons", null, (risk.reasons || []).map((r) => h("li", { text: r }))),
      risk.advice ? h("div.risk-advice", { text: risk.advice }) : null);
    if (risk.arrival_options?.length) {
      const current = this.op.arrival || arrivalOf(this.op);
      const group = h("div.arrival", { role: "radiogroup", "aria-label": "到账方式" });
      risk.arrival_options.forEach((opt) => {
        const [label, hint] = ARRIVAL[opt] || [opt, ""];
        const checked = opt === current;
        const inp = h("input", { type: "radio", name: "arrival", value: opt, checked });
        inp.addEventListener("change", () => this.revise(opt));
        group.append(h("label.arrival-opt", null, inp, h("span", null, h("b", { text: label }), h("span.muted.small", { text: hint }))));
      });
      box.append(h("div.arrival-title", { text: "到账方式" }), group);
    }
    if (risk.require_ack) {
      const cb = h("input", { type: "checkbox" });
      cb.addEventListener("change", () => { this.ack = cb.checked; this.updateClocks(); });
      box.append(h("label.ack", null, cb, h("span", { text: "我已了解以上风险，确认是我本人要办理" })));
    }
    return box;
  }

  updateClocks() {
    const now = simNowMs();
    const op = this.op;
    const exp = isoMs(op.expires_at);
    if (this.expiryEl && exp) {
      const left = Math.max(0, Math.round((exp - now) / 1000));
      this.expiryEl.textContent = left > 0 ? `确认单 ${Math.floor(left / 60)}:${String(left % 60).padStart(2, "0")} 后失效，失效后需重新发起` : "确认单已过期，请重新发起";
      if (left <= 0 && state.pendings.get(op.request_id)?.status === "open") {
        setPendingStatus(op.request_id, "expired");
      }
    }
    let blocked = false;
    const nb = isoMs(op.risk?.not_before);
    if (this.cooldownEl) {
      if (nb && nb > now) {
        const left = Math.ceil((nb - now) / 1000);
        this.cooldownEl.replaceChildren(icon("clock"), h("span", { text: `冷静期：请先停下来想一想，${left} 秒后才能继续。` }));
        this.cooldownEl.hidden = false;
        blocked = true;
      } else {
        this.cooldownEl.hidden = true;
      }
    }
    if (op.risk?.require_ack && !this.ack) blocked = true;
    if (this.mainBtn) this.mainBtn.disabled = blocked || state.busy;
  }

  async primary() {
    if (this.op.tier === "red" || this.op.kind === "strong_auth") return this.renderStrongAuth();
    this.mainBtn.disabled = true;
    const op = this.op;
    const resp = await runTurn(() => api.confirm(op.request_id, op.confirmation_code, op.risk?.require_ack ? this.ack : undefined),
      { label: "点击确认", kind: "confirm", forRequest: op.request_id });
    if (resp) closeSheet();
    else this.updateClocks();
  }

  async cancel() {
    const op = this.op;
    closeSheet();
    await runTurn(() => api.cancel(op.request_id), { label: "取消这笔操作", kind: "cancel", forRequest: op.request_id });
  }

  async revise(arrival) {
    const op = this.op;
    const resp = await runTurn(() => api.revise(op.request_id, arrival), { label: `改为${(ARRIVAL[arrival] || [arrival])[0]}`, kind: "revise", forRequest: op.request_id });
    if (resp?.pending) {
      this.op = { ...resp.pending, arrival };
      this.ack = false;
      state.activePendingId = resp.pending.request_id;
      this.renderConfirm();
    } else closeSheet();
  }

  // ---------- 红档强验证 ----------
  renderStrongAuth() {
    const op = this.op;
    this.pin = "";
    this.otp = "";
    this.field = "pin";
    const phone = state.session?.user?.masked_phone || "绑定手机";
    this.sendBtn = h("button.btn.small", { type: "button", onclick: () => this.sendOtp() }, "获取动态码");
    this.otpInfo = h("div.muted.small", { text: `动态码会以模拟短信发到 ${phone}，在右侧“模拟手机”里查看。` });
    this.pinDots = h("button.code-field.active", { type: "button", "aria-label": "交易密码", onclick: () => this.focus("pin") });
    this.otpDots = h("button.code-field", { type: "button", "aria-label": "短信动态码", onclick: () => this.focus("otp") });
    this.errorEl = h("div.sa-error", { role: "alert" });
    this.verifyBtn = h("button.btn.primary.block.lg", { type: "button", disabled: true, onclick: () => this.verify() }, "验证并执行");
    const keypad = h("div.keypad", { role: "group", "aria-label": "数字键盘" },
      ..."123456789".split("").map((d) => this.key(d)),
      h("button.key.muted", { type: "button", onclick: () => this.clearField(), "aria-label": "清空" }, "清空"),
      this.key("0"),
      h("button.key.muted", { type: "button", onclick: () => this.backspace(), "aria-label": "删除" }, "删除"));
    const amount = (op.lines || []).find((l) => l.emphasis);
    this.el.replaceChildren(
      this.header(),
      h("h2.ps-title", { text: "强验证" }),
      h("div.sa-what", null, h("span", { text: op.title }), amount ? h("b", { text: amount.value }) : null),
      h("div.sa-field", null, h("label", { text: "交易密码（6 位）" }), this.pinDots),
      h("div.sa-field", null, h("div.sa-otp-head", null, h("label", { text: "短信动态码（6 位）" }), this.sendBtn), this.otpDots, this.otpInfo),
      this.errorEl,
      keypad,
      this.verifyBtn,
      h("div.ps-foot.muted.small", { text: "演示交易密码见 README。密码和动态码只发给后端核验，不会给 AI 模型，也不进日志。连续错 3 次将锁定 10 分钟。" }),
      h("button.btn.ghost.block", { type: "button", onclick: () => this.cancel() }, "取消这笔操作"));
    this.paintFields();
    this.keyHandler = (e) => {
      if (/^\d$/.test(e.key)) { this.input(e.key); e.preventDefault(); }
      else if (e.key === "Backspace") { this.backspace(); e.preventDefault(); }
      else if (e.key === "Enter" && !this.verifyBtn.disabled) this.verify();
    };
    this.el.tabIndex = -1;
    this.el.addEventListener("keydown", this.keyHandler);
    this.el.focus();
  }
  key(d) { return h("button.key", { type: "button", onclick: () => this.input(d) }, d); }
  focus(f) { this.field = f; this.paintFields(); }
  input(d) {
    if (this.field === "pin") {
      if (this.pin.length < 6) this.pin += d;
      if (this.pin.length === 6) this.field = "otp";
    } else if (this.otp.length < 6) this.otp += d;
    this.paintFields();
  }
  backspace() {
    if (this.field === "otp" && !this.otp.length) this.field = "pin";
    if (this.field === "pin") this.pin = this.pin.slice(0, -1); else this.otp = this.otp.slice(0, -1);
    this.paintFields();
  }
  clearField() { if (this.field === "pin") this.pin = ""; else this.otp = ""; this.paintFields(); }
  paintFields() {
    const dots = (n, show) => Array.from({ length: 6 }, (_, i) => h(`span.cd${i < n ? ".on" : ""}`, { text: i < n ? (show ? show[i] : "●") : "" }));
    this.pinDots.replaceChildren(...dots(this.pin.length));
    this.otpDots.replaceChildren(...dots(this.otp.length, this.otp));
    this.pinDots.classList.toggle("active", this.field === "pin");
    this.otpDots.classList.toggle("active", this.field === "otp");
    this.verifyBtn.disabled = !(this.pin.length === 6 && this.otp.length === 6) || state.busy;
  }
  async sendOtp() {
    this.sendBtn.disabled = true;
    try {
      const r = await api.sendOtp(this.op.request_id);
      this.otpInfo.textContent = `已向 ${r.masked_phone || "绑定手机"} 发送模拟短信，${r.expires_at ? fmtTime(r.expires_at, "hm") + " 前" : "5 分钟内"}有效。`;
      emit("sms-refresh");
      let left = r.resend_after_seconds ?? 60;
      const step = () => {
        if (!this.sendBtn.isConnected) return;
        if (left <= 0) { this.sendBtn.disabled = false; this.sendBtn.textContent = "重新发送"; return; }
        this.sendBtn.textContent = `${left} 秒后可重发`;
        left -= 1;
        this.timers.push(setTimeout(step, 1000));
      };
      step();
      this.field = this.pin.length === 6 ? "otp" : "pin";
      this.paintFields();
    } catch (e) {
      this.sendBtn.disabled = false;
      this.errorEl.textContent = e.message;
    }
  }
  async verify() {
    const op = this.op;
    const pin = this.pin, otp = this.otp;
    this.pin = ""; this.otp = "";
    this.paintFields();
    this.verifyBtn.disabled = true;
    const resp = await runTurn(() => api.verify(op.request_id, pin, otp, op.risk?.require_ack ? this.ack : undefined),
      { label: "提交强验证", kind: "verify", forRequest: op.request_id });
    if (!resp) return;
    if (state.pendings.get(op.request_id)?.status === "open") {
      // 验证没通过：单子还在，留在面板里重试
      this.errorEl.textContent = resp.error?.message || resp.assistant?.text || "验证没有通过，请重试。";
      this.field = "pin";
      this.paintFields();
      return;
    }
    closeSheet();
    if (resp.error?.code === "locked") toast("红档操作已锁定 10 分钟");
  }
}

// 新单出现时自动弹出
on("open-pending", (id) => { if (!document.querySelector(".pending-sheet")) openPending(id); });
