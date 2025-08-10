# Rochdale Daily (static)

Fast, SEO-friendly static site with:
- Dark theme + yellow breaking ticker
- Date/time (left) • Weather (centre) • Search with suggestions (right)
- Mobile-first, responsive, accessible
- Articles loaded from `articles.json` (your pipeline writes here)
- Category/list pages via query params (e.g. `category.html?area=Heywood` or `?type=crime`)
- Post page at `post.html?slug=...`
- robots.txt + sitemap.xml

## Pipeline
1) Scrape Facebook via Playwright → rewrite with GPT → **append item** to `articles.json` (keep valid JSON).
2) Include fields:
```
{
  "id":"YYYY-name",
  "title":"...",
  "slug":"...",
  "excerpt":"...",
  "content_html":"<p>Safe HTML body…</p>",
  "area":"Heywood|Rochdale|Littleborough|Milnrow",
  "types":["crime|politics|education|announcements|appeals"],
  "published_at":"2025-08-10T09:10:00Z",
  "image_url":"assets/img/your-optimised-image.jpg",
  "source_url":"https://facebook.com/...",
  "quotes":["Short quote 1","Short quote 2"],
  "breaking":true|false
}
```
3) Optimise images to ~1200×675 JPG 70–85% quality. Place under `assets/img/` and reference via `image_url`.

## Local preview
Open `index.html` in your browser. For search/ticker to work, serve with a static server (VS Code Live Server or `python -m http.server`).

## Deploy (GitHub → Cloudflare Pages)
- Commit folder contents to your repo root.
- Cloudflare Pages project → Framework: None → Build command: `None` → Output: `/`.
- Set your custom domain `rochdaledaily.co.uk` to this Pages project.

## Notes
- GA4: add your measurement ID by replacing `window.__GA4_ID__` and include gtag if desired.
- Ads: replace `.ad` placeholders with your ad tags.