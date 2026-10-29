// Tests for workers/news-inbox/worker.js and functions/api/inbox-images.js.
// Run: node --test scraper/test_news_inbox_worker.mjs
import test from "node:test";
import assert from "node:assert/strict";
import worker, { senderDomain, storeEmail, KV_VALUE_LIMIT } from "../workers/news-inbox/worker.js";
import { onRequestGet, onRequestPost } from "../functions/api/inbox-images.js";

class FakeKV {
  constructor() { this.data = new Map(); }
  async put(key, value, opts = {}) { this.data.set(key, { value, metadata: opts.metadata, ttl: opts.expirationTtl }); }
  async get(key, opts = {}) {
    const hit = this.data.get(key);
    if (!hit) return null;
    return opts.type === "arrayBuffer" ? hit.value : hit.value;
  }
  async delete(key) { this.data.delete(key); }
  async list({ prefix }) {
    const keys = [...this.data.entries()].filter(([k]) => k.startsWith(prefix)).map(([name, v]) => ({ name, metadata: v.metadata }));
    return { keys, list_complete: true };
  }
}

const RAW = "From: Helen <helen@friedeggmedia.co.uk>\r\nSubject: Cricket\r\n\r\nbody";

function fakeMessage(raw = RAW, { rawSize, forwardFails = false, rawFails = false } = {}) {
  const calls = { forwarded: null, rejected: null };
  const bytes = new TextEncoder().encode(raw);
  return {
    calls,
    from: "bounce@friedeggmedia.co.uk",
    rawSize: rawSize ?? bytes.length,
    headers: new Headers({ subject: "Cricket", from: "Helen <helen@friedeggmedia.co.uk>" }),
    get raw() {
      if (rawFails) throw new Error("stream already read");
      return new Response(bytes).body;
    },
    async forward(to) { if (forwardFails) throw new Error("forward failed"); calls.forwarded = to; },
    setReject(reason) { calls.rejected = reason; },
  };
}

test("forwards first, then keeps the raw email", async () => {
  const kv = new FakeKV();
  const message = fakeMessage();
  await worker.email(message, { FORWARD_TO: "editor@example.com", INBOX: kv });
  assert.equal(message.calls.forwarded, "editor@example.com");
  const keys = [...kv.data.keys()];
  assert.equal(keys.length, 1);
  assert.match(keys[0], /^inbox-raw:/);
  const stored = kv.data.get(keys[0]);
  assert.equal(new TextDecoder().decode(stored.value), RAW);
  assert.equal(stored.metadata.d, "friedeggmedia.co.uk");
  assert.ok(!JSON.stringify(stored.metadata).includes("helen@"), "no personal address stored");
  assert.ok(stored.ttl > 0);
});

test("a failed store still forwards and leaves an error note", async () => {
  const kv = new FakeKV();
  const message = fakeMessage(RAW, { rawFails: true });
  await worker.email(message, { FORWARD_TO: "editor@example.com", INBOX: kv });
  assert.equal(message.calls.forwarded, "editor@example.com");
  const keys = [...kv.data.keys()];
  assert.equal(keys.length, 1);
  assert.match(keys[0], /^inbox-err:/);
  assert.match(kv.data.get(keys[0]).metadata.e, /store failed/);
});

test("missing FORWARD_TO rejects instead of swallowing the email", async () => {
  const message = fakeMessage();
  await worker.email(message, { INBOX: new FakeKV() });
  assert.ok(message.calls.rejected);
  assert.equal(message.calls.forwarded, null);
});

test("missing KV binding still forwards", async () => {
  const message = fakeMessage();
  await worker.email(message, { FORWARD_TO: "editor@example.com" });
  assert.equal(message.calls.forwarded, "editor@example.com");
});

test("a forward failure is not hidden", async () => {
  const kv = new FakeKV();
  await assert.rejects(worker.email(fakeMessage(RAW, { forwardFails: true }), { FORWARD_TO: "e@x.com", INBOX: kv }));
  assert.equal(kv.data.size, 0);
});

test("oversized email is recorded, not stored", async () => {
  const kv = new FakeKV();
  const result = await storeEmail(new Response("x").body, KV_VALUE_LIMIT + 1, { subject: "Huge", from: "a@b.org" }, kv);
  assert.equal(result.stored, false);
  assert.match([...kv.data.keys()][0], /^inbox-err:/);
});

test("senderDomain keeps only the domain", () => {
  assert.equal(senderDomain("Helen Greaney <helen@friedeggmedia.co.uk>"), "friedeggmedia.co.uk");
  assert.equal(senderDomain("press@rochdale.gov.uk"), "rochdale.gov.uk");
  assert.equal(senderDomain("nobody"), "");
});

// ------------------------------------------------------------ API ----

const TOKEN = "t0ken-abc";
const env = (kv) => ({ EVENTS_KV: kv, EVENTS_ADMIN_TOKEN: TOKEN });
const req = (url, init = {}, token = TOKEN) =>
  new Request(`https://rochdaledaily.co.uk/api/inbox-images${url}`, {
    ...init, headers: { "x-admin-token": token, "Content-Type": "application/json" },
  });

test("API refuses without the admin token", async () => {
  const kv = new FakeKV();
  assert.equal((await onRequestGet({ request: req("", {}, "wrong-token"), env: env(kv) })).status, 401);
  assert.equal((await onRequestPost({ request: req("", { method: "POST", body: "{}" }, ""), env: env(kv) })).status, 401);
});

test("API lists, serves raw bytes, and acks only its own keys", async () => {
  const kv = new FakeKV();
  await worker.email(fakeMessage(), { FORWARD_TO: "e@x.com", INBOX: kv });
  await kv.put("newsdesk:pending", "[]");
  const listing = await (await onRequestGet({ request: req(""), env: env(kv) })).json();
  assert.equal(listing.emails.length, 1);
  const key = listing.emails[0].key;
  const raw = await onRequestGet({ request: req(`?key=${encodeURIComponent(key)}`), env: env(kv) });
  assert.equal(await raw.text(), RAW);
  assert.equal((await onRequestGet({ request: req("?key=newsdesk:pending"), env: env(kv) })).status, 400);
  const acked = await (await onRequestPost({
    request: req("", { method: "POST", body: JSON.stringify({ action: "ack", keys: [key, "newsdesk:pending"] }) }),
    env: env(kv),
  })).json();
  assert.equal(acked.deleted, 1);
  assert.ok(kv.data.has("newsdesk:pending"), "never deletes other features' data");
  assert.equal(kv.data.has(key), false);
});
