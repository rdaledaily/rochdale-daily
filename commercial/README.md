# Rochdale Daily commercial data

This directory provides stable identities for advertisers and campaigns without replacing the live `/adverts.json` delivery system.

## Adding the 55-business cohort

1. Give every business a permanent `advertiser_id` in the form `adv-business-name`.
2. Add the public business record to `advertisers.json`.
3. Create a campaign in `campaigns.json` only when dates, destination URL and targeting are known.
4. Create or obtain artwork, then add the actual live placement to `/adverts.json`.
5. The placement `id` must remain unique for the life of the measurement history. Never recycle an old placement id for a different creative or business.
6. Keep at least one broad/non-targeted placement available while the initial cohort is being measured so the experiment does not optimise itself too early.

The CSV file in this directory is an intake template. `areas` should use a pipe-separated list such as `rochdale|heywood`; use `borough-wide` when appropriate.

## Public-repository privacy rule

This GitHub repository is public. Store only information that the business itself publishes for customers. Do not commit private contact names, unpublished email addresses, billing information, payment references, consent evidence, authentication information or reader-level tracking data.

## Identity model

`advertiser_id` identifies the business. `campaign_id` identifies one commercial campaign. The existing placement `id` in `/adverts.json` identifies one delivered creative/slot combination and is the measurement key used by the current tracker.

A business can therefore have many campaigns, and each campaign can have many placements, without losing historical reporting when artwork or targeting changes.

## Statuses

Advertisers: `prospect`, `needs-details`, `active`, `paused`, `former`.

Campaigns: `draft`, `needs-details`, `approved`, `scheduled`, `live`, `paused`, `completed`, `rejected`.

A business that has gone away should be marked `former`, not deleted, so historic reports still resolve correctly.
