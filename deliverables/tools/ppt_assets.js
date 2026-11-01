// 生成给队员手工粘贴进 PPT 的素材（deliverables/PPT素材/）。不改 答辩PPT.pptx。
//   先启动后端：python run.py --reset
//   node deliverables/tools/ppt_assets.js [http://127.0.0.1:8765] [--no-screens]
const fs = require("fs");
const path = require("path");
let chromium;
try { ({ chromium } = require("playwright")); } catch { ({ chromium } = require(require.resolve("playwright", { paths: ["/usr/lib/node_modules", "/usr/local/lib/node_modules", "/opt/node22/lib/node_modules"] }))); }

const BASE = process.argv.find((a) => a.startsWith("http")) || "http://127.0.0.1:8765";
const NO_SCREENS = process.argv.includes("--no-screens");
const ROOT = path.resolve(__dirname, "..", "..");
const OUT = path.join(ROOT, "deliverables", "PPT素材");
fs.mkdirSync(OUT, { recursive: true });
const bench = JSON.parse(fs.readFileSync(path.join(ROOT, "bench", "reports", "latest.json"), "utf8"));
const HIST = path.join(ROOT, "bench", "reports", "history");

const FONT = `"Microsoft YaHei","PingFang SC","Noto Sans CJK SC","WenQuanYi Zen Hei",sans-serif`;
const CSS = `*{box-sizing:border-box}body{margin:0;background:#fff;font-family:${FONT};color:#0f172a}
.wrap{width:1600px;padding:56px 64px}.h{font-size:52px;font-weight:800;color:#13204A;margin:0 0 10px}.sub{font-size:26px;color:#64748b;margin:0 0 34px}
table{border-collapse:collapse;width:100%;font-size:25px}th,td{border:2px solid #d6dce8;padding:14px 16px;text-align:left;vertical-align:top;line-height:1.4}
th{background:#13204A;color:#fff;font-size:26px}tr:nth-child(even) td{background:#f5f7fc}.src{font-size:19px;color:#64748b;margin-top:22px;line-height:1.5}
.ok{color:#059669;font-weight:800}.no{color:#dc2626;font-weight:800}.mut{color:#64748b}`;

async function htmlShot(page, name, html) {
  await page.setContent(`<html><head><meta charset="utf-8"><style>${CSS}</style></head><body>${html}</body></html>`);
  await page.waitForTimeout(150);
  await page.locator(".wrap").screenshot({ path: path.join(OUT, name) });
  console.log("png", name);
}

// ---------------------------------------------------------------- a 架构简版
function archHtml() {
  const box = (t, items, bg, fg = "#fff", note = "") => `<div style="display:flex;align-items:center;gap:26px">
    <div style="flex:1;background:${bg};color:${fg};border-radius:24px;padding:26px 34px">
      <div style="font-size:40px;font-weight:800">${t}</div><div style="font-size:28px;margin-top:8px;opacity:.95">${items}</div></div>
    <div style="width:260px;font-size:30px;font-weight:800;color:${bg}">${note}</div></div>`;
  const arrow = `<div style="text-align:center;font-size:40px;color:#94a3b8;line-height:1;margin:6px 0 6px -286px">▼</div>`;
  return `<div class="wrap"><div class="h">架构：模型提议，代码裁决</div><div class="sub">四层；模型只能提出待确认单，执行只发生在用户本人确认或强验证之后</div>
  ${box("渠道层", "App（可安装的手机网页 PWA） · 飞书私聊机器人 —— 按渠道分级风控", "#1d4ed8")}${arrow}
  ${box("Agent 编排层", "输入守卫 · 大模型工具调用与 DAG 规划 · 参数溯源 · 事实校验", "#7c3aed", "#fff", "模型提议")}${arrow}
  ${box("安全内核", "代码判档（绿/黄/红）· 确认绑定 / 交易密码 + 短信动态码 · 执行前复查 · 熔断 · 只追加审计 + 哈希链", "#059669", "#fff", "代码裁决")}${arrow}
  ${box("模拟账本 + 沙箱", "SQLite 演示数据 · 调度器 · 模型生成的分析代码只在受限子进程里运行（无网络、限时限内存）", "#13204A")}
  <div class="src">全部数据为模拟。看不到确认码、动态码、交易密码的是模型；能执行资金操作的只有安全内核。</div></div>`;
}

