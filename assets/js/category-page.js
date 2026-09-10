(() => {
  'use strict';

  const PAGE_SIZE = 12;
  const CATEGORY_LABELS = {
    news: 'Latest',
    crime: 'Crime',
    politics: 'Politics',
    business: 'Business',
    sport: 'Sport',
    health: 'Health',
    education: 'Education',
    environment: 'Environment',
    transport: 'Transport',
    traffic: 'Traffic',
    events: 'Events',
    community: 'Community',
    showbiz: 'Showbiz',
    announcements: 'Announcements',
    appeals: 'Appeals'
  };
  const AREA_LABELS = {
    rochdale: 'Rochdale',
    heywood: 'Heywood',
    middleton: 'Middleton',
    littleborough: 'Littleborough',
    milnrow: 'Milnrow'
  };
  const STATIC_CATEGORY_ROUTES = new Set([
    'business', 'community', 'crime', 'education', 'environment', 'events',
    'health', 'news', 'politics', 'sport', 'traffic', 'transport'
  ]);

  const els = {
    title: document.getElementById('page-title'),
    standfirst: document.getElementById('page-standfirst'),
    results: document.getElementById('story-results'),
    summary: document.getElementById('results-summary'),
    loading: document.getElementById('loading-state'),
    error: document.getElementById('error-state'),
    empty: document.getElementById('empty-state'),
    search: document.getElementById('story-search'),
    loadMore: document.getElementById('load-more'),
    loadWrap: document.getElementById('load-more-wrap')
  };

  const params = new URLSearchParams(window.location.search);
  const rawCategory = firstParam(params, ['type', 'category', 'section']);
  const rawArea = firstParam(params, ['area', 'town', 'place']);
  const selectedCategory = normaliseSlug(rawCategory);
  const selectedArea = normaliseSlug(rawArea);

  let allStories = [];
  let filteredStories = [];
  let visibleCount = PAGE_SIZE;
  let searchTerm = '';

  function firstParam(searchParams, names) {
    for (const name of names) {
      const value = searchParams.get(name);
      if (value && value.trim()) return value.trim();
    }
    return '';
  }

  function normaliseSlug(value) {
    return String(value || '')
      .trim()
      .toLowerCase()
      .replace(/&/g, 'and')
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/^-+|-+$/g, '');
  }

  function titleCase(value) {
    return String(value || '')
      .split('-')
      .filter(Boolean)
      .map(part => part.charAt(0).toUpperCase() + part.slice(1))
      .join(' ');
  }

  function categoryLabel(value) {
    return CATEGORY_LABELS[value] || titleCase(value);
  }

  function areaLabel(value) {
    return AREA_LABELS[value] || titleCase(value);
  }

  function storyCategory(story) {
    return normaliseSlug(story.category || (Array.isArray(story.types) ? story.types[0] : ''));
  }

  function storyArea(story) {
    return normaliseSlug(story.area || story.town || story.location || '');
  }

  function isPublished(story) {
    const status = normaliseSlug(story.status || '');
    return !status || status === 'published' || status === 'live';
  }

  function timestamp(story) {
    const value = story.published_at || story.first_published_at || story.scraped_at || '';
    const time = Date.parse(value);
    return Number.isFinite(time) ? time : 0;
  }

  function formatDate(value) {
    const date = new Date(value || '');
    if (!Number.isFinite(date.getTime())) return '';
    return new Intl.DateTimeFormat('en-GB', {
      day: 'numeric', month: 'long', year: 'numeric', hour: '2-digit', minute: '2-digit'
    }).format(date);
  }

  function imageUrl(story) {
    const value = String(story.image_url || story.img || '').trim();
    if (!value) return '';
    if (/^(?:https?:)?\/\//i.test(value) || value.startsWith('/')) return value;
    return `/${value.replace(/^\.\//, '')}`;
  }

  function articleHref(story) {
    const direct = String(story.url || '').trim();
    if (direct.startsWith('/articles/') || direct.startsWith('articles/')) {
      return direct.startsWith('/') ? direct : `/${direct}`;
    }
    const slug = normaliseSlug(story.slug || '');
    if (slug) return `/articles/${encodeURIComponent(slug)}.html`;
    const id = String(story.id || story.story_key || '').trim();
    return `/post.html?id=${encodeURIComponent(id)}`;
  }

  function buildFilterHref(category, area) {
    const query = new URLSearchParams();
    const normalCategory = normaliseSlug(category);
    const normalArea = normaliseSlug(area);
    if (normalCategory && normalCategory !== 'news') query.set('type', normalCategory);
    if (normalArea) query.set('area', normalArea);
    const suffix = query.toString();
    return suffix ? `/category.html?${suffix}` : '/category.html';
  }

  function preferredRoute() {
    if (selectedCategory && !selectedArea && STATIC_CATEGORY_ROUTES.has(selectedCategory)) {
      return `/news/${selectedCategory}.html`;
    }
    if (!selectedCategory && !selectedArea) return '/category.html';
    return buildFilterHref(selectedCategory, selectedArea);
  }

  function setCanonical(url) {
    let canonical = document.querySelector('link[rel="canonical"]');
    if (!canonical) {
      canonical = document.createElement('link');
      canonical.rel = 'canonical';
      document.head.appendChild(canonical);
    }
    canonical.href = new URL(url, window.location.origin).href;
  }

  function setDescription(text) {
    let meta = document.querySelector('meta[name="description"]');
    if (!meta) {
      meta = document.createElement('meta');
      meta.name = 'description';
      document.head.appendChild(meta);
    }
    meta.content = text;
  }

  function configurePageIdentity() {
    let heading = 'Latest news';
    let description = 'The latest verified local reporting from Rochdale Daily.';

    if (selectedCategory && selectedArea) {
      heading = `${categoryLabel(selectedCategory)} in ${areaLabel(selectedArea)}`;
      description = `${categoryLabel(selectedCategory)} stories and updates for ${areaLabel(selectedArea)} from Rochdale Daily.`;
    } else if (selectedCategory) {
      heading = selectedCategory === 'news' ? 'Latest news' : categoryLabel(selectedCategory);
      description = `${categoryLabel(selectedCategory)} news and updates from across Rochdale borough.`;
    } else if (selectedArea) {
      heading = `${areaLabel(selectedArea)} news`;
      description = `Latest local reporting, public-service information and community updates for ${areaLabel(selectedArea)}.`;
    }

    if (els.title) els.title.textContent = heading;
    if (els.standfirst) els.standfirst.textContent = description;
    document.title = `${heading} | Rochdale Daily`;
    setDescription(description);
    setCanonical(preferredRoute());

    document.querySelectorAll('[data-filter-category]').forEach(link => {
      const value = normaliseSlug(link.dataset.filterCategory);
      link.href = buildFilterHref(value, selectedArea);
      if (value === selectedCategory || (!selectedCategory && value === 'news')) link.setAttribute('aria-current', 'page');
      else link.removeAttribute('aria-current');
    });

    document.querySelectorAll('[data-filter-area]').forEach(link => {
      const value = normaliseSlug(link.dataset.filterArea);
      link.href = buildFilterHref(selectedCategory, value);
      if ((!value && !selectedArea) || (value && value === selectedArea)) link.setAttribute('aria-current', 'page');
      else link.removeAttribute('aria-current');
    });
  }

  function createMedia(story, className) {
    const media = document.createElement('div');
    media.className = className;
    const src = imageUrl(story);
    if (!src) {
      media.classList.add('is-empty');
      media.setAttribute('aria-hidden', 'true');
      return media;
    }
    const img = document.createElement('img');
    img.src = src;
    img.alt = String(story.image_alt || story.title || '');
    img.loading = className.includes('lead') ? 'eager' : 'lazy';
    img.decoding = 'async';
    img.addEventListener('error', () => {
      img.remove();
      media.classList.add('is-empty');
      media.setAttribute('aria-hidden', 'true');
    }, { once: true });
    media.appendChild(img);
    return media;
  }

  function storyMeta(story) {
    const pieces = [];
    const area = storyArea(story);
    const category = storyCategory(story);
    if (area) pieces.push(areaLabel(area));
    if (category) pieces.push(categoryLabel(category));
    const date = formatDate(story.published_at || story.first_published_at || story.scraped_at);
    if (date) pieces.push(date);
    return pieces.join(' · ');
  }

  function createLead(story) {
    const article = document.createElement('article');
    article.className = 'rd-lead-story';
    article.appendChild(createMedia(story, 'rd-lead-media'));

    const copy = document.createElement('div');
    copy.className = 'rd-lead-copy';

    const label = document.createElement('div');
    label.className = 'rd-story-label';
    label.textContent = categoryLabel(storyCategory(story) || 'news');

    const h2 = document.createElement('h2');
    const link = document.createElement('a');
    link.href = articleHref(story);
    link.textContent = story.title || 'Untitled story';
    h2.appendChild(link);

    const dek = document.createElement('p');
    dek.className = 'rd-story-dek';
    dek.textContent = story.excerpt || '';

    const meta = document.createElement('div');
    meta.className = 'rd-story-meta';
    meta.textContent = storyMeta(story);

    copy.append(label, h2);
    if (dek.textContent) copy.appendChild(dek);
    if (meta.textContent) copy.appendChild(meta);
    article.appendChild(copy);
    return article;
  }

  function createCard(story) {
    const article = document.createElement('article');
    article.className = 'rd-story-card';
    article.appendChild(createMedia(story, 'rd-card-media'));

    const label = document.createElement('div');
    label.className = 'rd-story-label';
    label.textContent = categoryLabel(storyCategory(story) || 'news');

    const h2 = document.createElement('h2');
    const link = document.createElement('a');
    link.href = articleHref(story);
    link.textContent = story.title || 'Untitled story';
    h2.appendChild(link);

    const dek = document.createElement('p');
    dek.className = 'rd-story-dek';
    dek.textContent = story.excerpt || '';

    const meta = document.createElement('div');
    meta.className = 'rd-story-meta';
    meta.textContent = storyMeta(story);

    article.append(label, h2);
    if (dek.textContent) article.appendChild(dek);
    if (meta.textContent) article.appendChild(meta);
    return article;
  }

  function applyFilters() {
    filteredStories = allStories.filter(story => {
      if (selectedCategory && selectedCategory !== 'news' && storyCategory(story) !== selectedCategory) return false;
      if (selectedArea && storyArea(story) !== selectedArea) return false;
      if (searchTerm) {
        const haystack = `${story.title || ''} ${story.excerpt || ''} ${story.area || ''} ${story.category || ''}`.toLowerCase();
        if (!haystack.includes(searchTerm)) return false;
      }
      return true;
    });
    visibleCount = PAGE_SIZE;
    render();
  }

  function render() {
    if (!els.results) return;
    if (els.loading) els.loading.hidden = true;
    if (els.error) els.error.hidden = true;
    if (els.empty) els.empty.hidden = filteredStories.length > 0;
    els.results.replaceChildren();

    const total = filteredStories.length;
    if (els.summary) {
      const scope = selectedArea ? ` in ${areaLabel(selectedArea)}` : '';
      els.summary.textContent = `${total.toLocaleString('en-GB')} ${total === 1 ? 'story' : 'stories'}${scope}`;
    }

    if (!total) {
      if (els.loadWrap) els.loadWrap.hidden = true;
      return;
    }

    const visible = filteredStories.slice(0, visibleCount);
    els.results.appendChild(createLead(visible[0]));

    if (visible.length > 1) {
      const grid = document.createElement('div');
      grid.className = 'rd-story-grid';
      visible.slice(1).forEach(story => grid.appendChild(createCard(story)));
      els.results.appendChild(grid);
    }

    if (els.loadWrap) els.loadWrap.hidden = visibleCount >= total;
    if (els.loadMore) els.loadMore.textContent = `Load more (${Math.max(0, total - visibleCount).toLocaleString('en-GB')} remaining)`;
  }

  async function loadStories() {
    configurePageIdentity();
    try {
      const response = await fetch('/articles.json', { headers: { Accept: 'application/json' } });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const payload = await response.json();
      const stories = Array.isArray(payload) ? payload : (Array.isArray(payload.articles) ? payload.articles : []);
      allStories = stories
        .filter(story => story && typeof story === 'object' && isPublished(story) && String(story.title || '').trim())
        .sort((a, b) => timestamp(b) - timestamp(a));
      applyFilters();
    } catch (error) {
      console.error('Rochdale Daily category route failed to load', error);
      if (els.loading) els.loading.hidden = true;
      if (els.error) els.error.hidden = false;
      if (els.empty) els.empty.hidden = true;
      if (els.results) els.results.replaceChildren();
      if (els.summary) els.summary.textContent = '';
      if (els.loadWrap) els.loadWrap.hidden = true;
    }
  }

  if (els.search) {
    let timer = 0;
    els.search.addEventListener('input', () => {
      window.clearTimeout(timer);
      timer = window.setTimeout(() => {
        searchTerm = els.search.value.trim().toLowerCase();
        applyFilters();
      }, 120);
    });
  }

  if (els.loadMore) {
    els.loadMore.addEventListener('click', () => {
      visibleCount += PAGE_SIZE;
      render();
      const cards = els.results.querySelectorAll('.rd-story-card');
      const target = cards[Math.max(0, cards.length - PAGE_SIZE)];
      if (target) target.scrollIntoView({ block: 'nearest' });
    });
  }

  loadStories();
})();
