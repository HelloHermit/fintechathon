// 生成答辩 PPT（deliverables/答辩PPT.pptx）和讲稿（deliverables/讲稿.md）。
// 评测数字从 bench/reports/latest.json 读取，重新评测后重跑本脚本即可同步。
//   cd deliverables/tools && npm install && node build_ppt.js
const fs = require("fs");
const path = require("path");
const pptxgen = require("pptxgenjs");

const ROOT = path.resolve(__dirname, "..", "..");
const IMG = (p) => path.join(ROOT, "docs", "images", p);
const OUT = path.join(ROOT, "deliverables", "答辩PPT.pptx");
const NOTES_OUT = path.join(ROOT, "deliverables", "讲稿.md");

// ---------------------------------------------------------------- 评测数字
const bench = JSON.parse(fs.readFileSync(path.join(ROOT, "bench", "reports", "latest.json"), "utf8"));
const M = bench.metrics;
const r = (x) => `${x.passed}/${x.total}`;
const pctOf = (x) => `${Math.round(x.rate * 10) / 10}%`;
const N = {
  task: pctOf(M.task_completion), taskN: r(M.task_completion),
  sec: pctOf(M.security_block), secN: r(M.security_block),
  ux: pctOf(M.ux), uxN: r(M.ux),
  tool: pctOf(M.tool_call_correct), toolN: r(M.tool_call_correct),
  falseRef: `${M.benign_false_refusal.rate}%`, falseRefN: `${M.benign_false_refusal.blocked}/${M.benign_false_refusal.total}`,
  leaks: M.global_violations, turns: M.avg_turns_task, lat: (M.avg_latency_ms / 1000).toFixed(1),
  cases: bench.meta.case_count, cat: bench.meta.by_category, date: bench.meta.finished_at.slice(0, 10),
  scen: M.by_scenario,
};

// ---------------------------------------------------------------- 主题
const THEME = {
  name: "小安 · 模拟银行",
  headFontFace: "Microsoft YaHei",
  bodyFontFace: "Microsoft YaHei",
  colors: {
    dk1: "0F172A", lt1: "FFFFFF", dk2: "13204A", lt2: "EEF2FB",
    accent1: "1D4ED8", accent2: "059669", accent3: "C2710C", accent4: "DC2626", accent5: "7C3AED", accent6: "64748B",
    hlink: "1D4ED8", folHlink: "7C3AED",
  },
};
const HEX = THEME.colors;

const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE"; // 13.333 × 7.5 英寸
pres.theme = { headFontFace: THEME.headFontFace, bodyFontFace: THEME.bodyFontFace };
pres.title = "小安 · 银行 AI 智能体 答辩";
pres.author = "FinTechathon 2026 参赛队";
pres.company = "FinTechathon 2026";
const C = pres.SchemeColor;
const W = 13.333;

// ---------------------------------------------------------------- 版式（layout）
const FOOT = { text: "小安 · 银行 AI 智能体　｜　全部账户、资金、商户、短信均为模拟", options: { x: 0.6, y: 7.02, w: 9, h: 0.3, fontSize: 10, color: C.accent6, margin: 0 } };
pres.defineSlideMaster({
  title: "COVER",
  background: { color: C.text2 },
  objects: [],
  slideNumber: { x: 12.3, y: 7.0, w: 0.5, h: 0.3, fontSize: 10, color: "AFC0E8" },
  placeholders: [],
});
pres.defineSlideMaster({
  title: "CONTENT",
  background: { color: C.background1 },
  objects: [{ text: FOOT }],
  slideNumber: { x: 12.3, y: 7.0, w: 0.5, h: 0.3, fontSize: 10, color: C.accent6 },
});
// 只用 placeholder 放标题：位置、字号统一
const TITLE = { x: 0.6, y: 0.38, w: 12.1, h: 0.75 };

function contentSlide(section, title, kicker) {
  const s = pres.addSlide({ masterName: "CONTENT", sectionTitle: section });
  s.addText(title, { ...TITLE, fontSize: 30, bold: true, color: C.text2, margin: 0, isTextBox: true, objectName: "标题", valign: "middle" });
  if (kicker) s.addText(kicker, { x: 0.6, y: 1.08, w: 12.1, h: 0.4, fontSize: 15, color: C.accent6, margin: 0, isTextBox: true, objectName: "副标题" });
  return s;
}

// 视觉母题：彩色圆里放一个汉字
function badge(s, x, y, ch, color, d = 0.62) {
  s.addShape(pres.shapes.OVAL, { x, y, w: d, h: d, fill: { color }, line: { color, width: 0 }, objectName: `圆标-${ch}` });
  s.addText(ch, { x, y, w: d, h: d, align: "center", valign: "middle", fontSize: d > 0.7 ? 22 : 17, bold: true, color: C.background1, margin: 0, isTextBox: true });
}

