// Copyright 2026 ROKCT INTELLIGENCE (PTY) LTD
//
// Live-site health check for the weekly site refresh. The same gate the
// shells' site-shots.yml applies to a freshly built site (HTTP 200, no
// console errors, a <main> landmark, a hero heading in the first screen, a
// page that is not blank), plus broken images, pointed at the DEPLOYED site
// in a real Chromium at 1440 and 390 wide in the light and dark themes.
// Nothing is published; it only reports.
//
// Env: HEALTH_URL (the live page), HEALTH_OUT (output dir), HEALTH_TOOLS (dir
// whose node_modules holds playwright and sharp), HEALTH_CONSOLE_ALLOW
// (optional regex of console errors to tolerate).
// Writes HEALTH_OUT/health.json and one PNG per view; exits 1 when unhealthy,
// 2 when the check itself could not run.
import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";

const req = createRequire(path.join(process.env.HEALTH_TOOLS || process.cwd(), "package.json"));
const { chromium } = req("playwright");
let sharp = null;
try {
  sharp = req("sharp");
} catch {
  /* contrast check is skipped without sharp */
}

const URL_ = process.env.HEALTH_URL;
const OUT = process.env.HEALTH_OUT || "health";
const ALLOW = process.env.HEALTH_CONSOLE_ALLOW ? new RegExp(process.env.HEALTH_CONSOLE_ALLOW) : null;
if (!URL_ || !/^https?:\/\//.test(URL_)) {
  console.error(`HEALTH_URL must be an http(s) URL, got '${URL_ || ""}'`);
  process.exit(2);
}
fs.mkdirSync(OUT, { recursive: true });

const VIEWS = [
  { key: "desktop", viewport: { width: 1440, height: 1000 }, dpr: 1 },
  { key: "phone", viewport: { width: 390, height: 800 }, dpr: 2 },
];
const THEMES = ["light", "dark"];
const problems = [];
const report = { url: URL_, checked_at: new Date().toISOString(), checks: [] };

const browser = await chromium.launch();
try {
  for (const view of VIEWS) {
    for (const theme of THEMES) {
      const label = `${view.key}-${theme}`;
      const ctx = await browser.newContext({
        viewport: view.viewport,
        deviceScaleFactor: view.dpr,
        colorScheme: theme,
      });
      await ctx.addInitScript((t) => {
        try {
          localStorage.setItem("theme", t);
        } catch {}
      }, theme);
      const page = await ctx.newPage();
      const errors = [];
      const badImages = new Set();
      const badResponses = new Set();
      page.on("console", (m) => {
        if (m.type() === "error" && !(ALLOW && ALLOW.test(m.text()))) errors.push(m.text());
      });
      page.on("pageerror", (e) => errors.push(`pageerror: ${e.message}`));
      page.on("response", (r) => {
        if (r.status() < 400) return;
        if (r.request().resourceType() === "image") badImages.add(`${r.status()} ${r.url()}`);
        else badResponses.add(`${r.status()} ${r.url()}`);
      });
      page.on("requestfailed", (r) => {
        const why = (r.failure() && r.failure().errorText) || "failed";
        if (r.resourceType() === "image" && !/ERR_ABORTED/.test(why)) badImages.add(`${why} ${r.url()}`);
      });

      let status = 0;
      let navError = "";
      try {
        const res = await page.goto(URL_, { waitUntil: "load", timeout: 90000 });
        status = res ? res.status() : 0;
        await page.waitForLoadState("networkidle", { timeout: 20000 }).catch(() => {});
        await page.waitForTimeout(1500);
      } catch (e) {
        navError = String(e.message || e).split("\n")[0];
      }

      let dom = { main: false, hero: false, heroText: "", textLength: 0, broken: [] };
      let stdev = -1;
      if (!navError) {
        dom = await page.evaluate(() => {
          const main = document.querySelector("main, [role=main]");
          const h1 = document.querySelector("h1");
          const r = h1 && h1.getBoundingClientRect();
          // An <img> that finished loading with no pixels is broken (lazy ones
          // that never started are not counted).
          const broken = [...document.images]
            .filter((i) => i.complete && i.naturalWidth === 0 && (i.currentSrc || i.src))
            .map((i) => i.currentSrc || i.src);
          return {
            main: !!main && main.getBoundingClientRect().height > 0,
            hero: !!r && r.height > 0 && r.top < window.innerHeight && (h1.textContent || "").trim().length > 0,
            heroText: h1 ? (h1.textContent || "").trim().slice(0, 80) : "",
            textLength: (document.body.innerText || "").trim().length,
            broken,
          };
        });
        for (const b of dom.broken) badImages.add(`not rendered ${b}`);
        const png = await page.screenshot({ caret: "hide" });
        fs.writeFileSync(path.join(OUT, `${label}.png`), png);
        if (sharp) {
          const st = await sharp(png).stats();
          stdev = Math.round((st.channels.slice(0, 3).reduce((s, c) => s + c.stdev, 0) / 3) * 10) / 10;
        }
      }

      const images = [...badImages];
      const check = { label, status, navError, errors, brokenImages: images, failedRequests: [...badResponses], main: dom.main, hero: dom.hero, heroText: dom.heroText, textLength: dom.textLength, stdev };
      report.checks.push(check);
      if (navError) problems.push(`${label}: could not load the page (${navError})`);
      else {
        if (status !== 200) problems.push(`${label}: HTTP ${status}`);
        if (errors.length) {
          const short = errors.slice(0, 3).map((e) => e.split("\n")[0].slice(0, 160));
          const where = [...badResponses].slice(0, 3);
          problems.push(`${label}: ${errors.length} console error(s): ${short.join(" | ")}${where.length ? ` (failed requests: ${where.join(", ")})` : ""}`);
        }
        if (images.length) problems.push(`${label}: ${images.length} broken image(s): ${images.slice(0, 3).join(" | ")}`);
        if (!dom.main) problems.push(`${label}: no main landmark`);
        if (!dom.hero) problems.push(`${label}: no hero heading in the first screen`);
        if (dom.textLength < 80 || (stdev >= 0 && stdev < 8)) problems.push(`${label}: the page looks blank (text ${dom.textLength}, contrast ${stdev})`);
      }
      await ctx.close();
    }
  }
} finally {
  await browser.close();
}

report.problems = problems;
report.healthy = problems.length === 0;
fs.writeFileSync(path.join(OUT, "health.json"), JSON.stringify(report, null, 2) + "\n");
for (const c of report.checks) console.log(JSON.stringify(c));
if (problems.length) {
  for (const p of problems) console.log(`::warning::${p}`);
  process.exit(1);
}
console.log(`Healthy: ${URL_}`);