// ---------------------------------------------------------------- b 对标 Revolut AIR
const AIR_ROWS = [
  ["能做的事", "消费查询与洞察、投资跟踪、订阅管理、卡片控制（含冻结丢失的卡）、旅行规划（旅行预算、eSIM）；推荐问题、文字/语音输入", "转账、账单、理财、卡片、订阅、跨场景联动六大场景；推荐问题、语音输入；出境游为 10-31 新增、未纳入 151 条评测；没有 eSIM"],
  ["渠道", "只有 App 内一个渠道（评论指出的不足）", "App（PWA）+ 飞书 IM，按渠道分级风控"],
  ["交易验证", "每一笔金融交易都绑定生物识别确认", "三档权限：查询自动、低风险点确认、高风险交易密码 + 短信动态码；没有生物识别"],
  ["模型能看到什么", "称金融数据不进入模型上下文", "看不到确认码、动态码、交易密码；本人模拟账本数据会进入上下文（已列为已知风险）"],
  ["转人工与例外", "评论指出“逃不出自动客服循环”、缺少清晰的转人工出口；冻结账户、反洗钱触发等例外处理弱", "明确的转人工出口；冻结、挂失、反诈拦截都有专门流程"],
  ["复杂任务", "公开资料未提及", "DAG 计划：一次确认、到点执行、可回退"],
  ["反诈与可解释", "公开资料未提及", "反诈评分 + 冷静期 + 延时到账；“安全透视”决策链与哈希链审计"],
];
const AIR_SOURCES = [
  "https://www.revolut.com/news/revolut_enters_new_era_of_money_intelligence_with_launch_of_ai_assistant/",
  "https://www.revolut.com/blog/post/air-ai-by-revolut",
  "https://ergomania.eu/revolut-air-ai-banking-assistant-ux/",
  "https://www.uktech.news（2026-04-09 报道）",
];
function airHtml() {
  return `<div class="wrap"><div class="h">行业对标：Revolut AIR</div><div class="sub">AIR 于 2026-04-09 在英国上线、后扩展到欧洲；以下只引用公开资料</div>
  <table><tr><th style="width:17%">维度</th><th style="width:41%">Revolut AIR（公开资料）</th><th>小安</th></tr>
  ${AIR_ROWS.map((r) => `<tr><td><b>${r[0]}</b></td><td>${r[1]}</td><td>${r[2]}</td></tr>`).join("")}</table>
  <div class="src"><b>结论</b>：对齐——自然语言查询与执行、订阅、卡片、投资、推荐问题、语音；超出——多渠道分级风控、三档权限、反诈与延时到账、可回退计划、转人工、可解释；不及——模拟原型、没有生物识别、没有 eSIM（出境游为 10-31 新增、未纳入评测）。<br>来源：Revolut 新闻稿与博客（revolut.com）、ergomania.eu UX 评论、uktech.news 2026-04-09 报道。</div></div>`;
}

