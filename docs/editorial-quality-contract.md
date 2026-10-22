# Rochdale Daily publication contract

The newsroom applies this contract to the active feed and the published HTML archive. Archive repairs preserve original publication dates; an old report must never become new news merely because it was corrected.

## Reporting and language

For non-crime stories, explain what happened, who was affected, which services or organisations were involved, where it happened, the established outcome or next step, and its relevance to the public. Use this as a natural narrative rather than a compulsory list of headings. End with a relevant reader takeaway and a specific invitation to comment. Missing facts must stay missing until sourced. Crime and court stories are excluded from this engagement structure.

Review spelling, British usage, grammar, syntax, readability, paragraph order, headline/body agreement and accidental combinations of different incidents. Automated archive text edits are exact, conservative and bound to the reviewed content hash. Preserve people, quantities, direct quotations, legal status and uncertainty. Substantive factual discrepancies require source verification; model findings alone are not evidence.

## Evidence and background

Seek useful additional reporting on the same incident and relevant factual context. Historical comparisons are separately dated and attributed; their people and outcomes must never be merged into the current event. Search snippets and posts on X are leads, not corroboration.

Crime rates require a verified measure, reporting period, geographical boundary and denominator. Missing data is not zero crime. GMP priorities must refer to the actual local team and its official dated source. Developer background must concern the correct company and distinguish independently documented findings from marketing or anonymous reviews. A speaker's relevant public role, expertise and declared interests can be explained; private motives cannot be invented.

Do not infer suicide from an unexplained death, describe methods, or label a place a hotspot without reliable public-health evidence. Use verified prevention context without sensationalising the location.

## Geography and category

Use the main subject's location, not a place mentioned incidentally in the body. Broad places such as Middleton and Heywood do not identify one ward. Exact ward names and unambiguous localities can supply evidence; insufficient evidence leaves a story at borough level pending verification. Never force an uncertain ward assignment to satisfy a completeness count.

Categories follow the deterministic headline policy in `scraper/story_integrity_audit.py`. Public-service attendance alone does not establish a crime. Keep the feed, article schema, topic pages and ward indexes in agreement.

## Links, images and search

Every indexable article needs relevant outgoing and incoming article links covering its area or topic. Exclude redirects and non-canonical duplicates as link targets. Generate the archive, area and topic indexes after story repairs.

Image priority is relevant internal photograph, relevant licensed Wikimedia Commons image, then a labelled place card. A rejected image must not reappear on the next build. Identify file images and illustrations clearly, retain attribution and licence/source links, and never imply that an unrelated person or premises was involved in an offence.

Use descriptive titles and summaries, one main headline, canonical article URLs, consistent NewsArticle metadata, valid image URLs and meaningful alternative text. Retain truthful publication/modification dates. There is no keyword-density target or ranking guarantee.

## Update times

Display each dated update in Europe/London, including the date and the applicable BST or GMT label. Preserve exact UTC timestamps in machine-readable time elements where available. Legacy UK wall-time labels receive a zone without a second offset conversion. Never relabel a winter time as BST or invent an exact instant for an ambiguous legacy clock-change time.

## Audit records

`archive_quality_reviews.json` records content-bound editorial and image reviews. `archive_quality_report.json` records coverage, applied conservative edits, category changes, unresolved geography, semantic findings, article links and rendered SEO findings. A successful model response is a completed review, not a declaration that every reported fact has independently been verified. The dedicated complete-archive workflow checks coverage and orphan status before reporting success.
