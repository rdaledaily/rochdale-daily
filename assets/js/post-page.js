(() => {
  'use strict';

  const els = {
    loading: document.getElementById('loading-state'),
    error: document.getElementById('error-state'),
    errorDetail: document.getElementById('error-detail'),
    article: document.getElementById('legacy-article'),
    kicker: document.getElementById('article-kicker'),
    title: document.getElementById('article-title'),
    dek: document.getElementById('article-dek'),
    byline: document.getElementById('article-byline'),
    published: document.getElementById('article-published'),
    updated: document.getElementById('article-updated'),
    hero: document.getElementById('article-hero'),
    heroImg: document.getElementById('article-image'),
    heroCaption: document.getElementById('article-image-caption'),
    body: document.getElementById('article-body'),
    sources: document.getElementById('article-sources'),
    sourceList: document.getElementById('article-source-list'),
    legal: document.getElementById('article-legal'),
    legalText: document.getElementById('article-legal-text'),
    replyText: document.getElementById('article-reply-text'),
    permanent: document.getElementById('permanent-link'),
    share: document.getElementById('share-article'),
    shareStatus: document.getElementById('share-status'),
    related: document.getElementById('related-stories'),
    relatedGrid: document.getElementById('related-grid'),
    recent: document.getElementById('recent-stories'),
    recentGrid: document.getElementById('recent-grid'),
    comments: document.getElementById('comments-root')
  };

  let currentStory = null;
  let canonicalUrl = window.location.href;

  function normaliseSlug(value) {
    return String(value || '')
      .trim()
      .toLowerCase()
      .replace(/\.html?$/i, '')
      .replace(/&/g, 'and')
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/^-+|-+$/g, '');
  }

  function cleanIdentifier(value) {
    let cleaned = String(value || '').trim();
    if (!cleaned) return '';
    try { cleaned = decodeURIComponent(cleaned); } catch (_) {}
    try {
      if (/^https?:\/\//i.test(cleaned)) cleaned = new URL(cleaned).pathname;
    } catch (_) {}
    cleaned = cleaned.replace(/[?#].*$/, '').replace(/^.*\//, '').replace(/\.html?$/i, '');
    return cleaned.trim();
  }

  function getIdentifiers() {
    const params = new URLSearchParams(window.location.search);
    const values = ['id', 'slug', 'story', 'story_key', 'article']
      .map(key => params.get(key))
      .filter(Boolean)
      .map(cleanIdentifier)
      .filter(Boolean);
    if (window.location.hash.length > 1) values.push(cleanIdentifier(window.location.hash.slice(1)));
    return [...new Set(values)];
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

  function findStory(stories, identifiers) {
    if (!identifiers.length) return null;
    for (const identifier of identifiers) {
      const literal = identifier.toLowerCase();
      const slugged = normaliseSlug(identifier);
      const match = stories.find(story => {
        const ids = [story.id, story.story_key]
          .filter(value => value !== undefined && value !== null)
          .map(value => String(value).trim().toLowerCase());
        if (ids.includes(literal)) return true;
        return normaliseSlug(story.slug || '') === slugged;
      });
      if (match) return match;
    }
    return null;
  }

  function safeUrl(value, options = {}) {
    const raw = String(value || '').trim();
    if (!raw) return '';
    if (raw.startsWith('#')) return options.allowHash ? raw : '';
    try {
      const url = new URL(raw, window.location.origin);
      const allowed = ['http:', 'https:'];
      if (options.allowMailto) allowed.push('mailto:');
      return allowed.includes(url.protocol) ? url.href : '';
    } catch (_) {
      return '';
    }
  }

  function imageUrl(story) {
    const value = String(story.image_url || story.img || '').trim();
    if (!value) return '';
    if (/^(?:https?:)?\/\//i.test(value) || value.startsWith('/')) return value;
    return `/${value.replace(/^\.\//, '')}`;
  }

  function articlePath(story) {
    const direct = String(story.url || '').trim();
    if (direct.startsWith('/articles/') || direct.startsWith('articles/')) {
      return direct.startsWith('/') ? direct : `/${direct}`;
    }
    const slug = normaliseSlug(story.slug || '');
    return slug ? `/articles/${encodeURIComponent(slug)}.html` : window.location.pathname + window.location.search;
  }

  function categoryPath(story) {
    const category = normaliseSlug(story.category || (Array.isArray(story.types) ? story.types[0] : 'news')) || 'news';
    return `/news/${encodeURIComponent(category)}.html`;
  }

  function categoryLabel(story) {
    const value = normaliseSlug(story.category || (Array.isArray(story.types) ? story.types[0] : 'news')) || 'news';
    return value === 'news' ? 'News' : value.split('-').map(part => part.charAt(0).toUpperCase() + part.slice(1)).join(' ');
  }

  function formatDate(value) {
    const date = new Date(value || '');
    if (!Number.isFinite(date.getTime())) return '';
    return new Intl.DateTimeFormat('en-GB', {
      day: 'numeric', month: 'long', year: 'numeric', hour: '2-digit', minute: '2-digit'
    }).format(date);
  }

  function setMeta(selector, attribute, value) {
    let element = document.querySelector(selector);
    if (!element) {
      element = document.createElement('meta');
      const match = selector.match(/meta\[(name|property)="([^"]+)"\]/);
      if (!match) return;
      element.setAttribute(match[1], match[2]);
      document.head.appendChild(element);
    }
    element.setAttribute(attribute, value);
  }

  function setCanonical(path) {
    let canonical = document.querySelector('link[rel="canonical"]');
    if (!canonical) {
      canonical = document.createElement('link');
      canonical.rel = 'canonical';
      document.head.appendChild(canonical);
    }
    canonicalUrl = new URL(path, window.location.origin).href;
    canonical.href = canonicalUrl;
  }

  function setSeo(story) {
    const title = String(story.title || 'Article');
    const description = String(story.excerpt || '').trim() || 'Local news from Rochdale Daily.';
    const path = articlePath(story);
    const image = imageUrl(story);
    document.title = `${title} | Rochdale Daily`;
    setCanonical(path);
    setMeta('meta[name="description"]', 'content', description);
    setMeta('meta[property="og:title"]', 'content', title);
    setMeta('meta[property="og:description"]', 'content', description);
    setMeta('meta[property="og:type"]', 'content', 'article');
    setMeta('meta[property="og:url"]', 'content', canonicalUrl);
    if (image) setMeta('meta[property="og:image"]', 'content', safeUrl(image) || image);

    const oldLd = document.getElementById('legacy-newsarticle-jsonld');
    if (oldLd) oldLd.remove();
    const ld = document.createElement('script');
    ld.id = 'legacy-newsarticle-jsonld';
    ld.type = 'application/ld+json';
    ld.textContent = JSON.stringify({
      '@context': 'https://schema.org',
      '@type': 'NewsArticle',
      headline: title,
      description,
      datePublished: story.published_at || story.first_published_at || undefined,
      dateModified: story.last_updated_at || story.published_at || story.first_published_at || undefined,
      mainEntityOfPage: canonicalUrl,
      image: image ? [safeUrl(image) || image] : undefined,
      author: { '@type': 'Organization', name: story.byline || 'Rochdale Daily' },
      publisher: { '@type': 'Organization', name: 'Rochdale Daily' }
    });
    document.head.appendChild(ld);
  }

  function sanitiseArticleHtml(html) {
    const template = document.createElement('template');
    template.innerHTML = String(html || '');

    template.content.querySelectorAll('script, style, iframe, object, embed, form, input, button, textarea, select, meta, link').forEach(node => node.remove());
    template.content.querySelectorAll('*').forEach(node => {
      [...node.attributes].forEach(attribute => {
        const name = attribute.name.toLowerCase();
        if (name.startsWith('on') || name === 'style' || name === 'srcdoc') node.removeAttribute(attribute.name);
      });

      if (node.hasAttribute('href')) {
        const href = safeUrl(node.getAttribute('href'), { allowHash: true, allowMailto: true });
        if (href) {
          node.setAttribute('href', href);
          if (/^https?:\/\//i.test(href) && new URL(href).origin !== window.location.origin) {
            node.setAttribute('rel', 'noopener noreferrer');
            node.setAttribute('target', '_blank');
          }
        } else {
          node.removeAttribute('href');
        }
      }

      if (node.hasAttribute('src')) {
        const src = safeUrl(node.getAttribute('src'));
        if (src) node.setAttribute('src', src);
        else node.removeAttribute('src');
      }

      if (node.tagName === 'IMG') {
        node.setAttribute('loading', 'lazy');
        node.setAttribute('decoding', 'async');
        if (!node.hasAttribute('alt')) node.setAttribute('alt', '');
      }
    });
    return template.content.cloneNode(true);
  }

  function appendPlainTextBody(text) {
    const paragraphs = String(text || '').split(/\n{2,}/).map(value => value.trim()).filter(Boolean);
    paragraphs.forEach(value => {
      const p = document.createElement('p');
      p.textContent = value;
      els.body.appendChild(p);
    });
  }

  function renderSources(story) {
    const names = Array.isArray(story.source_names) ? story.source_names.filter(Boolean) : [];
    const urls = Array.isArray(story.source_urls) ? story.source_urls.filter(Boolean) : [];
    if (!names.length && story.source_name) names.push(story.source_name);
    if (!urls.length && story.source_url) urls.push(story.source_url);

    const count = Math.max(names.length, urls.length);
    if (!count || !els.sources || !els.sourceList) {
      if (els.sources) els.sources.hidden = true;
      return;
    }

    els.sourceList.replaceChildren();
    const seen = new Set();
    for (let i = 0; i < count; i += 1) {
      const name = String(names[i] || names[0] || 'Original source').trim();
      const href = safeUrl(urls[i] || urls[0] || '');
      const key = `${name}|${href}`;
      if (seen.has(key)) continue;
      seen.add(key);

      const li = document.createElement('li');
      if (href) {
        const link = document.createElement('a');
        link.href = href;
        link.textContent = name;
        link.target = '_blank';
        link.rel = 'noopener noreferrer';
        li.appendChild(link);
      } else {
        li.textContent = name;
      }
      els.sourceList.appendChild(li);
    }
    els.sources.hidden = els.sourceList.children.length === 0;
  }

  function renderLegal(story) {
    const disclaimer = String(story.legal_disclaimer || '').trim();
    const reply = String(story.right_to_reply || '').trim();
    if (!disclaimer && !reply) {
      els.legal.hidden = true;
      return;
    }
    els.legalText.textContent = disclaimer;
    els.legalText.hidden = !disclaimer;
    els.replyText.textContent = reply;
    els.replyText.hidden = !reply;
    els.legal.hidden = false;
  }

  function createRelatedCard(story) {
    const article = document.createElement('article');
    article.className = 'rd-related-card';
    const h3 = document.createElement('h3');
    const link = document.createElement('a');
    link.href = articlePath(story);
    link.textContent = story.title || 'Untitled story';
    h3.appendChild(link);
    const p = document.createElement('p');
    const area = String(story.area || '').trim();
    const date = formatDate(story.published_at || story.first_published_at);
    p.textContent = [area, date].filter(Boolean).join(' · ');
    article.appendChild(h3);
    if (p.textContent) article.appendChild(p);
    return article;
  }

  function renderRelated(story, stories) {
    if (!els.related || !els.relatedGrid) return;
    const category = normaliseSlug(story.category || '');
    const area = normaliseSlug(story.area || '');
    const currentKey = String(story.id || story.story_key || story.slug || '');

    const candidates = stories
      .filter(item => String(item.id || item.story_key || item.slug || '') !== currentKey)
      .map(item => {
        let score = 0;
        if (category && normaliseSlug(item.category || '') === category) score += 2;
        if (area && normaliseSlug(item.area || '') === area) score += 1;
        return { item, score };
      })
      .filter(entry => entry.score > 0)
      .sort((a, b) => b.score - a.score || timestamp(b.item) - timestamp(a.item))
      .slice(0, 4)
      .map(entry => entry.item);

    els.relatedGrid.replaceChildren();
    candidates.forEach(item => els.relatedGrid.appendChild(createRelatedCard(item)));
    els.related.hidden = candidates.length === 0;
  }

  function renderRecent(stories) {
    if (!els.recent || !els.recentGrid) return;
    els.recentGrid.replaceChildren();
    stories.slice(0, 4).forEach(story => els.recentGrid.appendChild(createRelatedCard(story)));
    els.recent.hidden = stories.length === 0;
  }

  function mountComments(story) {
    if (!els.comments) return;
    const slug = normaliseSlug(story.slug || '');
    if (!slug) {
      els.comments.hidden = true;
      return;
    }
    els.comments.dataset.slug = slug;
    els.comments.dataset.category = normaliseSlug(story.category || 'news');
    els.comments.hidden = false;
    const script = document.createElement('script');
    script.src = '/assets/js/article-comments.js';
    script.defer = true;
    document.body.appendChild(script);
  }

  function renderStory(story, stories) {
    currentStory = story;
    setSeo(story);

    const category = categoryLabel(story);
    els.kicker.textContent = category;
    els.kicker.href = categoryPath(story);
    els.title.textContent = story.title || 'Untitled story';
    els.dek.textContent = story.excerpt || '';
    els.dek.hidden = !String(story.excerpt || '').trim();
    els.byline.textContent = story.byline || 'Rochdale Daily';

    const published = formatDate(story.published_at || story.first_published_at || story.scraped_at);
    els.published.textContent = published ? `Published ${published}` : '';
    els.published.hidden = !published;

    const updatedRaw = story.last_updated_at || '';
    const updated = formatDate(updatedRaw);
    const publishedTime = Date.parse(story.published_at || story.first_published_at || '');
    const updatedTime = Date.parse(updatedRaw);
    const showUpdated = updated && Number.isFinite(updatedTime) && (!Number.isFinite(publishedTime) || updatedTime - publishedTime > 60000);
    els.updated.textContent = showUpdated ? `Updated ${updated}` : '';
    els.updated.hidden = !showUpdated;

    const image = imageUrl(story);
    if (image) {
      els.heroImg.src = image;
      els.heroImg.alt = String(story.image_alt || story.title || '');
      const credit = String(story.image_credit || '').trim();
      els.heroCaption.textContent = credit ? `Image: ${credit}` : '';
      els.heroCaption.hidden = !credit;
      els.hero.hidden = false;
      els.heroImg.addEventListener('error', () => { els.hero.hidden = true; }, { once: true });
    } else {
      els.hero.hidden = true;
    }

    els.body.replaceChildren();
    if (story.content_html) {
      els.body.appendChild(sanitiseArticleHtml(story.content_html));
    } else if (story.body) {
      appendPlainTextBody(story.body);
    } else if (story.excerpt) {
      appendPlainTextBody(story.excerpt);
    }

    renderSources(story);
    renderLegal(story);
    renderRelated(story, stories);

    const permanentPath = articlePath(story);
    els.permanent.href = permanentPath;
    els.permanent.hidden = !normaliseSlug(story.slug || '');

    if (els.loading) els.loading.hidden = true;
    if (els.error) els.error.hidden = true;
    if (els.article) els.article.hidden = false;
    mountComments(story);
  }

  function showError(stories, identifiers, error) {
    if (els.loading) els.loading.hidden = true;
    if (els.article) els.article.hidden = true;
    if (els.error) els.error.hidden = false;
    if (els.comments) els.comments.hidden = true;

    if (error) {
      els.errorDetail.textContent = 'The article data could not be loaded. Please try the archive or homepage.';
    } else if (!identifiers.length) {
      els.errorDetail.textContent = 'This legacy article address needs an article id or slug. Recent stories are shown below.';
    } else {
      els.errorDetail.textContent = `No published story matched “${identifiers[0]}”. It may have moved or been withdrawn.`;
    }
    renderRecent(stories);
  }

  async function loadArticle() {
    const identifiers = getIdentifiers();
    try {
      const response = await fetch('/articles.json', { headers: { Accept: 'application/json' } });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const payload = await response.json();
      const stories = (Array.isArray(payload) ? payload : (Array.isArray(payload.articles) ? payload.articles : []))
        .filter(story => story && typeof story === 'object' && isPublished(story) && String(story.title || '').trim())
        .sort((a, b) => timestamp(b) - timestamp(a));
      const story = findStory(stories, identifiers);
      if (!story) {
        showError(stories, identifiers, null);
        return;
      }
      renderStory(story, stories);
    } catch (error) {
      console.error('Rochdale Daily legacy article route failed to load', error);
      showError([], identifiers, error);
    }
  }

  if (els.share) {
    els.share.addEventListener('click', async () => {
      if (!currentStory) return;
      const shareData = { title: currentStory.title || 'Rochdale Daily', url: canonicalUrl };
      try {
        if (navigator.share) {
          await navigator.share(shareData);
          if (els.shareStatus) els.shareStatus.textContent = 'Share sheet opened.';
        } else if (navigator.clipboard && window.isSecureContext) {
          await navigator.clipboard.writeText(canonicalUrl);
          if (els.shareStatus) els.shareStatus.textContent = 'Article link copied.';
        } else {
          window.prompt('Copy this article link:', canonicalUrl);
          if (els.shareStatus) els.shareStatus.textContent = 'Article link ready to copy.';
        }
      } catch (error) {
        if (error && error.name !== 'AbortError' && els.shareStatus) els.shareStatus.textContent = 'Could not share this article.';
      }
    });
  }

  loadArticle();
})();
