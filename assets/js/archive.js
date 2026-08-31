(async () => {
  let DATA = Array.isArray(window.__RD_ARCHIVE__) ? window.__RD_ARCHIVE__ : [];
  if (!DATA.length) {
    try {
      const response = await fetch('/archive-index.json', {headers:{Accept:'application/json'}});
      if (!response.ok) throw new Error('Archive index request failed');
      const payload = await response.json();
      DATA = Array.isArray(payload) ? payload : [];
    } catch (_) {
      const host = document.getElementById('archive-results');
      if (host) host.innerHTML = '<p class="archive-empty">The archive index is temporarily unavailable. Please try again shortly.</p>';
      const loadMore = document.getElementById('load-more');
      if (loadMore) loadMore.hidden = true;
      return;
    }
  }

  const PAGE = 60;
  let shown = PAGE;
  let activeSection = 'all';

  const input = document.getElementById('archive-search');
  const yearSelect = document.getElementById('archive-year');
  const monthSelect = document.getElementById('archive-month');
  const sections = document.getElementById('archive-sections');
  const results = document.getElementById('archive-results');
  const summary = document.getElementById('archive-summary');
  const clearButton = document.getElementById('archive-clear');
  const more = document.getElementById('load-more');
  if (!input || !yearSelect || !monthSelect || !sections || !results || !summary || !clearButton || !more) return;

  const esc = value => String(value || '').replace(/[&<>\"]/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;'}[char]));
  const parsedDate = value => { if (!value) return null; const date = new Date(value); return Number.isNaN(date.getTime()) ? null : date; };
  const normalCategory = item => (item.category || 'News').trim() || 'News';
  const sectionKey = value => String(value || 'News').trim().toLowerCase();
  const titleCase = value => { const text = String(value || 'News').trim(); return text ? text.replace(/\b\w/g, char => char.toUpperCase()) : 'News'; };
  const slugFor = item => {
    const direct = String(item.slug || '').trim();
    if (direct) return direct;
    const pathname = String(item.url || '').split(/[?#]/, 1)[0];
    const filename = pathname.split('/').filter(Boolean).pop() || '';
    return filename.replace(/\.html?$/i, '');
  };

  function dayKey(item) {
    const date = parsedDate(item.published_at);
    if (!date) return 'undated';
    return [date.getFullYear(), String(date.getMonth() + 1).padStart(2, '0'), String(date.getDate()).padStart(2, '0')].join('-');
  }

  function dayLabel(item) {
    const date = parsedDate(item.published_at);
    return date ? date.toLocaleDateString('en-GB', {weekday:'long', day:'numeric', month:'long', year:'numeric'}) : 'Date unavailable';
  }

  function shortDate(item) {
    const date = parsedDate(item.published_at);
    return date ? date.toLocaleDateString('en-GB', {day:'numeric', month:'short', year:'numeric'}) : '';
  }

  function timeLabel(item) {
    const date = parsedDate(item.published_at);
    if (!date || !/[T ]\d{1,2}:\d{2}/.test(item.published_at || '')) return '';
    return date.toLocaleTimeString('en-GB', {hour:'2-digit', minute:'2-digit'});
  }

  function buildFacets() {
    const years = [...new Set(DATA.map(item => { const date = parsedDate(item.published_at); return date ? String(date.getFullYear()) : ''; }).filter(Boolean))]
      .sort((a, b) => Number(b) - Number(a));
    yearSelect.insertAdjacentHTML('beforeend', years.map(year => `<option value="${esc(year)}">${esc(year)}</option>`).join(''));

    const categoryMap = new Map();
    DATA.forEach(item => {
      const label = normalCategory(item);
      const key = sectionKey(label);
      if (!categoryMap.has(key)) categoryMap.set(key, label);
    });
    const categories = [...categoryMap.entries()].sort((a, b) => a[1].localeCompare(b[1]));
    sections.innerHTML = [
      '<button class="archive-section-button is-active" type="button" data-section="all" aria-pressed="true">All sections</button>',
      ...categories.map(([key, label]) => `<button class="archive-section-button" type="button" data-section="${esc(key)}" aria-pressed="false">${esc(titleCase(label))}</button>`)
    ].join('');
  }

  function filtered() {
    const words = input.value.trim().toLowerCase().split(/\s+/).filter(Boolean);
    const year = yearSelect.value;
    const month = monthSelect.value;
    return DATA.filter(item => {
      const date = parsedDate(item.published_at);
      if (activeSection !== 'all' && sectionKey(normalCategory(item)) !== activeSection) return false;
      if (year !== 'all' && (!date || String(date.getFullYear()) !== year)) return false;
      if (month !== 'all' && (!date || String(date.getMonth()) !== month)) return false;
      if (!words.length) return true;
      const haystack = [item.title, item.description, item.category, slugFor(item)].join(' ').toLowerCase();
      return words.every(word => haystack.includes(word));
    });
  }

  function storyMarkup(item) {
    const category = titleCase(normalCategory(item));
    const meta = [shortDate(item), timeLabel(item)].filter(Boolean).join(' · ');
    const slug = slugFor(item);
    return `<article class="archive-item">
      <div class="archive-item-main">
        <div class="archive-item-meta"><span class="archive-category">${esc(category)}</span>${meta ? `<span class="archive-meta-divider">|</span><span>${esc(meta)}</span>` : ''}</div>
        <a class="archive-title" href="${esc(item.url)}">${esc(item.title)}</a>
        ${item.description ? `<p class="archive-description">${esc(item.description)}</p>` : ''}
      </div>
      <div class="archive-engagement"><a class="archive-comments" data-slug="${esc(slug)}" href="${esc(item.url)}#comments-root" aria-label="View comments on ${esc(item.title)}">Comments…</a></div>
    </article>`;
  }

  function groupedMarkup(items) {
    const groups = [];
    let current = null;
    items.forEach(item => {
      const key = dayKey(item);
      if (!current || current.key !== key) {
        current = {key, label: dayLabel(item), items: []};
        groups.push(current);
      }
      current.items.push(item);
    });
    return groups.map(group => `<section class="archive-day">
      <h2 class="archive-day-date"><span>${esc(group.label)}</span><span class="archive-day-count">${group.items.length} ${group.items.length === 1 ? 'story' : 'stories'}</span></h2>
      <div class="archive-day-stories">${group.items.map(storyMarkup).join('')}</div>
    </section>`).join('');
  }

  const commentCache = new Map();
  const commentQueue = [];
  let commentWorkers = 0;
  const MAX_COMMENT_WORKERS = 6;

  function commentsText(payload) {
    const comments = Array.isArray(payload.comments) ? payload.comments : [];
    const count = comments.length;
    if (payload.closed) return count ? `${count} comment${count === 1 ? '' : 's'} · closed` : 'Comments closed';
    return `${count} comment${count === 1 ? '' : 's'}`;
  }

  async function commentPayload(slug) {
    if (commentCache.has(slug)) return commentCache.get(slug);
    const promise = fetch(`/api/comments?slug=${encodeURIComponent(slug)}`, {headers:{Accept:'application/json'}})
      .then(response => { if (!response.ok) throw new Error('Comment request failed'); return response.json(); });
    commentCache.set(slug, promise);
    try { return await promise; } catch (error) { commentCache.delete(slug); throw error; }
  }

  async function hydrateComment(node) {
    try {
      const payload = await commentPayload(node.dataset.slug || '');
      if (!node.isConnected) return;
      node.textContent = commentsText(payload || {});
      node.dataset.loaded = '1';
    } catch (_) {
      if (!node.isConnected) return;
      node.textContent = 'Comments unavailable';
      node.classList.add('is-muted');
      node.dataset.loaded = '1';
    }
  }

  function runCommentQueue() {
    while (commentWorkers < MAX_COMMENT_WORKERS && commentQueue.length) {
      const node = commentQueue.shift();
      if (!node || !node.isConnected) continue;
      commentWorkers += 1;
      hydrateComment(node).finally(() => { commentWorkers -= 1; runCommentQueue(); });
    }
  }

  function requestCommentCount(node) {
    if (!node || node.dataset.queued || node.dataset.loaded) return;
    node.dataset.queued = '1';
    commentQueue.push(node);
    runCommentQueue();
  }

  let commentObserver = null;
  function observeComments() {
    if (commentObserver) commentObserver.disconnect();
    const nodes = [...results.querySelectorAll('.archive-comments[data-slug]')];
    if (!('IntersectionObserver' in window)) { nodes.forEach(requestCommentCount); return; }
    commentObserver = new IntersectionObserver(entries => {
      entries.forEach(entry => {
        if (entry.isIntersecting) {
          commentObserver.unobserve(entry.target);
          requestCommentCount(entry.target);
        }
      });
    }, {rootMargin:'500px 0px'});
    nodes.forEach(node => commentObserver.observe(node));
  }

  function updateSectionButtons() {
    sections.querySelectorAll('[data-section]').forEach(button => {
      const on = button.dataset.section === activeSection;
      button.classList.toggle('is-active', on);
      button.setAttribute('aria-pressed', on ? 'true' : 'false');
    });
  }

  function render(reset = false) {
    if (reset) shown = PAGE;
    const found = filtered();
    const visible = found.slice(0, shown);
    summary.innerHTML = found.length === DATA.length
      ? `<strong>${found.length.toLocaleString('en-GB')}</strong> stories in the archive`
      : `<strong>${found.length.toLocaleString('en-GB')}</strong> of ${DATA.length.toLocaleString('en-GB')} stories match`;
    results.innerHTML = visible.length ? groupedMarkup(visible) : '<p class="archive-empty">No archived stories match those filters.</p>';
    more.hidden = shown >= found.length;
    if (!more.hidden) {
      const remaining = found.length - shown;
      more.textContent = `Load more stories (${remaining.toLocaleString('en-GB')} remaining)`;
    }
    observeComments();
  }

  function resetFilters() {
    input.value = '';
    yearSelect.value = 'all';
    monthSelect.value = 'all';
    activeSection = 'all';
    updateSectionButtons();
    render(true);
  }

  buildFacets();
  input.addEventListener('input', () => render(true));
  yearSelect.addEventListener('change', () => render(true));
  monthSelect.addEventListener('change', () => render(true));
  clearButton.addEventListener('click', resetFilters);
  sections.addEventListener('click', event => {
    const button = event.target.closest('[data-section]');
    if (!button) return;
    activeSection = button.dataset.section || 'all';
    updateSectionButtons();
    render(true);
  });
  more.addEventListener('click', () => { shown += PAGE; render(); });
  render();
})();
