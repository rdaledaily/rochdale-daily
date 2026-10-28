// Markdown for Agents -- content negotiation for every Rochdale Daily page.
//
// A request whose Accept header lists text/markdown gets a Markdown version of
// the page; every other request (all browsers) gets the HTML exactly as before.
// This is the same contract as Cloudflare's paid zone toggle "Markdown for
// Agents" (Pro plan and up), built here so it runs on the plan the site is on.
//
// What an agent receives:
//   ---                       YAML frontmatter from the page's own meta tags
//   title / description / image / url
//   ---
//   # Headline ...            the page's main content only: masthead, nav,
//                             sidebars, adverts, share buttons, forms,
//                             scripts and styles are stripped
//   ```json ...```            the page's JSON-LD (NewsArticle etc.), verbatim
//
// Response headers on the Markdown version:
//   Content-Type: text/markdown; charset=utf-8
//   Vary: Accept               (HTML responses also carry it, so no cache ever
//                               hands Markdown to a browser or the reverse)
//   x-markdown-tokens          estimated token count (characters / 4)
//   Content-Signal             the SAME policy as robots.txt:
//                               search=yes, ai-train=no, use=reference
//                               (Cloudflare's toggle would default to
//                               ai-train=yes -- that would contradict robots.txt)
//
// Nothing here runs for the static assets listed in _routes.json, so images,
// CSS and JS are served without invoking any Function.
//
// Measured before shipping, across all 1,889 HTML pages in the repo:
// conversion median 0.7 ms, 95th percentile 1.5 ms; the largest listing pages
// (monthly archives) 14-19 ms. HTML -> Markdown is ~75% smaller.

const CONTENT_SIGNAL = 'search=yes, ai-train=no, use=reference';
const MAX_HTML_BYTES = 6 * 1024 * 1024;

