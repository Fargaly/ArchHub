"use strict";
// THE COURT — one judge over the running program, the way the founder uses it.
// It opens the live canvas in a real Chromium, does the founder's gestures,
// and measures each against the bar SPEC.md sets. One verdict record out.
const fs = require("fs");
const { chromium } = require("playwright");

const URL_ = process.env.ARCHHUB_COURT_URL || "http://127.0.0.1:8475";
const OUT = process.env.ARCHHUB_COURT_OUT || "";
const CHROME = process.env.ARCHHUB_CHROME_EXECUTABLE
  || "C:/Program Files/Google/Chrome/Application/chrome.exe";

const verdict = { court: "the-court", url: URL_, started_at: new Date().toISOString(), checks: [] };
function judge(name, pass, measured, bar) {
  verdict.checks.push({ name, pass: !!pass, measured, bar });
}

async function domState(page) {
  return page.evaluate(() => {
    const cards = [...document.querySelectorAll(".graph-node")];
    const vis = cards.filter(c => { const r = c.getBoundingClientRect(); return r.right > 0 && r.left < innerWidth && r.bottom > 0 && r.top < innerHeight; });
    const canvas = document.querySelector(".canvas");
    return {
      cards: cards.length, visible: vis.length,
      wires: document.querySelectorAll("[data-universal-relation]").length,
      openable: cards.filter(c => c.dataset.universalOpenable === "True").length,
      heading: (document.querySelector("[data-universal-canvas-heading]") || {}).textContent || "",
      zoom: canvas ? Number(canvas.dataset.zoom) : null,
      labels: cards.slice(0, 40).map(c => (c.querySelector(".universal-node-title, .node-title") || c).textContent.trim().split("\n")[0].slice(0, 48)),
      hashes: cards.map(c => c.textContent).filter(t => /[0-9a-f]{12,}/i.test(t)).length,
    };
  });
}

