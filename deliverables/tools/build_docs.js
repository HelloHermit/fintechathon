// 生成评审材料：
//   node build_docs.js diagrams   docs/diagrams/*.mmd → docs/images/*.svg + *.png
//   node build_docs.js pdf        docs/技术文档.md 等 → deliverables/pdf/*.pdf
// 依赖：npm install（marked、mermaid），以及系统里可用的 Playwright Chromium。
const fs = require("fs");
const path = require("path");
let chromium;
try { ({ chromium } = require("playwright")); } catch { ({ chromium } = require(require.resolve("playwright", { paths: ["/usr/lib/node_modules", "/usr/local/lib/node_modules"] }))); }

const ROOT = path.resolve(__dirname, "..", "..");
const DIAGRAMS = path.join(ROOT, "docs", "diagrams");
const IMAGES = path.join(ROOT, "docs", "images");
const PDF_OUT = path.join(ROOT, "deliverables", "pdf");
const MERMAID_JS = path.join(__dirname, "node_modules", "mermaid", "dist", "mermaid.min.js");
const MARKED_JS = path.join(__dirname, "node_modules", "marked", "lib", "marked.umd.js");
const DOCS = [
  ["docs/技术文档.md", "技术文档.pdf"],
  ["docs/安全自评报告.md", "安全自评报告.pdf"],
  ["docs/测试报告.md", "测试报告.pdf"],
  ["docs/部署说明.md", "部署说明.pdf"],
];
const FONT = `"PingFang SC","Noto Sans CJK SC","Source Han Sans SC","Microsoft YaHei","WenQuanYi Zen Hei",sans-serif`;
const MERMAID_INIT = { startOnLoad: false, theme: "base", fontFamily: FONT, flowchart: { htmlLabels: true, curve: "basis" },
  themeVariables: { primaryColor: "#e8efff", primaryBorderColor: "#1d4ed8", primaryTextColor: "#0f172a", lineColor: "#64748b", fontSize: "15px", secondaryColor: "#e7f7f0", tertiaryColor: "#fff4e0" } };

async function renderMermaid(page, code, id) {
  return page.evaluate(async ({ code, id }) => (await window.mermaid.render(id, code)).svg, { code, id });
}

async function mermaidPage(browser) {
  const page = await browser.newPage({ deviceScaleFactor: 2 });
  await page.setContent(`<html><head><style>body{margin:0;font-family:${FONT}}</style></head><body><div id="out"></div></body></html>`);
  await page.addScriptTag({ path: MERMAID_JS });
  await page.evaluate((cfg) => window.mermaid.initialize(cfg), MERMAID_INIT);
  return page;
}

async function diagrams(browser) {
  fs.mkdirSync(IMAGES, { recursive: true });
  const page = await mermaidPage(browser);
  for (const f of fs.readdirSync(DIAGRAMS).filter((x) => x.endsWith(".mmd")).sort()) {
    const name = f.replace(/\.mmd$/, "");
    const svg = await renderMermaid(page, fs.readFileSync(path.join(DIAGRAMS, f), "utf8"), `d_${name.replace(/\W/g, "_")}`);
    fs.writeFileSync(path.join(IMAGES, `${name}.svg`), svg);
    await page.evaluate((s) => { document.getElementById("out").innerHTML = s; }, svg);
    const el = await page.$("#out svg");
    await el.screenshot({ path: path.join(IMAGES, `${name}.png`), omitBackground: false });
    console.log("diagram", name);
  }
  await page.close();
}

const PDF_CSS = `
@page { size: A4; margin: 18mm 16mm 18mm 16mm; }
body { font-family: ${FONT}; font-size: 10.5pt; line-height: 1.65; color: #1e293b; }
h1 { font-size: 20pt; color: #0f172a; border-bottom: 3px solid #1d4ed8; padding-bottom: 6px; margin: 0 0 14px; }
h2 { font-size: 14.5pt; color: #1d4ed8; margin: 22px 0 8px; page-break-after: avoid; }
h3 { font-size: 12pt; color: #0f172a; margin: 16px 0 6px; page-break-after: avoid; }
table { border-collapse: collapse; width: 100%; margin: 8px 0 12px; font-size: 9.5pt; page-break-inside: auto; }
th, td { border: 1px solid #d6dce8; padding: 4px 6px; vertical-align: top; text-align: left; }
th { background: #eef2fb; }
tr { page-break-inside: avoid; }
code { font-family: "DejaVu Sans Mono", Menlo, Consolas, monospace; font-size: 9pt; background: #f1f4f9; padding: 0 3px; border-radius: 3px; }
pre { background: #0f172a; color: #e2e8f0; padding: 8px 10px; border-radius: 6px; white-space: pre-wrap; word-break: break-all; font-size: 8.5pt; page-break-inside: avoid; }
pre code { background: none; color: inherit; padding: 0; }
blockquote { border-left: 4px solid #f59e0b; background: #fff8eb; margin: 8px 0; padding: 6px 12px; color: #7a4504; }
img, svg { max-width: 100%; height: auto; }
.mermaid-figure { text-align: center; margin: 10px 0 14px; page-break-inside: avoid; }
a { color: #1d4ed8; text-decoration: none; }
.sim-banner { font-size: 8.5pt; color: #b45309; background: #fff4e0; padding: 3px 8px; border-radius: 4px; display: inline-block; margin-bottom: 10px; }
`;

