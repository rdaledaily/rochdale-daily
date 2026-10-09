# Forward editorial and search quality standard

Effective for newly published automated reports from 9 October 2026. Historical articles are preserved; fixing an old article is a correction, not a fresh publication.

## Reporting checklist
1. The headline must match the opening paragraphs and the verified event. Avoid clickbait or a claim that the article does not substantiate.
2. Capture the original source URL, publication time, named organisation, and relevant evidence before writing. Search-engine snippets and competitor articles are leads, not independently verified primary facts.
3. Check all names, dates, places, numbers, job titles, legal allegations, casualties and quotations against the original document or identifiable reporting. Do not manufacture eyewitness statements or quotations.
4. For disputed claims, attribute them and seek a response where appropriate. Clearly distinguish allegations, charges, convictions and verdicts. Escalate sensitive criminal, medical and death reports to editorial review.
5. The first two paragraphs must explain the verified local news: who, what, where and when, with why/how where established. Keep short stories short when evidence is thin.
6. Do not pad reports with invented reaction, hollow commentary or repetitive generic phrasing. Do not copy competitors' distinctive wording.
7. Name the reporter or editorial desk honestly, show original published date/time and material update time; do not change publication dates just to appear new.
8. Editorial coverage and advertising must remain separate. Label advertorials clearly, verify claims and never present them as independently reported news.
9. Use accurate, relevant pictures with permission/credit and meaningful alt text; don't imply stock or generated images depict a real incident.
10. Validate HTML title, H1, canonical link, unique summary, NewsArticle schema where appropriate, sitemap inclusion and valid images. SEO must never override accuracy.

## Automation
- scraper/editorial_review.py reports conservative warning signals. It does not establish truth.
- scraper/article_gate.py rejects *new* automated articles with those signals. Manual and sponsored copy need their own editor approval and advertising review.
- CI executes scraper/test_editorial_review.py.
- The gate currently logs rejections; it does not provide a durable editorial-review queue. A dedicated queue, detailed source evidence and fact-by-fact verification are next steps.
- Google Search Console indexing reports, Search performance, Lighthouse/Core Web Vitals, Bing Webmaster Tools and Google News appearance require their own live measurements. Never infer a perfect SEO score from static code.
