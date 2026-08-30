// End-to-end test of the breaking publication path.
//
// Exercises the two Cloudflare Pages Functions against a real breaking.json
// produced by the watcher, plus the supersede handoff. Run:
//
//   node scraper/test_breaking_edge.cjs
//
// No network, no Cloudflare -- env.ASSETS is stubbed with the files as Pages
// would serve them.

const fs = require('fs');
const path = require('path');
const os = require('os');

const REPO = path.resolve(__dirname, '..');
const failures = [];

function check(condition, label) {
  if (condition) {
    console.log(`  ok   ${label}`);
  } else {
    console.log(`  FAIL ${label}`);
    failures.push(label);
  }
}

function section(title) {
  console.log(`\n${title}`);
}

/** Load an ES-module Function as CommonJS without a build step. */
function loadFunction(relPath) {
  const src = fs
    .readFileSync(path.join(REPO, relPath), 'utf8')
    .replace(/export async function onRequest/, 'async function onRequest');
  const file = path.join(os.tmpdir(), `fn_${Math.random().toString(36).slice(2)}.cjs`);
  fs.writeFileSync(file, `${src}\nmodule.exports = { onRequest };`);
  const mod = require(file);
  fs.unlinkSync(file);
  return mod.onRequest;
}

function makeEnv(files) {
  return {
    ASSETS: {
      fetch: async url => {
        const key = new URL(String(url)).pathname;
        if (!(key in files)) return { ok: false, status: 404, json: async () => ({}) };
        const body = files[key];
        return {
          ok: true,
          status: 200,
          json: async () => JSON.parse(JSON.stringify(body)),
          text: async () => JSON.stringify(body)
        };
      }
    }
  };
}

const NOW = new Date();
const iso = ms => new Date(NOW.getTime() + ms).toISOString().replace(/\.\d{3}Z$/, 'Z');

const breakingEntry = {
  slug: 'appeal-after-bury-road-collision',
  title: 'Appeal after Bury Road collision',
  quote:
    'Officers were called at around 4.15pm on Saturday 30 August to reports of a collision on Bury Road, Rochdale.\n\nAnyone with information is asked to contact police quoting log 1234.',
  source_name: 'Greater Manchester Police',
  source_url: 'https://www.gmp.police.uk/news/greater-manchester/news/appeal-bury-road/',
  source_published_at: iso(-10 * 60 * 1000),
  detected_at: iso(-9 * 60 * 1000),
  published_at: iso(-9 * 60 * 1000),
  expires_at: iso(18 * 3600 * 1000),
  area: 'rochdale',
  category: 'crime',
  image_url: 'assets/img/cards/police.jpg',
  byline: 'Rochdale Daily',
  attribution: 'Greater Manchester Police said:',
  status: 'live'
};

const heldEntry = {
  ...breakingEntry,
  slug: 'man-charged-after-rochdale-burglary',
  title: 'Man charged after Rochdale burglary',
  source_url: 'https://www.gmp.police.uk/news/greater-manchester/news/charged/',
  status: 'held',
  hold_reason: 'charge'
};

const staticFeed = {
  generated_at: iso(-3600 * 1000),
  articles: [
    {
      id: 'a1',
      slug: 'rochdale-library-reopens',
      title: 'Rochdale library reopens after refurbishment',
      published_at: iso(-2 * 3600 * 1000),
      first_published_at: iso(-2 * 3600 * 1000),
      source_url: 'https://www.rochdale.gov.uk/news/1'
    },
    {
      id: 'a2',
      slug: 'heywood-park-plans',
      title: 'Heywood park plans approved',
      published_at: iso(-5 * 3600 * 1000),
      first_published_at: iso(-5 * 3600 * 1000),
      source_url: 'https://www.rochdale.gov.uk/news/2'
    }
  ]
};

const blocklist = { slugs: [], source_urls: [], title_patterns: ['rochdale valiant'] };

const frontpage = loadFunction('functions/articles/frontpage.json.js');
const breakingPage = loadFunction('functions/breaking/[slug].js');

async function callFrontpage(files) {
  const env = makeEnv(files);
  const res = await frontpage({
    request: { url: 'https://rochdaledaily.co.uk/articles/frontpage.json' },
    env
  });
  return JSON.parse(await res.text());
}

