# Reader experience setup

## Commercial objective

£12,000/month = 5 corporate partnerships at £1,200 + 10 section sponsors at £350 + 10 banners at £175 + 10 featured listings at £75. The private sales dashboard now shows these targets and agreed proposals separately from payment. My Rochdale points local businesses to the existing proposal form; that form now times out safely and preserves the pre-filled email fallback. Revenue requires signed, retained, paid customers.

## Implemented repairs

My Rochdale retains briefing → councillors and recorded votes → news → crime/policing. It rebuilds controls on every postcode lookup, fences late responses, preserves archive access if the ward map fails, and labels unavailable sources. Central Rochdale matches qualified place names rather than any town centre. Upcoming events combine dated published reporting with approved submissions, with duplicate filtering and valid published-page/source links.

Newsletter forms share a timed, single-submit controller across homepage and existing articles; every form requires explicit consent. Saved signups are distinguished from an unconfigured delivery provider. Subscriber exports use individual KV records so concurrent index updates cannot silently lose subscribers, with quoted CSV cells. Contact export remains editor-only.

New-story prompts exclude the article being read and unpublished records; feed requests time out instead of freezing polling. Related-story prompts include a discussion link only where comments exist. Swipe navigation ignores forms, links and selected text. Comment failures restore controls and only acknowledge a report that the server accepted. Articles expose links to sources, editorial standards, corrections and My Rochdale.

## Account setup Sarah may need to complete

Configuration presence and actual provider readiness are different. This repair does not confirm that Cloudflare secrets are configured or that a paid account is active.

| Service | Setup | Purpose |
| --- | --- | --- |
| Brevo | Configure `BREVO_API_KEY` and a positive numeric `BREVO_LIST_ID` in Cloudflare production. Verify the sending domain and sender, including SPF/DKIM, and configure unsubscribe handling. Import older consented signups through the protected export after checking suppression lists. Set up a daily campaign in Brevo. | Signup storage alone does not send newsletters. Existing local subscribers are not automatically reactivated or silently added to a new provider list. |
| Stripe | Configure `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, and recurring Price IDs `STRIPE_PRICE_CORPORATE`, `STRIPE_PRICE_SECTION`, `STRIPE_PRICE_BANNER`, `STRIPE_PRICE_DIRECTORY`. Match £1,200 / £350 / £175 / £75 per month respectively. Register the existing `/api/stripe-webhook` endpoint and verify its signature path using test mode before live billing. | Customer-approved advertiser subscription checkout. |
| OneSignal | Configure `ONESIGNAL_APP_ID` and `ONESIGNAL_REST_API_KEY`, with the site origin and existing service worker path. | Opt-in browser push. In-page new-story and related-story prompts do not need this account. |
| DfT Bus Open Data | Verify `BODS_API_KEY` in production if travel fails. | Borough bus disruption feed; does not cover every road or train movement. |
| Cloudflare KV | Keep `EVENTS_KV`, `EVENTS_ADMIN_TOKEN`, and a strong `EVENTS_IP_SALT` configured. Never place credentials in a public URL or repository. | Subscriber consent ledger and existing moderated services. |

The postcode lookup, MET Norway forecast, Environment Agency flood monitoring and Planning Data integrations already use public APIs without reader-facing keys. Councillor votes and GMP priorities retain their named, dated original sources. GMP's absence from Police.uk street-level data must not be represented as zero crime. Unverified incidents and other neighbourhoods are never substituted for postcode results.

## Next editorial improvements

- A brief daily newsletter selected by the editor, with local usefulness at the top and links to the complete articles.
- Follow-up coverage linked to earlier reporting so readers can see what changed after publication.
- Specific, civil questions at the end of community and service stories, plus newsdesk responses to useful local contributions.
- Ward-based reporting and local tips, with visible sources, publication dates, corrections and right-of-reply links.
- Real comment counts and actual audience measurements; no invented activity, claims of verification, testimonials or awards.

No provider account, purchase, subscription or campaign has been created by these code changes.
