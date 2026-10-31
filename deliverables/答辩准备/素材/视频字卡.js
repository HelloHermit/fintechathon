// 生成演示视频的开场卡和结尾卡（1920×1080 PNG）。结尾卡数字读 bench/reports/latest.json。
// 用法（项目根目录）：node deliverables/答辩准备/素材/视频字卡.js
// 需要 Playwright（云端会话已预装；本机没有就请会话 C 代为生成）。全部数据为模拟。
const fs = require("fs");
const path = require("path");
let chromium;
try { ({ chromium } = require("playwright")); } catch { ({ chromium } = require(require.resolve("playwright", { paths: ["/opt/node22/lib/node_modules", "/usr/lib/node_modules", "/usr/local/lib/node_modules"] }))); }

const ROOT = path.resolve(__dirname, "..", "..", "..");
const OUT = __dirname;
const bench = JSON.parse(fs.readFileSync(path.join(ROOT, "bench", "reports", "latest.json"), "utf8"));
const M = bench.metrics;
const pct = (x) => `${Math.round(x.rate * 10) / 10}%`;
const date = bench.meta.finished_at.slice(0, 10);

const CSS = `*{box-sizing:border-box}body{margin:0;width:1920px;height:1080px;display:flex;align-items:center;justify-content:center;background:#13204A;color:#fff;
font-family:"Microsoft YaHei","PingFang SC","Noto Sans CJK SC","WenQuanYi Zen Hei",sans-serif}
.c{width:1560px}.k{color:#9EE0C5;font-size:34px;margin-bottom:26px}.t{font-size:132px;font-weight:700;line-height:1.1}
.s{font-size:50px;margin-top:22px;color:#D7E1F8}.p{font-size:44px;margin-top:40px;color:#9EE0C5;font-weight:700}
.f{margin-top:60px;font-size:28px;color:#AFC0E8}
.n{display:grid;grid-template-columns:repeat(3,1fr);gap:36px;margin-top:56px}.n div{background:#1d2c5e;border-radius:24px;padding:34px 36px}
.n b{display:block;font-size:84px;color:#9EE0C5;line-height:1.1}.n span{font-size:30px;color:#D7E1F8}
.cov{margin-top:40px;font-size:30px;line-height:1.6;color:#D7E1F8}.cov em{font-style:normal;color:#9EE0C5}`;

const opening = `<div class="c"><div class="k">FinTechathon 2026 · 人工智能赛道 · 银行 AI 智能体</div>
<div class="t">小安</div><div class="s">说一句就能办，每一步都有代码把关</div>
<div class="p">模型提议，代码裁决</div>
<div class="f">全部账户、资金、商户、短信均为模拟数据</div></div>`;

const ending = `<div class="c"><div class="k">独立黑盒评测 · ${bench.meta.case_count} 条用例 · 真实大模型 ${bench.meta.model} · ${date}</div>
<div class="t" style="font-size:96px">模型提议，代码裁决</div>
<div class="n">
<div><b>${pct(M.task_completion)}</b><span>任务完成率（${M.task_completion.passed}/${M.task_completion.total}）</span></div>
<div><b>${pct(M.security_block)}</b><span>攻击拦截率（${M.security_block.passed}/${M.security_block.total}）</span></div>
<div><b>${M.global_violations}</b><span>敏感信息泄露次数</span></div></div>
<div class="cov">安全用例 ${M.security_block.total} 条覆盖：<em>诱导转账</em> 7 · <em>信息套取</em> 8 · <em>越权</em> 3 · <em>直接注入</em> 4 · <em>间接注入</em> 3 · 文字确认绕过 3 · 熔断 3 · 幻觉 3 · 越界数据 3 · 协议层 8</div>
<div class="f">评测集由不读后端实现的一方编写，失败照实保留（见测试报告）· 演示画面为回放模式 · 全部数据为模拟</div></div>`;

(async () => {
  const browser = await chromium.launch();
  const page = await (await browser.newContext({ viewport: { width: 1920, height: 1080 } })).newPage();
  for (const [name, body] of [["视频-开场卡.png", opening], ["视频-结尾卡.png", ending]]) {
    await page.setContent(`<!doctype html><meta charset="utf-8"><style>${CSS}</style>${body}`);
    await page.waitForTimeout(300);
    await page.screenshot({ path: path.join(OUT, name) });
    console.log("written", name);
  }
  console.log(`结尾卡数字来自 ${bench.meta.finished_at}（代码 ${bench.meta.git}）`);
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
