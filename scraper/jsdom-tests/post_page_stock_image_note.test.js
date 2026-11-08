// The client-rendered article page (post.html + post-page.js) shows the same
// visible image qualification as the Python generator (image_hierarchy.
// visible_image_note): the stock police photo says "Stock image: police. Not a
// photograph of this event." beside the credit, not only in alt text.
// Run: node scraper/jsdom-tests/post_page_stock_image_note.test.js  (needs jsdom)
const fs = require("fs");
const path = require("path");
const { JSDOM } = require(process.env.JSDOM_PATH || "jsdom");

const root = path.join(__dirname, "..", "..");
const html = fs.readFileSync(path.join(root, "post.html"), "utf8")
  .replace(/<script[^>]*src="\/assets\/js\/post-page\.js"[^>]*><\/script>/, "");
const script = fs.readFileSync(path.join(root, "assets", "js", "post-page.js"), "utf8");

const now = new Date().toISOString();
const base = {
  id: "t1", slug: "stock-police-test", title: "Woman dies at Tesco in Rochdale", excerpt: "A woman has died.",
  content_html: "<p>Greater Manchester Police confirmed the death.</p>", category: "news", area: "rochdale",
  published_at: now, first_published_at: now, source_urls: [], source_names: [],
  image_url: "assets/img/cards/police.jpg", image_credit: "Rochdale Daily",
};
const cases = [
  { name: "stock police photo", record: Object.assign({}, base, {
      image_status: "standard-police-image", image_alt: "Stock image: police. Not a photograph of this event." }),
    expect: "Stock image: police. Not a photograph of this event. Image: Rochdale Daily" },
  { name: "Stock alt on another status is not shown", record: Object.assign({}, base, {
      slug: "stock-police-test", image_status: "editorial-photo", image_alt: "Stock image: police. Not a photograph of this event." }),
    expect: "Image: Rochdale Daily" },
  { name: "Geograph file photo still shown", record: Object.assign({}, base, {
      image_status: "commons-photo-cached", image_backfill_method: "geograph", image_credit: "A N Other / Geograph (CC BY-SA 2.0)",
      image_alt: "File image: Yorkshire Street. Not a photograph of this event." }),
    expect: "File image: Yorkshire Street. Not a photograph of this event. Image: A N Other / Geograph (CC BY-SA 2.0)" },
];

function run(c) {
  return new Promise((resolve) => {
    const dom = new JSDOM(html, {
      url: "https://rochdaledaily.co.uk/post.html?slug=stock-police-test",
      runScripts: "dangerously",
      pretendToBeVisual: true,
      beforeParse(window) {
        window.fetch = async (url) => {
          const ok = (body) => ({ ok: true, status: 200, json: async () => body, text: async () => JSON.stringify(body), headers: { get: () => "application/json" } });
          if (String(url).includes("articles.json")) return ok([c.record]);
          return { ok: false, status: 404, json: async () => ({}), text: async () => "", headers: { get: () => "" } };
        };
        window.matchMedia = () => ({ matches: false, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {} });
        window.scrollTo = () => {};
        window.IntersectionObserver = class { observe() {} unobserve() {} disconnect() {} };
      },
    });
    const el = dom.window.document.createElement("script");
    el.textContent = script;
    dom.window.document.body.appendChild(el);
    dom.window.document.dispatchEvent(new dom.window.Event("DOMContentLoaded"));
    setTimeout(() => {
      const caption = dom.window.document.querySelector("#article-image-caption");
      resolve(caption ? caption.textContent.trim() : "(no caption element)");
    }, 400);
  });
}

(async () => {
  let failed = 0;
  for (const c of cases) {
    const got = await run(c);
    const pass = got === c.expect;
    if (!pass) failed += 1;
    console.log(`${pass ? "PASS" : "FAIL"} ${c.name}: ${JSON.stringify(got)}`);
  }
  if (failed) { process.exitCode = 1; return; }
  console.log("Post page image note checks passed.");
})();
