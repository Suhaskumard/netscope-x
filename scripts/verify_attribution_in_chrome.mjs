// Real Chrome (CDP) check of the causal-attribution view (Phase 99).
//   node scripts/verify_attribution_in_chrome.mjs <url with ?view=attribution&capture=ID> <expected.json> <out_dir>
// For every dependency in the list: select it, read the RENDERED numbers, and check
//  (a) sum of displayed contributions == displayed strength (within display rounding),
//  (b) displayed strength == independently recomputed strength, (c) each displayed contribution == independent Shapley
//  (average over all 120 orderings), (d) the page's own consistency badge says consistent, (e) no console errors.
import { spawn } from "node:child_process";
import { readFileSync, writeFileSync, mkdirSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const [url, expectedPath, outDir] = process.argv.slice(2);
mkdirSync(outDir, { recursive: true });
const expected = JSON.parse(readFileSync(expectedPath, "utf8"));
const CHROME = process.env.CHROME_PATH ?? "C:/Program Files/Google/Chrome/Application/chrome.exe";
const port = 9335;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const chrome = spawn(CHROME, [`--remote-debugging-port=${port}`, "--headless=new", "--disable-gpu", "--no-first-run",
  `--user-data-dir=${mkdtempSync(join(tmpdir(), "ns-chrome-"))}`, "--window-size=1400,1100", "about:blank"], { stdio: "ignore" });
try {
  let targets;
  for (let i = 0; i < 50; i++) { try { targets = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json(); break; } catch { await sleep(200); } }
  const ws = new WebSocket(targets.find((t) => t.type === "page").webSocketDebuggerUrl);
  await new Promise((r) => (ws.onopen = r));
  let id = 0; const pending = new Map(); const errors = [];
  ws.onmessage = (m) => {
    const d = JSON.parse(m.data);
    if (d.id && pending.has(d.id)) { pending.get(d.id)(d); pending.delete(d.id); }
    else if (d.method === "Runtime.exceptionThrown") errors.push(d.params.exceptionDetails.text);
    else if (d.method === "Runtime.consoleAPICalled" && d.params.type === "error") errors.push(JSON.stringify(d.params.args.map((a) => a.value)));
  };
  const send = (method, params = {}) => new Promise((res) => { const i = ++id; pending.set(i, res); ws.send(JSON.stringify({ id: i, method, params })); });
  const ev = async (expr) => (await send("Runtime.evaluate", { expression: expr, awaitPromise: true, returnByValue: true })).result?.result?.value;
  const waitFor = async (expr, what) => { for (let i = 0; i < 100; i++) { if (await ev(expr)) return; await sleep(150); } throw new Error("timeout: " + what); };
  await send("Runtime.enable"); await send("Page.enable"); await send("Page.navigate", { url });
  await waitFor(`document.querySelectorAll('[data-testid^="dep-"]').length > 0`, "dependency list");

  const ids = await ev(`[...document.querySelectorAll('[data-testid^="dep-"]')].map(b => b.getAttribute('data-testid').slice(4))`);
  const order = expected.order;
  const rows = [];
  for (const depId of ids) {
    await ev(`document.querySelector('[data-testid="dep-${depId}"]').click()`);
    await waitFor(`document.querySelector('[data-testid=attribution]')?.getAttribute('data-dependency-id') === '${depId}' && !!document.querySelector('[data-testid=consistency]')`, "attribution " + depId);
    await sleep(250);
    const got = await ev(`(() => { const t = (id) => document.querySelector('[data-testid="' + id + '"]')?.textContent;
      return { strength: t('strength-value'), sum: t('contrib-sum'), residual: t('residual'), badge: document.querySelector('[data-testid=consistency]').dataset.consistent,
        contrib: ${JSON.stringify(order)}.map(s => t('contrib-' + s)), raw: ${JSON.stringify(order)}.map(s => t('raw-' + s)),
        selected: document.querySelector('[data-testid="dep-${depId}"]').className.includes('sky-400') }; })()`);
    const exp = expected.dependencies.find((d) => d.dependency_id === depId);
    const shown = got.contrib.map(Number);
    const sumShown = shown.reduce((a, b) => a + b, 0);
    const checks = {
      shownContributionsSumToShownStrength: Math.abs(sumShown - Number(got.strength)) < 6 * 0.5e-4 + 1e-9, // 5 terms, each rounded to 4 dp
      shownSumEqualsPageSumLabel: Math.abs(sumShown - Number(got.sum)) < 6 * 0.5e-4 + 1e-9,
      strengthMatchesIndependent: Math.abs(Number(got.strength) - exp.strength) < 0.5e-4 + 1e-9,
      contributionsMatchIndependentShapley: shown.every((v, i) => Math.abs(v - exp.contribution[i]) < 0.5e-4 + 1e-9),
      independentContributionsSumExactly: Math.abs(exp.contribution.reduce((a, b) => a + b, 0) - exp.strength) < 1e-12,
      pageBadgeConsistent: got.badge === "true",
    };
    const shot = await send("Page.captureScreenshot", { format: "png" });
    const file = join(outDir, `attr_${rows.length + 1}.png`);
    writeFileSync(file, Buffer.from(shot.result.data, "base64"));
    rows.push({ depId: depId.split(":").pop(), strength: got.strength, contributions: got.contrib, sum: got.sum, residual: got.residual,
      temporalRaw: got.raw[4], checks, screenshot: file });
  }
  const summary = { dependencies: rows.length, withTemporalPrecedence: rows.filter((r) => parseFloat(r.temporalRaw) > 0).length, rows,
    consoleErrors: errors, allPass: rows.every((r) => Object.values(r.checks).every(Boolean)) && errors.length === 0 };
  writeFileSync(join(outDir, "summary.json"), JSON.stringify(summary, null, 2));
  console.log(JSON.stringify({ ...summary, rows: rows.map((r) => ({ dep: r.depId, strength: r.strength, contributions: r.contributions, sum: r.sum,
    temporal: r.temporalRaw, ok: Object.values(r.checks).every(Boolean), failed: Object.entries(r.checks).filter(([, v]) => !v).map(([k]) => k) })) }, null, 1));
  ws.close();
} finally { chrome.kill(); }
