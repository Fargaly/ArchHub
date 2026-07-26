"use strict";

const fs = require("fs");
const { chromium } = require("playwright");

function hexRgb(value) {
  const match = /^#([0-9a-f]{6})$/i.exec(value || "");
  if (!match) return null;
  const raw = match[1];
  return [0, 2, 4].map(index => parseInt(raw.slice(index, index + 2), 16));
}

function luminance(rgb) {
  const values = rgb.map(value => {
    const channel = value / 255;
    return channel <= 0.04045 ? channel / 12.92
      : Math.pow((channel + 0.055) / 1.055, 2.4);
  });
  return 0.2126 * values[0] + 0.7152 * values[1] + 0.0722 * values[2];
}

function contrast(first, second) {
  const a = hexRgb(first);
  const b = hexRgb(second);
  if (!a || !b) return 0;
  const high = Math.max(luminance(a), luminance(b));
  const low = Math.min(luminance(a), luminance(b));
  return (high + 0.05) / (low + 0.05);
}

(async () => {
  const url = process.env.ARCHHUB_COURT_URL;
  const session = process.env.ARCHHUB_COURT_SESSION;
  const expectedTheme = JSON.parse(process.env.ARCHHUB_COURT_THEME || "{}");
  if (!url || !session || !Object.keys(expectedTheme).length) {
    throw new Error("browser court environment is incomplete");
  }
  const configuredChrome = process.env.ARCHHUB_CHROME_EXECUTABLE;
  const defaultChrome = "C:/Program Files/Google/Chrome/Application/chrome.exe";
  const launch = { headless: true };
  if (configuredChrome) launch.executablePath = configuredChrome;
  else if (fs.existsSync(defaultChrome)) launch.executablePath = defaultChrome;
  const browser = await chromium.launch(launch);
  const messages = [];

  async function inspect(viewport) {
    const page = await browser.newPage({ viewport });
    await page.context().addCookies([{
      name: "ArchHub-Session", value: session, url,
      httpOnly: true, sameSite: "Strict"
    }]);
    page.on("console", message => {
      if (message.type() === "error" || message.type() === "warning") {
        messages.push(`${message.type()}: ${message.text()}`);
      }
    });
    page.on("pageerror", error => messages.push(`pageerror: ${error.message}`));
    const started = Date.now();
    await page.goto(url, { waitUntil: "domcontentloaded", timeout: 30000 });
    try {
      await page.locator("[data-universal-root]").first().waitFor({
        state: "visible", timeout: 30000
      });
    } catch (error) {
      const structuralState = await page.evaluate(() => {
        const status = document.querySelector(".status-message");
        return {
          appPresent: Boolean(document.querySelector(".archhub-app")),
          rootCount: document.querySelectorAll("[data-universal-root]").length,
          statusVisible: status?.dataset.visible || "",
          statusTextLength: (status?.textContent || "").length,
        };
      });
      error.message += "\nCourt structural state: "
        + JSON.stringify(structuralState)
        + "; console/page errors: " + messages.length;
      throw error;
    }
    const interactiveMs = Date.now() - started;
    const report = await page.evaluate(({ expectedTheme }) => {
      const style = getComputedStyle(document.documentElement);
      const actualTheme = Object.fromEntries(Object.keys(expectedTheme).map(name => [
        name, style.getPropertyValue(`--${name.replaceAll("_", "-")}`).trim()
      ]));
      const controls = Array.from(document.querySelectorAll("button,input,select,textarea"))
        .filter(element => {
          const computed = getComputedStyle(element);
          const bounds = element.getBoundingClientRect();
          return computed.display !== "none" && computed.visibility !== "hidden"
            && bounds.width > 0 && bounds.height > 0;
        });
      const unnamed = controls.filter(element => {
        const label = element.getAttribute("aria-label")
          || element.getAttribute("title")
          || element.textContent?.trim()
          || Array.from(element.labels || []).map(item => item.textContent?.trim())
            .filter(Boolean).join(" ");
        return !label;
      }).map(element => ({
        tag: element.tagName,
        className: element.className,
        type: element.getAttribute("type"),
      }));
      const navigation = performance.getEntriesByType("navigation")[0];
      return {
        title: document.title,
        sessionHidden: !document.querySelector('meta[name="archhub-session"]'),
        csrfPresent: /^[A-Za-z0-9_-]{32,128}$/.test(
          document.querySelector('meta[name="archhub-csrf"]')?.content || ""),
        nodes: document.querySelectorAll("[data-universal-root]").length,
        catalogue: document.querySelectorAll("[data-universal-definition]").length,
        appVisible: document.querySelector(".archhub-app")?.getBoundingClientRect().width > 0,
        themeMatches: Object.keys(expectedTheme).every(
          name => actualTheme[name].toLowerCase() === String(expectedTheme[name]).toLowerCase()
        ),
        actualTheme,
        overflow: {
          body: document.body.scrollWidth > innerWidth,
          app: document.querySelector(".archhub-app")?.scrollWidth > innerWidth,
        },
        unnamed,
        navigation: navigation ? {
          responseEnd: Math.round(navigation.responseEnd),
          domContentLoaded: Math.round(navigation.domContentLoadedEventEnd),
          load: Math.round(navigation.loadEventEnd),
        } : null,
      };
    }, { expectedTheme });
    await page.keyboard.press("Tab");
    report.keyboardFocus = await page.evaluate(() =>
      document.activeElement !== document.body
      && document.activeElement !== document.documentElement
      && document.activeElement != null
    );
    report.interactiveMs = interactiveMs;
    await page.close();
    return report;
  }

  const desktop = await inspect({ width: 1600, height: 960 });
  const mobile = await inspect({ width: 390, height: 844 });
  await browser.close();
  const contrastRatios = {
    inkOnBackground: contrast(expectedTheme.ink, expectedTheme.bg),
    softInkOnPanel: contrast(expectedTheme.ink_soft, expectedTheme.bg_panel),
    accentOnBackground: contrast(expectedTheme.accent, expectedTheme.bg),
  };
  const checks = {
    "page-identity": desktop.title === "ArchHub" && desktop.sessionHidden
      && desktop.csrfPresent,
    "meaningful-app-visible": desktop.appVisible && desktop.nodes >= 15
      && desktop.catalogue >= 8,
    "exact-theme-applied": desktop.themeMatches && mobile.themeMatches,
    "no-console-or-page-errors": messages.length === 0,
    "desktop-no-overflow": !desktop.overflow.body && !desktop.overflow.app,
    "mobile-no-overflow": !mobile.overflow.body && !mobile.overflow.app,
    "navigation-budget": desktop.interactiveMs <= 3000
      && desktop.navigation && desktop.navigation.responseEnd <= 2000
      && desktop.navigation.load <= 3000,
    "keyboard-focus": desktop.keyboardFocus && mobile.keyboardFocus,
    "accessible-control-names": desktop.unnamed.length === 0
      && mobile.unnamed.length === 0,
    "minimum-text-contrast": contrastRatios.inkOnBackground >= 4.5
      && contrastRatios.softInkOnPanel >= 4.5
      && contrastRatios.accentOnBackground >= 4.5,
  };
  process.stdout.write(JSON.stringify({
    checks,
    details: {
      subjectDigest: process.env.ARCHHUB_COURT_SUBJECT_DIGEST || "",
      desktop,
      mobile,
      contrastRatios,
      messages,
    },
  }));
})().catch(error => {
  process.stderr.write(error.stack || String(error));
  process.exit(1);
});