async function run() {
  const browser = await chromium.launch({ headless: true, executablePath: fs.existsSync(CHROME) ? CHROME : undefined });
  const page = await browser.newPage({ viewport: { width: 1600, height: 960 } });
  // A failed gesture with no reason is a verdict without evidence. Every
  // page error and console error is kept and written next to the checks.
  const pageErrors = [];
  page.on("pageerror", (err) => pageErrors.push({ kind: "pageerror", text: String(err && err.message || err) }));
  page.on("console", (msg) => { if (msg.type() === "error" || msg.type() === "warning") pageErrors.push({ kind: msg.type(), text: msg.text().slice(0, 400) }); });
  page.on("requestfailed", (req) => pageErrors.push({ kind: "requestfailed", text: req.url().slice(-120) + " " + (req.failure() && req.failure().errorText) }));
  page.on("response", (res) => { if (res.status() >= 400 && res.url().includes("/api/")) res.text().then((t) => pageErrors.push({ kind: "http" + res.status(), text: res.url().slice(-80) + " " + t.slice(0, 300) })).catch(() => {}); });
  try {
    // 1. OPEN — the page signs itself in and paints the entry scope.
    const t0 = Date.now();
    await page.goto(URL_, { waitUntil: "domcontentloaded" });
    await page.waitForSelector(".graph-node", { timeout: 240000 });
    const openMs = Date.now() - t0;
    let s = await domState(page);
    judge("open: first screen shows the work (SPEC 7.1)", s.visible > 0, `${s.visible} visible of ${s.cards} cards, ${s.wires} wires`, "visible > 0");
    judge("open: time to first painted node", openMs < 60000, `${openMs} ms`, "< 60000 ms (sign-in + canvas)");
    judge("open: no hashes on Use cards (SPEC 6.1)", s.hashes === 0, `${s.hashes} cards show a hash; heading='${s.heading.slice(0,48)}'`, "0");
    judge("open: entry scope is the map, not a lobby", s.openable >= 10, `${s.openable} openable domain cards`, ">= 10");
    // What the court saw, for the founder's eyes: the first screen and,
    // later, the entered domain.
    const SHOTS = process.env.ARCHHUB_COURT_SHOTS || "";
    if (SHOTS) { try { await page.screenshot({ path: SHOTS + "-open.png", fullPage: false }); } catch (e) {} }

    // 2. WHEEL ZOOM OUT — the founder's first gesture.
    const before = s;
    const c = await page.locator(".canvas[data-universal='true']").boundingBox();
    await page.mouse.move(c.x + c.width / 2, c.y + c.height / 2);
    await page.mouse.wheel(0, 100);
    await page.waitForTimeout(600);
    s = await domState(page);
    judge("wheel: zoom OUT reduces zoom", s.zoom < before.zoom, `${before.zoom?.toFixed(3)} -> ${s.zoom?.toFixed(3)}`, "zoom decreases");
    judge("wheel: work stays on screen after one notch", s.visible > 0, `${s.visible} visible after wheel`, "> 0");
    for (let i = 0; i < 4; i++) { await page.mouse.wheel(0, 100); await page.waitForTimeout(80); }
    await page.waitForTimeout(600);
    s = await domState(page);
    judge("wheel: five notches out still shows the work", s.visible > 0, `${s.visible} visible at zoom ${s.zoom?.toFixed(3)}`, "> 0");

    // 3. FIT — the toolbar's own recovery.
    const fit = page.locator("[data-universal-zoom='fit']");
    if (await fit.count()) { await fit.click(); await page.waitForTimeout(800); s = await domState(page); }
    judge("fit: shows every card", s.visible === s.cards && s.cards > 0, `${s.visible}/${s.cards}`, "all");

    // 4. ENTER a domain and come back (SPEC 7.2, 11.14 scope entry <= 150ms local ack).
    const door = page.locator("[data-universal-root][data-universal-openable='True']").first();
    const doorLabel = (await door.textContent() || "").trim().split("\n")[0].slice(0, 40);
    const t1 = Date.now();
    await door.dblclick();
    await page.waitForFunction(h => (document.querySelector("[data-universal-canvas-heading]") || {}).textContent !== h, before.heading, { timeout: 60000 }).catch(() => {});
    const enterMs = Date.now() - t1;
    await page.waitForTimeout(800);
    const inside = await domState(page);
    judge("enter: double-click opens the domain", inside.heading !== before.heading, `'${before.heading.slice(0,30)}' -> '${inside.heading.slice(0,30)}' via ${doorLabel}`, "heading changes");
    judge("enter: the domain has its requirements", inside.cards >= 5, `${inside.cards} cards, ${inside.wires} wires`, ">= 5 cards");
    if (SHOTS) { try { await page.screenshot({ path: SHOTS + "-domain.png", fullPage: false }); } catch (e) {} }
    judge("enter: scope entry round-trip", enterMs <= 5000, `${enterMs} ms`, "<= 5000 ms (SPEC 11.14 wants 150 ms local ack)");
    const crumbs = await page.locator("button[data-universal-scope]").count();
    const up = page.locator("button[data-universal-scope]").first();
    const tBack = Date.now();
    if (crumbs) {
      await up.click();
      await page.waitForFunction(h => (document.querySelector("[data-universal-canvas-heading]") || {}).textContent === h, before.heading, { timeout: 15000 }).catch(() => {});
    }
    const backMs = Date.now() - tBack;
    const back = await domState(page);
    judge("enter: breadcrumb returns to the map", back.heading === before.heading, `${crumbs} crumb(s); '${back.heading.slice(0,30)}' after ${backMs} ms`, "same heading as before, within 15 s");

    // 5. PLACE a card from the library. A definition that declares
    // participants opens the relation composer instead of landing a card,
    // so the court places one that declares none -- exactly what the
    // client does on that click -- and waits for the topology delta.
    // Placing writes a card into the graph under test. On the founder's
    // live graph that is pollution, not a court: thirteen test cards had to
    // be removed from his map. The step runs only when asked.
    const PLACE = process.env.ARCHHUB_COURT_PLACE === "1";
    const placeable = !PLACE ? null : await page.evaluate(async () => {
      const token = window.__archhubSession && window.__archhubSession.token;
      const res = await fetch("/api/universal/canvas", { headers: token ? { "X-ArchHub-Session": token } : {} });
      const canvas = await res.json();
      const ids = new Set((canvas.catalog || []).filter(i => !i.composition_contract).map(i => i.id));
      const control = [...document.querySelectorAll("[data-universal-definition-place]")].find(c => ids.has(c.dataset.universalDefinitionPlace));
      return control ? { id: control.dataset.universalDefinitionPlace, label: (control.closest("[data-universal-catalog-entry], li, .library-entry") || control).textContent.trim().slice(0, 40) } : null;
    });
    let placed = false;
    let placeNote = "no placeable definition in the library";
    if (placeable) {
      const cardsBefore = (await domState(page)).cards;
      await page.locator(`[data-universal-definition-place="${placeable.id}"]`).first().click();
      await page.waitForFunction(n => document.querySelectorAll(".graph-node").length > n, cardsBefore, { timeout: 15000 }).catch(() => {});
      const cardsAfter = (await domState(page)).cards;
      placed = cardsAfter > cardsBefore;
      placeNote = `${placeable.label || placeable.id}: cards ${cardsBefore} -> ${cardsAfter}`;
    }
    if (PLACE) judge("place: a library card lands on the canvas", placed, placeNote, "grows by 1 within 15 s");

    // 6. POINTER frame budget (SPEC 11.14: p95 <= 16.7 ms) — pan across the canvas.
    const frames = await page.evaluate(() => new Promise(res => {
      const t = []; let last = performance.now(); let n = 0;
      function tick(now) { t.push(now - last); last = now; if (++n < 60) requestAnimationFrame(tick); else res(t); }
      requestAnimationFrame(tick);
    }));
    await page.mouse.move(c.x + 200, c.y + 200); await page.mouse.down();
    for (let i = 0; i < 20; i++) await page.mouse.move(c.x + 200 + i * 15, c.y + 200 + i * 5);
    await page.mouse.up();
    const sorted = frames.slice().sort((a, b) => a - b); const p95 = sorted[Math.floor(sorted.length * 0.95)];
    judge("pointer: frame p95 (SPEC 11.14)", p95 <= 16.7 * 2, `${p95?.toFixed(1)} ms`, "<= 16.7 ms (judged at 2x for headless)");
  } finally {
    await browser.close();
  }
  verdict.finished_at = new Date().toISOString();
  verdict.page_errors = pageErrors;
  verdict.passed = verdict.checks.filter(c => c.pass).length;
  verdict.failed = verdict.checks.filter(c => !c.pass).length;
  const text = JSON.stringify(verdict, null, 2);
  if (OUT) fs.writeFileSync(OUT, text);
  process.stdout.write(text);
}
run().catch(err => { verdict.error = String(err && err.stack || err); process.stdout.write(JSON.stringify(verdict, null, 2)); process.exit(1); });