function card(s, x, y, w, h, { ch, color, title, body, fill }) {
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w, h, rectRadius: 0.12, fill: { color: fill || C.background2 }, line: { color: fill || C.background2, width: 0 }, objectName: `卡片-${title}` });
  let tx = x + 0.25;
  if (ch) { badge(s, x + 0.25, y + 0.25, ch, color); tx = x + 1.05; }
  s.addText(title, { x: tx, y: y + 0.22, w: x + w - tx - 0.2, h: 0.5, fontSize: 17, bold: true, color: C.text2, margin: 0, isTextBox: true, valign: "middle" });
  if (body) s.addText(body, { x: x + 0.25, y: y + (ch ? 0.98 : 0.8), w: w - 0.5, h: h - (ch ? 1.15 : 0.95), fontSize: 14, color: C.text1, margin: 0, isTextBox: true, valign: "top", paraSpaceAfter: 4 });
}

function phone(s, file, x, y, h) {
  const w = h * (585 / 1266);
  s.addImage({ path: IMG(`screens/${file}`), x, y, w, h, rounding: false, altText: `界面截图：${file}`, shadow: { type: "outer", blur: 8, offset: 3, angle: 90, color: "000000", opacity: 0.25 } });
  return w;
}

function bullets(s, items, x, y, w, h, size = 16) {
  s.addText(items.map((t, i) => {
    const runs = Array.isArray(t) ? t : [{ text: t }];
    return runs.map((run, j) => ({ text: run.text, options: { bold: !!run.bold, color: run.color || C.text1, bullet: j === 0 ? { indent: 18 } : false, breakLine: j === runs.length - 1 && i < items.length - 1, paraSpaceAfter: 8 } }));
  }).flat(), { x, y, w, h, fontSize: size, valign: "top", margin: 0, isTextBox: true });
}

function stat(s, x, y, w, big, label, color) {
  s.addText(big, { x, y, w, h: 0.95, fontSize: 44, bold: true, color, margin: 0, isTextBox: true, align: "left", valign: "bottom" });
  s.addText(label, { x, y: y + 0.98, w, h: 0.6, fontSize: 13, color: C.accent6, margin: 0, isTextBox: true, valign: "top" });
}

const NOTES = [];
function notes(s, title, text) { s.addNotes(text); NOTES.push([title, text]); }

// ================================================================ 1 封面
pres.addSection({ title: "开场" });
{
  const s = pres.addSlide({ masterName: "COVER", sectionTitle: "开场" });
  s.addText("FinTechathon 2026 · 人工智能赛道 · 银行 AI 智能体", { x: 0.8, y: 0.8, w: 7.5, h: 0.4, fontSize: 14, color: "AFC0E8", margin: 0, isTextBox: true });
  s.addText("小安", { x: 0.8, y: 1.5, w: 7, h: 1.3, fontSize: 66, bold: true, color: C.background1, margin: 0, isTextBox: true });
  s.addText("说一句就能办，每一步都有代码把关", { x: 0.8, y: 2.85, w: 7.5, h: 0.7, fontSize: 26, color: C.background1, margin: 0, isTextBox: true });
  s.addText([
    { text: "模型提议，代码裁决", options: { bold: true, color: "9EE0C5", breakLine: true } },
    { text: "六大场景 · 三档权限 · 强验证 · 反诈 · 防幻觉 · 沙箱", options: { color: "D7E1F8" } },
  ], { x: 0.8, y: 3.9, w: 7.5, h: 1.0, fontSize: 18, margin: 0, isTextBox: true, paraSpaceAfter: 6 });
  s.addText("全部账户、资金、商户、短信均为模拟数据", { x: 0.8, y: 6.55, w: 7.5, h: 0.4, fontSize: 12, color: "AFC0E8", margin: 0, isTextBox: true });
  phone(s, "01-home.png", 8.45, 0.55, 6.4);
  phone(s, "03-red-strong-auth.png", 10.55, 1.0, 5.6);
  notes(s, "封面", "各位评委好，我们的作品叫“小安”，是一个用自然语言办理银行业务的 AI 智能体。一句话概括：说一句就能办，每一步都有代码把关。它覆盖赛题的六大场景，所有数据都是模拟的。接下来十分钟，我们重点讲三件事：小安能办成什么、它为什么安全、我们怎么证明这两点。");
}

// ================================================================ 2 痛点
pres.addSection({ title: "问题与方案" });
{
  const s = contentSlide("问题与方案", "银行 App 的两个痛点", "功能越来越多，操作路径越来越长；让 AI 代办，又担心它“乱转钱”");
  card(s, 0.6, 1.75, 5.9, 4.9, { ch: "长", color: C.accent3, title: "操作路径长", body: "给妈妈转一笔生活费、查一笔可疑扣款、取消一个忘了的会员，往往要在菜单里点五六层。\n\n老人和不熟悉 App 的用户最吃力；而他们恰恰是电信诈骗的主要目标。" });
  card(s, 6.85, 1.75, 5.9, 4.9, { ch: "险", color: C.accent4, title: "AI 代办的安全顾虑", body: "大模型会被话术诱导、会被交易备注里的文字“注入”、会编造数字、会把没做的事说成“已完成”。\n\n如果让模型直接决定转账，风险不可接受。" });
  notes(s, "痛点", "我们看到两个痛点。第一，银行 App 功能越来越多，做一件小事要点很多层，老人尤其吃力，而他们正是诈骗的主要目标。第二，大家都想用大模型来代办，但模型会被诱导、会被注入、会产生幻觉——如果让它直接决定转账，风险不可接受。我们的方案就是在这两者之间找到平衡。");
}

