/**
 * news@rochdaledaily.co.uk inbox Worker — forwards every email, keeps a copy
 * for the image saver.
 *
 * Cloudflare Email Routing hands each email to this Worker instead of a plain
 * forwarding rule. In this order, the Worker:
 *
 *   1. Forwards the email, unchanged, to FORWARD_TO (the Gmail inbox the old
 *      rule forwarded to). This happens first and on its own, so nothing in
 *      step 2 can cost the newsdesk an email.
 *   2. Stores the raw email in KV under "inbox-raw:<time>-<id>".
 *
 * No parsing happens here. The free Workers plan allows ~10 ms of CPU per
 * email, and decoding an 8 MB press release in JavaScript would exceed it.
 * Storing the bytes is I/O, not CPU. The GitHub lane email-images.yml collects
 * the stored emails through /api/inbox-images, extracts every image with
 * Python's standard email parser, commits them to assets/img/cards/ and then
 * deletes the stored email.
 *
 * If storing fails, an "inbox-err:" record is written instead, so the lane
 * reports the miss rather than nothing happening.
 *
 * Settings (Workers & Pages -> rd-news-inbox -> Settings):
 *   FORWARD_TO  variable    the Gmail address news@ forwarded to before
 *   INBOX       KV binding  the SAME namespace the site uses as EVENTS_KV
 *
 * Pasted into the Cloudflare dashboard editor; it has no imports.
 */

export const RAW_KEY_PREFIX = "inbox-raw:";
export const ERROR_KEY_PREFIX = "inbox-err:";
// Unclaimed emails expire so a long-broken lane cannot fill the namespace.
export const KEEP_SECONDS = 90 * 24 * 60 * 60;
// Cloudflare KV's largest value. Email Routing's own inbound cap is the same.
export const KV_VALUE_LIMIT = 25 * 1024 * 1024;

/** The sending organisation's domain, never the person's address. */
export function senderDomain(fromHeader) {
  const text = String(fromHeader || "");
  const angle = /<([^>]+)>/.exec(text);
  const address = (angle ? angle[1] : text).trim();
  const at = address.lastIndexOf("@");
  return at === -1 ? "" : address.slice(at + 1).toLowerCase().replace(/[^a-z0-9.-]/g, "");
}

function metadata(subject, domain, size, now) {
  // Cloudflare caps metadata at 1024 bytes of JSON; the subject is the only
  // field that can be long, and the lane re-reads it from the email anyway.
  return { s: String(subject || "").slice(0, 300), d: domain, z: size, r: now.toISOString() };
}

export async function storeEmail(raw, size, headers, kv, now = new Date(), id = crypto.randomUUID()) {
  const subject = headers.subject || "";
  const domain = senderDomain(headers.from);
  if (size > KV_VALUE_LIMIT) {
    await recordError(kv, subject, domain, `email is ${size} bytes, over the 25 MiB store limit`, now);
    return { stored: false, reason: "too large" };
  }
  const key = `${RAW_KEY_PREFIX}${now.toISOString()}-${id.slice(0, 8)}`;
  const bytes = await new Response(raw).arrayBuffer();
  await kv.put(key, bytes, { expirationTtl: KEEP_SECONDS, metadata: metadata(subject, domain, bytes.byteLength, now) });
  return { stored: true, key, bytes: bytes.byteLength };
}

export async function recordError(kv, subject, domain, reason, now = new Date()) {
  try {
    await kv.put(`${ERROR_KEY_PREFIX}${now.toISOString()}-${crypto.randomUUID().slice(0, 8)}`, String(reason).slice(0, 500), {
      expirationTtl: KEEP_SECONDS,
      metadata: { s: String(subject || "").slice(0, 300), d: domain || "", r: now.toISOString(), e: String(reason).slice(0, 300) },
    });
  } catch (error) {
    console.error(`could not record inbox error: ${error && error.message}`);
  }
}

export default {
  async email(message, env) {
    if (!env.FORWARD_TO) {
      // Refuse loudly rather than accept an email nobody will ever see.
      message.setReject("news@ inbox is being reconfigured; please try again later");
      return;
    }
    await message.forward(env.FORWARD_TO);

    const headers = {
      subject: message.headers.get("subject") || "",
      from: message.headers.get("from") || message.from || "",
    };
    if (!env.INBOX) {
      console.error("INBOX KV binding missing: email forwarded but images not kept");
      return;
    }
    try {
      const result = await storeEmail(message.raw, message.rawSize, headers, env.INBOX);
      console.log(`news@ kept for image saver: ${JSON.stringify(result)}`);
    } catch (error) {
      console.error(`news@ store failed: ${error && error.message}`);
      await recordError(env.INBOX, headers.subject, senderDomain(headers.from), `store failed: ${error && error.message}`);
    }
  },
};
