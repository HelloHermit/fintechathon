// 安全透视：把一轮对话的决策链（TraceStep）画成时间线。
import { h, icon } from "./util.js";

export const KIND = {
  guard: ["输入守卫", "shield"], llm: ["模型调用", "sparkle"], tool: ["工具调用", "code"], resolver: ["代码解析", "search"],
  provenance: ["参数溯源", "eye"], tier: ["代码判档", "lock"], risk: ["反诈评分", "alert"], auth: ["确认 / 强验证", "lock"],
  fact_check: ["事实校验", "check"], plan: ["任务规划", "plan"], audit: ["审计", "audit"],
};
const STATUS = { pass: "通过", warned: "提示", blocked: "拦截", pending: "待定", success: "成功", failed: "失败" };
const GUARD = { pass: "输入正常", warned: "输入有风险提示", blocked: "输入已拦截" };

export function renderTrace(turn, { compact = false } = {}) {
  if (!turn) {
    return h("div.trace-empty", null, icon("shield"), h("div", { text: "和小安说一句话后，这里会实时显示每一步：模型提了什么、代码怎么校验和判档。" }));
  }
  const steps = turn.trace || [];
  const guard = turn.guard || {};
  const summary = h("div.trace-summary", null,
    guard.input ? h(`span.chip.${guard.input === "blocked" ? "danger" : guard.input === "warned" ? "warn" : "ok"}`, { text: GUARD[guard.input] || guard.input }) : null,
    guard.fact_check ? h(`span.chip.${guard.fact_check === "corrected" ? "warn" : "ok"}`, { text: guard.fact_check === "corrected" ? "事实校验：已纠正回复" : "事实校验：通过" }) : null,
    guard.locked_until ? h("span.chip.danger", { text: "会话只读中" }) : null,
    turn.pending ? h(`span.chip.${turn.pending.tier === "red" ? "danger" : "warn"}`, { text: turn.pending.tier === "red" ? "待强验证" : "待确认" }) : null);
  const totalMs = steps.reduce((a, x) => a + (Number(x.ms) || 0), 0);
  const list = h("ol.trace", null, steps.map((st) => {
    const [kname, ic] = KIND[st.kind] || [st.kind, "sparkle"];
    const hasDetail = st.detail && Object.keys(st.detail).length;
    const item = h(`li.tstep.${st.status || "pass"}`, null,
      h("span.tstep-ic", null, icon(ic)),
      h("div.tstep-main", null,
        h("div.tstep-head", null, h("span.tstep-kind", { text: kname }), h(`span.tstep-st.${st.status || "pass"}`, { text: STATUS[st.status] || st.status || "" }),
          st.ms != null ? h("span.tstep-ms", { text: `${st.ms}ms` }) : null),
        h("div.tstep-label", { text: st.label || "" }),
        hasDetail && !compact ? h("details.tstep-detail", null, h("summary", { text: "详情" }), h("pre", { text: JSON.stringify(st.detail, null, 2) })) : null));
    return item;
  }));
  return h("div.trace-wrap", null,
    summary,
    steps.length ? list : h("div.muted.small", { text: "这一轮没有决策链记录。" }),
    h("div.trace-foot.muted.small", { text: `${steps.length} 步 · 合计 ${totalMs}ms${turn.turn_id ? ` · ${turn.turn_id}` : ""}` }));
}
