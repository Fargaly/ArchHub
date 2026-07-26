"use strict";

// Isolated evidence court for one already-authorised composition entry.
// It records the browser pipeline without attaching to a live ArchHub process.
const fs = require("fs");
const { chromium } = require("playwright");

const CHECKS = Object.freeze([
  "scope-entry-functional",
  "scope-entry-does-not-request-full-canvas",
  "scope-entry-does-not-submit-noop-gesture",
  "scope-interaction-is-not-blocked-by-pointerup-mutations",
  "scope-response-carries-exact-authorised-revision",
]);

function scopeRoot() {
  return document.querySelector("[data-universal-canvas-heading]")
    ?.dataset.universalCanvasHeading || "";
}

function openableCard() {
  const canvas = document.querySelector(".canvas[data-universal='true']");
  if (!canvas) return null;
  const canvasRect = canvas.getBoundingClientRect();
  return [...canvas.querySelectorAll(
    "[data-universal-root][data-universal-openable='True']"
  )].map(card => {
    const rect = card.getBoundingClientRect();
    return {
      id: card.dataset.universalRoot || "",
      left: rect.left,
      top: rect.top,
      right: rect.right,
      bottom: rect.bottom,
      visible: rect.width > 20 && rect.height > 20
        && rect.left >= canvasRect.left && rect.right <= canvasRect.right
        && rect.top >= canvasRect.top && rect.bottom <= canvasRect.bottom,
    };
  }).find(card => card.id && card.visible) || null;
}

