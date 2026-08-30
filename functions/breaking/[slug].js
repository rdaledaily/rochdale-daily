// Rochdale Daily breaking-story page, rendered at request time.
//
// The GMP watcher (scraper/gmp_watch.py) writes breaking.json within a minute
// of Greater Manchester Police posting. This Function turns an entry in that
// file into a readable page immediately, so a breaking card on the front page
// has somewhere real to click through to without waiting for a site rebuild.
//
// These pages are deliberately thin and deliberately honest: they carry GMP's
// own words, quoted and attributed, and say plainly that a fuller report
// follows. Nothing here is model-written. When the newsroom pipeline publishes
// its own article from the same GMP post, scraper/retire_breaking.py marks the
// entry superseded and this Function redirects to the canonical piece.
//
// They are noindex,follow on purpose. A breaking entry expires after about
// eighteen hours, and a page that ranks and then vanishes is worse for the
// paper than one that never ranked: the canonical article is what should carry
// the story in search, and the link from here passes readers to it.

const BRAND = 'Rochdale Daily';
const SITE = 'https://rochdaledaily.co.uk';

function escapeHtml(value) {
  return String(value == null ? '' : value)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function normaliseSlug(value) {
  return String(value == null ? '' : value)
    .replace(/^\.\.\//, '').replace(/^breaking\//, '').replace(/\.html$/i, '')
    .trim().toLowerCase();
}

function ukTime(iso) {
  const parsed = Date.parse(iso || '');
  if (!Number.isFinite(parsed)) return '';
  try {
    return new Intl.DateTimeFormat('en-GB', {
      timeZone: 'Europe/London', weekday: 'long', day: 'numeric', month: 'long',
      hour: '2-digit', minute: '2-digit', hour12: false
    }).format(new Date(parsed));
  } catch (_) {
    return new Date(parsed).toISOString();
  }
}

function renderPage(entry) {
  const title = escapeHtml(entry.title || 'Breaking');
  const attribution = escapeHtml(entry.attribution || 'Greater Manchester Police said:');
  const sourceUrl = escapeHtml(entry.source_url || '');
  const sourceName = escapeHtml(entry.source_name || 'Greater Manchester Police');
  const stamp = escapeHtml(ukTime(entry.published_at));
  const image = escapeHtml(entry.image_url || 'assets/img/cards/police.jpg');
  const paragraphs = String(entry.quote || '')
    .split(/\n{2,}/).map(p => p.trim()).filter(Boolean)
    .map(p => `<p>${escapeHtml(p)}</p>`).join('\n');
  const excerpt = escapeHtml(String(entry.quote || '').slice(0, 200));
  const canonical = `${SITE}/breaking/${escapeHtml(normaliseSlug(entry.slug))}.html`;

  return `<!DOCTYPE html>
<html lang="en-GB">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex,follow">
<title>${title} | ${BRAND}</title>
<meta name="description" content="${excerpt}">
<link rel="canonical" href="${canonical}">
<meta property="og:type" content="article">
<meta property="og:title" content="${title}">
<meta property="og:description" content="${excerpt}">
<meta property="og:url" content="${canonical}">
<meta property="og:site_name" content="${BRAND}">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="${title}">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Roboto+Condensed:wght@700;800&family=Roboto:wght@400;500;700&family=Source+Serif+4:opsz,wght@8..60,600;8..60,700&display=swap" rel="stylesheet">
<style>
:root{--ink:#202020;--muted:#666;--line:#d8d8d8;--paper:#fff;--red:#c8102e;--navy:#0b1f3a;--cyan:#22d3ee;--max:760px}
*{box-sizing:border-box}
body{margin:0;background:#e9e9e9;color:var(--ink);font-family:Roboto,Arial,Helvetica,sans-serif;line-height:1.5}
a{color:inherit}
img{display:block;width:100%;height:auto}
.wrap{width:min(var(--max),calc(100% - 30px));margin-inline:auto}
header.masthead{background:var(--navy);color:#fff;padding:14px 0}
header.masthead a{text-decoration:none;font-family:"Roboto Condensed",Arial,sans-serif;font-weight:800;letter-spacing:.5px;font-size:22px;text-transform:uppercase}
header.masthead .tag{color:var(--cyan);font-size:12px;font-weight:700;letter-spacing:1.5px;display:block;margin-top:2px;text-transform:uppercase}
main{background:var(--paper);padding:26px 0 34px;margin:18px auto;border:1px solid var(--line);width:min(var(--max),calc(100% - 30px))}
main>.inner{width:calc(100% - 44px);margin-inline:auto}
.kicker{display:inline-block;background:var(--red);color:#fff;font-family:"Roboto Condensed",Arial,sans-serif;font-weight:800;font-size:13px;letter-spacing:1.5px;padding:5px 11px;text-transform:uppercase}
h1{font-family:"Source Serif 4",Georgia,serif;font-weight:700;font-size:clamp(27px,5vw,40px);line-height:1.15;margin:14px 0 10px}
.meta{color:var(--muted);font-size:14px;border-bottom:1px solid var(--line);padding-bottom:14px;margin-bottom:18px}
.developing{background:#fff8e1;border-left:4px solid #f5c400;padding:12px 14px;margin:0 0 20px;font-size:15px}
.attribution{font-weight:700;margin:0 0 10px}
blockquote{margin:0 0 18px;padding:0 0 0 18px;border-left:4px solid var(--navy);font-size:17px}
blockquote p{margin:0 0 12px}
figure{margin:0 0 20px}
figcaption{color:var(--muted);font-size:13px;padding-top:6px}
.source{background:#f2f2f2;padding:14px;font-size:15px;margin:22px 0}
.source a{color:#0057a8}
.legal{color:var(--muted);font-size:13px;border-top:1px solid var(--line);padding-top:14px;margin-top:24px}
.back{display:inline-block;margin-top:20px;font-weight:700;text-decoration:none;color:#0057a8}
</style>
</head>
<body>
<header class="masthead"><div class="wrap">
  <a href="/">${BRAND}<span class="tag">Breaking</span></a>
</div></header>

<main>
  <div class="inner">
    <span class="kicker">Breaking</span>
    <h1>${title}</h1>
    <div class="meta">${stamp ? `Published ${stamp}` : ''}${stamp ? ' &middot; ' : ''}Source: ${sourceName}</div>

    <figure>
      <img src="/${image}" alt="${title}" loading="eager">
      <figcaption>Picture: ${BRAND} library image</figcaption>
    </figure>

    <p class="developing"><strong>This is a developing story.</strong> It carries
    ${sourceName}'s statement in full, as published, and nothing beyond it. We are
    working on a fuller report and this page will be replaced by it.</p>

    <p class="attribution">${attribution}</p>
    <blockquote>
${paragraphs || '<p>No statement text was available.</p>'}
    </blockquote>

    <div class="source">
      Read the original statement:
      <a href="${sourceUrl}" rel="nofollow noopener noreferrer" target="_blank">${sourceName}</a>
    </div>

    <p class="legal">Information in this report comes from ${sourceName} and has not
    been independently verified by ${BRAND}. No inference of guilt should be drawn
    from any arrest or police appeal. If you are named here and wish to respond,
    contact <a href="mailto:news@rochdaledaily.co.uk">news@rochdaledaily.co.uk</a>
    and we will publish a correction or reply promptly.</p>

    <a class="back" href="/">&larr; Back to ${BRAND}</a>
  </div>
</main>
</body>
</html>`;
}

function notFound() {
  return new Response(
    `<!DOCTYPE html><html lang="en-GB"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex"><title>Story not found | ${BRAND}</title>
<style>body{font-family:Roboto,Arial,sans-serif;margin:0;background:#e9e9e9;color:#202020}
.b{width:min(560px,calc(100% - 30px));margin:70px auto;background:#fff;border:1px solid #d8d8d8;padding:30px}
a{color:#0057a8}</style></head><body><div class="b">
<h1>That breaking update has moved on</h1>
<p>Breaking updates are short-lived. This one has either been replaced by our
full report or has expired.</p>
<p><a href="/">Go to the ${BRAND} front page</a></p>
</div></body></html>`,
    {
      status: 404,
      headers: {
        'content-type': 'text/html; charset=utf-8',
        'cache-control': 'no-store'
      }
    }
  );
}

export async function onRequest(context) {
  const { params, env, request } = context;
  const slug = normaliseSlug(params && params.slug);
  if (!slug) return notFound();

  let items = [];
  try {
    const response = await env.ASSETS.fetch(new URL('/breaking.json', request.url));
    if (response.ok) {
      const data = await response.json();
      const listed = Array.isArray(data) ? data : (data && data.items);
      if (Array.isArray(listed)) items = listed;
    }
  } catch (_) {
    return notFound();
  }

  const entry = items.find(item => item && normaliseSlug(item.slug) === slug);
  if (!entry) return notFound();

  // The pipeline has published the real article: send the reader there, and
  // tell search engines the stub was only ever temporary.
  if (entry.status === 'superseded' && entry.superseded_by) {
    const target = new URL(
      `/articles/${normaliseSlug(entry.superseded_by)}.html`,
      request.url
    );
    return Response.redirect(target.toString(), 301);
  }

  // Held entries are awaiting editorial review and must not be readable.
  if (entry.status !== 'live') return notFound();

  const expires = Date.parse(entry.expires_at || '');
  if (Number.isFinite(expires) && expires <= Date.now()) return notFound();

  return new Response(renderPage(entry), {
    headers: {
      'content-type': 'text/html; charset=utf-8',
      // Short cache: a developing story changes, and the retire step can
      // supersede it at any moment.
      'cache-control': 'public, max-age=30, must-revalidate',
      'x-rd-breaking': 'gmp-watch'
    }
  });
}
