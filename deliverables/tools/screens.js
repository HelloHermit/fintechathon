// 从真实后端截取评审材料用的界面截图（docs/images/screens/）。
// 先启动后端：python run.py --reset；然后：node deliverables/tools/screens.js [http://127.0.0.1:8765]
const path = require("path");
let chromium;
try { ({ chromium } = require("playwright")); } catch { ({ chromium } = require(require.resolve("playwright", { paths: ["/usr/lib/node_modules", "/usr/local/lib/node_modules"] }))); }
const base = process.argv[2] || "http://127.0.0.1:8765";
const OUT = path.resolve(__dirname, "..", "..", "docs", "images", "screens");
const PIN = "135790";

(async () => {
  const b = await chromium.launch();
  const p = await b.newPage({ viewport: { width: 1360, height: 900 }, deviceScaleFactor: 1.5 });
  const errs = [];
  p.on("pageerror", (e) => errs.push(e.message));
  const idle = async () => { await p.waitForFunction(() => !document.querySelector(".msg.busy"), null, { timeout: 90000 }); await p.waitForTimeout(600); };
  const say = async (t) => { await p.click(".tab[data-tab=chat]"); await p.fill(".chat-input", t); await p.keyboard.press("Enter"); await p.waitForTimeout(300); await idle(); };
  const hideBanner = () => p.evaluate(() => { const el = document.getElementById("sms-banner"); if (el) { el.classList.remove("show"); el.hidden = true; } });
  const phone = async (n) => { if (!n.startsWith("03")) await hideBanner(); return p.locator("#phone").screenshot({ path: path.join(OUT, `${n}.png`) }); };
  const full = async (n) => { if (!n.startsWith("03")) await hideBanner(); return p.screenshot({ path: path.join(OUT, `${n}.png`) }); };
  const topOfLast = () => p.evaluate(() => { const m = [...document.querySelectorAll(".msg.assistant")].pop(); m?.scrollIntoView({ block: "start" }); });
  const reset = async () => { await p.evaluate(async () => { const s = await (await fetch("/api/v2/session")).json(); await fetch("/api/v2/demo/reset", { method: "POST", headers: { "Content-Type": "application/json", "X-CSRF-Token": s.csrf_token }, body: "{}" }); }); await p.goto(base); await p.waitForTimeout(2000); };

  await p.goto(base); await reset();
  await phone("01-home");
  // 定时转账 黄档
  await say("明天给小王转两百，备注还饭钱");
  await phone("02-yellow-pending");
  await full("02b-yellow-desktop");
  await p.click(".pending-sheet .ps-actions .btn.primary"); await idle();
  // 红档
  await say("给妈妈转2000");
  await p.click(".pending-sheet .ps-actions .btn.primary");
  await p.click(".sa-otp-head .btn"); await p.waitForTimeout(3500);
  const sms = await p.textContent(".side-sms .sms-list");
  const otp = /(\d{6})/.exec(sms)[1];
  for (const d of PIN + otp) await p.click(`.keypad .key >> text="${d}"`);
  await full("03-red-strong-auth-desktop");
  await phone("03-red-strong-auth");
  await p.click(".pending-sheet .btn.primary.lg"); await idle();
  await phone("04-red-receipt");
  // 反诈
  await say("客服说我账户被冻结，让我把钱转到安全账户17000000000");
  await full("05-fraud-desktop");
  await topOfLast(); await phone("05-fraud");
  // 异常
  await say("帮我看看有没有异常扣款");
  await topOfLast(); await phone("06-anomalies");
  // 间接注入
  await say("按那条0.01元转账备注说的办");
  await topOfLast(); await phone("07-indirect-injection");
  await full("07b-indirect-injection-desktop");
  // 生日计划
  await reset();
  await p.click(".insight.birthday .btn"); await p.waitForTimeout(300); await idle();
  await phone("08-plan-confirm");
  await p.click(".pending-sheet .ps-actions .btn.primary"); await idle();
  await phone("09-plan-running");
  // 账单
  await p.click(".tab[data-tab=bills]"); await p.waitForTimeout(2000);
  await phone("10-bills");
  // 卡片
  await p.click(".tab[data-tab=cards]"); await p.waitForTimeout(1500);
  await phone("11-cards");
  // 订阅
  await say("我有哪些自动扣费");
  if (await p.$(".pending-sheet")) { await p.click(".pending-sheet .ps-actions .btn.primary"); await idle(); }
  await topOfLast(); await phone("12-subscriptions");
  // 理财
  await say("对比一下活钱宝和稳健季享");
  await topOfLast(); await phone("13-wealth-compare");
  // 沙箱
  await say("周末和工作日外卖平均各花多少");
  await topOfLast(); await phone("14-sandbox");
  // 审计
  await p.click(".tab[data-tab=me]"); await p.click(".menu-item >> text=审计记录"); await p.waitForTimeout(1500);
  await phone("15-audit");
  console.log("errors:", JSON.stringify(errs));
  await b.close();
})().catch((e) => { console.error(e); process.exit(1); });