// ---------------------------------------------------------------- c 评测迭代
function runs() {
  const files = fs.readdirSync(HIST).filter((f) => /^\d{8}-\d{6}\.json$/.test(f)).sort();
  return files.map((f) => {
    const d = JSON.parse(fs.readFileSync(path.join(HIST, f), "utf8"));
    if (d.meta.case_count < 100) return null; // 只取全量
    return { when: d.meta.finished_at.slice(5, 16), git: d.meta.git, task: d.metrics.task_completion, sec: d.metrics.security_block, ux: d.metrics.ux };
  }).filter(Boolean);
}
function iterHtml(rs) {
  const W = 1200, H = 520, pad = 70, gw = (W - pad * 2) / rs.length;
  const bar = (x, v, color, label) => {
    const h = (v / 100) * (H - 110);
    return `<rect x="${x}" y="${H - 50 - h}" width="110" height="${h}" rx="10" fill="${color}"/>
      <text x="${x + 55}" y="${H - 62 - h}" text-anchor="middle" font-size="30" font-weight="800" fill="${color}">${v}%</text>`;
  };
  const groups = rs.map((r, i) => {
    const x0 = pad + i * gw + gw / 2 - 120;
    return `${bar(x0, r.task.rate, "#1d4ed8")}${bar(x0 + 130, r.sec.rate, "#059669")}
      <text x="${x0 + 120}" y="${H - 12}" text-anchor="middle" font-size="26" fill="#334155">第 ${i + 1} 轮 · ${r.when}</text>`;
  }).join("");
  return `<div class="wrap"><div class="h">评测迭代：三轮全量，问题照实修</div><div class="sub">独立黑盒评测 ${bench.meta.case_count} 条，真实大模型；每轮失败都定位到“后端问题”或“评测程序问题”再修</div>
  <svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" style="font-family:${FONT}">
    <line x1="40" x2="${W - 20}" y1="${H - 50}" y2="${H - 50}" stroke="#cbd5e1" stroke-width="2"/>${groups}</svg>
  <div style="display:flex;gap:40px;font-size:28px;margin-top:10px"><span><b style="color:#1d4ed8">■</b> 任务完成率</span><span><b style="color:#059669">■</b> 攻击拦截率</span></div>
  <div class="src">第 1 轮安全类偏低，主要是评测程序发请求过快触发了聊天限流（这本身是一项防护），改为按提示等待重试后恢复；第 2 轮剩下 1 条后端问题（房租建议金额）和 1 条评测程序缺陷（读错短信顺序），都已修复。明细见 docs/测试报告.md。</div></div>`;
}

// ---------------------------------------------------------------- e 18 项能力
const CAPS = [
  ["智能转账", "按姓名 / 称呼转账", "“给小王转500”“给我妈转一千块”", ["T1"]],
  ["智能转账", "按手机号转账", "“给13900000123转300”→ 首次收款人风险提示", ["T2"]],
  ["智能转账", "按用途 / 备注转账", "“把这个月房租交了”→ 建议 ¥4,500 供点选", ["T3"]],
  ["智能转账", "定时转账", "“明天给小王转200，备注还饭钱”→ 到点执行", ["T4"]],
  ["智能转账", "AA 收款", "“昨晚和小王、小张吃饭花了360，AA一下”", ["T5"]],
  ["智能转账", "大额转账强验证", "“给妈妈转2000”→ 交易密码 + 短信动态码", ["T6"]],
  ["账单分析", "消费分类统计与查询", "“这个月花了多少”“上个月外卖花了多少”", ["L1", "L2"]],
  ["账单分析", "异常交易识别", "“帮我看看有没有异常扣款”", ["L3"]],
  ["账单分析", "月度 / 年度报告", "“生成10月账单报告”“我今年的消费年报”", ["L4", "L5"]],
  ["理财", "产品查询、对比与推荐", "“对比一下活钱宝和稳健季享”“推荐点稳一点的”", ["W1", "W3"]],
  ["理财", "风险测评与适当性", "“我想买点理财”→ 问卷 → 等级；不匹配的拒绝", ["W2", "W6"]],
  ["理财", "申购与赎回、持仓收益", "“买一万稳健季享”“稳健季享赎回五千”", ["W4", "W5", "W7"]],
  ["卡片管理", "查询与申请虚拟卡", "“我有哪些卡”“帮我开张网购用的虚拟卡”", ["K1", "K2"]],
  ["卡片管理", "限额调整", "“降到2000”（黄）/“提到2万”（红）", ["K3"]],
  ["卡片管理", "冻结 / 解冻、挂失 / 解挂", "“我卡丢了”→ 临时冻结或正式挂失", ["K4", "K5", "K6"]],
  ["订阅 / 代扣", "订阅查询与自动识别", "“我有哪些自动扣费”→ 识别出读书App", ["S1", "S4"]],
  ["订阅 / 代扣", "续费提醒与一键取消", "首页“2 项订阅 7 天内续费”；“健身会员不要了”", ["S2", "S3"]],
  ["跨场景联动", "生日检测与一键筹备计划", "首页生日提醒 → DAG 计划 → 一次确认 → 到点执行 → 可回退", ["X1", "X2", "X3", "X4", "X5"]],
];
function capStatus(caps) {
  const rs = bench.results.filter((r) => caps.includes(r.cap));
  const pass = rs.filter((r) => r.status === "pass").length;
  return { pass, total: rs.length, ok: rs.length > 0 && pass === rs.length };
}
function capsHtml() {
  return `<div class="wrap"><div class="h">六大场景 18 项典型能力</div><div class="sub">每项至少 1 条、多数 3 种说法的黑盒用例；结果来自 ${bench.meta.finished_at.slice(0, 16)} 的评测（真实大模型）</div>
  <table style="font-size:23px"><tr><th style="width:13%">场景</th><th style="width:24%">能力</th><th>验收句（节选）</th><th style="width:15%">评测结果</th></tr>
  ${CAPS.map(([sc, cap, say, ids]) => { const st = capStatus(ids); return `<tr><td>${sc}</td><td><b>${cap}</b></td><td>${say}</td><td class="${st.ok ? "ok" : "no"}">${st.ok ? "✓ 通过" : "✗ 未全过"} ${st.pass}/${st.total}</td></tr>`; }).join("")}
  </table><div class="src">能力名称按冲刺方案第 4 节整理；提交前请对照赛题官方原文核对用词。</div></div>`;
}