async function pdf(browser) {
  fs.mkdirSync(PDF_OUT, { recursive: true });
  const mpage = await mermaidPage(browser);
  for (const [src, out] of DOCS) {
    const file = path.join(ROOT, src);
    if (!fs.existsSync(file)) { console.log("skip (missing)", src); continue; }
    let md = fs.readFileSync(file, "utf8");
    // 图片内联成 data URI（页面里不能直接读本地文件）；图表优先用同名 SVG，打印更清晰
    const inline = (src) => {
      if (/^(https?|data):/.test(src)) return src;
      let abs = path.resolve(path.dirname(file), src);
      const svg = abs.replace(/\.png$/, ".svg");
      if (/[\\/]images[\\/][^\\/]+\.png$/.test(abs) && fs.existsSync(svg)) abs = svg;
      if (!fs.existsSync(abs)) return src;
      const type = abs.endsWith(".svg") ? "image/svg+xml" : abs.endsWith(".jpg") ? "image/jpeg" : "image/png";
      return `data:${type};base64,${fs.readFileSync(abs).toString("base64")}`;
    };
    md = md.replace(/!\[([^\]]*)\]\(([^)\s]+)\)/g, (_, alt, src) => `![${alt}](${inline(src)})`);
    md = md.replace(/<img([^>]*?)src="([^"]+)"/g, (_, pre, src) => `<img${pre}src="${inline(src)}"`);
    // ```mermaid 代码块 → 内联 SVG
    let i = 0;
    const blocks = [];
    md = md.replace(/```mermaid\n([\s\S]*?)```/g, (_, code) => { blocks.push(code); return `@@MERMAID_${i++}@@`; });
    const svgs = [];
    for (let k = 0; k < blocks.length; k++) svgs.push(await renderMermaid(mpage, blocks[k], `m${k}_${Date.now()}`));
    const page = await browser.newPage();
    await page.setContent(`<html><head><meta charset="utf-8"><style>${PDF_CSS}</style></head><body><div class="sim-banner">FinTechathon 2026 参赛材料 · 全部账户、资金、商户、短信均为模拟</div><div id="doc"></div></body></html>`);
    await page.addScriptTag({ path: MARKED_JS });
    const base = "file://" + path.dirname(file) + "/";
    await page.evaluate(({ md, svgs, base }) => {
      let html = window.marked.parse(md);
      svgs.forEach((s, k) => { html = html.replace(`<p>@@MERMAID_${k}@@</p>`, `<div class="mermaid-figure">${s}</div>`).replace(`@@MERMAID_${k}@@`, s); });
      const doc = document.getElementById("doc");
      doc.innerHTML = html;
      doc.querySelectorAll("img").forEach((img) => { const s = img.getAttribute("src"); if (s && !/^(https?|data|file):/.test(s)) img.src = new URL(s, base).href; });
    }, { md, svgs, base });
    await page.waitForTimeout(300);
    await page.pdf({ path: path.join(PDF_OUT, out), format: "A4", printBackground: true, displayHeaderFooter: true,
      headerTemplate: `<div style="font-size:7px;width:100%;text-align:right;padding-right:16mm;color:#94a3b8;font-family:${FONT}">小安 · 银行 AI 智能体（模拟）</div>`,
      footerTemplate: `<div style="font-size:7px;width:100%;text-align:center;color:#94a3b8"><span class="pageNumber"></span> / <span class="totalPages"></span></div>`,
      margin: { top: "18mm", bottom: "16mm", left: "16mm", right: "16mm" } });
    await page.close();
    console.log("pdf", out);
  }
  await mpage.close();
}

(async () => {
  const what = process.argv[2] || "all";
  const browser = await chromium.launch();
  try {
    if (what === "diagrams" || what === "all") await diagrams(browser);
    if (what === "pdf" || what === "all") await pdf(browser);
  } finally {
    await browser.close();
  }
})().catch((e) => { console.error(e); process.exit(1); });
