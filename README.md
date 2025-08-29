Got it ✅ — here’s a **full clean rewrite** of your project spec / README for **Rochdale Daily**, tightened for clarity, SEO, and production use.

---

# 📰 Rochdale Daily (Static Site)

A fast, privacy-conscious, SEO-friendly local news site built with a **static frontend** and an **automated scraping + rewriting pipeline**.

---

## ✨ Features

* Dark theme with **yellow breaking news ticker**
* Header:

  * **Date/time** (left)
  * **Weather widget** (centre)
  * **Search with autocomplete** (right)
* **Mobile-first**, responsive, accessible UI
* Articles loaded dynamically from `articles.json`
* Category/list pages via query parameters:

  * `category.html?area=Heywood`
  * `category.html?type=crime`
* Single post view: `post.html?slug=...`
* `robots.txt` + `sitemap.xml` for SEO & Google News indexing

---

## ⚙️ Pipeline Overview

1. **Scrape** Facebook group posts with Playwright + session cookie.
2. **Rewrite** into professional articles with GPT.
3. **Classify & enrich** with metadata:

   * Location (e.g. Heywood, Milnrow, Rochdale, Littleborough)
   * Category (crime, politics, education, announcements, appeals, etc.)
   * Quotes (selected reader comments)
   * Breaking flag
4. **Optimise images**

   * If post includes images → download & compress
   * If not → generate AI placeholder
   * Size: 1200×675px, JPG at \~80% quality
   * Save to `/assets/img/`
5. **Write to JSON**

   * Append or overwrite `articles.json` in repo root
   * Must remain a valid JSON array

---

## 📦 Article JSON Format

Each article in `articles.json` must follow this structure:

```json
{
  "id": "20250829-heywood-burglary",
  "title": "Burglary in Heywood sparks police appeal",
  "slug": "heywood-burglary",
  "excerpt": "Police are appealing for witnesses after a burglary in Heywood...",
  "content_html": "<p>Full safe HTML body here...</p>",
  "area": "Heywood",
  "types": ["crime", "appeals"],
  "published_at": "2025-08-29T09:10:00Z",
  "image_url": "assets/img/heywood-burglary.jpg",
  "source_url": "https://facebook.com/groups/.../post/123",
  "quotes": [
    "This has really shaken up the community.",
    "We need more CCTV around here."
  ],
  "breaking": false
}
```

---

## 🖥 Local Preview

* Open `index.html` in a browser.
* For ticker/search (which require `fetch`), serve via a local static server:

  * VS Code Live Server extension, or
  * `python -m http.server`

---

## 🚀 Deployment (GitHub → Cloudflare Pages)

1. Commit repo root to GitHub.
2. Connect repo to **Cloudflare Pages**.

   * Framework: **None**
   * Build command: **None**
   * Output directory: `/`
3. Point custom domain: `rochdaledaily.co.uk` → Cloudflare Pages project.

---

## 📊 Analytics

* Add GA4 tracking by replacing `window.__GA4_ID__` with your Measurement ID.
* Include `gtag.js` snippet in `index.html` if desired.

---

## 📝 Notes

* Always ensure `articles.json` is a valid JSON array.
* Slugs should be **lowercase, dash-separated, URL-safe**.
* IDs should follow `YYYYMMDD-slug` format to guarantee uniqueness.
* Sanitise all `content_html` (no `<script>`, `<iframe>`, or inline JS) to prevent XSS.
* Update `sitemap.xml` automatically from `articles.json` so Google indexes new stories quickly.

---

⚡ This is now a **production-ready spec**: it tells developers (or your future self) exactly how the site is structured, how the pipeline works, and what rules every article must follow.

Would you like me to go ahead and **write the `sitemap.xml` generator script** that pulls from `articles.json`? That’ll lock in the SEO side.