// ---------------------------------------------------------------- 文字版
function writeTexts(rs) {
  const air = ["# 对标 Revolut AIR（文字版）", "", "| 维度 | Revolut AIR（公开资料） | 小安 |", "|---|---|---|",
    ...AIR_ROWS.map((r) => `| ${r.join(" | ")} |`), "",
    "**结论**：对齐——自然语言查询与执行、订阅、卡片、投资、推荐问题、语音；超出——多渠道分级风控、三档权限、反诈与延时到账、可回退计划、转人工、可解释；不及——模拟原型、没有生物识别、没有 eSIM（出境游为 10-31 新增、未纳入评测）。", "",
    "来源：", ...AIR_SOURCES.map((s) => `- ${s}`), ""].join("\n");
  fs.writeFileSync(path.join(OUT, "b-对标RevolutAIR.md"), air);
  const caps = ["# 六大场景 18 项典型能力对照（文字版）", "", `结果来自 ${bench.meta.finished_at}（北京时间）的黑盒评测，代码版本 \`${bench.meta.git}\`，真实大模型。能力名称按冲刺方案第 4 节整理，提交前请对照赛题官方原文核对用词。`, "",
    "| # | 场景 | 能力 | 验收句（节选） | 用例编号 | 结果 |", "|---|---|---|---|---|---|",
    ...CAPS.map(([sc, cap, say, ids], i) => { const st = capStatus(ids); return `| ${i + 1} | ${sc} | ${cap} | ${say} | ${ids.join("、")} | ${st.ok ? "通过" : "未全过"} ${st.pass}/${st.total} |`; }), ""].join("\n");
  fs.writeFileSync(path.join(OUT, "e-18项能力对照.md"), caps);
  const it = ["# 评测迭代（文字版）", "", "| 轮次 | 时间（北京） | 代码版本 | 任务完成率 | 攻击拦截率 | 体验 |", "|---|---|---|---|---|---|",
    ...rs.map((r, i) => `| 第 ${i + 1} 轮 | ${r.when} | \`${r.git}\` | ${r.task.rate}%（${r.task.passed}/${r.task.total}） | ${r.sec.rate}%（${r.sec.passed}/${r.sec.total}） | ${r.ux.rate}%（${r.ux.passed}/${r.ux.total}） |`), ""].join("\n");
  fs.writeFileSync(path.join(OUT, "c-评测迭代.md"), it);
}

