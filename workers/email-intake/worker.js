// Rochdale Daily — email intake Worker.
//
// Bound to the news@rochdaledaily.co.uk Email Routing rule ("Send to a
// Worker"). Paste this file into the Cloudflare dashboard editor as-is.
//
// For every message it does three cheap things, in this order:
//   1. forwards it to the newsdesk Gmail, unmodified, exactly as today;
//   2. stores the raw message in the PRIVATE EVENTS_KV store
//      (key inbox:raw:<stamp>-<uuid>, kept 30 days);
//   3. pings GitHub (repository_dispatch "email-received") so the
//      email-intake workflow parses it and commits it to the repo straight
//      away. If the ping fails, the workflow's 20-minute sweep still finds it.
//
// No parsing happens here. Measured on a real 700KB press release, parsing in
// the Worker cost 75ms CPU on a cold start; Cloudflare's free plan allows
// 10ms. Storing bytes and making two requests costs a fraction of that.
// Raw messages never enter the public repo: the workflow commits only the
// parsed text, attachments and photos, with sender addresses hashed.
//
// Settings (Worker → Settings → Bindings / Variables and Secrets):
//   EVENTS_KV     KV binding  the same namespace the website's Pages project uses
//   FORWARD_TO    text        the verified Gmail address mail is forwarded to
//   GITHUB_TOKEN  secret      fine-grained PAT, this repo only, Contents: read/write
//   GITHUB_REPO   text        optional, default "rdaledaily/rochdale-daily"

const DEFAULT_REPO = "rdaledaily/rochdale-daily";
const RAW_TTL_SECONDS = 30 * 24 * 3600;

export default {
  async email(message, env) {
    const raw = await new Response(message.raw).arrayBuffer();

    // 1. Gmail first: nothing below can stop the newsdesk getting the email.
    if (env.FORWARD_TO) await message.forward(env.FORWARD_TO);
    else console.error("FORWARD_TO is not set — message was NOT forwarded to Gmail");

    // 2. Keep the raw bytes privately for the repo intake.
    const stamp = new Date().toISOString().replace(/[-:]/g, "").replace(/\.\d+Z$/, "Z");
    const key = `inbox:raw:${stamp}-${crypto.randomUUID()}`;
    try {
      await env.EVENTS_KV.put(key, raw, { expirationTtl: RAW_TTL_SECONDS, metadata: { bytes: raw.byteLength } });
    } catch (error) {
      console.error("intake shortfall: raw message not stored:", String((error && error.message) || error));
      return { stored: false };
    }

    // 3. Wake the workflow now rather than at the next sweep.
    try {
      const res = await (env.fetch || fetch)(`https://api.github.com/repos/${env.GITHUB_REPO || DEFAULT_REPO}/dispatches`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${env.GITHUB_TOKEN}`,
          Accept: "application/vnd.github+json",
          "Content-Type": "application/json",
          "User-Agent": "rochdale-daily-email-intake",
          "X-GitHub-Api-Version": "2022-11-28",
        },
        body: JSON.stringify({ event_type: "email-received", client_payload: { key } }),
      });
      if (!res.ok) console.error(`dispatch -> ${res.status}; the 20-minute sweep will pick up ${key}`);
      return { stored: true, key, dispatched: res.ok };
    } catch (error) {
      console.error("dispatch failed; the 20-minute sweep will pick up", key, String((error && error.message) || error));
      return { stored: true, key, dispatched: false };
    }
  },
};