async function callBreaking(slug, files) {
  return breakingPage({
    params: { slug },
    env: makeEnv(files),
    request: { url: `https://rochdaledaily.co.uk/breaking/${slug}` }
  });
}

(async () => {
  // ----------------------------------------------------------------------
  section('Front page: a breaking entry leads');
  // ----------------------------------------------------------------------
  let files = {
    '/articles/frontpage.json': staticFeed,
    '/story_blocklist.json': blocklist,
    '/breaking.json': { items: [breakingEntry, heldEntry] }
  };
  let out = await callFrontpage(files);

  check(out.articles.length === 3, `breaking card added to the feed (got ${out.articles.length})`);
  check(out.articles[0].title === breakingEntry.title, 'the breaking story leads the front page');
  check(out.articles[0].slug === '../breaking/appeal-after-bury-road-collision', 'card links to the breaking route');
  check(out.articles[0].kicker === 'BREAKING', 'card carries the BREAKING kicker');
  check(out.articles[0].frontpage_rank === 0, 'breaking card ranked first');
  check(out.articles[0].slot === 'lead', 'breaking card takes the lead slot');
  check(String(out.breaking || '').includes(breakingEntry.title), 'headline reaches the ticker');
  check(out.breaking_count === 1, 'breaking_count reports one');
  check(
    !out.articles.some(a => a.title === heldEntry.title),
    'a held story never reaches the front page'
  );
  check(
    out.articles[0].content_html.includes('Greater Manchester Police said:'),
    'attribution carried into the card body'
  );
  check(
    out.articles[0].content_html.includes('Officers were called'),
    "GMP's own words carried verbatim"
  );

  // ----------------------------------------------------------------------
  section('Front page: the ordinary feed still behaves');
  // ----------------------------------------------------------------------
  const noBreaking = await callFrontpage({
    '/articles/frontpage.json': staticFeed,
    '/story_blocklist.json': blocklist,
    '/breaking.json': { items: [] }
  });
  check(noBreaking.articles.length === 2, 'no breaking entries leaves the feed untouched');
  check(noBreaking.breaking_count === 0, 'breaking_count is zero');
  check(noBreaking.articles[0].slug === 'rochdale-library-reopens', 'newest ordinary story leads');

  const missingFile = await callFrontpage({
    '/articles/frontpage.json': staticFeed,
    '/story_blocklist.json': blocklist
  });
  check(missingFile.articles.length === 2, 'a missing breaking.json is survivable');

  // ----------------------------------------------------------------------
  section('Front page: expiry, blocklist and the canonical handover');
  // ----------------------------------------------------------------------
  const expired = { ...breakingEntry, expires_at: iso(-60 * 1000) };
  out = await callFrontpage({
    '/articles/frontpage.json': staticFeed,
    '/story_blocklist.json': blocklist,
    '/breaking.json': { items: [expired] }
  });
  check(out.articles.length === 2, 'an expired breaking entry is not served');

  const blockedByTitle = { ...breakingEntry, title: 'Rochdale Valiant launches media portal' };
  out = await callFrontpage({
    '/articles/frontpage.json': staticFeed,
    '/story_blocklist.json': blocklist,
    '/breaking.json': { items: [blockedByTitle] }
  });
  check(
    out.articles.length === 2,
    'a blocked subject cannot come back through the breaking door'
  );

  const feedWithCanonical = {
    ...staticFeed,
    articles: [
      {
        id: 'a3',
        slug: 'police-appeal-bury-road-collision-rochdale',
        title: 'Police appeal for witnesses after Bury Road collision',
        published_at: iso(-4 * 60 * 1000),
        first_published_at: iso(-4 * 60 * 1000),
        source_url: breakingEntry.source_url,
        source_urls: [breakingEntry.source_url]
      },
      ...staticFeed.articles
    ]
  };
  out = await callFrontpage({
    '/articles/frontpage.json': feedWithCanonical,
    '/story_blocklist.json': blocklist,
    '/breaking.json': { items: [breakingEntry] }
  });
  check(out.articles.length === 3, 'the story appears once, not twice');
  check(
    out.articles[0].slug === 'police-appeal-bury-road-collision-rochdale',
    'the canonical article wins once the pipeline has published it'
  );
  check(
    !out.articles.some(a => String(a.slug).startsWith('../breaking/')),
    'the breaking stub steps aside'
  );

  // ----------------------------------------------------------------------
  section('The breaking page renders');
  // ----------------------------------------------------------------------
  files = { '/breaking.json': { items: [breakingEntry, heldEntry] } };
  let res = await callBreaking('appeal-after-bury-road-collision', files);
  check(res.status === 200, 'live entry renders 200');
  let html = await res.text();
  check(html.includes('<h1>Appeal after Bury Road collision</h1>'), 'headline rendered');
  check(html.includes('Greater Manchester Police said:'), 'attribution rendered');
  check(html.includes('Officers were called at around 4.15pm'), 'statement rendered verbatim');
  check(html.includes('Anyone with information'), 'both statement paragraphs rendered');
  check(html.includes('noindex,follow'), 'stub is noindex so the canonical article ranks');
  check(html.includes('This is a developing story'), 'reader told it is developing');
  check(html.includes(breakingEntry.source_url), 'links back to the GMP statement');
  check(html.includes('rel="nofollow noopener noreferrer"'), 'outbound source link is safe');
  check(html.includes('news@rochdaledaily.co.uk'), 'right of reply offered');
  check(html.includes('No inference of guilt'), 'standard legal note present');

  res = await callBreaking('appeal-after-bury-road-collision.html', files);
  check(res.status === 200, 'the .html suffix the homepage generates also resolves');

  res = await callBreaking('man-charged-after-rochdale-burglary', files);
  check(res.status === 404, 'a held story is not readable at its URL either');

  res = await callBreaking('does-not-exist', files);
  check(res.status === 404, 'unknown slug 404s');

  res = await callBreaking('appeal-after-bury-road-collision', {
    '/breaking.json': { items: [{ ...breakingEntry, expires_at: iso(-60 * 1000) }] }
  });
  check(res.status === 404, 'an expired entry 404s rather than serving stale copy');

  // ----------------------------------------------------------------------
  section('Escaping');
  // ----------------------------------------------------------------------
  const nasty = {
    ...breakingEntry,
    title: 'Appeal <script>alert(1)</script> after incident',
    quote: 'Officers said "<img src=x onerror=alert(2)>" was seen.'
  };
  res = await callBreaking('appeal-after-bury-road-collision', {
    '/breaking.json': { items: [{ ...nasty, slug: 'appeal-after-bury-road-collision' }] }
  });
  html = await res.text();
  check(!html.includes('<script>alert(1)</script>'), 'headline HTML is escaped');
  check(!html.includes('<img src=x onerror='), 'statement HTML is escaped');
  check(html.includes('&lt;script&gt;'), 'escaped form present instead');

  out = await callFrontpage({
    '/articles/frontpage.json': staticFeed,
    '/story_blocklist.json': blocklist,
    '/breaking.json': { items: [{ ...nasty, slug: 'x' }] }
  });
  check(
    !out.articles[0].content_html.includes('<script>'),
    'feed content_html escapes injected markup'
  );

  // ----------------------------------------------------------------------
  section('Supersede handoff');
  // ----------------------------------------------------------------------
  const superseded = {
    ...breakingEntry,
    status: 'superseded',
    superseded_by: 'police-appeal-bury-road-collision-rochdale'
  };
  res = await callBreaking('appeal-after-bury-road-collision', {
    '/breaking.json': { items: [superseded] }
  });
  check(res.status === 301, 'a superseded stub 301s rather than 404ing');
  check(
    String(res.headers.get('location')).endsWith(
      '/articles/police-appeal-bury-road-collision-rochdale.html'
    ),
    'redirect points at the canonical article'
  );

  console.log('');
  if (failures.length) {
    console.log(`${failures.length} FAILED:`);
    failures.forEach(name => console.log(`  - ${name}`));
    process.exit(1);
  }
  console.log('all breaking edge tests passed');
})().catch(error => {
  console.error('test harness error:', error);
  process.exit(1);
});
