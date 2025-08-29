# Rochdale Daily (static)

Fast, SEO-friendly static news site:

- Dark theme + yellow breaking ticker
- Date/time (left) • Weather (centre) • Search with suggestions (right)
- Mobile-first, responsive, accessible
- Articles loaded from `articles.json` (pipeline writes here)
- Category/list pages: `category.html?area=Heywood` or `?type=crime`
- Post page: `post.html?slug=...`
- robots.txt + sitemap.xml

## Pipeline
1. Scrape Facebook via Playwright → rewrite with GPT → overwrite `articles.json` (must remain valid JSON array).
2. Each article object must include:
```json
{
  "id":"20250829-heywood-burglary",
  "title":"...",
  "slug":"heywood-burglary",
  "excerpt":"...",
  "content_html":"<p>Safe HTML body…</p>",
  "area":"Heywood|Rochdale|Littleborough|Milnrow",
  "types":["crime","politics","education","announcements","appeals"],
  "published_at":"2025-08-29T09:10:00Z",
  "image_url":"assets/img/heywood-burglary.jpg",
  "source_url":"https://facebook.com/...",
  "quotes":["Short quote 1","Short quote 2"],
  "breaking":false
}