// Content root, tried in order: the first that yields real text wins.
// Homepage, trust and section pages: <main>. Article pages (which have no
// <main>): .article-main, which excludes the sidebar. Anything else: <body>.
// A candidate that converts to almost nothing falls through to the next.
const ROOT_SELECTORS = [
  { selector: 'main', present: /<main[\s>]/i },
  { selector: '.article-main', present: /class=["'][^"']*\barticle-main\b/ },
  { selector: 'body', present: /./ },
];
const MIN_ROOT_CHARS = 200;

// Elements removed with everything inside them.
const SKIP_TAGS = new Set([
  'script', 'style', 'noscript', 'template', 'svg', 'canvas', 'iframe',
  'object', 'embed', 'video', 'audio', 'form', 'button', 'select', 'textarea',
  'input', 'label', 'nav', 'header', 'footer', 'aside', 'dialog', 'head',
]);
// Classes that mark furniture rather than content.
const SKIP_CLASSES = [
  'ad-slot', 'article-share', 'sr-only', 'skip-link', 'utility', 'masthead',
  'primary-nav', 'site-footer', 'cookie', 'newsletter-box', 'rail-newsletter',
  'mobile-jump', 'mobile-sections', 'filter-bar', 'event-filters', 'dem-tabs',
  'dem-ward-pick', 'add-event', 'read-next-bar', 'comments',
];
const VOID_TAGS = new Set([
  'area', 'base', 'br', 'col', 'hr', 'img', 'input', 'link', 'meta', 'source',
  'track', 'wbr',
]);
const BLOCK_TAGS = new Set([
  'p', 'div', 'section', 'article', 'main', 'figure', 'figcaption', 'table',
  'tr', 'dl', 'dt', 'dd', 'details', 'summary', 'address',
]);

// ---------------------------------------------------------------- negotiation

export function wantsMarkdown(accept) {
  if (!accept) return false;
  return accept.split(',').some((part) => {
    const [type, ...params] = part.trim().toLowerCase().split(';');
    if (type.trim() !== 'text/markdown') return false;
    const q = params.map((p) => p.trim()).find((p) => p.startsWith('q='));
    return !q || parseFloat(q.slice(2)) > 0;
  });
}

function addVaryAccept(headers) {
  const vary = headers.get('Vary');
  if (!vary) headers.set('Vary', 'Accept');
  else if (!/(^|,)\s*accept\s*(,|$)/i.test(vary)) headers.set('Vary', `${vary}, Accept`);
}

// ---------------------------------------------------------------- helpers

const ENTITIES = {
  amp: '&', lt: '<', gt: '>', quot: '"', apos: "'", nbsp: ' ', ndash: '–',
  mdash: '—', hellip: '…', lsquo: '‘', rsquo: '’',
  ldquo: '“', rdquo: '”', pound: '£', euro: '€',
  middot: '·', bull: '•', copy: '©', reg: '®',
  trade: '™', times: '×', deg: '°', rarr: '→', larr: '←',
};

export function decodeEntities(s) {
  return s.replace(/&(#x[0-9a-f]+|#\d+|[a-z]+);/gi, (m, e) => {
    if (e[0] === '#') {
      const n = e[1] === 'x' || e[1] === 'X' ? parseInt(e.slice(2), 16) : parseInt(e.slice(1), 10);
      try { return String.fromCodePoint(n); } catch { return m; }
    }
    const v = ENTITIES[e.toLowerCase()];
    return v === undefined ? m : v;
  });
}

function absolute(href, base) {
  try { return new URL(href, base).toString(); } catch { return href; }
}

function metaContent(html, attr, name) {
  const re = new RegExp(`<meta\\b[^>]*\\b${attr}=["']${name}["'][^>]*>`, 'i');
  const tag = html.match(re);
  if (!tag) return '';
  const c = tag[0].match(/\bcontent=("([^"]*)"|'([^']*)')/i);
  return c ? decodeEntities(c[2] ?? c[3] ?? '').trim() : '';
}

function yamlValue(v) {
  return JSON.stringify(v.replace(/\s+/g, ' ').trim());
}

export function frontmatter(html, pageUrl) {
  const titleTag = html.match(/<title[^>]*>([\s\S]*?)<\/title>/i);
  const title = metaContent(html, 'name', 'title') || metaContent(html, 'property', 'og:title')
    || (titleTag ? decodeEntities(titleTag[1]).trim() : '');
  const description = metaContent(html, 'name', 'description') || metaContent(html, 'property', 'og:description');
  const image = metaContent(html, 'property', 'og:image');
  const canonical = html.match(/<link\b[^>]*\brel=["']canonical["'][^>]*>/i);
  const canonHref = canonical && canonical[0].match(/\bhref=["']([^"']+)["']/i);
  const url = canonHref ? absolute(canonHref[1], pageUrl) : pageUrl;
  const lines = [];
  if (title) lines.push(`title: ${yamlValue(title)}`);
  if (description) lines.push(`description: ${yamlValue(description)}`);
  if (image) lines.push(`image: ${yamlValue(absolute(image, pageUrl))}`);
  lines.push(`url: ${yamlValue(url)}`);
  return `---\n${lines.join('\n')}\n---\n\n`;
}

export function jsonLd(html) {
  const blocks = [];
  const re = /<script\b[^>]*type=["']application\/ld\+json["'][^>]*>([\s\S]*?)<\/script>/gi;
  let m;
  while ((m = re.exec(html))) {
    const body = m[1].trim();
    if (!body) continue;
    try { blocks.push(JSON.stringify(JSON.parse(body))); } catch { blocks.push(body.replace(/\s+/g, ' ')); }
  }
  return blocks.length ? `\n\n\`\`\`json\n${blocks.join('\n')}\n\`\`\`\n` : '';
}

// ---------------------------------------------------------------- converter
//
// Elements whose
// Markdown wraps their content -- links, headings, list items, quotes, table
// cells -- push a frame on start and are rendered from it on their end tag.

// A small HTML walker. HTMLRewriter was the first choice, but it calls back
// into JavaScript once per element and once per end tag; on the homepage that
// alone measured ~150 ms per conversion against a 10 ms CPU allowance on the
// free plan. This single regex pass over HTML the site's own generators wrote
// costs a few milliseconds. It gives the converter the same three events --
// start tag (with an onEndTag hook), end tag, text -- and closes elements left
// open (a <p> or <li> without its end tag) when their parent ends.

const TOKEN = /<!--[\s\S]*?-->|<![^>]*>|<\/([a-zA-Z][\w:-]*)\s*>|<([a-zA-Z][\w:-]*)((?:[^>"']|"[^"]*"|'[^']*')*)>/g;

const ATTR = /([^\s"'>\/=]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'>]+)))?/g;

function parseAttrs(raw) {
  const map = new Map();
  let m;
  ATTR.lastIndex = 0;
  while ((m = ATTR.exec(raw))) {
    const name = m[1].toLowerCase();
    if (!map.has(name)) map.set(name, m[2] ?? m[3] ?? m[4] ?? '');
  }
  return map;
}

class El {
  constructor(tag, attrs, selfClosing, entry) {
    this.tagName = tag;
    this.selfClosing = selfClosing;
    this.canHaveContent = !selfClosing && !VOID_TAGS.has(tag);
    this._attrs = attrs;
    this._map = null;
    this._entry = entry;
  }

  getAttribute(n) {
    if (!this._map) this._map = /\S/.test(this._attrs) ? parseAttrs(this._attrs) : EMPTY_MAP;
    const v = this._map.get(n);
    if (v === undefined) return null;
    return v.includes('&') ? decodeEntities(v) : v;
  }

  hasAttribute(n) { return this.getAttribute(n) !== null; }

  onEndTag(fn) { this._entry.ends.push(fn); }
}
const EMPTY_MAP = new Map();

export function walkHtml(html, { element, text }) {
  const stack = []; // { tag, ends: [] }
  let last = 0;
  let m;
  TOKEN.lastIndex = 0;
  while ((m = TOKEN.exec(html))) {
    if (m.index > last) text({ text: html.slice(last, m.index) });
    last = TOKEN.lastIndex;
    if (m[1]) {
      const tag = m[1].toLowerCase();
      let i = stack.length - 1;
      while (i >= 0 && stack[i].tag !== tag) i -= 1;
      if (i < 0) continue; // stray end tag
      while (stack.length > i) { const e = stack.pop(); for (const fn of e.ends) fn(); }
    } else if (m[2]) {
      const tag = m[2].toLowerCase();
      let raw = m[3] || '';
      const selfClosing = raw.endsWith('/') || /\/\s*$/.test(raw);
      if (selfClosing) raw = raw.replace(/\/\s*$/, '');
      const entry = { tag, ends: [] };
      const el = new El(tag, raw, selfClosing, entry);
      element(el);
      if (el.canHaveContent) stack.push(entry);
    }
  }
  if (last < html.length) text({ text: html.slice(last) });
  while (stack.length) { const e = stack.pop(); for (const fn of e.ends) fn(); }
}

// Scripts, styles and inline SVG are three quarters of the homepage's bytes
// and none of its content. Cutting them with one regex pass before parsing
// keeps the conversion inside the Workers CPU budget. (JSON-LD is read from the
// original HTML separately, before this.)
export function stripNoise(html) {
  return html
    .replace(/<head\b[\s\S]*?<\/head>/i, '')
    .replace(/<!--[\s\S]*?-->/g, '')
    .replace(/<(script|style|template|svg|noscript|iframe)\b[\s\S]*?<\/\1\s*>/gi, '');
}

function hasText(s, min) {
  let n = 0;
  for (let i = 0; i < s.length && n < min; i += 1) {
    const c = s.charCodeAt(i);
    if (c > 32) n += 1;
  }
  return n >= min;
}

export async function htmlToMarkdown(html, pageUrl) {
  const lean = stripNoise(html);
  let best = '';
  for (const { selector, present } of ROOT_SELECTORS) {
    if (!present.test(lean)) continue;
    const md = convertRoot(lean, pageUrl, selector);
    if (hasText(md, MIN_ROOT_CHARS)) return md;
    if (md.length > best.length) best = md;
  }
  return best;
}

function convertRoot(html, pageUrl, root) {
  const frames = [{ kind: 'root', parts: [] }];
  const lists = []; // stack of { ordered, n }
  let inRoot = 0;   // depth inside the content root
  let skip = 0;     // depth inside a skipped subtree
  let pre = 0;

  const top = () => frames[frames.length - 1];
  const emit = (s) => { top().parts.push(s); };
  const push = (kind, extra = {}) => { frames.push({ kind, parts: [], ...extra }); };
  const pop = () => { const f = frames.pop(); return { ...f, text: f.parts.join('') }; };

  const shouldSkip = (el) => {
    const tag = el.tagName;
    if (SKIP_TAGS.has(tag)) return true;
    if (el.hasAttribute('hidden')) return true;
    if (el.getAttribute('aria-hidden') === 'true') return true;
    const cls = ` ${el.getAttribute('class') || ''} `;
    return SKIP_CLASSES.some((c) => cls.includes(` ${c} `));
  };

  // Registers fn for the element's end tag. Returns false when the element has
  // none (void tags, and self-closing tags such as <path/> inside an <svg>), so
  // a depth counter is only raised when it is certain to come back down.
  const onEnd = (el, fn) => {
    if (VOID_TAGS.has(el.tagName) || el.selfClosing || el.canHaveContent === false) return false;
    try { el.onEndTag(fn); return true; } catch { return false; }
  };

  const elementHandler = {
    element(el) {
      if (!inRoot) return;
      const tag = el.tagName;
      if (skip) {
        if (onEnd(el, () => { skip -= 1; })) skip += 1;
        return;
      }
      if (shouldSkip(el)) {
        if (onEnd(el, () => { skip -= 1; })) skip += 1;
        return;
      }

      if (/^h[1-6]$/.test(tag)) {
        push('heading', { level: Number(tag[1]) });
        onEnd(el, () => {
          const f = pop();
          const t = f.text.replace(/\s+/g, ' ').trim();
          if (t) emit(`\n\n${'#'.repeat(f.level)} ${t}\n\n`);
        });
      } else if (tag === 'a') {
        const href = el.getAttribute('href') || '';
        push('link', { href });
        onEnd(el, () => {
          const f = pop();
          const usable = f.href && !/^(#|javascript:|mailto:\s*$)/i.test(f.href);
          if (/\n/.test(f.text.trim())) {
            // A card: the link wraps an image, a heading and a summary. Keep
            // the blocks and put the link on the heading (or first text line).
            const lines = tidy(f.text).split('\n');
            if (usable) {
              const url = absolute(f.href, pageUrl);
              let i = lines.findIndex((l) => /^#{1,6} /.test(l));
              if (i < 0) i = lines.findIndex((l) => l && !l.startsWith('!['));
              if (i >= 0) {
                const m = lines[i].match(/^(#{1,6} )?(.*)$/);
                lines[i] = `${m[1] || ''}[${m[2].replace(/[[\]]/g, '\\$&')}](${url})`;
              }
            }
            emit(`\n\n${lines.join('\n')}\n\n`);
            return;
          }
          const t = f.text.replace(/\s+/g, ' ').trim();
          if (!t) return;
          emit(usable ? `[${t.replace(/[[\]]/g, '\\$&')}](${absolute(f.href, pageUrl)})` : t);
        });
      } else if (tag === 'strong' || tag === 'b') {
        push('strong');
        onEnd(el, () => { const t = pop().text; emit(t.trim() ? `**${t.trim()}** ` : t); });
      } else if (tag === 'em' || tag === 'i') {
        push('em');
        onEnd(el, () => { const t = pop().text; emit(t.trim() ? `_${t.trim()}_ ` : t); });
      } else if (tag === 'code' && !pre) {
        push('code');
        onEnd(el, () => { const t = pop().text; emit(t ? `\`${t}\`` : ''); });
      } else if (tag === 'pre') {
        pre += 1;
        push('pre');
        onEnd(el, () => { pre -= 1; const t = pop().text; emit(`\n\n\`\`\`\n${t.replace(/\n+$/, '')}\n\`\`\`\n\n`); });
      } else if (tag === 'blockquote') {
        push('quote');
        onEnd(el, () => {
          const t = tidy(pop().text);
          if (t) emit(`\n\n${t.split('\n').map((l) => `> ${l}`.trimEnd()).join('\n')}\n\n`);
        });
      } else if (tag === 'ul' || tag === 'ol') {
        lists.push({ ordered: tag === 'ol', n: 0 });
        emit('\n\n');
        onEnd(el, () => { lists.pop(); emit('\n\n'); });
      } else if (tag === 'li') {
        const list = lists[lists.length - 1] || { ordered: false, n: 0 };
        list.n += 1;
        const marker = list.ordered ? `${list.n}. ` : '- ';
        const indent = '  '.repeat(Math.max(0, lists.length - 1));
        push('li');
        onEnd(el, () => {
          const t = tidy(pop().text);
          if (!t) return;
          const [first, ...rest] = t.split('\n');
          const pad = indent + ' '.repeat(marker.length);
          emit(`\n${indent}${marker}${first}${rest.map((l) => (l ? `\n${pad}${l}` : '\n')).join('')}`);
        });
      } else if (tag === 'img') {
        const src = el.getAttribute('src');
        if (src && !src.startsWith('data:')) {
          const alt = (el.getAttribute('alt') || '').replace(/[[\]]/g, '').trim();
          emit(`\n\n![${alt}](${absolute(src, pageUrl)})\n\n`);
        }
      } else if (tag === 'br') {
        emit('\n');
      } else if (tag === 'hr') {
        emit('\n\n---\n\n');
      } else if (tag === 'td' || tag === 'th') {
        push('cell');
        onEnd(el, () => { const t = pop().text.replace(/\s+/g, ' ').trim(); emit(`| ${t} `); });
      } else if (tag === 'tr') {
        emit('\n');
        onEnd(el, () => emit('|\n'));
      } else if (tag === 'span' || tag === 'small' || tag === 'time') {
        // Adjacent spans ("anonymous" + "0800 555 111") must not run together.
        emit(' ');
        onEnd(el, () => emit(' '));
      } else if (BLOCK_TAGS.has(tag)) {
        emit('\n\n');
        onEnd(el, () => emit('\n\n'));
      }
    },
  };

  const textHandler = {
    text(chunk) {
      if (!inRoot || skip) return;
      const t = chunk.text;
      if (pre) { emit(t.includes('&') ? decodeEntities(t) : t); return; }
      if (!/\S/.test(t)) { emit(' '); return; }
      const raw = t.includes('&') ? decodeEntities(t) : t;
      emit(raw.replace(/\s+/g, ' '));
    },
  };

  // inRoot counts nesting of elements matching the root selector, so a root
  // nested inside another (it never is on this site) still closes correctly.
  const matchesRoot = root.startsWith('.')
    ? (el) => ` ${el.getAttribute('class') || ''} `.includes(` ${root.slice(1)} `)
    : (el) => el.tagName === root;

  walkHtml(html, {
    element(el) {
      if (matchesRoot(el) && onEnd(el, () => { inRoot -= 1; })) inRoot += 1;
      elementHandler.element(el);
    },
    text: textHandler.text,
  });

  while (frames.length > 1) { const f = pop(); emit(f.text); }
  return tidy(frames[0].parts.join(''));
}

function tidy(s) {
  let fenced = false;
  return s
    .split('\n')
    .map((l) => {
      if (/^\s*```/.test(l)) { fenced = !fenced; return l.trim(); }
      if (fenced) return l;
      return l.replace(/ {2,}/g, ' ').trimEnd().replace(/^ (?=\S)/, '');
    })
    .join('\n')
    .replace(/\n{3,}/g, '\n\n')
    .trim();
}

// ---------------------------------------------------------------- handler

export async function onRequest(context) {
  const { request } = context;
  const method = request.method;
  const markdown = (method === 'GET' || method === 'HEAD') && wantsMarkdown(request.headers.get('Accept'));

  const response = await context.next();
  const type = response.headers.get('Content-Type') || '';
  if (!type.toLowerCase().includes('text/html')) return response;

  const headers = new Headers(response.headers);
  addVaryAccept(headers);

  if (!markdown || response.status !== 200) {
    return new Response(response.body, { status: response.status, statusText: response.statusText, headers });
  }

  const html = await response.text();
  if (html.length > MAX_HTML_BYTES) {
    headers.set('x-markdown-status', 'too-large');
    return new Response(html, { status: 200, headers });
  }

  let md;
  try {
    const pageUrl = request.url;
    const body = await htmlToMarkdown(html, pageUrl);
    md = `${frontmatter(html, pageUrl)}${body}${jsonLd(html)}`.replace(/\n*$/, '\n');
  } catch (err) {
    // Report the failure; the page itself is still the default representation.
    console.error('markdown conversion failed', request.url, err && err.stack);
    headers.set('x-markdown-status', 'conversion-failed');
    return new Response(html, { status: 200, headers });
  }

  for (const h of ['Content-Length', 'Content-Encoding', 'Content-Range', 'Transfer-Encoding', 'ETag', 'Last-Modified']) {
    headers.delete(h);
  }
  headers.set('Content-Type', 'text/markdown; charset=utf-8');
  headers.set('x-markdown-tokens', String(Math.ceil(md.length / 4)));
  if (!headers.has('Content-Signal')) headers.set('Content-Signal', CONTENT_SIGNAL);

  return new Response(method === 'HEAD' ? null : md, { status: 200, headers });
}
