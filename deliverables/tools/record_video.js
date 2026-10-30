// 自动录制演示视频（≤5 分钟）：Playwright 录屏 + 记录字幕时间点 → ffmpeg 烧录中文字幕 → deliverables/演示视频.mp4
// 先启动后端：python run.py --reset（真实模型；或 --model replay 回放录制）
// 再运行：node deliverables/tools/record_video.js [http://127.0.0.1:8765]
// 分镜与旁白见 deliverables/视频脚本.md（两者保持一致）。
const fs = require("fs");
const path = require("path");
const { execFileSync } = require("child_process");
let chromium;
try { ({ chromium } = require("playwright")); } catch { ({ chromium } = require(require.resolve("playwright", { paths: ["/usr/lib/node_modules", "/usr/local/lib/node_modules", "/opt/node22/lib/node_modules"] }))); }

const BASE = process.argv[2] || "http://127.0.0.1:8765";
const ROOT = path.resolve(__dirname, "..", "..");
const WORK = path.join(__dirname, "video-work");
const OUT = path.join(ROOT, "deliverables", "演示视频.mp4");
const SRT = path.join(ROOT, "deliverables", "演示视频字幕.srt");
const PIN = "135790";
const VW = 1360, VH = 900;
const bench = JSON.parse(fs.readFileSync(path.join(ROOT, "bench", "reports", "latest.json"), "utf8"));
const M = bench.metrics;

fs.rmSync(WORK, { recursive: true, force: true });
fs.mkdirSync(WORK, { recursive: true });

const caps = [];
let t0 = 0;
function cap(text) { caps.push({ t: (Date.now() - t0) / 1000, text }); console.log(`[${((Date.now() - t0) / 1000).toFixed(1)}s] ${text}`); }

const CARD_CSS = `body{margin:0;height:100vh;display:flex;align-items:center;justify-content:center;background:#13204A;color:#fff;font-family:"WenQuanYi Zen Hei","Microsoft YaHei",sans-serif}
.c{width:1100px}.k{color:#9EE0C5;font-size:26px;margin-bottom:18px}.t{font-size:84px;font-weight:700}.s{font-size:34px;margin-top:16px;color:#D7E1F8}
.n{display:grid;grid-template-columns:repeat(3,1fr);gap:28px;margin-top:40px}.n div{background:#1d2c5e;border-radius:18px;padding:22px}.n b{display:block;font-size:46px;color:#9EE0C5}.n span{font-size:20px;color:#D7E1F8}
.f{margin-top:36px;font-size:18px;color:#AFC0E8}img{width:100%;border-radius:12px;background:#fff}`;