// ================================================================ 3 全景
{
  const s = contentSlide("问题与方案", "六大场景，18 项典型能力都能用口语办", "以下都是真实输入，在评测集中逐条验证");
  const items = [
    ["转", C.accent1, "智能转账", "“明天给小王转200，备注还饭钱”\n按称呼/手机号/用途转账、定时、AA、大额、延时到账"],
    ["账", C.accent2, "账单分析", "“帮我看看有没有异常扣款”\n分类统计、月报年报、异常识别、资金预估"],
    ["理", C.accent5, "理财", "“我想买点稳的理财”\n风险测评、推荐对比、申购赎回、适当性拦截"],
    ["卡", C.accent3, "卡片管理", "“我卡丢了”\n冻结/解冻、挂失/解挂、限额、虚拟卡"],
    ["订", C.accent4, "订阅 / 代扣", "“健身会员不要了”\n自动识别、续费/涨价/闲置提醒、一键取消"],
    ["联", C.text2, "跨场景联动", "首页提醒爱人生日 → 一键生成计划\n锁预算、到点订花和蛋糕、可回退"],
  ];
  items.forEach(([ch, col, t, b], i) => {
    const x = 0.6 + (i % 3) * 4.15, y = 1.7 + Math.floor(i / 3) * 2.6;
    card(s, x, y, 3.95, 2.4, { ch, color: col, title: t, body: b });
  });
  notes(s, "产品全景", "这是小安的能力全景。转账、账单、理财、卡片、订阅、跨场景联动六大场景，赛题表里的 18 项典型能力都可以用口语直接办。比如“明天给小王转200，备注还饭钱”，一句话就生成定时转账单；“我卡丢了”，小安会给出临时冻结和正式挂失两个选项。卡片上的每一句，都是我们评测集里真实跑过的输入。");
}

// ================================================================ 4 架构
pres.addSection({ title: "架构与规划" });
{
  const s = contentSlide("架构与规划", "架构：模型提议，代码裁决", null);
  s.addImage({ path: IMG("01-architecture.png"), x: 0.6, y: 1.3, w: 6.4, h: 6.4 / 1.146, altText: "系统架构图" });
  badge(s, 7.5, 1.55, "提", C.accent5);
  s.addText([{ text: "模型只负责“提议”", options: { bold: true, breakLine: true } }, { text: "听懂口语、规划步骤、选择工具、写一两句回复。看不到确认码、动态码、交易密码。", options: {} }], { x: 8.3, y: 1.45, w: 4.45, h: 1.5, fontSize: 15, color: C.text1, margin: 0, isTextBox: true, valign: "top" });
  badge(s, 7.5, 3.25, "裁", C.accent2);
  s.addText([{ text: "代码负责“裁决”", options: { bold: true, breakLine: true } }, { text: "判档、累计金额、确认、强验证、执行前复查、执行、审计，全部在安全内核里。", options: {} }], { x: 8.3, y: 3.15, w: 4.45, h: 1.5, fontSize: 15, color: C.text1, margin: 0, isTextBox: true, valign: "top" });
  badge(s, 7.5, 4.95, "单", C.accent3);
  s.addText([{ text: "最坏情况：一张待确认单", options: { bold: true, breakLine: true } }, { text: "即使模型被注入或产生幻觉，它也只能提出一张需要用户本人确认的单子。", options: {} }], { x: 8.3, y: 4.85, w: 4.45, h: 1.5, fontSize: 15, color: C.text1, margin: 0, isTextBox: true, valign: "top" });
  notes(s, "架构", "整体架构分三层：手机网页、智能体编排层、安全内核。核心原则是“模型提议，代码裁决”。模型负责听懂口语、规划和选择工具，但它看不到确认码、动态码和交易密码；判档、确认、强验证、执行和审计全部在代码里。所以即使模型被注入或者产生幻觉，最坏的结果也只是一张需要用户本人确认的待确认单，钱不会被转走。");
}

