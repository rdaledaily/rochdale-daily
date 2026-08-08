// Rochdale Daily homepage feed override for Feel Good Festival weekend.
// This runs at /articles/frontpage.json and fixes the response at request time,
// so scraper runs cannot overwrite the editorial live lead.

const LIVE_UNTIL = Date.parse('2026-08-09T01:30:00+01:00');

function storyTime(article) {
  const value = article?.first_published_at || article?.published_at || article?.last_updated_at || '';
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function liveStory(nowIso) {
  return {
    id: 'feel-good-festival-2026-live',
    slug: '../feel-good-live',
    story_key: 'editorial:feel-good-festival-2026-live',
    title: 'LIVE: Rochdale Feel Good Festival 2026 — updates throughout the day',
    excerpt: 'Follow Rochdale Daily live from Feel Good Festival 2026, with Gabrielle, Ash, Starsailor, town-centre updates, timings, food and drink, travel and everything happening across Rochdale.',
    content_html: '<p>Follow Rochdale Daily’s rolling live coverage of Feel Good Festival 2026 throughout Saturday 8 August.</p>',
    area: 'rochdale',
    category: 'news',
    types: ['news'],
    source_kind: 'editorial',
    status: 'published',
    published_at: '2026-08-08T07:00:00Z',
    first_published_at: '2026-08-08T07:00:00Z',
    last_updated_at: nowIso,
    scraped_at: nowIso,
    source_name: 'Rochdale Daily',
    source_url: 'https://rochdaledaily.co.uk/feel-good-live.html',
    source_names: ['Rochdale Daily'],
    source_urls: ['https://rochdaledaily.co.uk/feel-good-live.html'],
    image_url: 'assets/img/cards/rochdale-town-hall.jpg',
    image_credit: 'Rochdale Daily',
    byline: 'Rochdale Daily',
    manual_article: true,
    editorial_lock: true,
    publication_route: 'editorial-live',
    rewrite_quality_checked: true,
    featured: true,
    force_lead: true,
    is_ongoing: true,
    ongoing_label: 'LIVE',
    update_count: 5,
    frontpage_rank: 0,
    frontpage_priority: 10000,
    slot: 'lead'
  };
}

export async function onRequest(context) {
  const { request, env } = context;
  const assetUrl = new URL(request.url);

  // ASSETS.fetch bypasses this Function and retrieves the generated static JSON.
  const upstream = await env.ASSETS.fetch(assetUrl);
  if (!upstream.ok) return upstream;

  let data;
  try {
    data = await upstream.json();
  } catch (_) {
    return upstream;
  }

  if (!data || !Array.isArray(data.articles)) {
    return new Response(JSON.stringify(data), {
      status: 200,
      headers: { 'content-type': 'application/json; charset=utf-8', 'cache-control': 'no-store' }
    });
  }

  const now = new Date();
  const nowIso = now.toISOString();
  let articles = data.articles.filter(a => a && a.id !== 'feel-good-festival-2026-live');

  // Stale featured flags must not make old articles outrank today's reporting.
  articles.sort((a, b) => storyTime(b) - storyTime(a));

  if (now.getTime() <= LIVE_UNTIL) {
    articles.unshift(liveStory(nowIso));
  }

  articles.forEach((article, index) => {
    article.frontpage_rank = index;
    article.frontpage_priority = index === 0 ? 10000 : Math.max(1, 1000 - index);
    article.slot = index === 0 ? 'lead' : index === 1 ? 'secondary-1' : index === 2 ? 'secondary-2' : '';
  });

  data.articles = articles;
  data.count = articles.length;
  data.generated_at = nowIso;

  if (articles[0]?.id === 'feel-good-festival-2026-live') {
    const liveTitle = articles[0].title;
    const existing = String(data.breaking || '').trim();
    data.breaking = liveTitle + (existing && !existing.includes(liveTitle) ? '     •     BREAKING     •     ' + existing : '');
  }

  return new Response(JSON.stringify(data), {
    status: 200,
    headers: {
      'content-type': 'application/json; charset=utf-8',
      'cache-control': 'no-store, no-cache, must-revalidate, max-age=0',
      'x-rd-homepage-fix': 'feel-good-live-v1'
    }
  });
}
