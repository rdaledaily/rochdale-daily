// Proves that a poisoned story record cannot inject HTML into the homepage.
// Run: node scraper/jsdom-tests/homepage_xss.test.js  (needs jsdom installed)
const fs = require("fs");
const path = require("path");
const { JSDOM } = require(process.env.JSDOM_PATH || "jsdom");

const html = fs.readFileSync(path.join(__dirname, "..", "..", "index.html"), "utf8");
const EVIL = '<img src=x onerror="window.__pwned=1">';
// Start from a real, currently-published record so every client-side filter
// (locality evidence, recency, source denylist) lets it through; then poison
// every display field.
const feed = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "..", "articles", "frontpage.json"), "utf8"));
const base = (Array.isArray(feed) ? feed : feed.articles).find(a => a.slug && a.title) || {};
const poisoned = [Object.assign({}, base, {
  slug: base.slug, title: base.title + " " + EVIL, excerpt: "Summary " + EVIL, summary: "Summary " + EVIL,
  body: ["Para one Rochdale " + EVIL], byline: "By " + EVIL, source_name: (base.source_name || "") + EVIL,
  image_credit: EVIL, kicker: EVIL, published_at: new Date().toISOString(), first_published_at: new Date().toISOString(),
  image_url: 'assets/img/cards/x.jpg" onerror="window.__pwned=1',
})];

const dom = new JSDOM(html, {
  url: "https://rochdaledaily.co.uk/",
  runScripts: "dangerously",
  pretendToBeVisual: true,
  beforeParse(window) {
    window.fetch = async (url) => {
      const u = String(url);
      const ok = (body) => ({ ok: true, status: 200, json: async () => body, text: async () => JSON.stringify(body), headers: { get: () => "application/json" } });
      if (u.includes("articles.json") || u.includes("frontpage.json")) return ok(poisoned);
      return { ok: false, status: 404, json: async () => ({}), text: async () => "", headers: { get: () => "" } };
    };
    window.matchMedia = () => ({ matches: false, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {} });
    window.scrollTo = () => {};
    window.IntersectionObserver = class { observe() {} unobserve() {} disconnect() {} };
    window.requestIdleCallback = (cb) => setTimeout(cb, 0);
  },
});

setTimeout(() => {
  const doc = dom.window.document;
  const injected = doc.querySelectorAll('img[onerror*="__pwned"]').length;
  const text = doc.body.innerHTML;
  const rendered = text.includes(base.slug);
  console.log("story rendered:", rendered, "| injected onerror elements:", injected, "| pwned flag:", dom.window.__pwned || 0);
  if (!rendered) { console.log("FAIL: story not rendered, test inconclusive"); process.exit(2); }
  if (injected > 0 || dom.window.__pwned) { console.log("FAIL: HTML injection reached the DOM"); process.exit(1); }
  console.log("PASS: poisoned fields rendered as text");
  process.exit(0);
}, 1500);