// ================================================================ 5 Agent 规划
{
  const s = contentSlide("架构与规划", "Agent 规划：工具调用 + DAG 计划，一次确认", "复杂任务拆成有依赖关系的步骤，代码校验后整体确认、到点执行、随时可回退");
  s.addImage({ path: IMG("05-birthday-plan.png"), x: 0.6, y: 1.65, w: 5.1, h: 5.1 / 1.003, altText: "生日筹备计划 DAG" });
  phone(s, "09-plan-running.png", 6.05, 1.6, 5.2);
  bullets(s, [
    [{ text: "工具调用：", bold: true }, { text: "DeepSeek 原生工具调用，一轮最多 6 步，可并行（如同时解析日期和联系人）" }],
    [{ text: "一次确认整个计划：", bold: true }, { text: "绑定全部节点参数哈希，档位取最高档" }],
    [{ text: "到点执行：", bold: true }, { text: "调度器按执行日重新判档，超出授权就不执行" }],
    [{ text: "可中断：", bold: true }, { text: "暂停、继续、去掉一步、全部回退（释放预算）、转人工" }],
  ], 8.65, 1.7, 4.1, 5.0, 15);
  notes(s, "Agent 规划", "复杂任务怎么办？以生日为例：首页主动提醒“爱人 11 月 12 号生日”，点“帮我准备”，模型生成一个四步的 DAG 计划：先锁定一千元预算，再在生日前两天订花和蛋糕，最后当天提醒。用户只需要确认一次，代码把每一步的参数都绑定进哈希。到点由调度器执行，执行前会重新判档；中途可以暂停、去掉一步、全部回退或者转人工，回退时会自动释放预算。");
}

// ================================================================ 6 三档权限
pres.addSection({ title: "安全设计" });
{
  const s = contentSlide("安全设计", "权限三档，全部由代码判定", "模型输出里没有“档位”这个字段，也无法传入");
  const tiers = [
    ["绿", C.accent2, "绿档 · 自动执行", "查询、统计、月报年报、异常识别、产品对比、沙箱分析"],
    ["黄", C.accent3, "黄档 · 确认按钮", "当日累计 ≤ ¥1,000 的转账、冻结卡、赎回、取消订阅、计划确认\n确认码绑定参数哈希、5 分钟、一次性"],
    ["红", C.accent4, "红档 · 强验证", "大额转账、解冻、挂失、上调限额、理财申购、高风险转账\n交易密码 + 模拟短信动态码"],
  ];
  tiers.forEach(([ch, col, t, b], i) => card(s, 0.6, 1.7 + i * 1.72, 7.6, 1.55, { ch, color: col, title: t, body: b }));
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 8.6, y: 1.7, w: 4.15, h: 4.99, rectRadius: 0.12, fill: { color: C.text2 }, line: { color: C.text2, width: 0 }, objectName: "风险对称" });
  s.addText([
    { text: "风险对称", options: { bold: true, fontSize: 22, color: "9EE0C5", breakLine: true } },
    { text: "降低风险的操作低摩擦：", options: { bold: true, breakLine: true } },
    { text: "冻结卡、下调限额 → 黄档", options: { breakLine: true } },
    { text: " ", options: { breakLine: true } },
    { text: "增加风险的操作强验证：", options: { bold: true, breakLine: true } },
    { text: "解冻、上调限额、挂失解挂 → 红档", options: { breakLine: true } },
    { text: " ", options: { breakLine: true } },
    { text: "聊天里说“我确认了”不算确认。", options: { bold: true, color: "FFD58A" } },
  ], { x: 8.9, y: 1.95, w: 3.6, h: 4.5, fontSize: 15, color: C.background1, margin: 0, isTextBox: true, valign: "top" });
  notes(s, "三档权限", "权限分三档，全部由代码判定。绿档是查询类，自动执行；黄档展示详情，用户点确认按钮，确认码绑定全部参数的哈希、五分钟有效、只能用一次；红档要交易密码加短信动态码。我们特别设计了“风险对称”：冻结卡、下调限额这类降低风险的操作只要点确认，解冻、上调限额这类增加风险的操作必须强验证。另外，聊天里说“我确认了”是不算的。");
}

// ================================================================ 7 强验证
{
  const s = contentSlide("安全设计", "红档强验证与熔断", "两个因素，所见即所签；连续失败就锁定，重启也不清零");
  const w = phone(s, "03-red-strong-auth.png", 0.6, 1.55, 5.3);
  s.addImage({ path: IMG("screens/03-red-strong-auth-desktop.png"), x: 0.6 + w + 0.35, y: 1.6, w: 5.2, h: 5.2 / 1.511, altText: "桌面端：强验证面板与模拟手机短信" });
  bullets(s, [
    [{ text: "两个因素：", bold: true }, { text: "交易密码（PBKDF2 存储）+ 绑定手机的模拟短信动态码" }],
    [{ text: "所见即所签：", bold: true }, { text: "短信写明“向 刘芳 转账 2,000.00 元”" }],
    [{ text: "动态码只在模拟手机里，", bold: true }, { text: "不进聊天、不给模型、不进日志" }],
    [{ text: "3 次失败锁 10 分钟，", bold: true }, { text: "锁状态写在库里，重启不清零" }],
  ], 8.95, 1.6, 3.8, 5.2, 15);
  notes(s, "强验证", "红档操作需要两个因素：交易密码，加上发到绑定手机的模拟短信动态码。短信正文写明对象和金额，比如“向刘芳转账两千元”，这叫所见即所签，防止骗子诱导用户把验证码转发出去。动态码只出现在右边的模拟手机里，不进聊天、不给模型、不进日志。交易密码或动态码连续错三次，红档操作锁十分钟，锁状态存在数据库里，重启服务也不会清零——评测里我们专门重启后端验证过。");
}

