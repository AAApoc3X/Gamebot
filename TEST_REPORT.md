# Games Bot KAOS API update validation

Updated October 17, 2026. This package replaces parser-based rewards with KAOS kapi_minor, matching the Kill Tracker approach.

## Automated validation

85 tests pass, using local databases and simulated Discord, HTTP and KAOS responses.

Retained game checks cover wallets, balance conservation, duplicate transfers, midnight/24-hour claims, all 11 games, game ownership, frozen prize rules, inactivity refunds, after-win choices, unique lottery picks, bundle refunds, cutoff windows, highest/each payouts, Bingo, giveaways, purchase deduplication, secret Tip4Serv authentication, daylight-saving schedules and restart persistence.

API checks cover:

- Community-scoped API-key selection; generic keys require explicit guild binding.
- Encrypted community key storage; no key in settings export; wrong master-key failure.
- Community route isolation and whoami scope mismatch rejection.
- whoami request limits, 429 Retry-After and 5xx/network retry behavior.
- UID-based link lookups, nested response formats, missing links and unknown/mismatched responses.
- No stale positive eligibility after a failed forced lookup; no old role/manual fallback.
- Correct points, kit and item routes/bodies and stable idempotency keys.
- Repeated API attempts use identical reward body/key after a timeout.
- Restart resumes API sending state; accepted rewards are not replayed.
- Failed HTTP 4xx requires correction/manual retry; disabled delivery makes no request.
- Discord payload serialization and revised setup fields, owner/member access, persistent panels and game views.
- Exact original database schema migration preserves balances, pauses delivery, leaves old sent rewards alone, holds ambiguous parser records and safely converts unsent records. Reopening does not repeat migration or pause an already re-enabled API deployment.

Local compilation passes. The bot has 35 executable slash commands. Setup no longer accepts a Transactions channel, KAOS bot or linked role. API key entry and /link_check replace manual verify_link.

## Operational verification still required

No real Discord token or KAOS API key was used in these tests. The new code has not been uploaded to GitHub or deployed to the user's Railway service. A live link lookup and real points/kit/item test are required after deployment. KAOS response compatibility is checked conservatively; an unrecognized response holds eligibility rather than assuming a link.

See API_UPGRADE.md for deployment and migration steps. Preserve the existing /data volume. Existing Tip4Serv webhook behavior is retained and still needs a controlled live purchase check if not already verified.

API accepted means the credit/bank endpoint returned success. It does not mean a kit/item was claimed into inventory. Legacy parser outcomes cannot be deduplicated using a new API key, so held legacy rewards require owner review before release.

## Named server selection checks

Ten additional tests cover catalog isolation, no-charge missing selection, saved preferences, immutable destinations, after-win holds, reward ownership, bundle-wide destinations, choosing prize/server in either order, lottery/Bingo destinations, ticket-only giveaways and catalog changes after entry.

Guided settings tests cover default sections, native selectors, draft validation, stale settings conflicts, ownership checks, multi-reward bundles/products, odds input, cancellation, save confirmation and the 4,000-character API-key form. No live Discord/KAOS credentials were used.

Player-entry update: 14 additional tests cover manual number fields, reviewed Quick Pick persistence, quick-only/manual-only rules, duplicate purchase prevention, cancellation, account control ownership, stale modal submissions, frozen bundle prices, destination/reward choices, count-menu pagination and command schema changes.
