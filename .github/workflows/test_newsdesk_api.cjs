// Tests for functions/api/newsdesk.js — the editor's auto-publish queue.
// Run: node scraper/test_newsdesk_api.cjs
//
// The line that must hold: no token, no access — to submit, to list, or to
// drain. And a queued record must be pipeline-shaped, so publish-pending-manual
// can merge it with no special-casing.

const fs = require("fs");
const path = require("path");
const os = require("os");

const REPO = path.resolve(__dirname, "..");
const failures = [];
const ok = (c, l) => { console.log((c ? "  ok   " : "  FAIL ") + l); if (!c) failures.push(l); };

function load(rel) {
  let src = fs.readFileSync(path.join(REPO, rel), "utf8")
    .replace(/export async function onRequestGet/, "async function onRequestGet")
    .replace(/export async function onRequestPost/, "async function onRequestPost");
  const file = path.join(os.tmpdir(), `fn_${Math.random().toString(36).slice(2)}.cjs`);
  fs.writeFileSync(file, src + "\nmodule.exports={onRequestGet,onRequestPost};");
  const mod = require(file); fs.unlinkSync(file); return mod;
}
const fn = load("functions/api/newsdesk.js");

// Minimal KV + request stubs.
function makeKV(initial) {
  const store = new Map(Object.entries(initial || {}));
  return {
    store,
    async get(key, opts) { const v = store.get(key); return v == null ? null : (opts && opts.type === "json" ? JSON.parse(v) : v); },
    async put(key, val) { store.set(key, val); },
  };
}
function req(body, token) {
  return {
    url: "https://rochdaledaily.co.uk/api/newsdesk" + (body === null ? "?queue=pending" : ""),
    headers: { get: h => (h.toLowerCase() === "x-admin-token" ? (token || "") : null) },
    json: async () => body,
  };
}
const TOKEN = "s3cret-admin-token";
const ENV = kv => ({ EVENTS_KV: kv, EVENTS_ADMIN_TOKEN: TOKEN });

const GOOD = {
  title: "Residents rally round after Kirkholt house fire",
  excerpt: "Neighbours in Kirkholt have raised hundreds of pounds for a family whose home was badly damaged by fire on Monday.",
  body: "Neighbours acted fast.:contentReference[oaicite:2]{index=2}\n\nThe family thanked everyone.",
  category: "community", area: "kirkholt",
  image_url: "assets/img/cards/police.jpg", image_credit: "Rochdale Daily",
  published_at: "2026-09-03T10:00:00+01:00",
};

(async () => {
  console.log("\nAuth is required for everything");
  let kv = makeKV();
  let r = await fn.onRequestPost({ request: req(GOOD, "wrong"), env: ENV(kv) });
  ok(r.status === 401, "submit with a wrong token is 401");
  r = await fn.onRequestGet({ request: req(null, "wrong"), env: ENV(kv) });
  ok(r.status === 401, "listing the queue with a wrong token is 401");
  r = await fn.onRequestPost({ request: req(GOOD, ""), env: ENV(kv) });
  ok(r.status === 401, "no token at all is 401");
  ok(kv.store.size === 0, "nothing was written on any unauthorised call");

  console.log("\nA good submission queues a pipeline-shaped record");
  kv = makeKV();
  r = await fn.onRequestPost({ request: req(GOOD, TOKEN), env: ENV(kv) });
  ok(r.status === 201, "authorised submit returns 201");
  const pending = JSON.parse(kv.store.get("newsdesk:pending"));
  ok(pending.length === 1, "one item queued");
  const rec = pending[0].article;
  ok(rec.slug === "residents-rally-round-after-kirkholt-house-fire", "slug derived from the headline");
  ok(rec.id === rec.slug, "id matches slug");
  ok(rec.manual_article === true && rec.editorial_lock === true, "manual + lock flags set");
  ok(rec.image_url === "assets/img/cards/police.jpg" && rec.img === rec.image_url, "image carried to both fields");
  ok(rec.image_status === "editorial-photo", "image marked as the editor's photo");
  ok(!/contentReference|oaicite/.test(rec.body), "citation markers stripped server-side too");
  ok(rec.category === "community" && rec.area === "kirkholt", "category and ward area carried");
  ok(rec.right_to_reply && !rec.right_to_reply.toLowerCase().startsWith("right to reply"), "right-to-reply has no dup label");

  console.log("\nValidation refuses incomplete or unsafe records");
  kv = makeKV();
  for (const [patch, label] of [
    [{ title: "" }, "no headline"],
    [{ body: "" }, "no body"],
    [{ image_url: "" }, "no image"],
    [{ category: "gossip" }, "unknown category"],
  ]) {
    const r2 = await fn.onRequestPost({ request: req({ ...GOOD, ...patch }, TOKEN), env: ENV(kv) });
    ok(r2.status === 400, `${label} is rejected 400`);
  }
  ok(kv.store.size === 0, "no invalid record reached the queue");

  console.log("\nDuplicate slug is refused");
  kv = makeKV();
  await fn.onRequestPost({ request: req(GOOD, TOKEN), env: ENV(kv) });
  r = await fn.onRequestPost({ request: req(GOOD, TOKEN), env: ENV(kv) });
  ok(r.status === 409, "the same slug queued twice is 409");
  ok(JSON.parse(kv.store.get("newsdesk:pending")).length === 1, "still only one queued");

  console.log("\nList and drain (the workflow's side)");
  kv = makeKV();
  await fn.onRequestPost({ request: req(GOOD, TOKEN), env: ENV(kv) });
  await fn.onRequestPost({ request: req({ ...GOOD, title: "Second Kirkholt story about the fund", slug: "" }, TOKEN), env: ENV(kv) });
  const list = await fn.onRequestGet({ request: req(null, TOKEN), env: ENV(kv) });
  const listed = JSON.parse(await readBody(list));
  ok(listed.count === 2, "queue lists both items to the admin");
  const ids = listed.pending.map(p => p.id);
  r = await fn.onRequestPost({ request: req({ action: "drain", ids: [ids[0]] }, TOKEN), env: ENV(kv) });
  const drained = JSON.parse(await readBody(r));
  ok(drained.drained === 1 && drained.remaining === 1, "draining one leaves one");
  r = await fn.onRequestPost({ request: req({ action: "drain", ids: [] }, TOKEN), env: ENV(kv) });
  ok(r.status === 400, "a drain with no ids is refused");

  console.log("\nNot-configured is handled");
  r = await fn.onRequestPost({ request: req(GOOD, TOKEN), env: { EVENTS_ADMIN_TOKEN: TOKEN } });
  ok(r.status === 503, "missing KV binding returns 503, not a crash");

  console.log("");
  if (failures.length) { console.log(`${failures.length} FAILED`); process.exit(1); }
  console.log("all newsdesk API tests passed");
})().catch(e => { console.error(e); process.exit(1); });

// The Response bodies are real Response objects; read them uniformly.
async function readBody(resp) { return await resp.text(); }
