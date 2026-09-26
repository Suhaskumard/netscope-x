// Drives the REAL Chrome browser (Chrome DevTools Protocol) against the running topology explorer and checks that
// selecting each snapshot renders the graph that was recorded at that snapshot (Phase 97).
//   node scripts/verify_explorer_in_chrome.mjs <explorer_url> <expected.json> <out_dir>
// expected.json: [{version, nodes:[ip], edges:["ipA|ipB"], conf:{"ipA|ipB":0.637}}], read from the persisted graph
// files independently of the API/UI. Order visited includes going BACK to earlier snapshots.
import { spawn } from "node:child_process";
import { readFileSync, writeFileSync, mkdirSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const [url, expectedPath, outDir] = process.argv.slice(2);
mkdirSync(outDir, { recursive: true });
const expected = JSON.parse(readFileSync(expectedPath, "utf8"));
const CHROME = process.env.CHROME_PATH ?? "C:/Program Files/Google/Chrome/Application/chrome.exe";
const port = 9333;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const chrome = spawn(CHROME, [`--remote-debugging-port=${port}`, "--headless=new", "--disable-gpu", "--no-first-run",
  `--user-data-dir=${mkdtempSync(join(tmpdir(), "ns-chrome-"))}`, "--window-size=1400,1000", "about:blank"], { stdio: "ignore" });
let results = [];
try {
  let targets;
  for (let i = 0; i < 50; i++) {
    try { targets = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json(); break; } catch { await sleep(200); }
  }
  const page = targets.find((t) => t.type === "page");
  const ws = new WebSocket(page.webSocketDebuggerUrl);
  await new Promise((r) => (ws.onopen = r));
  let id = 0;
  const pending = new Map();
  const requests = [];
  const consoleErrors = [];
  ws.onmessage = (m) => {
    const msg = JSON.parse(m.data);
    if (msg.id && pending.has(msg.id)) { pending.get(msg.id)(msg); pending.delete(msg.id); }
    else if (msg.method === "Network.requestWillBeSent") requests.push(msg.params.request.url);
    else if (msg.method === "Runtime.exceptionThrown") consoleErrors.push(msg.params.exceptionDetails.text);
    else if (msg.method === "Runtime.consoleAPICalled" && msg.params.type === "error") consoleErrors.push(JSON.stringify(msg.params.args.map((a) => a.value)));
  };
  const send = (method, params = {}) => new Promise((res) => { const i = ++id; pending.set(i, res); ws.send(JSON.stringify({ id: i, method, params })); });
  const evalJs = async (expr) => (await send("Runtime.evaluate", { expression: expr, awaitPromise: true, returnByValue: true })).result?.result?.value;
  await send("Network.enable"); await send("Runtime.enable"); await send("Page.enable");
  await send("Page.navigate", { url });

  const waitFor = async (expr, what) => {
    for (let i = 0; i < 100; i++) { if (await evalJs(expr)) return; await sleep(150); }
    throw new Error("timeout waiting for " + what);
  };
  await waitFor(`!!document.querySelector('[data-testid=snapshot-tick-1]')`, "snapshot ticks");

  const read = () => evalJs(`(() => {
    const t = (id) => document.querySelector('[data-testid=' + id + ']')?.textContent ?? null;
    const cy = window.__cy;
    return { label: t('snapshot-label'), nodeCount: t('node-count'), edgeCount: t('edge-count'),
      cyNodes: cy.nodes().map(n => ({ id: n.id(), label: n.data('label'), status: n.data('status') })),
      cyEdges: cy.edges().map(e => ({ key: e.data('key'), status: e.data('status'), clabel: e.data('clabel') })) };
  })()`);

  const order = [4, 1, 3, 2, 1, 4]; // includes going back in time
  for (const v of order) {
    await evalJs(`document.querySelector('[data-testid=snapshot-tick-${v}]').click()`);
    await waitFor(`document.querySelector('[data-testid=snapshot-label]')?.textContent.includes('snapshot v${v} ') && !!document.querySelector('[data-testid=node-count]')`, `v${v} render`);
    await sleep(600); // let cytoscape settle
    const got = await read();
    const exp = expected.find((e) => e.version === v);
    // "current" elements = not ghosts of removed items
    const curNodes = got.cyNodes.filter((n) => n.status !== "removed").map((n) => n.id).sort();
    const curEdges = got.cyEdges.filter((e) => e.status !== "removed").map((e) => e.key).sort();
    const confOk = got.cyEdges.filter((e) => e.status !== "removed").every((e) => Math.abs(parseFloat(e.clabel) - exp.conf[e.key]) < 0.006);
    const checks = {
      nodesMatchRecorded: JSON.stringify(curNodes) === JSON.stringify(exp.nodes),
      edgesMatchRecorded: JSON.stringify(curEdges) === JSON.stringify(exp.edges),
      countsMatch: Number(got.nodeCount) === exp.nodes.length && Number(got.edgeCount) === exp.edges.length,
      confidenceLabelsMatch: confOk,
    };
    const shot = await send("Page.captureScreenshot", { format: "png" });
    const file = join(outDir, `snapshot_v${v}_visit${results.length + 1}.png`);
    writeFileSync(file, Buffer.from(shot.result.data, "base64"));
    results.push({ visited: v, label: got.label, nodes: curNodes, edges: curEdges, ghosts: got.cyNodes.filter((n) => n.status === "removed").length, checks, screenshot: file });
  }
  const snapshotFetches = requests.filter((u) => u.includes("/history/snapshots/") && u.includes("/topology"));
  const summary = {
    results,
    distinctGraphsRendered: new Set(results.map((r) => r.nodes.join(",") + "/" + r.edges.join(","))).size,
    topologyRequests: [...new Set(snapshotFetches.map((u) => u.replace(/capture_id=[0-9a-f]+/, "capture_id=…")))],
    consoleErrors,
    allPass: results.every((r) => Object.values(r.checks).every(Boolean)) && consoleErrors.length === 0,
  };
  writeFileSync(join(outDir, "summary.json"), JSON.stringify(summary, null, 2));
  console.log(JSON.stringify(summary, (k, v) => (k === "nodes" || k === "edges" ? v.length : v), 2));
  ws.close();
} finally {
  chrome.kill();
}
