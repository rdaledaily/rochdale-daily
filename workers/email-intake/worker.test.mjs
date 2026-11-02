// node workers/email-intake/worker.test.mjs
import assert from "node:assert/strict";
import worker from "./worker.js";

const raw = new TextEncoder().encode("From: a@b.example\r\nSubject: Test\r\n\r\nHello\r\n");

function harness({ kvFails = false, dispatchStatus = 204, noForwardTo = false } = {}) {
  const log = [];
  const kv = new Map();
  const env = {
    FORWARD_TO: noForwardTo ? "" : "desk@example.com",
    GITHUB_TOKEN: "tok",
    EVENTS_KV: { put: async (k, v, o) => { log.push("kv"); if (kvFails) throw new Error("kv down"); kv.set(k, { v: new Uint8Array(v), o }); } },
    fetch: async (url, init) => { log.push("dispatch"); log.dispatch = { url, init }; return new Response(null, { status: dispatchStatus }); },
  };
  const message = { from: "a@b.example", raw: new Blob([raw]).stream(), forward: async (to, h) => { log.push("forward"); log.forward = { to, h }; } };
  return { env, message, log, kv };
}

let passed = 0;
const test = async (name, fn) => { await fn(); passed += 1; console.log("ok -", name); };

await test("forwards first, unmodified, then stores raw bytes privately, then dispatches", async () => {
  const h = harness();
  const r = await worker.email(h.message, h.env);
  assert.deepEqual([...h.log], ["forward", "kv", "dispatch"]);
  assert.equal(h.log.forward.to, "desk@example.com");
  assert.equal(h.log.forward.h, undefined);
  const [[key, { v, o }]] = [...h.kv];
  assert.match(key, /^inbox:raw:\d{8}T\d{6}Z-[0-9a-f-]{36}$/);
  assert.deepEqual(v, raw);
  assert.equal(o.expirationTtl, 30 * 24 * 3600);
  assert.equal(h.log.dispatch.url, "https://api.github.com/repos/rdaledaily/rochdale-daily/dispatches");
  assert.deepEqual(JSON.parse(h.log.dispatch.init.body), { event_type: "email-received", client_payload: { key } });
  assert.equal(h.log.dispatch.init.headers.Authorization, "Bearer tok");
  assert.deepEqual(r, { stored: true, key, dispatched: true });
});

await test("KV down: still forwarded, no dispatch, shortfall returned", async () => {
  const h = harness({ kvFails: true });
  const r = await worker.email(h.message, h.env);
  assert.deepEqual([...h.log], ["forward", "kv"]);
  assert.deepEqual(r, { stored: false });
});

await test("dispatch rejected: stored and forwarded; sweep will collect it", async () => {
  const h = harness({ dispatchStatus: 401 });
  const r = await worker.email(h.message, h.env);
  assert.equal(r.stored, true);
  assert.equal(r.dispatched, false);
});

await test("no FORWARD_TO: still stored and dispatched (and logged loudly)", async () => {
  const h = harness({ noForwardTo: true });
  const r = await worker.email(h.message, h.env);
  assert.deepEqual([...h.log], ["kv", "dispatch"]);
  assert.equal(r.stored, true);
});

console.log(`\n${passed} passed`);
