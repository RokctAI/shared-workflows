// Copyright 2026 ROKCT INTELLIGENCE (PTY) LTD
// Prints the CORTEX portfolio's A4 page (/portfolio/print, hosting_sdk 1.27.0)
// to a PDF once the deployed site serves the wanted version.
// Usage: node render_pdf.mjs <site-url> <version> <out.pdf>
import { chromium } from "playwright";

const [site, version, out] = process.argv.slice(2);
const url = `${site.replace(/\/$/, "")}/portfolio/print`;
const browser = await chromium.launch();
const page = await browser.newPage();
let ok = false;
// The snapshot PR auto-merges and Vercel redeploys; wait up to 40 minutes.
for (let i = 0; i < 40 && !ok; i++) {
  try {
    await page.goto(`${url}?v=${Date.now()}`, { waitUntil: "networkidle", timeout: 60000 });
    ok = (await page.locator(`[data-portfolio-version="${version}"]`).count()) > 0;
  } catch {}
  if (!ok) await new Promise((r) => setTimeout(r, 60000));
}
if (!ok) {
  console.error(`::error::${url} never served version ${version}; no PDF made`);
  process.exit(1);
}
await page.emulateMedia({ media: "print" });
await page.pdf({ path: out, format: "A4", printBackground: true, preferCSSPageSize: true });
await browser.close();
console.log(`wrote ${out}`);