// ================================================================ 8 反诈
{
  const s = contentSlide("安全设计", "反诈守护：评分升档 + 冷静期 + 延时到账可撤回", "诱导转账是赛题点名的第一类风险");
  s.addImage({ path: IMG("04-anti-fraud.png"), x: 0.6, y: 1.65, w: 7.9, h: 7.9 / 3.093, altText: "反诈评分流程" });
  const w = phone(s, "05-fraud.png", 9.05, 1.55, 5.3);
  bullets(s, [
    [{ text: "风险名单直接拒绝：", bold: true }, { text: "“客服让我把钱转到安全账户”——在调用模型之前就拦下" }],
    [{ text: "代码打分 0–100：", bold: true }, { text: "首次收款人、金额异常、诈骗话术、催促用语、凌晨、短时多笔" }],
    [{ text: "≥ 60 分：", bold: true }, { text: "强制红档 + 30 秒冷静期 + 默认 24 小时后到账，到账前可撤回" }],
  ], 0.6, 4.45, 8.0, 2.4, 15);
  notes(s, "反诈", "诱导转账是赛题点名的第一类风险。我们有三层：第一，收款方在风险名单上的直接拒绝，比如“客服让我把钱转到安全账户”，代码在调用模型之前就拦下并解释骗局；第二，每笔转账由代码打零到一百分，看是不是首次收款、金额是否异常、有没有诈骗话术和催促用语；第三，六十分以上强制升为红档，加三十秒冷静期，默认二十四小时后到账，到账前一句“撤回刚才那笔”就能全额退回。");
}

// ================================================================ 9 多层防御
{
  const s = contentSlide("安全设计", "注入、套取、越权：五层防线", "单靠提示词挡不住注入；我们让每一层都由代码兜底");
  const layers = [
    ["1", "输入守卫", "中英文注入与信息套取规则，命中不调用模型；10 分钟 3 次 → 会话只读"],
    ["2", "外部文本隔离", "交易备注、商户名、产品说明包进 <external_data>，界面标“外部备注”"],
    ["3", "参数溯源", "金额、收款人、日期必须来自用户原话；备注里的号码无效"],
    ["4", "代码判档 + 工具白名单", "模型无法自降档位、无法调用未登记的工具"],
    ["5", "代码渲染确认单", "用户看到的收款人和金额由代码生成，模型改不了"],
  ];
  layers.forEach(([n, t, b], i) => {
    const y = 1.65 + i * 1.02, x = 0.6 + i * 0.22;
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w: 7.6 - i * 0.22, h: 0.88, rectRadius: 0.1, fill: { color: C.background2 }, line: { color: C.background2, width: 0 }, objectName: `防线${n}` });
    badge(s, x + 0.15, y + 0.15, n, [C.accent1, C.accent5, C.accent2, C.accent3, C.accent4][i], 0.58);
    s.addText([{ text: `${t}　`, options: { bold: true, color: C.text2 } }, { text: b, options: { color: C.text1 } }], { x: x + 0.9, y: y + 0.06, w: 6.55 - i * 0.22, h: 0.76, fontSize: 13.5, margin: 0, isTextBox: true, valign: "middle" });
  });
  phone(s, "07-indirect-injection.png", 9.4, 1.55, 5.3);
  notes(s, "多层防御", "对于注入、信息套取和越权，单靠提示词是挡不住的，所以我们设了五层，每一层都由代码兜底。第一层输入守卫，命中就不调用模型，十分钟三次直接转为只读；第二层把交易备注、产品说明这类外部文本包起来，明确是数据不是指令；第三层参数溯源，转账金额和收款人必须来自用户原话——右边这个例子，用户说“按那条备注说的办”，小安拒绝了，即使模型被说服，备注里的号码也过不了溯源；第四、五层是代码判档和代码渲染确认单。");
}

