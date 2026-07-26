"use strict";

// This court drives an isolated ApplicationServer. It never attaches to the
// founder's running desktop session and writes screenshots only when the
// caller explicitly supplies a temporary directory.
const fs = require("fs");
const path = require("path");
const { chromium } = require("playwright");

const CHECKS = Object.freeze([
  "page-identity",
  "canvas-has-real-nodes-and-wires",
  "selection-projects-properties",
  "property-edit-updates-node",
  "keyboard-undo-redo",
  "presentation-color-updates-node",
  "multi-selection",
  "modifier-selection-and-deselection",
  "group-and-ungroup-preserve-members",
  "directional-marquee",
  "modifier-marquee-selection-and-deselection",
  "wheel-zoom",
  "space-pan",
  "wire-selects-relation",
  "scope-navigation",
  "library-search-is-local-and-usable",
  "library-placement",
  "visual-parameter-creation",
  "inspector-build-lens",
  "inspector-tabs-operational",
  "visual-interface-creation",
  "visual-input-interface-creation",
  "socket-wire-creation",
  "mutation-acknowledgements-within-budget",
  "scope-entry-within-budget",
  "no-failed-governed-responses",
  "no-console-or-page-errors",
]);

function asNumber(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function selectedRoots() {
  try {
    const parsed = JSON.parse(document.querySelector(".canvas")?.dataset.selection || "[]");
    return Array.isArray(parsed) ? parsed.filter(value => typeof value === "string") : [];
  } catch (_) {
    return [];
  }
}

function currentScope() {
  return document.querySelector("[data-universal-canvas-heading]")
    ?.dataset.universalCanvasHeading || "";
}

function visibleCards() {
  const canvas = document.querySelector(".canvas[data-universal='true']");
  if (!canvas) return [];
  const canvasRect = canvas.getBoundingClientRect();
  return [...canvas.querySelectorAll("[data-universal-root]")].map(card => {
    const rect = card.getBoundingClientRect();
    return {
      id: card.dataset.universalRoot || "",
      openable: card.dataset.universalOpenable === "True",
      left: rect.left,
      top: rect.top,
      right: rect.right,
      bottom: rect.bottom,
      width: rect.width,
      height: rect.height,
      visible: rect.width > 20 && rect.height > 20
        && rect.left >= canvasRect.left && rect.right <= canvasRect.right
        && rect.top >= canvasRect.top && rect.bottom <= canvasRect.bottom,
    };
  }).filter(card => card.id && card.visible);
}

function isInsideCanvas(box, canvasRect, margin = 4) {
  return box.left >= canvasRect.left + margin
    && box.right <= canvasRect.right - margin
    && box.top >= canvasRect.top + margin
    && box.bottom <= canvasRect.bottom - margin;
}

function overlaps(left, right) {
  return left.left < right.right && left.right > right.left
    && left.top < right.bottom && left.bottom > right.top;
}

function marqueePlan() {
  const canvas = document.querySelector(".canvas[data-universal='true']");
  if (!canvas) return null;
  const canvasRect = canvas.getBoundingClientRect();
  const cards = visibleCards();
  for (const card of cards) {
    const windowBox = {
      left: card.left - 6, right: card.right + 6,
      top: card.top - 6, bottom: card.bottom + 6,
    };
    if (!isInsideCanvas(windowBox, canvasRect)) continue;
    if (cards.some(other => other.id !== card.id && overlaps(windowBox, other))) continue;
    const crossingBox = {
      left: card.left + card.width * 0.45, right: card.right + 12,
      top: card.top - 8, bottom: card.bottom + 8,
    };
    if (!isInsideCanvas(crossingBox, canvasRect)) continue;
    if (cards.some(other => other.id !== card.id && overlaps(crossingBox, other))) continue;
    return {
      id: card.id,
      window: { startX: windowBox.left, startY: windowBox.top,
        endX: windowBox.right, endY: windowBox.bottom },
      crossing: { startX: crossingBox.right, startY: crossingBox.top,
        endX: crossingBox.left, endY: crossingBox.bottom },
    };
  }
  return null;
}

function blankCanvasPoint() {
  const canvas = document.querySelector(".canvas[data-universal='true']");
  if (!canvas) return null;
  const rect = canvas.getBoundingClientRect();
  for (let y = rect.top + 24; y < rect.bottom - 24; y += 36) {
    for (let x = rect.left + 24; x < rect.right - 24; x += 36) {
      const target = document.elementFromPoint(x, y);
      if (target && target.closest(".canvas") === canvas
        && !target.closest("[data-universal-root],.canvas-toolbar,.composer,.wire-hit")) {
        return { x, y };
      }
    }
  }
  return null;
}

const PAGE_HELPER_SCRIPT = [
  asNumber,
  selectedRoots,
  currentScope,
  visibleCards,
  isInsideCanvas,
  overlaps,
  marqueePlan,
  blankCanvasPoint,
].map(helper => helper.toString()).join("\n") + `
window.__archhubCourt = Object.freeze({
  asNumber,
  selectedRoots,
  currentScope,
  visibleCards,
  marqueePlan,
  blankCanvasPoint,
});`;

async function waitFor(page, predicate, argument, timeout = 10000) {
  await page.waitForFunction(predicate, argument, { timeout });
}

async function moveDrag(page, from, to) {
  await page.mouse.move(from.startX, from.startY);
  await page.mouse.down();
  await page.mouse.move(to.endX, to.endY, { steps: 8 });
  await page.mouse.up();
}

function sameRoots(left, right) {
  return Array.isArray(left) && Array.isArray(right)
    && left.length === right.length
    && left.every((root, index) => root === right[index]);
}

async function performGesture(page, expectedRoots, trigger, timeout = 15000) {
  let requestBody = null;
  const responsePromise = page.waitForResponse(response => {
    if (new URL(response.url()).pathname !== "/api/universal/gesture"
        || response.request().method() !== "POST") return false;
    try {
      const candidate = response.request().postDataJSON();
      if (!sameRoots(candidate?.roots, expectedRoots)) return false;
      requestBody = candidate;
      return true;
    } catch (_) {
      return false;
    }
  }, { timeout });
  await trigger();
  const response = await responsePromise;
  let responseBody = {};
  try { responseBody = await response.json(); } catch (_) {}
  const baseRevision = responseBody.base_revision;
  const committedRevision = responseBody.committed_revision
    ?? responseBody.revision;
  return {
    status: response.status(),
    request: requestBody,
    response: responseBody,
    valid: response.status() === 200
      && Number.isInteger(requestBody?.projection_revision)
      && baseRevision === requestBody.projection_revision
      && Number.isInteger(committedRevision)
      && committedRevision > baseRevision,
  };
}

async function recordScreenshot(page, name) {
  const directory = process.env.ARCHHUB_EDITOR_COURT_SCREENSHOT_DIR;
  if (!directory) return null;
  fs.mkdirSync(directory, { recursive: true });
  const target = path.join(directory, `${name}.png`);
  await page.screenshot({ path: target, fullPage: false });
  return target;
}

(async () => {
  const url = process.env.ARCHHUB_COURT_URL;
  const session = process.env.ARCHHUB_COURT_SESSION;
  if (!url || !session) throw new Error("graph editor court environment is incomplete");

  const configuredChrome = process.env.ARCHHUB_CHROME_EXECUTABLE;
  const defaultChrome = "C:/Program Files/Google/Chrome/Application/chrome.exe";
  const launch = { headless: true };
  if (configuredChrome) launch.executablePath = configuredChrome;
  else if (fs.existsSync(defaultChrome)) launch.executablePath = defaultChrome;

  const browser = await chromium.launch(launch);
  const page = await browser.newPage({ viewport: { width: 1600, height: 960 } });
  await page.addInitScript({ content: PAGE_HELPER_SCRIPT });
  const messages = [];
  const failedResponseReads = [];
  const receiptResponseReads = [];
  const requestEvents = [];
  const universalRequestStarted = new WeakMap();
  const details = {
    screenshots: [], messages, failedResponses: [], interactionResponses: [],
    universalResponseLatencies: [],
    receiptTimings: [],
  };
  const checks = Object.fromEntries(CHECKS.map(name => [name, false]));
  try {
    await page.context().addCookies([{
      name: "ArchHub-Session", value: session, url,
      httpOnly: true, sameSite: "Strict",
    }]);
    page.on("console", message => {
      if (message.type() === "error" || message.type() === "warning") {
        messages.push(`${message.type()}: ${message.text()}`);
      }
    });
    page.on("pageerror", error => messages.push(
      `pageerror: ${error.stack || error.message}`
    ));
    page.on("request", request => {
      const route = new URL(request.url()).pathname;
      requestEvents.push({ route, method: request.method() });
      if (route === "/api/universal/gesture"
          || route === "/api/universal/interaction") {
        universalRequestStarted.set(request, performance.now());
      }
    });
    page.on("response", response => {
      const route = new URL(response.url()).pathname;
      const request = response.request();
      let requestBody = null;
      if (route === "/api/universal/gesture"
          || route === "/api/universal/interaction") {
        try { requestBody = request.postDataJSON(); } catch (_) {}
      }
      if (route === "/api/universal/interaction") {
        details.interactionResponses.push({
          status: response.status(),
          control: requestBody?.control || "",
        });
      }
      const started = universalRequestStarted.get(request);
      if (started !== undefined) {
        details.universalResponseLatencies.push({
          route,
          status: response.status(),
          control: requestBody?.control || "",
          durationMs: Math.round((performance.now() - started) * 10) / 10,
        });
      }
      if (response.status() >= 200 && response.status() < 300
          && (route === "/api/universal/gesture"
            || route === "/api/universal/interaction")) {
        receiptResponseReads.push((async () => {
          let payload;
          try { payload = await response.json(); } catch (_) { return; }
          if (payload?.projection_mode !== "receipt-v1") return;
          details.receiptTimings.push({
            route,
            control: requestBody?.control || "",
            committedRevision: payload.committed_revision ?? null,
            serverTimingMs: payload.server_timing_ms || null,
          });
        })());
      }
      if (response.status() < 400) return;
      failedResponseReads.push((async () => {
        let body = "";
        try { body = await response.text(); } catch (_) {}
        details.failedResponses.push({
          route,
          status: response.status(),
          body: body.slice(0, 1000),
          request: requestBody,
        });
      })());
    });
    await page.goto(url, { waitUntil: "domcontentloaded", timeout: 30000 });
    await page.locator(".canvas[data-universal='true']").waitFor({
      state: "visible", timeout: 30000,
    });
    await page.locator(".inspector[data-universal='true']").waitFor({
      state: "visible", timeout: 30000,
    });
    try {
      await waitFor(page, () => {
        const wires = [...document.querySelectorAll(
          ".canvas .wire-hit[data-universal-relation]"
        )];
        return wires.length > 0 && wires.every(wire => (
          (wire.getAttribute("d") || "").startsWith("M ")
          && wire.dataset.sourceNode && wire.dataset.targetNode
        ));
      }, null, 15000);
    } catch (error) {
      const diagnostic = await page.evaluate(() => ({
        wireCount: document.querySelectorAll(
          ".canvas .wire-hit[data-universal-relation]"
        ).length,
        nodeCount: document.querySelectorAll(
          ".canvas [data-universal-root]"
        ).length,
        wires: [...document.querySelectorAll(
          ".canvas .wire-hit[data-universal-relation]"
        )].slice(0, 12).map(wire => ({
          relation: wire.dataset.universalRelation || "",
          segment: wire.dataset.universalSegment || "",
          source: wire.dataset.sourceNode || "",
          target: wire.dataset.targetNode || "",
          sourceInterface: wire.dataset.sourceInterface || "",
          targetInterface: wire.dataset.targetInterface || "",
          path: wire.getAttribute("d") || "",
        })),
      }));
      throw new Error(
        "initial wire geometry unavailable: " + JSON.stringify(diagnostic)
        + "; " + String(error.message || error)
      );
    }

    const cards = await page.evaluate(() => window.__archhubCourt.visibleCards());
    const initial = await page.evaluate(cards => ({
      title: document.title,
      sessionHidden: !document.querySelector('meta[name="archhub-session"]'),
      csrf: /^[A-Za-z0-9_-]{32,128}$/.test(
        document.querySelector('meta[name="archhub-csrf"]')?.content || ""),
      cards,
      wireCount: document.querySelectorAll(".canvas .wire-hit[data-universal-relation]").length,
      selectedRoots: window.__archhubCourt.selectedRoots(),
      validWireCount: [...document.querySelectorAll(
        ".canvas .wire-hit[data-universal-relation]")].filter(wire => {
        const d = wire.getAttribute("d") || "";
        return d.startsWith("M ") && wire.dataset.sourceNode && wire.dataset.targetNode;
      }).length,
    }), cards);
    details.initial = initial;
    checks["page-identity"] = initial.title === "ArchHub" && initial.sessionHidden && initial.csrf;
    checks["canvas-has-real-nodes-and-wires"] = initial.cards.length >= 2
      && initial.wireCount > 0 && initial.wireCount === initial.validWireCount;
    const initialScreenshot = await recordScreenshot(
      page, "graph-editor-initial"
    );
    if (initialScreenshot) details.screenshots.push(initialScreenshot);
    const first = initial.cards.find(
      card => !initial.selectedRoots.includes(card.id)
    ) || initial.cards[0];
    const second = initial.cards.find(card => card.id !== first?.id);
    if (!first || !second) throw new Error("graph editor court needs two visible cards");

    const initialSelectionExchange = await performGesture(
      page, [first.id],
      () => page.mouse.click(
        (first.left + first.right) / 2,
        (first.top + first.bottom) / 2
      )
    );
    details.initialSelectionExchange = initialSelectionExchange;
    await waitFor(page, root => {
      const selected = window.__archhubCourt.selectedRoots();
      return selected.length === 1 && selected[0] === root
        && document.querySelector(".inspector")?.dataset.inspectedNode === root;
    }, first.id);
    checks["selection-projects-properties"] = initialSelectionExchange.valid
      && await page.evaluate(root => (
      document.querySelector(".inspector")?.dataset.inspectedNode === root
        && document.querySelectorAll(".inspector [data-inspector-tabpanel]").length > 0
        && document.querySelectorAll(".inspector [data-universal-properties-panel]").length > 0
    ), first.id);

    const titleInput = page.locator(".inspector label.property-row:visible")
      .filter({ hasText: /^title\b/i }).locator(
        "input[data-universal-event-fact-input][data-universal-control]"
      ).first();
    if (await titleInput.count()) {
      const originalTitle = await titleInput.inputValue();
      const editedTitle = `${originalTitle} Court`;
      await titleInput.fill(editedTitle);
      const [propertyResponse] = await Promise.all([
        page.waitForResponse(response => (
          new URL(response.url()).pathname === "/api/universal/interaction"
          && response.request().method() === "POST"
        ), { timeout: 15000 }),
        titleInput.evaluate(input => input.dispatchEvent(new Event("change", {
          bubbles: true, cancelable: true,
        }))),
      ]);
      try {
        await waitFor(page, ({ root, title }) => {
          const card = [...document.querySelectorAll(
            ".canvas [data-universal-root]"
          )].find(candidate => candidate.dataset.universalRoot === root);
          return card?.querySelector(".node-title")?.textContent === title;
        }, { root: first.id, title: editedTitle }, 15000);
        checks["property-edit-updates-node"] = propertyResponse.status() === 200
          && await titleInput.inputValue() === editedTitle;
      } catch (error) {
        details.propertyEditError = String(error.message || error);
      }
      details.propertyEdit = await page.evaluate(({ root, originalTitle,
        editedTitle, status }) => {
        const card = [...document.querySelectorAll(
          ".canvas [data-universal-root]"
        )].find(candidate => candidate.dataset.universalRoot === root);
        const row = [...document.querySelectorAll(
          ".inspector label.property-row"
        )].find(candidate => candidate.getClientRects().length > 0
          && candidate.querySelector(
            ".property-label")?.textContent?.trim().toLowerCase() === "title");
        return {
          root, originalTitle, editedTitle, status,
          cardTitle: card?.querySelector(".node-title")?.textContent || "",
          inputValue: row?.querySelector("input")?.value || "",
        };
      }, {
        root: first.id, originalTitle, editedTitle,
        status: propertyResponse.status(),
      });

      const undoControl = page.locator(
        '[data-universal-history="undo"][data-universal-control]'
      ).first();
      const redoControl = page.locator(
        '[data-universal-history="redo"][data-universal-control]'
      ).first();
      if (await undoControl.count() && await redoControl.count()) {
        try {
          const undoRoot = await undoControl.getAttribute(
            "data-universal-control");
          const undoResponsePromise = page.waitForResponse(response => {
            if (new URL(response.url()).pathname !== "/api/universal/interaction"
                || response.request().method() !== "POST") return false;
            try {
              return response.request().postDataJSON()?.control === undoRoot;
            } catch (_) {
              return false;
            }
          }, { timeout: 15000 });
          await undoControl.focus();
          await page.keyboard.press("Control+z");
          const undoResponse = await undoResponsePromise;
          await waitFor(page, ({ root, title }) => {
            const card = [...document.querySelectorAll(
              ".canvas [data-universal-root]"
            )].find(candidate => candidate.dataset.universalRoot === root);
            return card?.querySelector(".node-title")?.textContent === title;
          }, { root: first.id, title: originalTitle }, 15000);

          const redoRoot = await redoControl.getAttribute(
            "data-universal-control");
          const redoResponsePromise = page.waitForResponse(response => {
            if (new URL(response.url()).pathname !== "/api/universal/interaction"
                || response.request().method() !== "POST") return false;
            try {
              return response.request().postDataJSON()?.control === redoRoot;
            } catch (_) {
              return false;
            }
          }, { timeout: 15000 });
          await redoControl.focus();
          await page.keyboard.press("Control+y");
          const redoResponse = await redoResponsePromise;
          await waitFor(page, ({ root, title }) => {
            const card = [...document.querySelectorAll(
              ".canvas [data-universal-root]"
            )].find(candidate => candidate.dataset.universalRoot === root);
            return card?.querySelector(".node-title")?.textContent === title;
          }, { root: first.id, title: editedTitle }, 15000);
          const finalTitle = await page.evaluate(root => {
            const card = [...document.querySelectorAll(
              ".canvas [data-universal-root]"
            )].find(candidate => candidate.dataset.universalRoot === root);
            return card?.querySelector(".node-title")?.textContent || "";
          }, first.id);
          checks["keyboard-undo-redo"] = undoResponse.status() === 200
            && redoResponse.status() === 200
            && finalTitle === editedTitle;
          details.historyKeyboard = {
            undoStatus: undoResponse.status(),
            redoStatus: redoResponse.status(),
            undoControl: undoRoot,
            redoControl: redoRoot,
            originalTitle,
            editedTitle,
            finalTitle,
          };
        } catch (error) {
          details.historyKeyboardError = String(error.message || error);
        }
      }
    }

    const presentationTab = page.locator(
      '[data-universal-properties-panel]'
    ).filter({ hasText: /^Presentation$/ }).first();
    if (await presentationTab.count()) {
      const panelControl = await presentationTab.getAttribute(
        "data-universal-properties-panel");
      const panelResponsePromise = page.waitForResponse(response => {
        if (new URL(response.url()).pathname !== "/api/universal/interaction"
            || response.request().method() !== "POST") return false;
        try {
          return response.request().postDataJSON()?.control === panelControl;
        } catch (_) {
          return false;
        }
      }, { timeout: 15000 });
      await presentationTab.click();
      try {
        const panelResponse = await panelResponsePromise;
        const colorInput = page.locator(
          '.inspector [data-inspector-tabpanel]:not([hidden]) '
          + 'input[type="color"][data-universal-control]'
          + '[data-universal-event-fact-input]'
        ).first();
        await colorInput.waitFor({ state: "visible", timeout: 15000 });
        const colorControl = await colorInput.getAttribute(
          "data-universal-control");
        const originalColor = await page.evaluate(root => {
          const card = [...document.querySelectorAll(
            ".canvas [data-universal-root]"
          )].find(candidate => candidate.dataset.universalRoot === root);
          return card?.style.getPropertyValue("--node-color").trim() || "";
        }, first.id);
        const editedColor = originalColor.toLowerCase() === "#336699"
          ? "#2f80ed" : "#336699";
        const colorResponsePromise = page.waitForResponse(response => {
          if (new URL(response.url()).pathname !== "/api/universal/interaction"
              || response.request().method() !== "POST") return false;
          try {
            return response.request().postDataJSON()?.control === colorControl;
          } catch (_) {
            return false;
          }
        }, { timeout: 15000 });
        await colorInput.evaluate((input, value) => {
          input.value = value;
          input.dispatchEvent(new Event("change", {
            bubbles: true, cancelable: true,
          }));
        }, editedColor);
        const colorResponse = await colorResponsePromise;
        await waitFor(page, ({ root, color }) => {
          const card = [...document.querySelectorAll(
            ".canvas [data-universal-root]"
          )].find(candidate => candidate.dataset.universalRoot === root);
          const input = document.querySelector(
            '.inspector [data-inspector-tabpanel]:not([hidden]) '
            + 'input[type="color"][data-universal-control]'
          );
          const source = document.querySelector(
            '.inspector [data-inspector-tabpanel]:not([hidden]) '
            + '.presentation-source'
          );
          return card?.style.getPropertyValue("--node-color").trim()
              .toLowerCase() === color
            && input?.value?.toLowerCase() === color
            && source?.textContent?.trim().startsWith("PERSONAL-WIP");
        }, { root: first.id, color: editedColor }, 15000);
        const presentationResult = await page.evaluate(
          ({ root, originalColor, editedColor }) => {
            const card = [...document.querySelectorAll(
              ".canvas [data-universal-root]"
            )].find(candidate => candidate.dataset.universalRoot === root);
            const input = document.querySelector(
              '.inspector [data-inspector-tabpanel]:not([hidden]) '
              + 'input[type="color"][data-universal-control]'
            );
            const source = document.querySelector(
              '.inspector [data-inspector-tabpanel]:not([hidden]) '
              + '.presentation-source'
            );
            return {
              root,
              originalColor,
              editedColor,
              cardColor: card?.style.getPropertyValue("--node-color").trim()
                || "",
              inputValue: input?.value || "",
              source: source?.textContent?.trim() || "",
            };
          },
          { root: first.id, originalColor, editedColor },
        );
        checks["presentation-color-updates-node"] =
          panelResponse.status() === 200
          && colorResponse.status() === 200
          && presentationResult.cardColor.toLowerCase() === editedColor
          && presentationResult.inputValue.toLowerCase() === editedColor
          && presentationResult.source.startsWith("PERSONAL-WIP");
        details.presentationColor = {
          panelStatus: panelResponse.status(),
          colorStatus: colorResponse.status(),
          panelControl,
          colorControl,
          ...presentationResult,
        };
        const presentationScreenshot = await recordScreenshot(
          page, "graph-editor-presentation"
        );
        if (presentationScreenshot) {
          details.screenshots.push(presentationScreenshot);
        }
      } catch (error) {
        details.presentationColorError = String(error.message || error);
      }
    }

    const propertiesTab = page.locator(
      '[data-universal-properties-panel]'
    ).filter({ hasText: /^Properties$/ }).first();
    if (await propertiesTab.count()) {
      const control = await propertiesTab.getAttribute(
        "data-universal-properties-panel");
      const propertiesResponsePromise = page.waitForResponse(response => {
        if (new URL(response.url()).pathname !== "/api/universal/interaction"
            || response.request().method() !== "POST") return false;
        try {
          return response.request().postDataJSON()?.control === control;
        } catch (_) {
          return false;
        }
      }, { timeout: 15000 });
      await propertiesTab.click();
      await propertiesResponsePromise;
      await titleInput.waitFor({ state: "visible", timeout: 15000 });
    }

    const multiSelectionExchange = await performGesture(
      page, [first.id, second.id], async () => {
        await page.keyboard.down("Control");
        try {
          await page.mouse.click(
            (second.left + second.right) / 2,
            (second.top + second.bottom) / 2
          );
        } finally {
          await page.keyboard.up("Control");
        }
      }
    );
    await waitFor(page, roots => {
      const selected = window.__archhubCourt.selectedRoots();
      return selected.length === roots.length
        && roots.every(root => selected.includes(root));
    }, [first.id, second.id]);
    checks["multi-selection"] = multiSelectionExchange.valid
      && await page.evaluate(roots => {
        const selected = window.__archhubCourt.selectedRoots();
        return selected.length === roots.length
          && roots.every(root => selected.includes(root));
      }, [first.id, second.id]);

    details.modifierSelection = {
      initial: await page.evaluate(() => window.__archhubCourt.selectedRoots()),
      multiSelectionExchange,
    };
    try {
      const shiftExchange = await performGesture(
        page, [second.id], async () => {
          await page.keyboard.down("Shift");
          try {
            await page.mouse.click(
              (first.left + first.right) / 2,
              (first.top + first.bottom) / 2
            );
          } finally {
            await page.keyboard.up("Shift");
          }
        }
      );
      await waitFor(page, ({ removed, retained }) => {
        const selected = window.__archhubCourt.selectedRoots();
        return selected.length === 1
          && !selected.includes(removed) && selected[0] === retained;
      }, { removed: first.id, retained: second.id });
      details.modifierSelection.afterShift = await page.evaluate(
        () => window.__archhubCourt.selectedRoots()
      );
      details.modifierSelection.shiftExchange = shiftExchange;

      const controlExchange = await performGesture(
        page, [second.id, first.id], async () => {
          await page.keyboard.down("Control");
          try {
            await page.mouse.click(
              (first.left + first.right) / 2,
              (first.top + first.bottom) / 2
            );
          } finally {
            await page.keyboard.up("Control");
          }
        }
      );
      await waitFor(page, roots => {
        const selected = window.__archhubCourt.selectedRoots();
        return selected.length === roots.length
          && roots.every(root => selected.includes(root));
      }, [first.id, second.id]);
      details.modifierSelection.afterControl = await page.evaluate(
        () => window.__archhubCourt.selectedRoots()
      );
      details.modifierSelection.controlExchange = controlExchange;
      checks["modifier-selection-and-deselection"] = shiftExchange.valid
        && controlExchange.valid
        && details.modifierSelection.afterShift.length === 1
        && details.modifierSelection.afterShift[0] === second.id
        && details.modifierSelection.afterControl.length === 2
        && [first.id, second.id].every(
          root => details.modifierSelection.afterControl.includes(root)
        );
    } catch (error) {
      details.modifierSelection.error = String(error.message || error);
    }

    const groupControl = page.locator(
      '.canvas-toolbar button[data-universal-control="app:control:canvas:group"]'
    );
    const groupDomStarted = performance.now();
    try {
      await groupControl.waitFor({ state: "attached", timeout: 10000 });
    } catch (error) {
      details.groupControlError = String(error.message || error);
    }
    details.grouping = {
      groupControlCount: await groupControl.count(),
      groupControlDomMs: Math.round((performance.now() - groupDomStarted) * 10) / 10,
      members: [first.id, second.id],
    };
    if (details.grouping.groupControlCount) {
      const nodesBeforeGroup = await page.locator(
        ".canvas [data-universal-root]"
      ).count();
      const groupResponse = page.waitForResponse(response => (
        new URL(response.url()).pathname === "/api/universal/interaction"
        && response.request().method() === "POST"
      ), { timeout: 20000 });
      await groupControl.click();
      const groupStatus = (await groupResponse).status();
      details.grouping.groupStatus = groupStatus;
      await waitFor(page, ({ members, before }) => {
        const selected = window.__archhubCourt.selectedRoots();
        return selected.length === 1 && !members.includes(selected[0])
          && document.querySelectorAll(".canvas [data-universal-root]").length
            === before - members.length + 1;
      }, { members: [first.id, second.id], before: nodesBeforeGroup }, 20000);
      const composition = (await page.evaluate(
        () => window.__archhubCourt.selectedRoots()
      ))[0];
      const ungroupControl = page.locator(
        '.canvas-toolbar button[data-universal-control="app:control:canvas:ungroup"]'
      );
      const ungroupDomStarted = performance.now();
      try {
        await ungroupControl.waitFor({ state: "attached", timeout: 10000 });
      } catch (error) {
        details.ungroupControlError = String(error.message || error);
      }
      details.grouping.composition = composition || "";
      details.grouping.ungroupControlCount = await ungroupControl.count();
      details.grouping.ungroupControlDomMs = Math.round(
        (performance.now() - ungroupDomStarted) * 10
      ) / 10;
      if (composition && details.grouping.ungroupControlCount) {
        const ungroupResponse = page.waitForResponse(response => (
          new URL(response.url()).pathname === "/api/universal/interaction"
          && response.request().method() === "POST"
        ), { timeout: 20000 });
        await ungroupControl.click();
        const ungroupStatus = (await ungroupResponse).status();
        details.grouping.ungroupStatus = ungroupStatus;
        await waitFor(page, ({ members, composition, before }) => {
          const visible = new Set([...document.querySelectorAll(
            ".canvas [data-universal-root]"
          )].map(card => card.dataset.universalRoot));
          const selected = window.__archhubCourt.selectedRoots();
          return !visible.has(composition)
            && members.every(root => visible.has(root) && selected.includes(root))
            && visible.size === before;
        }, {
          members: [first.id, second.id], composition,
          before: nodesBeforeGroup,
        }, 20000);
        checks["group-and-ungroup-preserve-members"] = groupStatus === 200
          && ungroupStatus === 200;
        details.composition = {
          root: composition,
          members: [first.id, second.id],
        };
      }
    }

    const marquee = await page.evaluate(() => window.__archhubCourt.marqueePlan());
    details.marquee = marquee;
    if (marquee) {
      const windowExchange = await performGesture(
        page, [marquee.id],
        () => moveDrag(page, marquee.window, marquee.window)
      );
      await waitFor(page, root => {
        const selected = window.__archhubCourt.selectedRoots();
        return selected.length === 1 && selected[0] === root;
      }, marquee.id);
      const containing = await page.evaluate(root => {
        const selected = window.__archhubCourt.selectedRoots();
        return selected.length === 1 && selected[0] === root;
      }, marquee.id);

      const partialWindow = {
        startX: marquee.crossing.endX,
        startY: marquee.crossing.startY,
        endX: marquee.crossing.startX,
        endY: marquee.crossing.endY,
      };
      const partialWindowExchange = await performGesture(
        page, [], () => moveDrag(page, partialWindow, partialWindow)
      );
      await waitFor(page, () => (
        window.__archhubCourt.selectedRoots().length === 0
      ), null);
      const partialWindowRejected = await page.evaluate(
        () => window.__archhubCourt.selectedRoots().length === 0
      );

      const crossingExchange = await performGesture(
        page, [marquee.id],
        () => moveDrag(page, marquee.crossing, marquee.crossing)
      );
      await waitFor(page, root => {
        const selected = window.__archhubCourt.selectedRoots();
        return selected.length === 1 && selected[0] === root;
      }, marquee.id);
      const crossing = await page.evaluate(root => {
        const selected = window.__archhubCourt.selectedRoots();
        return selected.length === 1 && selected[0] === root;
      }, marquee.id);
      details.marquee.windowExchange = windowExchange;
      details.marquee.partialWindow = partialWindow;
      details.marquee.partialWindowExchange = partialWindowExchange;
      details.marquee.crossingExchange = crossingExchange;
      checks["directional-marquee"] = windowExchange.valid
        && partialWindowExchange.valid
        && crossingExchange.valid
        && containing && partialWindowRejected && crossing;

      details.modifierMarquee = {
        initial: await page.evaluate(() => window.__archhubCourt.selectedRoots()),
      };
      try {
        const retained = (await page.evaluate(
          target => window.__archhubCourt.visibleCards().find(
            card => card.id !== target
          ), marquee.id
        ));
        if (!retained) {
          throw new Error("modifier marquee needs one retained visible node");
        }
        const baselineExchange = await performGesture(
          page, [marquee.id, retained.id], async () => {
            await page.keyboard.down("Control");
            try {
              await page.mouse.click(
                (retained.left + retained.right) / 2,
                (retained.top + retained.bottom) / 2
              );
            } finally {
              await page.keyboard.up("Control");
            }
          }
        );
        await waitFor(page, roots => {
          const selected = window.__archhubCourt.selectedRoots();
          return selected.length === roots.length
            && roots.every(root => selected.includes(root));
        }, [marquee.id, retained.id]);
        details.modifierMarquee.retained = retained.id;
        details.modifierMarquee.baseline = await page.evaluate(
          () => window.__archhubCourt.selectedRoots()
        );
        details.modifierMarquee.baselineExchange = baselineExchange;

        const shiftExchange = await performGesture(
          page, [retained.id], async () => {
            await page.keyboard.down("Shift");
            try {
              await moveDrag(page, marquee.window, marquee.window);
            } finally {
              await page.keyboard.up("Shift");
            }
          }
        );
        await waitFor(page, root => {
          const selected = window.__archhubCourt.selectedRoots();
          return selected.length === 1 && selected[0] === root;
        }, retained.id);
        details.modifierMarquee.afterShift = await page.evaluate(
          () => window.__archhubCourt.selectedRoots()
        );
        details.modifierMarquee.shiftExchange = shiftExchange;

        const controlExchange = await performGesture(
          page, [retained.id, marquee.id], async () => {
            await page.keyboard.down("Control");
            try {
              await moveDrag(page, marquee.window, marquee.window);
            } finally {
              await page.keyboard.up("Control");
            }
          }
        );
        await waitFor(page, roots => {
          const selected = window.__archhubCourt.selectedRoots();
          return selected.length === roots.length
            && roots.every(root => selected.includes(root));
        }, [retained.id, marquee.id]);
        details.modifierMarquee.afterControl = await page.evaluate(
          () => window.__archhubCourt.selectedRoots()
        );
        details.modifierMarquee.controlExchange = controlExchange;
        checks["modifier-marquee-selection-and-deselection"] = (
          baselineExchange.valid
          && shiftExchange.valid
          && controlExchange.valid
          && details.modifierMarquee.afterShift.length === 1
          && details.modifierMarquee.afterShift[0] === retained.id
          && details.modifierMarquee.afterControl.length === 2
          && details.modifierMarquee.afterControl[0] === retained.id
          && details.modifierMarquee.afterControl[1] === marquee.id
        );
      } catch (error) {
        details.modifierMarquee.error = String(error.message || error);
      }
    }

    const blank = await page.evaluate(() => window.__archhubCourt.blankCanvasPoint());
    details.blankCanvasPoint = blank;
    if (blank) {
      const beforeZoom = await page.evaluate(() => window.__archhubCourt.asNumber(
        document.querySelector(".canvas")?.dataset.zoom
      ));
      await page.mouse.move(blank.x, blank.y);
      const wheelResponse = page.waitForResponse(response => (
        new URL(response.url()).pathname === "/api/universal/gesture"
        && response.request().method() === "POST"
      ), { timeout: 15000 });
      await page.mouse.wheel(0, -160);
      await waitFor(page, before => {
        const zoom = window.__archhubCourt.asNumber(
          document.querySelector(".canvas")?.dataset.zoom
        );
        return zoom !== null && before !== null && Math.abs(zoom - before) > 0.0001;
      }, beforeZoom);
      checks["wheel-zoom"] = (await wheelResponse).status() === 200;

      const panPoint = await page.evaluate(
        () => window.__archhubCourt.blankCanvasPoint()
      );
      details.panPoint = panPoint;
      if (!panPoint) throw new Error("graph editor court has no blank pan point");
      const beforePan = await page.evaluate(() => ({
        x: window.__archhubCourt.asNumber(document.querySelector(".canvas")?.dataset.panX),
        y: window.__archhubCourt.asNumber(document.querySelector(".canvas")?.dataset.panY),
      }));
      await page.locator(".canvas[data-universal='true']").focus();
      await page.keyboard.down("Space");
      await page.mouse.move(panPoint.x, panPoint.y);
      await page.mouse.down();
      await page.mouse.move(panPoint.x + 72, panPoint.y + 44, { steps: 8 });
      const panResponse = page.waitForResponse(response => (
        new URL(response.url()).pathname === "/api/universal/gesture"
        && response.request().method() === "POST"
      ), { timeout: 15000 });
      await page.mouse.up();
      await page.keyboard.up("Space");
      await waitFor(page, before => {
        const canvas = document.querySelector(".canvas");
        return window.__archhubCourt.asNumber(canvas?.dataset.panX) !== before.x
          || window.__archhubCourt.asNumber(canvas?.dataset.panY) !== before.y;
      }, beforePan);
      checks["space-pan"] = (await panResponse).status() === 200;
    }

    const wirePoint = await page.evaluate(() => {
      const wires = [...document.querySelectorAll(
        ".canvas .wire-hit[data-universal-relation]"
      )].filter(candidate => (
        candidate.dataset.context === "True"
        && getComputedStyle(candidate).visibility !== "hidden"
        && getComputedStyle(candidate).pointerEvents !== "none"
      ));
      for (const wire of wires) {
        if (typeof wire.getTotalLength !== "function") continue;
        const length = wire.getTotalLength();
        const matrix = wire.getScreenCTM();
        if (!matrix || !Number.isFinite(length) || length <= 0) continue;
        for (let step = 1; step < 20; step += 1) {
          const point = wire.getPointAtLength(length * step / 20);
          const screen = new DOMPoint(point.x, point.y).matrixTransform(matrix);
          const target = document.elementFromPoint(screen.x, screen.y)
            ?.closest(".wire-hit[data-universal-relation]");
          if (target === wire) {
            return { id: wire.dataset.universalRelation,
              x: screen.x, y: screen.y };
          }
        }
      }
      return null;
    });
    details.wirePoint = wirePoint;
    if (wirePoint) {
      await page.mouse.click(wirePoint.x, wirePoint.y);
      try {
        await waitFor(page, relation => [...document.querySelectorAll(
          `.canvas [data-universal-relation="${relation}"]`)].some(
          wire => wire.dataset.focused === "True"), wirePoint.id);
        checks["wire-selects-relation"] = true;
      } catch (error) {
        details.wireSelectionError = String(error.message || error);
        details.wireAfterClick = await page.evaluate(({ id, x, y }) => {
          const target = document.elementFromPoint(x, y);
          const wires = [...document.querySelectorAll(
            `.canvas [data-universal-relation="${id}"]`
          )].map(wire => ({
            className: wire.getAttribute("class") || "",
            context: wire.dataset.context || "",
            focused: wire.dataset.focused || "",
          }));
          const status = document.querySelector(".status-message");
          return {
            target: target ? {
              className: target.getAttribute("class") || "",
              relation: target.getAttribute("data-universal-relation") || "",
            } : null,
            wires,
            status: status ? {
              text: status.textContent || "",
              visible: status.dataset.visible || "",
            } : null,
          };
        }, wirePoint);
      }
    }

    const openable = (await page.evaluate(
      () => window.__archhubCourt.visibleCards()
    )).find(card => card.openable);
    if (openable) {
      const previousScope = await page.evaluate(
        () => window.__archhubCourt.currentScope()
      );
      const scopeStarted = performance.now();
      const scopeResponsePromise = page.waitForResponse(response => {
        if (new URL(response.url()).pathname !== "/api/universal/interaction"
            || response.request().method() !== "POST") return false;
        try {
          return response.request().postDataJSON()?.control === openable.id;
        } catch (_) {
          return false;
        }
      }, { timeout: 30000 });
      await page.mouse.dblclick((openable.left + openable.right) / 2,
        (openable.top + openable.bottom) / 2);
      try {
        const scopeResponse = await scopeResponsePromise;
        details.scopeResponse = {
          status: scopeResponse.status(),
          responseMs: Math.round((performance.now() - scopeStarted) * 10) / 10,
        };
        await waitFor(page, previous => {
          const current = window.__archhubCourt.currentScope();
          return current && current !== previous;
        }, previousScope, 30000);
        const nextScope = await page.evaluate(
          () => window.__archhubCourt.currentScope()
        );
        details.scopeResponse.renderedMs = Math.round(
          (performance.now() - scopeStarted) * 10
        ) / 10;
        checks["scope-navigation"] = scopeResponse.status() === 200
          && Boolean(nextScope && nextScope !== previousScope);
        details.scope = { previous: previousScope, current: nextScope };
      } catch (error) {
        details.scopeNavigationError = String(error.message || error);
        details.scope = await page.evaluate(({ id, previous }) => {
          const card = document.querySelector(
            `.canvas [data-universal-root="${id}"]`
          );
          const status = document.querySelector(".status-message");
          return {
            previous,
            current: window.__archhubCourt.currentScope(),
            interaction: card?.dataset.universalInteraction || "",
            control: card?.dataset.universalInteractionControl || "",
            event: card?.dataset.universalInteractionEvent || "",
            status: status ? {
              text: status.textContent || "",
              visible: status.dataset.visible || "",
            } : null,
          };
        }, { id: openable.id, previous: previousScope });
      }
    }

    const librarySearch = page.locator(
      '[data-universal-library-search]'
    ).first();
    if (await librarySearch.count()) {
      const requestsBefore = requestEvents.length;
      await librarySearch.fill("watcher");
      try {
        await waitFor(page, () => {
          const entries = [...document.querySelectorAll(
            '[data-universal-library-entry]'
          )].filter(entry => !entry.hidden);
          const names = entries.map(entry => entry.querySelector(
            '.universal-library-name')?.textContent?.trim() || "");
          return entries.length === 1
            && names[0] === "Watcher"
            && entries[0].querySelector(
              '[data-universal-definition-place]'
            ) instanceof HTMLButtonElement;
        }, null, 10000);
        const librarySearchResult = await page.evaluate(() => {
          const entries = [...document.querySelectorAll(
            '[data-universal-library-entry]'
          )].filter(entry => !entry.hidden);
          return {
            query: document.querySelector(
              '[data-universal-library-search]')?.value || "",
            names: entries.map(entry => entry.querySelector(
              '.universal-library-name')?.textContent?.trim() || ""),
            sections: [...document.querySelectorAll(
              '[data-universal-library-section]'
            )].filter(section => !section.hidden).map(section =>
              section.querySelector(
                '.universal-library-section')?.textContent?.trim() || ""),
            resultCount: document.querySelector(
              '[data-universal-library-result-count]')?.textContent?.trim()
              || "",
          };
        });
        librarySearchResult.requests = requestEvents.slice(requestsBefore);
        checks["library-search-is-local-and-usable"] =
          librarySearchResult.query === "watcher"
          && librarySearchResult.names.length === 1
          && librarySearchResult.names[0] === "Watcher"
          && librarySearchResult.resultCount === "1 node"
          && librarySearchResult.requests.length === 0;
        details.librarySearch = librarySearchResult;
      } catch (error) {
        details.librarySearchError = String(error.message || error);
      }
    }

    const rootsBeforePlacement = await page.locator(
      ".canvas [data-universal-root]"
    ).evaluateAll(cards => cards.map(card => card.dataset.universalRoot));
    const nodesBeforePlacement = rootsBeforePlacement.length;
    const placement = page.locator(
      '[data-universal-library-entry]:visible '
      + '[data-universal-definition-place]'
    ).first();
    if (await placement.count()) {
      await librarySearch.focus();
      await librarySearch.press("ArrowDown");
      await waitFor(page, () => {
        const active = document.querySelector(
          '[data-universal-library-entry][data-search-active="true"]'
        );
        const place = active?.querySelector(
          '[data-universal-definition-place]'
        );
        return active?.querySelector(
          '.universal-library-name'
        )?.textContent?.trim() === "Watcher"
          && place instanceof HTMLButtonElement
          && !place.disabled;
      }, null, 10000);
      const placementControl = await placement.getAttribute(
        "data-universal-interaction-control");
      const placementDefinition = await placement.getAttribute(
        "data-universal-definition-place");
      const placementResponsePromise = page.waitForResponse(response => {
        if (new URL(response.url()).pathname !== "/api/universal/interaction"
            || response.request().method() !== "POST") return false;
        try {
          return response.request().postDataJSON()?.control === placementControl;
        } catch (_) {
          return false;
        }
      }, { timeout: 30000 });
      await librarySearch.press("Enter");
      try {
        const placementResponse = await placementResponsePromise;
        let placementPayload = {};
        try { placementPayload = await placementResponse.json(); } catch (_) {}
        const createdRoot = placementPayload.created_root || "";
        if (!createdRoot) {
          throw new Error("keyboard placement response omitted created_root");
        }
        await page.waitForFunction(({ root, beforeRoots }) => {
          const card = document.querySelector(
            `.canvas [data-universal-root="${root}"]`
          );
          const currentRoots = [...document.querySelectorAll(
            ".canvas [data-universal-root]"
          )].map(item => item.dataset.universalRoot);
          return Boolean(card)
            && !beforeRoots.includes(root)
            && card.querySelector(".node-title")?.textContent?.trim() === "Watcher"
            && currentRoots.length === beforeRoots.length + 1
            && beforeRoots.every(beforeRoot => currentRoots.includes(beforeRoot))
            && currentRoots.filter(currentRoot => !beforeRoots.includes(
              currentRoot
            )).length === 1;
        }, { root: createdRoot, beforeRoots: rootsBeforePlacement }, {
          timeout: 10000,
        });
        const rootsAfterPlacement = await page.locator(
          ".canvas [data-universal-root]"
        ).evaluateAll(cards => cards.map(card => card.dataset.universalRoot));
        const nodesAfterPlacement = await page.locator(
          ".canvas [data-universal-root]"
        ).count();
        const createdTitle = await page.locator(
          `.canvas [data-universal-root="${createdRoot}"] .node-title`
        ).textContent();
        checks["library-placement"] = placementResponse.status() === 200
          && placementDefinition !== null
          && !rootsBeforePlacement.includes(createdRoot)
          && nodesAfterPlacement === nodesBeforePlacement + 1
          && rootsBeforePlacement.every(root => rootsAfterPlacement.includes(root))
          && rootsAfterPlacement.filter(root => !rootsBeforePlacement.includes(
            root
          )).length === 1
          && createdTitle?.trim() === "Watcher";
        details.libraryPlacement = {
          status: placementResponse.status(),
          control: placementControl,
          definition: placementDefinition,
          createdRoot,
          createdTitle: createdTitle?.trim() || "",
          before: nodesBeforePlacement,
          after: nodesAfterPlacement,
          rootsBefore: rootsBeforePlacement,
          rootsAfter: rootsAfterPlacement,
          input: "keyboard",
        };
      } catch (error) {
        details.libraryPlacementError = String(error.message || error);
        details.libraryPlacement = await placement.evaluate((control, before) => {
          const status = document.querySelector(".status-message");
          return {
            before,
            after: document.querySelectorAll(
              ".canvas [data-universal-root]"
            ).length,
            definition: control.dataset.universalDefinitionPlace || "",
            interaction: control.dataset.universalInteraction || "",
            interactionControl: control.dataset.universalInteractionControl || "",
            status: status ? {
              text: status.textContent || "",
              visible: status.dataset.visible || "",
            } : null,
          };
        }, nodesBeforePlacement);
      }
    }

    details.authoringSurfaces = await page.evaluate(() => ({
      selectedRoots: [...document.querySelectorAll(
        '.canvas [data-universal-root][data-selected="True"]'
      )].map(item => item.dataset.universalRoot),
      relationForms: [...document.querySelectorAll(
        '.inspector [data-universal-relation-form]'
      )].map(form => ({
        root: form.dataset.universalRelationForm || '',
        fields: [...form.querySelectorAll(
          '[data-universal-relation-form-field]'
        )].map(field => field.dataset.universalRelationFormField),
      })),
      outputs: document.querySelectorAll(
        '.canvas [data-universal-output][data-universal-interface]'
      ).length,
      inputs: document.querySelectorAll(
        '.canvas [data-universal-input][data-universal-interface]'
      ).length,
      interfaceNodes: [...document.querySelectorAll(
        '.canvas [data-universal-root]'
      )].filter(card => card.querySelector('[data-universal-interface]')).length,
    }));

    const propertyForm = page.locator(
      ".inspector [data-universal-relation-form]"
    ).filter({ has: page.locator(
      '[data-universal-relation-form-field="label"]'
    ) }).first();
    if (await propertyForm.count()) {
      const label = propertyForm.locator(
        '[data-universal-relation-form-field="label"]');
      const value = propertyForm.locator(
        '[data-universal-relation-form-field="value"]');
      const submit = propertyForm.locator(
        '[data-universal-relation-form-submit]');
      const control = await submit.getAttribute("data-universal-control");
      const parameterResponsePromise = page.waitForResponse(response => {
        if (new URL(response.url()).pathname !== "/api/universal/interaction"
            || response.request().method() !== "POST") return false;
        try {
          return response.request().postDataJSON()?.control === control;
        } catch (_) {
          return false;
        }
      }, { timeout: 30000 });
      await label.fill("Acoustic rating");
      await value.fill("Rw 50");
      await label.press("Enter");
      try {
        const parameterResponse = await parameterResponsePromise;
        await waitFor(page, () => [...document.querySelectorAll(
          ".inspector label.property-row .property-label"
        )].some(item => item.textContent?.trim() === "Acoustic rating"), null, 20000);
        const parameterValue = await page.evaluate(() => {
          const row = [...document.querySelectorAll(
            ".inspector label.property-row"
          )].find(item => item.querySelector(
            ".property-label")?.textContent?.trim() === "Acoustic rating");
          return row?.querySelector("input")?.value || "";
        });
        checks["visual-parameter-creation"] = parameterResponse.status() === 200
          && parameterValue === "Rw 50";
        details.parameterCreation = {
          status: parameterResponse.status(), value: parameterValue,
        };
      } catch (error) {
        details.parameterCreationError = String(error.message || error);
      }
    }

    const buildLens = page.locator(
      '[data-universal-inspector-lens]'
    ).filter({ hasText: "Build" }).first();
    if (await buildLens.count()) {
      const control = await buildLens.getAttribute(
        "data-universal-inspector-lens");
      const lensResponsePromise = page.waitForResponse(response => {
        if (new URL(response.url()).pathname !== "/api/universal/interaction"
            || response.request().method() !== "POST") return false;
        try {
          return response.request().postDataJSON()?.control === control;
        } catch (_) {
          return false;
        }
      }, { timeout: 30000 });
      await buildLens.click();
      try {
        const lensResponse = await lensResponsePromise;
        await waitFor(page, controlRoot => {
          const control = [...document.querySelectorAll(
            '[data-universal-inspector-lens]'
          )].find(item => (
            item.dataset.universalInspectorLens === controlRoot
          ));
          return control?.dataset.active === "true";
        }, control, 20000);
        checks["inspector-build-lens"] = lensResponse.status() === 200;
        details.inspectorLens = {
          status: lensResponse.status(),
          control,
        };
      } catch (error) {
        details.inspectorLensError = String(error.message || error);
      }
    }

    const interfacesTab = page.locator(
      '[data-universal-properties-panel]'
    ).filter({ hasText: "Interfaces" }).first();
    if (await interfacesTab.count()) {
      const control = await interfacesTab.getAttribute(
        "data-universal-properties-panel");
      const tabResponsePromise = page.waitForResponse(response => {
        if (new URL(response.url()).pathname !== "/api/universal/interaction"
            || response.request().method() !== "POST") return false;
        try {
          return response.request().postDataJSON()?.control === control;
        } catch (_) {
          return false;
        }
      }, { timeout: 30000 });
      await interfacesTab.click();
      try {
        const tabResponse = await tabResponsePromise;
        await page.waitForSelector(
          '.inspector [data-universal-relation-form] '
          + '[data-universal-relation-form-field="name"]',
          { state: "visible", timeout: 20000 },
        );
        checks["inspector-tabs-operational"] = tabResponse.status() === 200;
        details.inspectorTab = {
          status: tabResponse.status(),
          control,
        };
      } catch (error) {
        details.inspectorTabError = String(error.message || error);
      }
    }

    const interfaceForm = page.locator(
      ".inspector [data-universal-relation-form]"
    ).filter({ has: page.locator(
      '[data-universal-relation-form-field="name"]'
    ) }).first();
    if (await interfaceForm.count()) {
      const name = interfaceForm.locator(
        '[data-universal-relation-form-field="name"]');
      const presentation = interfaceForm.locator(
        '[data-universal-relation-form-field="presentation"]');
      const contract = interfaceForm.locator(
        '[data-universal-relation-form-field="contract"]');
      const submit = interfaceForm.locator(
        '[data-universal-relation-form-submit]');
      const control = await submit.getAttribute("data-universal-control");
      const outputsBefore = await page.locator(
        '.canvas [data-universal-output][data-universal-interface]'
      ).count();
      const interfaceResponsePromise = page.waitForResponse(response => {
        if (new URL(response.url()).pathname !== "/api/universal/interaction"
            || response.request().method() !== "POST") return false;
        try {
          return response.request().postDataJSON()?.control === control;
        } catch (_) {
          return false;
        }
      }, { timeout: 30000 });
      await name.fill("Result");
      await presentation.selectOption({ label: "Output" });
      await contract.selectOption({ label: "Universal Cell" });
      await name.press("Enter");
      try {
        const interfaceResponse = await interfaceResponsePromise;
        await waitFor(page, before => document.querySelectorAll(
          '.canvas [data-universal-output][data-universal-interface]'
        ).length > before, outputsBefore, 20000);
        const outputsAfter = await page.locator(
          '.canvas [data-universal-output][data-universal-interface]'
        ).count();
        checks["visual-interface-creation"] = interfaceResponse.status() === 200
          && outputsAfter > outputsBefore;
        details.interfaceCreation = {
          status: interfaceResponse.status(),
          before: outputsBefore,
          after: outputsAfter,
        };
      } catch (error) {
        details.interfaceCreationError = String(error.message || error);
      }
    }

    const nodesBeforeTargetPlacement = await page.locator(
      ".canvas [data-universal-root]"
    ).count();
    if (await placement.count()) {
      const placementControl = await placement.getAttribute(
        "data-universal-interaction-control");
      const targetPlacementResponsePromise = page.waitForResponse(response => {
        if (new URL(response.url()).pathname !== "/api/universal/interaction"
            || response.request().method() !== "POST") return false;
        try {
          return response.request().postDataJSON()?.control === placementControl;
        } catch (_) {
          return false;
        }
      }, { timeout: 30000 });
      await placement.click();
      try {
        const targetPlacementResponse = await targetPlacementResponsePromise;
        await waitFor(page, before => document.querySelectorAll(
          ".canvas [data-universal-root]"
        ).length > before, nodesBeforeTargetPlacement, 20000);
        details.wireTargetPlacement = {
          status: targetPlacementResponse.status(),
          before: nodesBeforeTargetPlacement,
          after: await page.locator(
            ".canvas [data-universal-root]"
          ).count(),
        };
      } catch (error) {
        details.wireTargetPlacementError = String(error.message || error);
      }
    }

    if (await interfaceForm.count()) {
      const name = interfaceForm.locator(
        '[data-universal-relation-form-field="name"]');
      const presentation = interfaceForm.locator(
        '[data-universal-relation-form-field="presentation"]');
      const contract = interfaceForm.locator(
        '[data-universal-relation-form-field="contract"]');
      const submit = interfaceForm.locator(
        '[data-universal-relation-form-submit]');
      const control = await submit.getAttribute("data-universal-control");
      const inputsBefore = await page.locator(
        '.canvas [data-universal-input][data-universal-interface]'
      ).count();
      const inputResponsePromise = page.waitForResponse(response => {
        if (new URL(response.url()).pathname !== "/api/universal/interaction"
            || response.request().method() !== "POST") return false;
        try {
          return response.request().postDataJSON()?.control === control;
        } catch (_) {
          return false;
        }
      }, { timeout: 30000 });
      await name.fill("Input");
      await presentation.selectOption({ label: "Input" });
      await contract.selectOption({ label: "Universal Cell" });
      await name.press("Enter");
      try {
        const inputResponse = await inputResponsePromise;
        await waitFor(page, before => document.querySelectorAll(
          '.canvas [data-universal-input][data-universal-interface]'
        ).length > before, inputsBefore, 20000);
        const inputsAfter = await page.locator(
          '.canvas [data-universal-input][data-universal-interface]'
        ).count();
        checks["visual-input-interface-creation"] = inputResponse.status() === 200
          && inputsAfter > inputsBefore;
        details.inputInterfaceCreation = {
          status: inputResponse.status(),
          before: inputsBefore,
          after: inputsAfter,
        };
      } catch (error) {
        details.inputInterfaceCreationError = String(error.message || error);
      }
    }

    details.wireSurface = await page.evaluate(() => ({
      outputs: [...document.querySelectorAll(
        '.canvas [data-universal-output][data-universal-interface]'
      )].map(socket => ({
        owner: socket.dataset.universalOutput || '',
        interface: socket.dataset.universalInterface || '',
        existingOnly: socket.dataset.existingOnly || '',
        visible: Boolean(socket.offsetWidth || socket.offsetHeight),
      })),
      inputs: [...document.querySelectorAll(
        '.canvas [data-universal-input][data-universal-interface]'
      )].map(socket => ({
        owner: socket.dataset.universalInput || '',
        interface: socket.dataset.universalInterface || '',
        existingOnly: socket.dataset.existingOnly || '',
        visible: Boolean(socket.offsetWidth || socket.offsetHeight),
      })),
    }));

    const outputs = page.locator(
      '.canvas [data-universal-output][data-universal-interface]:not([data-existing-only="true"])'
    );
    for (let index = 0; index < await outputs.count(); index += 1) {
      const output = outputs.nth(index);
      if (!await output.isVisible()) continue;
      const sourceBox = await output.boundingBox();
      if (!sourceBox) continue;
      details.wirePointer = await page.evaluate(({ x, y }) => {
        const hit = document.elementFromPoint(x, y);
        const socket = hit?.closest('[data-universal-interface]');
        return {
          ownerBefore: window.__archhubPointerOwner || null,
          hitTag: hit?.tagName || '',
          hitClass: hit?.className || '',
          hitInterface: socket?.dataset.universalInterface || '',
          hitOutput: socket?.dataset.universalOutput || '',
          hitInput: socket?.dataset.universalInput || '',
        };
      }, {
        x: sourceBox.x + sourceBox.width / 2,
        y: sourceBox.y + sourceBox.height / 2,
      });
      await page.mouse.move(
        sourceBox.x + sourceBox.width / 2,
        sourceBox.y + sourceBox.height / 2,
      );
      await page.mouse.down();
      details.wirePointer.ownerAfter = await page.evaluate(
        () => window.__archhubPointerOwner || null
      );
      const candidates = page.locator(
        '.canvas [data-universal-input].wire-target-ready:not([data-existing-only="true"])'
      );
      details.wireCandidateCount = await candidates.count();
      let target = null;
      for (let candidate = 0; candidate < await candidates.count(); candidate += 1) {
        const item = candidates.nth(candidate);
        if (await item.isVisible()) {
          target = item;
          break;
        }
      }
      if (!target) {
        await page.mouse.up();
        continue;
      }
      const targetBox = await target.boundingBox();
      if (!targetBox) {
        await page.mouse.up();
        continue;
      }
      const wiresBefore = await page.locator(
        ".canvas .wire-hit[data-universal-relation]"
      ).count();
      const wireResponsePromise = page.waitForResponse(response => (
        new URL(response.url()).pathname === "/api/universal/interaction"
          && response.request().method() === "POST"
      ), { timeout: 30000 });
      await page.mouse.move(
        targetBox.x + targetBox.width / 2,
        targetBox.y + targetBox.height / 2,
        { steps: 8 },
      );
      await page.mouse.up();
      try {
        const wireResponse = await wireResponsePromise;
        let wirePayload = {};
        try { wirePayload = await wireResponse.json(); } catch (_) {}
        details.wireCreation = {
          status: wireResponse.status(),
          before: wiresBefore,
          projectionMode: wirePayload.projection_mode || "",
          connectionCount: wirePayload.connection_count ?? null,
          createdRoot: wirePayload.created_root || "",
          topologyRecovery: wirePayload.topology_recovery === true,
          patch: wirePayload.topology_patch ? {
            upsertNodes: wirePayload.topology_patch.upsert_nodes?.length ?? null,
            upsertWires: wirePayload.topology_patch.upsert_wires?.length ?? null,
            removeNodes: wirePayload.topology_patch.remove_nodes?.length ?? null,
            removeWires: wirePayload.topology_patch.remove_wires?.length ?? null,
            wireOrder: wirePayload.topology_patch.wire_order?.length ?? null,
          } : null,
        };
        await waitFor(page, before => document.querySelectorAll(
          ".canvas .wire-hit[data-universal-relation]"
        ).length > before, wiresBefore, 20000);
        const wiresAfter = await page.locator(
          ".canvas .wire-hit[data-universal-relation]"
        ).count();
        checks["socket-wire-creation"] = wireResponse.status() === 200
          && wiresAfter > wiresBefore;
        details.wireCreation.after = wiresAfter;
      } catch (error) {
        details.wireCreationError = String(error.message || error);
        details.wireAfterRelease = await page.evaluate(() => ({
          owner: window.__archhubPointerOwner || null,
          wireCount: document.querySelectorAll(
            ".canvas .wire-hit[data-universal-relation]"
          ).length,
          candidates: document.querySelectorAll(
            ".canvas .wire-target-ready"
          ).length,
          previews: document.querySelectorAll(
            ".canvas .universal-wire-preview"
          ).length,
          status: document.querySelector(".status-message")?.textContent || "",
        }));
      }
      break;
    }
    const screenshot = await recordScreenshot(page, "graph-editor-desktop");
    if (screenshot) details.screenshots.push(screenshot);
  } finally {
    await Promise.allSettled(failedResponseReads);
    await Promise.allSettled(receiptResponseReads);
    const successfulMutationLatencies = details.universalResponseLatencies
      .filter(item => item.status >= 200 && item.status < 300);
    const mutationLatencyViolations = successfulMutationLatencies
      .filter(item => item.durationMs > 100);
    details.performanceBudgets = {
      mutationAcknowledgementMs: 100,
      scopeEntryMs: 150,
      successfulMutationCount: successfulMutationLatencies.length,
      maximumMutationAcknowledgementMs: successfulMutationLatencies.length
        ? Math.max(...successfulMutationLatencies.map(item => item.durationMs))
        : null,
      mutationLatencyViolations,
      scopeEntryMeasuredMs: details.scopeResponse?.renderedMs ?? null,
    };
    checks["mutation-acknowledgements-within-budget"] = (
      successfulMutationLatencies.length > 0
      && mutationLatencyViolations.length === 0
    );
    checks["scope-entry-within-budget"] = (
      Number.isFinite(details.scopeResponse?.renderedMs)
      && details.scopeResponse.renderedMs <= 150
    );
    checks["no-failed-governed-responses"] =
      details.failedResponses.length === 0;
    checks["no-console-or-page-errors"] = messages.length === 0;
    await browser.close();
  }
  process.stdout.write(JSON.stringify({ checks, details }));
})().catch(error => {
  process.stderr.write(error.stack || String(error));
  process.exit(1);
});
