// Announce a live site's pages to IndexNow (Bing, Yandex, Seznam, Naver; AI
// search that reads Bing). Reads the site's public key from /indexnow-key.txt
// (base_sdk >= 1.68.0) and its URLs from /sitemap.xml. Never fails the job:
// a site without the key file is skipped. Usage: SITE_URL=https://x node indexnow.mjs
const site = (process.env.SITE_URL || "").replace(/\/+$/, "");
if (!site) { console.log("indexnow: no SITE_URL, skipped"); process.exit(0); }
const host = new URL(site).host;
async function text(u) { try { const r = await fetch(u, { redirect: "follow" }); return r.ok ? await r.text() : null; } catch { return null; } }
const key = ((await text(`${site}/indexnow-key.txt`)) || "").trim();
if (!/^[0-9a-f]{32}$/.test(key)) { console.log(`indexnow: ${site} has no key file yet, skipped`); process.exit(0); }
const xml = (await text(`${site}/sitemap.xml`)) || "";
let urls = [...xml.matchAll(/<loc>\s*([^<\s]+)\s*<\/loc>/g)].map((m) => m[1]).filter((u) => { try { return new URL(u).host === host; } catch { return false; } });
if (urls.length === 0) urls = [`${site}/`];
urls = [...new Set(urls)].slice(0, 10000);
try {
  const r = await fetch("https://api.indexnow.org/indexnow", {
    method: "POST",
    headers: { "content-type": "application/json; charset=utf-8" },
    body: JSON.stringify({ host, key, keyLocation: `${site}/indexnow-key.txt`, urlList: urls }),
  });
  console.log(`indexnow: ${site}: sent ${urls.length} URL(s), HTTP ${r.status}`);
} catch (e) {
  console.log(`indexnow: ${site}: not sent (${e.message})`);
}
