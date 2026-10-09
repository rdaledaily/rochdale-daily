/* In-page notification for newly published Rochdale Daily stories.
 * A visit establishes a baseline; only genuinely newer stories trigger alerts.
 * No browser notification permission, no third-party service, no sound without opt-in.
 */
(() => {
  'use strict';
  if (window.__rdNewStoryWatcher) return;
  window.__rdNewStoryWatcher = true;
  const INTERVAL = 90000;
  const FRESH_MS = 36 * 60 * 60 * 1000;
  const MAX_SEEN = 300;
  const KEY = 'rd_new_story_seen_v1';
  let known = new Set();
  let baseline = false;
  let timer = null;
  let busy = false;
  let lastSound = 0;
  try {
    const stored = JSON.parse(localStorage.getItem(KEY) || '[]');
    if (Array.isArray(stored)) known = new Set(stored.filter(x => typeof x === 'string').slice(-MAX_SEEN));
  } catch (_) {}
  const html = document.documentElement;
  const style = document.createElement('style');
  style.textContent = [
    '.rd-new-story-stack{position:fixed;top:16px;right:16px;z-index:9500;max-width:min(360px,calc(100vw - 32px));display:grid;gap:8px}',
    '.rd-new-story-alert{background:#102c41;color:white;border:1px solid #b4d5df;border-left:5px solid #50c9e7;border-radius:8px;padding:14px;box-shadow:0 7px 22px #0004;font:14px/1.45 system-ui}',
    '.rd-new-story-alert strong{display:block;font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:#9febfc;margin-bottom:5px}',
    '.rd-new-story-alert a{color:#fff;font-weight:750;text-decoration:underline;text-underline-offset:3px}',
    '.rd-new-story-alert button{background:transparent;border:0;color:#e1f8ff;cursor:pointer;float:right;font-size:20px;line-height:1;margin:-3px -5px 0 9px}',
    '@media(prefers-reduced-motion:reduce){.rd-new-story-alert{animation:none}}'
  ].join('');
  document.head.appendChild(style);
  const stack = document.createElement('div');
  stack.className = 'rd-new-story-stack';
  stack.setAttribute('aria-label', 'New local stories');
  document.body.appendChild(stack);
  function id(story) { return String(story.story_key || story.slug || story.id || '').trim(); }
  function published(story) {
    const t = Date.parse(story.first_published_at || story.published_at || '');
    return Number.isFinite(t) ? t : 0;
  }
  function url(story) {
    const slug = String(story.slug || '').trim();
    if (!/^[a-z0-9][a-z0-9-]{0,180}$/i.test(slug)) return '';
    return '/articles/' + encodeURIComponent(slug) + '.html';
  }
  function eligible(story, now) {
    if (!story || typeof story !== 'object' || story.status === 'draft') return false;
    const t = published(story);
    return Boolean(id(story) && url(story) && String(story.title || '').trim() &&
      t > 0 && t <= now + 120000 && now - t < FRESH_MS);
  }
  function save() {
    try { localStorage.setItem(KEY, JSON.stringify(Array.from(known).slice(-MAX_SEEN))); } catch (_) {}
  }
  function alertStory(story) {
    const card = document.createElement('section');
    card.className = 'rd-new-story-alert';
    const close = document.createElement('button');
    close.type = 'button'; close.textContent = '×'; close.setAttribute('aria-label', 'Dismiss new story');
    close.addEventListener('click', () => card.remove());
    const label = document.createElement('strong'); label.textContent = 'New on Rochdale Daily';
    const link = document.createElement('a'); link.href = url(story); link.textContent = String(story.title);
    card.append(close, label, link);
    stack.prepend(card);
    while (stack.childElementCount > 3) stack.lastElementChild.remove();
    const now = Date.now();
    if (now - lastSound > 15000 && typeof window.RochdaleDailyChime === 'function') {
      window.RochdaleDailyChime();
      lastSound = now;
    }
  }
  async function poll() {
    if (busy || document.visibilityState === 'hidden') return;
    busy = true;
    try {
      const response = await fetch('/articles.json?new_story_check=' + Date.now(), {
        cache: 'no-store', headers: { Accept: 'application/json' }
      });
      if (!response.ok) return;
      const body = await response.json();
      const stories = Array.isArray(body) ? body : (Array.isArray(body.articles) ? body.articles : []);
      const now = Date.now();
      const incoming = stories.filter(s => eligible(s, now)).sort((a, b) => published(a) - published(b));
      const fresh = incoming.filter(s => !known.has(id(s)));
      incoming.forEach(s => known.add(id(s)));
      if (known.size > MAX_SEEN) known = new Set(Array.from(known).slice(-MAX_SEEN));
      save();
      if (baseline) fresh.slice(-3).forEach(alertStory);
      baseline = true;
    } catch (_) { /* offline or temporary feed issue: retry on next interval */ }
    finally { busy = false; }
  }
  poll();
  timer = setInterval(poll, INTERVAL);
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') poll();
  });
})();