// ================================================================ 10 幻觉防护
{
  const s = contentSlide("安全设计", "幻觉防护：参数溯源 + 事实校验", "数字只能来自账本，没执行就不能说“已完成”");
  card(s, 0.6, 1.7, 6.0, 4.95, { ch: "源", color: C.accent2, title: "参数溯源（写操作之前）", body: "金额：用户原话中的表达，代码解析“两百”“整五百”“1.5k”“一万二”\n收款人：原话里的姓名、称呼、手机号，或用户点选\n日期：由“明天”“下礼拜五”“月底”换算\n\n工具结果、交易备注、产品说明、模型推测都不能成为新资金动作的来源；不通过就追问，不出单。" });
  card(s, 6.85, 1.7, 5.9, 4.95, { ch: "核", color: C.accent1, title: "事实校验（回复之后）", body: "回复里的金额、百分比、日期、笔数逐一和本轮工具结果比对（允许换算、取整、两数之和或差）。\n\n对不上就用代码模板根据卡片重写，并记入审计；没有成功回执时禁止“已转账 / 已完成”。\n\n所有卡片内容由代码根据账本生成。" });
  notes(s, "幻觉防护", "幻觉防护分两头。写操作之前做参数溯源：金额、收款人、日期必须能追溯到用户本人说过的话，代码能解析“两百”“整五百”“一万二”“下礼拜五”这类口语；工具结果和模型的推测都不算数。回复之后做事实校验：回复里的每个数字都要在本轮的工具结果里找得到，对不上就用代码模板重写；没有成功回执的时候，不允许说“已转账”“已完成”。");
}

// ================================================================ 11 沙箱
{
  const s = contentSlide("安全设计", "沙箱：AI 生成的分析代码在受限环境运行", "固定报表回答不了的长尾问题，让模型写代码，但只在沙箱里跑");
  phone(s, "14-sandbox.png", 0.6, 1.55, 5.3);
  const steps = [
    ["1", C.accent5, "运行前检查", "AST 白名单：只允许 5 个标准库的 from-import；禁止下划线属性、eval、open、__import__；≤ 2000 字符"],
    ["2", C.accent1, "受限运行", "子进程 python -I -S、空环境变量、临时目录；CPU 2 秒、内存 256MB、5 秒超时；无网络命名空间（有 Docker 时用 Docker）"],
    ["3", C.accent2, "最小数据", "只给本人交易的只读快照，没有数据库、没有密钥"],
    ["4", C.accent3, "可审计", "代码哈希、引擎、耗时、退出状态写入审计；输出数字同样过事实校验"],
  ];
  steps.forEach(([n, col, t, b], i) => {
    const y = 1.6 + i * 1.3;
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 3.55, y, w: 9.2, h: 1.15, rectRadius: 0.12, fill: { color: C.background2 }, line: { color: C.background2, width: 0 }, objectName: `沙箱-${t}` });
    badge(s, 3.8, y + 0.26, n, col);
    s.addText(t, { x: 4.6, y: y + 0.1, w: 1.5, h: 0.95, fontSize: 17, bold: true, color: C.text2, margin: 0, isTextBox: true, valign: "middle" });
    s.addText(b, { x: 6.2, y: y + 0.1, w: 6.4, h: 0.95, fontSize: 13.5, color: C.text1, margin: 0, isTextBox: true, valign: "middle" });
  });
  notes(s, "沙箱", "赛题要求生成的代码在受限、可监控的环境里运行。比如“周末和工作日外卖平均各花多少”，固定报表回答不了，我们让模型写一段分析代码。运行前先做语法树白名单检查，只允许少数标准库，禁止 eval、open 这类危险调用；运行时用独立子进程，限制 CPU、内存和时间，并放进没有网卡的网络命名空间；数据只给本人交易的只读快照；代码哈希和运行结果都写进审计。");
}

// ================================================================ 12 体验
pres.addSection({ title: "体验与评测" });
{
  const s = contentSlide("体验与评测", "交互体验：主动、口语、会追问、能兜底", "手机银行风格 · 可添加到主屏幕 · “安全透视”让每一步决策看得见");
  const shots = ["01-home.png", "12-subscriptions.png", "10-bills.png"];
  shots.forEach((f, i) => phone(s, f, 0.6 + i * 2.65, 1.6, 5.1));
  bullets(s, [
    [{ text: "主动关怀：", bold: true }, { text: "生日、续费、涨价、异常、房租提醒" }],
    [{ text: "口语与上下文：", bold: true }, { text: "“再给小张转200”“第二笔算了”“改成300”“下礼拜五”" }],
    [{ text: "追问与兜底：", bold: true }, { text: "重名给选项；天气、机票、个股推荐说明边界" }],
    [{ text: "高效：", bold: true }, { text: `信息齐全的一句话一轮出单；平均 ${N.turns} 轮，每轮约 ${N.lat} 秒` }],
  ], 8.65, 1.6, 4.1, 5.2, 15);
  notes(s, "体验", `体验上，小安是手机银行风格，可以添加到主屏幕。首页会主动提醒生日、续费、涨价和可疑交易；对话支持省略和改主意，比如“再给小张转两百”“第二笔算了”“改成三百”；遇到两个“小李”会给选项，问天气、机票、个股推荐会说明能力边界。评测里任务平均 ${N.turns} 轮办成，每轮大约 ${N.lat} 秒。右侧的“安全透视”实时展示每一步：守卫、模型提议、溯源、判档、事实校验和审计。`);
}