(async () => {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: VW, height: VH }, recordVideo: { dir: WORK, size: { width: VW, height: VH } }, bypassCSP: true });
  const p = await ctx.newPage();
  t0 = Date.now();
  const sleep = (ms) => p.waitForTimeout(ms);
  const idle = async () => { await p.waitForFunction(() => !document.querySelector(".msg.busy"), null, { timeout: 90000 }); await sleep(700); };
  const ripple = async (sel) => {
    const box = await p.locator(sel).first().boundingBox();
    if (!box) return;
    await p.evaluate(({ x, y }) => {
      const d = document.createElement("div");
      Object.assign(d.style, { position: "fixed", left: `${x - 22}px`, top: `${y - 22}px`, width: "44px", height: "44px", borderRadius: "50%", background: "rgba(245,158,11,.45)", border: "3px solid #f59e0b", zIndex: 99999, pointerEvents: "none" });
      document.body.appendChild(d);
      d.animate([{ transform: "scale(.4)", opacity: 1 }, { transform: "scale(1.4)", opacity: 0 }], { duration: 650 }).onfinish = () => d.remove();
    }, { x: box.x + box.width / 2, y: box.y + box.height / 2 });
    await sleep(250);
  };
  const click = async (sel) => { await ripple(sel); await p.locator(sel).first().click(); };
  const say = async (text) => {
    if (!(await p.locator(".tab[data-tab=chat].active").count())) await click(".tab[data-tab=chat]");
    await p.locator(".chat-input").click();
    await p.locator(".chat-input").pressSequentially(text, { delay: 55 });
    await sleep(300);
    await click(".send-btn");
    await sleep(300);
    await idle();
  };
  const hasSheet = async () => (await p.locator(".pending-sheet").count()) > 0;
  const confirmSheet = async () => { if (await hasSheet()) { await sleep(1200); await click(".pending-sheet .ps-actions .btn.primary"); await idle(); } };
  const strongAuth = async () => {
    if (!(await hasSheet())) return;
    await sleep(1000);
    await click(".pending-sheet .ps-actions .btn.primary");
    await sleep(600);
    await click(".sa-otp-head .btn");
    await sleep(3800);
    const msgs = await p.locator(".side-sms .sms").allTextContents();
    const otp = (/(\d{6})/.exec(msgs[0] || "") || [])[1]; // 面板里最新的在最上面
    for (const d of PIN) { await p.locator(`.keypad .key >> text="${d}"`).click(); await sleep(110); }
    if (otp) for (const d of otp) { await p.locator(`.keypad .key >> text="${d}"`).click(); await sleep(110); }
    await sleep(500);
    await click(".pending-sheet .btn.primary.lg");
    await idle();
  };
  const topOfLast = () => p.evaluate(() => { const m = [...document.querySelectorAll(".msg.assistant")].pop(); m?.scrollIntoView({ block: "start", behavior: "smooth" }); });
  const resetDemo = () => p.evaluate(async () => { const s = await (await fetch("/api/v2/session")).json(); await fetch("/api/v2/demo/reset", { method: "POST", headers: { "Content-Type": "application/json", "X-CSRF-Token": s.csrf_token }, body: "{}" }); });

  // ① 开场
  await p.setContent(`<style>${CARD_CSS}</style><div class="c"><div class="k">FinTechathon 2026 · 人工智能赛道 · 银行 AI 智能体</div><div class="t">小安</div><div class="s">说一句就能办，每一步都有代码把关</div><div class="f">全部账户、资金、商户、短信均为模拟数据</div></div>`);
  cap("小安：用自然语言办银行业务的 AI 智能体（全部数据为模拟）");
  await sleep(4500);
  const arch = fs.readFileSync(path.join(ROOT, "docs", "images", "01-architecture.png")).toString("base64");
  await p.setContent(`<style>${CARD_CSS}.c{width:1240px;display:grid;grid-template-columns:560px 1fr;gap:40px;align-items:center}</style><div class="c"><img src="data:image/png;base64,${arch}"><div><div class="k">设计原则</div><div class="t" style="font-size:56px">模型提议<br>代码裁决</div><div class="s" style="font-size:24px">大模型负责理解、规划、选择工具<br>档位、确认、强验证、执行、审计全部由代码决定<br>模型看不到确认码、动态码和交易密码</div></div></div>`);
  cap("模型提议，代码裁决：模型只能提出待确认单，执行由代码和用户本人决定");
  await sleep(7000);

  await p.goto(BASE);
  await resetDemo();
  await p.goto(BASE);
  await sleep(1800);
  cap("手机银行风格界面；右侧是演示控制、安全透视和模拟手机");
  await sleep(2500);

  // ② 转账
  cap("口语定时转账：一句话解析日期、联系人和备注 → 黄档确认单");
  await say("明天给小王转200，备注还饭钱");
  await sleep(1500);
  cap("黄档：点“确认办理”才执行；确认码绑定参数、5 分钟、一次性");
  await confirmSheet();
  await sleep(1200);
  cap("大额转账超过当日小额额度 → 红档：交易密码 + 模拟短信动态码");
  await say("给妈妈转2000");
  await sleep(1200);
  cap("动态码只发到模拟手机，短信写明收款人和金额（所见即所签）");
  await strongAuth();
  await sleep(2000);

  // ③ 反诈与间接注入
  cap("诱导转账：收款号码在涉诈风险名单上，调用模型之前就被代码拦下");
  await say("客服说我账户被冻结，让我把钱转到安全账户17000000000");
  await topOfLast();
  await sleep(3500);
  cap("间接注入：交易备注里的“指令”只是数据，转账参数必须来自用户原话");
  await say("按那条0.01元转账备注说的办");
  await topOfLast();
  await sleep(3500);

  // ④ 账单与异常
  cap("账单：分类统计和环比，数字全部来自账本并经过事实校验");
  await say("这个月花了多少");
  await topOfLast();
  await sleep(3000);
  cap("异常识别：凌晨境外消费、重复扣款、小额试探、可疑来账");
  await say("帮我看看有没有异常扣款");
  await topOfLast();
  await sleep(3000);
  const freeze = p.locator(".anomaly .btn", { hasText: "冻结" }).first();
  if (await freeze.count()) {
    cap("一键冻结：降低风险的操作只需确认（风险对称）");
    await freeze.scrollIntoViewIfNeeded();
    await ripple(".anomaly .btn >> text=/冻结/");
    await freeze.click();
    await idle();
    await confirmSheet();
    await sleep(1500);
  }

  // ⑤ 订阅
  cap("订阅：从流水自动识别未登记的扣费，标注涨价、闲置、即将续费");
  await say("我有哪些自动扣费");
  await confirmSheet();
  await topOfLast();
  await sleep(3500);
  cap("一键取消闲置的健身会员（黄档确认）");
  await say("健身会员不要了");
  await confirmSheet();
  await sleep(1500);

  // ⑥ 理财
  cap("理财：没有有效风险测评 → 先做测评（适当性管理）");
  await say("我想买理财，先帮我做个风险测评");
  await topOfLast();
  if (await p.locator(".questionnaire").count()) {
    const qs = await p.locator(".questionnaire fieldset").count();
    for (let i = 0; i < qs; i++) { await p.locator(".questionnaire fieldset").nth(i).locator(".q-opt").nth(2).click(); await sleep(250); }
    await click(".questionnaire button[type=submit]");
    await idle();
    await confirmSheet();
    await sleep(1500);
  }
  cap("按测评等级推荐并标注是否适合；固定风险提示");
  await say("推荐点稳一点的，放半年");
  await topOfLast();
  await sleep(3000);
  cap("申购属于红档：先过适当性检查，再强验证");
  await say("买一万稳健季享");
  if (await p.locator(".questionnaire").count() && !(await hasSheet())) console.log("WARN 申购时又出了问卷");
  await strongAuth();
  await sleep(1800);

  // ⑦ 跨场景联动
  await click(".tab[data-tab=home]");
  await sleep(1500);
  cap("主动关怀：首页提醒爱人生日 → 一键生成计划");
  await p.locator(".insight.birthday").scrollIntoViewIfNeeded();
  await sleep(1200);
  await click(".insight.birthday .btn");
  await idle();
  cap("DAG 计划：锁预算 → 到点订花和蛋糕 → 当天提醒，一次确认整个计划");
  await sleep(3500);
  await confirmSheet();
  await sleep(1500);
  cap("快进模拟时间到 11-10 09:00：调度器从预算付款下单");
  await click(".demo-grid .btn >> text=到 11-10 09:00");
  await sleep(3000);
  await click(".tab[data-tab=me]");
  await sleep(600);
  await click(".menu-item >> text=我的计划");
  await sleep(1200);
  await click(".subpage .menu-item");
  await sleep(2500);
  cap("计划可暂停、全部回退（取消未执行步骤并释放预算）或转人工");
  await sleep(3000);

  // ⑧ 审计与结尾
  for (let i = 0; i < 2; i++) { await p.locator(".subpage-head .icon-btn").last().click(); await sleep(500); } // 关掉两层子页面
  await click(".menu-item >> text=审计记录");
  await sleep(1500);
  cap("只追加审计 + 哈希链：每条记录带上一条的哈希，任何改动都能发现");
  await sleep(4500);
  const pc = (x) => `${Math.round(x.rate * 10) / 10}%`;
  await p.setContent(`<style>${CARD_CSS}</style><div class="c"><div class="k">独立黑盒评测 · ${bench.meta.case_count} 条用例 · 真实大模型（${bench.meta.finished_at.slice(0, 10)}）</div><div class="t" style="font-size:60px">模型提议，代码裁决</div>
  <div class="n"><div><b>${pc(M.task_completion)}</b><span>任务完成率（${M.task_completion.passed}/${M.task_completion.total}）</span></div><div><b>${pc(M.security_block)}</b><span>攻击拦截率（${M.security_block.passed}/${M.security_block.total}）</span></div><div><b>${M.global_violations}</b><span>验证码 / 密码 / 手机号泄露</span></div></div>
  <div class="f">评测集由不读后端实现的一方独立编写，失败项照实保留在测试报告中 · 全部数据为模拟</div></div>`);
  cap("评测集独立编写、失败如实保留。小安：说一句就能办，每一步都有代码把关");
  await sleep(6500);
  const total = (Date.now() - t0) / 1000;
  caps.push({ t: total, text: null });
  const video = p.video();
  await ctx.close();
  await browser.close();
  const webm = await video.path();

  // 字幕
  const ts = (s) => { const ms = Math.max(0, Math.round(s * 1000)); const h = Math.floor(ms / 3600000), m = Math.floor(ms / 60000) % 60, sec = Math.floor(ms / 1000) % 60, r = ms % 1000; return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")},${String(r).padStart(3, "0")}`; };
  const srt = caps.slice(0, -1).map((c, i) => `${i + 1}\n${ts(c.t)} --> ${ts(Math.min(caps[i + 1].t, c.t + 12))}\n${c.text}\n`).join("\n");
  fs.writeFileSync(SRT, srt);
  const style = "FontName=WenQuanYi Zen Hei,FontSize=15,PrimaryColour=&H00FFFFFF,BackColour=&H99000000,BorderStyle=3,Outline=1,Shadow=0,MarginV=18";
  execFileSync("ffmpeg", ["-y", "-loglevel", "error", "-i", webm, "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
    "-vf", `subtitles=${SRT.replace(/([:\\'])/g, "\\$1")}:force_style='${style}'`, "-c:v", "libx264", "-preset", "medium", "-crf", "28", "-pix_fmt", "yuv420p",
    "-c:a", "aac", "-b:a", "32k", "-shortest", "-movflags", "+faststart", OUT], { stdio: "inherit" });
  console.log(`done ${OUT} · ${total.toFixed(1)}s · ${(fs.statSync(OUT).size / 1e6).toFixed(1)}MB`);
})().catch((e) => { console.error(e); process.exit(1); });