// ---------------------------------------------------------------- d 高清截图
async function screens(browser) {
  const ctx = await browser.newContext({ viewport: { width: 1360, height: 900 }, deviceScaleFactor: 2 });
  const p = await ctx.newPage();
  const idle = async () => { await p.waitForFunction(() => !document.querySelector(".msg.busy"), null, { timeout: 90000 }); await p.waitForTimeout(700); };
  const say = async (t) => { await p.click(".tab[data-tab=chat]"); await p.fill(".chat-input", t); await p.keyboard.press("Enter"); await p.waitForTimeout(300); await idle(); };
  const hideBanner = () => p.evaluate(() => { const el = document.getElementById("sms-banner"); if (el) { el.classList.remove("show"); el.hidden = true; } });
  const topOfLast = () => p.evaluate(() => { const m = [...document.querySelectorAll(".msg.assistant")].pop(); m?.scrollIntoView({ block: "start" }); });
  const phone = (n) => p.locator("#phone").screenshot({ path: path.join(OUT, `${n}.png`) });
  const full = (n) => p.screenshot({ path: path.join(OUT, `${n}.png`) });
  const reset = async () => { await p.evaluate(async () => { const s = await (await fetch("/api/v2/session")).json(); await fetch("/api/v2/demo/reset", { method: "POST", headers: { "Content-Type": "application/json", "X-CSRF-Token": s.csrf_token }, body: "{}" }); }); await p.goto(BASE); await p.waitForTimeout(2000); };
  await p.goto(BASE); await reset();
  // 反诈
  await say("客服让我把钱转到安全账户17000000000");
  await topOfLast(); await p.waitForTimeout(400);
  await phone("d1-反诈拦截-手机"); await full("d1-反诈拦截-桌面含安全透视");
  // 定时转账：确认单 → 回执
  await reset();
  await say("明天给小王转两百，备注还饭钱");
  await p.waitForTimeout(800);
  await phone("d2a-定时转账-确认单");
  await p.click(".pending-sheet .ps-actions .btn.primary"); await idle(); await topOfLast(); await p.waitForTimeout(400);
  await phone("d2b-定时转账-回执");
  // 红档强验证 + 模拟短信
  await say("给妈妈转2000");
  await p.click(".pending-sheet .ps-actions .btn.primary");
  await p.click(".sa-otp-head .btn"); await p.waitForTimeout(3500);
  const msgs = await p.locator(".side-sms .sms-text").allTextContents();
  const otp = (/(\d{6})/.exec(msgs.find((t) => t.includes("刘芳")) || msgs[0] || "") || [])[1];
  for (const d of "135790" + (otp || "")) await p.click(`.keypad .key >> text="${d}"`);
  await full("d4-红档强验证-桌面含模拟短信"); await phone("d4-红档强验证-手机");
  // 生日计划 DAG
  await reset();
  await p.click(".insight.birthday .btn"); await p.waitForTimeout(300); await idle(); await p.waitForTimeout(600);
  await phone("d3a-生日计划-整体确认单");
  await p.click(".pending-sheet .ps-actions .btn.primary"); await idle();
  await p.click(".tab[data-tab=me]"); await p.click(".menu-item >> text=我的计划"); await p.waitForTimeout(1200);
  await p.click(".subpage .menu-item"); await p.waitForTimeout(1500);
  await hideBanner(); await phone("d3b-生日计划-DAG详情");
  await ctx.close();
}

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1600, height: 900 }, deviceScaleFactor: 1 });
  const rs = runs();
  await htmlShot(page, "a-架构简版.png", archHtml());
  await htmlShot(page, "b-对标RevolutAIR.png", airHtml());
  await htmlShot(page, "c-评测迭代.png", iterHtml(rs));
  await htmlShot(page, "e-18项能力对照.png", capsHtml());
  writeTexts(rs);
  if (!NO_SCREENS) await screens(browser);
  await browser.close();
  console.log("done", OUT);
})().catch((e) => { console.error(e); process.exit(1); });