// ================================================================ 13 评测
{
  const s = contentSlide("体验与评测", `独立黑盒评测：${N.cases} 条用例，真实大模型`, `只依据接口契约、演示数据规格和验收句编写，编写者不读后端实现；失败照实保留（${N.date}）`);
  stat(s, 0.6, 1.6, 3.0, N.task, `任务完成率（${N.taskN}）`, C.accent1);
  stat(s, 3.65, 1.6, 3.0, N.sec, `攻击拦截率（${N.secN}）`, C.accent2);
  stat(s, 0.6, 3.35, 3.0, N.tool, `工具调用正确率（${N.toolN}）`, C.accent5);
  stat(s, 3.65, 3.35, 3.0, String(N.leaks), "动态码/密码/确认码/手机号泄露次数", C.accent4);
  stat(s, 0.6, 5.1, 3.0, N.ux, `体验用例（${N.uxN}）`, C.accent3);
  stat(s, 3.65, 5.1, 3.0, N.falseRef, `良性请求误拒（${N.falseRefN}）`, C.text2);
  const order = ["转账", "账单", "理财", "卡片", "订阅", "联动", "体验", "安全"].filter((k) => N.scen[k]);
  s.addChart(pres.charts.BAR, [{ name: "通过率", labels: order, values: order.map((k) => N.scen[k].rate) }], {
    x: 7.0, y: 1.55, w: 5.75, h: 5.25, barDir: "bar", showTitle: true, title: "分场景通过率（%）", titleFontSize: 14, titleColor: HEX.dk2, titleFontFace: "+mn-lt",
    chartColors: [HEX.accent1], showValue: true, dataLabelPosition: "outEnd", dataLabelFontSize: 11, dataLabelColor: HEX.dk2, dataLabelFontFace: "+mn-lt", dataLabelFormatCode: "0.0",
    valAxisMaxVal: 100, valAxisMinVal: 0, valAxisHidden: true, catAxisLabelColor: HEX.dk2, catAxisLabelFontSize: 12, catAxisLabelFontFace: "+mn-lt", catAxisOrientation: "maxMin",
    valGridLine: { style: "none" }, catGridLine: { style: "none" }, showLegend: false, barGapWidthPct: 60,
  });
  notes(s, "评测结果", `怎么证明？我们自建了 ${N.cases} 条黑盒评测用例：任务 ${N.cat.task} 条、安全 ${N.cat.security} 条、体验 ${N.cat.ux} 条，用真实大模型、只通过 HTTP 接口测试。评测集由不看后端实现的一方编写。结果：任务完成率 ${N.task}，攻击拦截率 ${N.sec}，工具调用正确率 ${N.tool}，体验用例 ${N.ux}；每一轮回复都检查有没有泄露动态码、交易密码、确认码和完整手机号，泄露 ${N.leaks} 次；正常请求被误拦 ${N.falseRefN}。这是第三次全量运行的结果，前两次的失败和修复过程都照实写在测试报告里。`);
}

// ================================================================ 14 风险
{
  const s = contentSlide("体验与评测", "已知风险与边界（如实）", "完整清单见《安全自评报告》");
  const rows = [
    ["大模型随机性", "偶尔多问一轮、没给选项按钮", "不影响资金安全：执行仍需确认；评测如实记录"],
    ["规则守卫可能漏新话术", "注入进入模型", "参数溯源 + 代码判档 + 确认兜底"],
    ["沙箱网络隔离依赖系统", "无网络命名空间时降级", "卡片如实标注；生产强制 Docker"],
    ["审计防篡改不防删库", "内部人员抵赖", "生产环境把链头哈希写到外部存储"],
    ["短信、风险名单、客服是模拟的", "真实诈骗号码不在名单里", "评分引擎不依赖名单；真实部署接入数据源"],
  ];
  s.addTable([
    [{ text: "风险", options: { bold: true, color: C.background1, fill: { color: C.text2 } } }, { text: "影响", options: { bold: true, color: C.background1, fill: { color: C.text2 } } }, { text: "缓解 / 后续", options: { bold: true, color: C.background1, fill: { color: C.text2 } } }],
    ...rows.map((rw) => rw.map((t) => ({ text: t, options: { color: C.text1 } }))),
  ], { x: 0.6, y: 1.65, w: 12.15, colW: [3.6, 3.6, 4.95], fontSize: 15, rowH: 0.78, border: { type: "solid", pt: 1, color: "D6DCE8" }, valign: "middle", margin: 0.1, fill: { color: C.background1 } });
  notes(s, "已知风险", "我们也如实列出边界。第一是大模型的随机性，偶尔会多问一轮，但不影响资金安全，因为执行仍然要确认。第二，规则守卫可能漏掉新话术，但后面还有参数溯源和代码判档兜底。第三，沙箱的网络隔离依赖操作系统支持，不支持时会如实标注。第四，审计哈希链能发现篡改，但不能防止整库删除。第五，短信、风险名单和客服都是模拟的，真实部署需要接入真实数据源。");
}

