# Primary-source claim verification: rollout status

The forward-only gate in `scraper/article_gate.py` now requires `claim_evidence.evidence_issues(article)` to return no problems for new automated articles.

## Evidence contract
```json
{
  "primary_source_verified": true,
  "evidence_sources": [
    {
      "url": "https://www.rochdale.gov.uk/news/article/example",
      "captured_text": "A directly fetched, preserved extract of the primary source containing the reported facts."
    }
  ],
  "verified_claims": [
    {
      "claim": "A complete factual assertion in the article",
      "source_url": "https://www.rochdale.gov.uk/news/article/example",
      "supporting_excerpt": "An exact passage copied from the captured source material."
    }
  ]
}
```
This contract checks presence, allowed primary-source domains and exact passage matches. It does **not** independently fetch webpages, authenticate captures, determine if the passage actually entails the claim, detect contradictory sources, or guarantee full claim coverage. The boolean attestation is not independent evidence.

## Operational warning
Until each automated producer provides evidence_sources, verified_claims and an attestation from a trusted verification process, newly ingested automated articles will be rejected. This is intentional fail-closed behaviour, but may reduce or stop automated new article output. Monitor the publishing logs and editorial supply before considering the rollout complete.

## Next engineering requirements
- Collect primary-source pages through a server-side allowlisted fetcher with timestamp, provenance and content hash, and avoid untrusted client-supplied attestations.
- Break drafted text into factual claims, independently compare each claim to captured passages (including negation, names, dates, amounts and legal status), and route uncertain claims to human review.
- Keep evidence and editorial rejections in a durable private review queue rather than dropping them; provide correction/retry workflow.
- Verify upstream workflow actually calls the final article gate; add an integration fixture for successful primary-source publishing and a fixture for failed evidence.
- Audit manual and sponsored editorial routes separately.
- Confirm deployed workflow success and reader-facing freshness after release.