async function run() {
  const url = process.env.ARCHHUB_COURT_URL;
  const session = process.env.ARCHHUB_COURT_SESSION;
  const configuredChrome = process.env.ARCHHUB_CHROME_EXECUTABLE;
  const defaultChrome = "C:/Program Files/Google/Chrome/Application/chrome.exe";
  const launch = { headless: true };
  if (configuredChrome) launch.executablePath = configuredChrome;
  else if (fs.existsSync(defaultChrome)) launch.executablePath = defaultChrome;

  const browser = await chromium.launch(launch);
  const page = await browser.newPage({ viewport: { width: 1600, height: 960 } });
  const requests = [];
  const requestIndex = new WeakMap();
  const responseReads = [];
  let tracking = false;
  try {
    await page.context().addCookies([{
      name: "ArchHub-Session", value: session, url,
      httpOnly: true, sameSite: "Strict",
    }]);
    page.on("request", request => {
      if (!tracking) return;
      const route = new URL(request.url()).pathname;
      if (![
        "/api/universal/canvas",
        "/api/universal/gesture",
        "/api/universal/interaction",
      ].includes(route)) return;
      let body = null;
      try { body = request.postDataJSON(); } catch (_) {}
      const entry = {
        sequence: requests.length,
        route,
        method: request.method(),
        startedMs: performance.now(),
        body,
      };
      requests.push(entry);
      requestIndex.set(request, entry);
    });
    page.on("response", response => {
      const entry = requestIndex.get(response.request());
      if (!entry) return;
      entry.responseMs = performance.now();
      entry.status = response.status();
      responseReads.push((async () => {
        try { entry.response = await response.json(); } catch (_) {}
      })());
    });

    await page.goto(url, { waitUntil: "domcontentloaded", timeout: 30000 });
    await page.locator(".canvas[data-universal='true']").waitFor({
      state: "visible", timeout: 30000,
    });
    const initialScope = await page.evaluate(scopeRoot);
    const card = await page.evaluate(openableCard);
    if (!card) throw new Error("scope locality court found no openable composition");

    await page.evaluate(() => {
      const canvas = document.querySelector(".canvas[data-universal='true']");
      const state = { batches: [], mutations: 0 };
      const observer = new MutationObserver(records => {
        state.batches.push({
          at: performance.now(),
          count: records.length,
          childList: records.filter(item => item.type === "childList").length,
          attributes: records.filter(item => item.type === "attributes").length,
        });
        state.mutations += records.length;
      });
      observer.observe(canvas, {
        subtree: true, childList: true, attributes: true,
        attributeFilter: [
          "class", "data-selection", "data-universal-canvas-heading",
          "style", "aria-selected",
        ],
      });
      window.__archhubScopeLocalityTrace = { state, observer };
    });

    tracking = true;
    const startedMs = performance.now();
    await page.mouse.dblclick(
      (card.left + card.right) / 2,
      (card.top + card.bottom) / 2,
    );
    await page.waitForFunction(previous => {
      const current = document.querySelector(
        "[data-universal-canvas-heading]"
      )?.dataset.universalCanvasHeading || "";
      return current && current !== previous;
    }, initialScope, { timeout: 30000 });
    const renderedMs = performance.now();
    tracking = false;
    await Promise.all(responseReads);
    const finalScope = await page.evaluate(scopeRoot);
    const dom = await page.evaluate(() => {
      const trace = window.__archhubScopeLocalityTrace;
      trace.observer.disconnect();
      return trace.state;
    });

    const scopeRequest = requests.find(item =>
      item.route === "/api/universal/interaction"
      && item.body?.control === card.id
    );
    const gesturesBeforeScope = requests.filter(item =>
      item.route === "/api/universal/gesture"
      && (!scopeRequest || item.sequence < scopeRequest.sequence)
    );
    const noopGestures = gesturesBeforeScope.filter(item =>
      Number.isSafeInteger(item.body?.projection_revision)
      && item.response?.projection_mode === "receipt-v1"
      && item.response.committed_revision === item.body.projection_revision
    );
    const canvasRequests = requests.filter(
      item => item.route === "/api/universal/canvas"
    );
    const response = scopeRequest?.response;
    const responseScope = response?.scope?.current;
    const responseRevision = response?.revision;
    const committedRevision = response?.committed_revision;
    const exactRevision = (
      Number.isSafeInteger(responseRevision)
      && Number.isSafeInteger(committedRevision)
      && responseRevision === committedRevision
    );
    const checks = {
      "scope-entry-functional": Boolean(
        scopeRequest?.status === 200
        && finalScope && finalScope !== initialScope
      ),
      "scope-entry-does-not-request-full-canvas": canvasRequests.length === 0,
      "scope-entry-does-not-submit-noop-gesture": noopGestures.length === 0,
      "scope-interaction-is-not-blocked-by-pointerup-mutations": (
        gesturesBeforeScope.length === 0
      ),
      "scope-response-carries-exact-authorised-revision": Boolean(
        exactRevision && responseScope === finalScope
      ),
    };
    return {
      passed: Object.values(checks).every(Boolean),
      checks,
      details: {
        initialScope,
        finalScope,
        card: card.id,
        elapsedMs: Math.round((renderedMs - startedMs) * 10) / 10,
        requestCount: requests.length,
        fullCanvasRequestCount: canvasRequests.length,
        gesturesBeforeScope: gesturesBeforeScope.length,
        noopGesturesBeforeScope: noopGestures.length,
        domReconciliationBatches: dom.batches.length,
        domMutationRecords: dom.mutations,
        requests: requests.map(item => ({
          sequence: item.sequence,
          route: item.route,
          method: item.method,
          status: item.status,
          control: item.body?.control || "",
          projectionRevision: item.body?.projection_revision
            ?? item.body?.revision ?? null,
          projectionMode: item.body?.projection_mode || "",
          committedRevision: item.response?.committed_revision ?? null,
          responseProjectionMode: item.response?.projection_mode || "",
          durationMs: Number.isFinite(item.responseMs)
            ? Math.round((item.responseMs - item.startedMs) * 10) / 10
            : null,
        })),
        domBatches: dom.batches,
      },
    };
  } finally {
    await browser.close();
  }
}

run().then(result => {
  process.stdout.write(JSON.stringify(result));
}).catch(error => {
  process.stderr.write(String(error.stack || error));
  process.exitCode = 1;
});