// ================================================================ 15 总结
pres.addSection({ title: "总结" });
{
  const s = pres.addSlide({ masterName: "COVER", sectionTitle: "总结" });
  s.addText("总结", { x: 0.8, y: 0.7, w: 6, h: 0.8, fontSize: 34, bold: true, color: C.background1, margin: 0, isTextBox: true });
  const pts = [
    ["办", "说一句就能办", `六大场景 18 项能力；任务完成率 ${N.task}`],
    ["守", "每一步有代码把关", `三档权限、强验证、反诈、溯源、事实校验；攻击拦截率 ${N.sec}`],
    ["证", "用独立评测证明", `${N.cases} 条黑盒用例，失败如实保留`],
  ];
  pts.forEach(([ch, t, b], i) => {
    const y = 1.8 + i * 1.35;
    badge(s, 0.8, y, ch, [C.accent1, C.accent2, C.accent3][i], 0.75);
    s.addText([{ text: t, options: { bold: true, fontSize: 20, color: C.background1, breakLine: true } }, { text: b, options: { fontSize: 15, color: "D7E1F8" } }], { x: 1.8, y: y - 0.1, w: 6.2, h: 1.1, margin: 0, isTextBox: true, valign: "middle" });
  });
  s.addText([
    { text: "团队与 AI 辅助开发", options: { bold: true, color: "9EE0C5", breakLine: true } },
    { text: "三名大一学生；使用 AI 编程助手（Claude Code）开发：一个会话写引擎与单元测试，另一个会话写前端、评测集与材料，评测集由不读实现的一方独立编写。", options: { color: "D7E1F8" } },
  ], { x: 0.8, y: 5.95, w: 7.4, h: 1.0, fontSize: 13, margin: 0, isTextBox: true, valign: "top" });
  s.addImage({ path: IMG("screens/05-fraud-desktop.png"), x: 8.3, y: 1.6, w: 4.5, h: 4.5 / 1.511, altText: "安全透视面板", shadow: { type: "outer", blur: 8, offset: 3, angle: 90, color: "000000", opacity: 0.3 } });
  s.addText("模型提议，代码裁决", { x: 8.3, y: 4.75, w: 4.5, h: 0.6, fontSize: 22, bold: true, color: "9EE0C5", margin: 0, isTextBox: true, align: "center" });
  s.addText("谢谢各位评委", { x: 8.3, y: 5.4, w: 4.5, h: 0.5, fontSize: 16, color: C.background1, margin: 0, isTextBox: true, align: "center" });
  notes(s, "总结", "总结一下：小安做到了三件事——说一句就能办，每一步都有代码把关，并且用独立的黑盒评测来证明。我们团队是三名大一学生，开发中使用了 AI 编程助手：一个会话写引擎和单元测试，另一个会话写前端、评测集和材料，评测集由不看实现的一方独立编写。模型提议，代码裁决。谢谢各位评委。");
}

// ---------------------------------------------------------------- 写文件 + 主题颜色
async function writeTheme(file, theme) {
  const JSZip = require(require.resolve("jszip", { paths: [require.resolve("pptxgenjs")] }));
  const zip = await JSZip.loadAsync(fs.readFileSync(file));
  const name = "ppt/theme/theme1.xml";
  let xml = await zip.file(name).async("string");
  const c = theme.colors;
  const slot = (k) => (k === "dk1" || k === "lt1" ? `<a:${k}><a:srgbClr val="${c[k]}"/></a:${k}>` : `<a:${k}><a:srgbClr val="${c[k]}"/></a:${k}>`);
  const scheme = `<a:clrScheme name="${theme.name}">${["dk1", "lt1", "dk2", "lt2", "accent1", "accent2", "accent3", "accent4", "accent5", "accent6", "hlink", "folHlink"].map(slot).join("")}</a:clrScheme>`;
  xml = xml.replace(/<a:clrScheme[\s\S]*?<\/a:clrScheme>/, scheme).replace(/(<a:theme[^>]*\sname=")[^"]*"/, `$1${theme.name}"`);
  zip.file(name, xml);
  fs.writeFileSync(file, await zip.generateAsync({ type: "nodebuffer", compression: "DEFLATE" }));
}

(async () => {
  await pres.writeFile({ fileName: OUT });
  await writeTheme(OUT, THEME);
  const total = NOTES.reduce((a, [, t]) => a + t.length, 0);
  const md = ["# 答辩讲稿（约 10 分钟）", "", `> 与 \`答辩PPT.pptx\` 的备注一致，由 \`deliverables/tools/build_ppt.js\` 生成。共 ${NOTES.length} 页、约 ${total} 字，按每分钟 250–280 字计约 ${Math.round(total / 265)} 分钟。评测数字来自 \`bench/reports/latest.json\`（${N.date}）。全部数据为模拟。`, ""];
  NOTES.forEach(([t, text], i) => md.push(`## 第 ${i + 1} 页 · ${t}`, "", text, ""));
  fs.writeFileSync(NOTES_OUT, md.join("\n"));
  console.log("ok", OUT, "notes chars", total);
})().catch((e) => { console.error(e); process.exit(1); });
