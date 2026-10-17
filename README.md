# Rust Games Bot

## Multiple named reward servers

Players can choose where kits, items and KAOS points are delivered. Owners manage the named KAOS slot list and before/after selection timing. See SERVER_SELECTION_GUIDE.md in this package for commands and migration behavior.


A separate Discord bot for Rust Console communities. It manages its own ticket currency and delivers in-game kit, item and KAOS-point rewards through the KAOS kapi_minor API, using community-specific API keys. It does not modify the Kill Tracker.

## Included

- Per-community wallets and an auditable, transactional ticket ledger.
- Renameable tickets; grants/removals, confirmed player transfers, free ticket giveaways.
- Persistent Games and Daily claim buttons. `/daily` and the button share one claim record.
- Daily reset at local midnight or after 24 hours; configurable claim channel and amount.
- Supply Drop, Pick a Crate, Scratch Card, Dice Challenge, Prize Wheel, Fishing, Treasure Dig, Higher or Lower, Minefield, Deal or Keep, and animated Rock Paper Scissors.
- Scheduled Rust World Lottery: three unique numbers, manual picks or Quick Pick, extra combinations, entry bundles, exact draw intervals/days/times and cutoffs.
- Community Bingo: paid cards, first row/column/diagonal wins, all tied winners, participation rewards for other entrants.
- Base, Elite and Premium prizes, multiple weighted kit/item alternatives and bundles; KAOS-point alternative; choice before entry or after winning.
- Configurable zero-match lottery returns and RPS loss/draw returns.
- Linked-only participation or allow-unlinked with rewards waiting for an API-confirmed KAOS link.
- Tip4Serv one-time payment webhook with a secret endpoint and payment-level deduplication.
- Owner/staff controls, durable results and reward queue, owner-confirmed real reward tests, read-only reports and guided Discord configuration.
- Original local GIF animations and their generator. No external animation service required.

## Deploy to Railway from GitHub

1. Create a NEW Discord application and bot for Games. Do not replace the Kill Tracker token.
2. Invite it as a Guild/server installation with `bot` and `applications.commands` scopes.
3. Upload the extracted contents of this folder to a NEW GitHub repository. Keep these files at the repository root, including Dockerfile, requirements.txt, railway.toml and the assets folder. Do not upload the ZIP itself. Never upload secrets or a database.
4. In Railway, create a project/service from that repository. The included Dockerfile runs Python 3.12 and installs requirements.
5. Add Railway Variables: `DISCORD_BOT_TOKEN`, and `DATA_DIR=/data`. For this PUBLIC hosted bot, leave `DISCORD_GUILD_ID` unset. It is an optional development-only shortcut for one guild.
6. Attach ONE persistent Railway volume mounted at `/data`. The database is `/data/games.sqlite3`. Keep this volume for future deployments. Run only ONE replica with this SQLite database.
7. Deploy. Keep the bot token private. `.env.example` is a reference; the program reads environment variables and does not automatically load a local .env file.
8. Follow OWNER_GUIDE.md for channel setup, prize names, links, tests and enabling games. Defaults are deliberately paused; no in-game items are sent until configured/enabled.

The bot uses standard guild intents. Privileged Message Content and Server Members intents are not required. Player links are looked up through the KAOS API. Ordinary messages and receipt screenshots never grant tickets.

Keep DISCORD_GUILD_ID consistent. With it set, commands register to that guild; with it absent, global commands are used and Discord propagation can take longer. Switching registration modes on an already used application can leave both sets visible; do not run multiple bot instances to fix it.

## KAOS API connection

This version uses the SAME kapi_minor API method as Kill Tracker. It never writes reward commands to a Transactions channel. Parser ingress, KAOS bot mentions and a linked Discord role are not required by Games Bot.

Each community owner creates a key at https://minor.ka0s.uk through KAOS `/kaos` → Integrations. Tick:

- `links:read` for player-link checks.
- `bank:kit` for kit rewards.
- `bank:item` for item rewards.
- `economy:credit` for KAOS-point rewards.

Two supported key-storage methods:

1. **Railway variable, same as Kill Tracker:** `KAOS_API_KEY_<DISCORD_GUILD_ID>`. For this owner's community: `KAOS_API_KEY_1212174166669922386`. The value is the KAOS token. Each additional community needs its own variable/key. This works without an encryption master key because Railway holds the secret. An optional generic `KAOS_API_KEY` works ONLY when `KAOS_API_GUILD_ID` explicitly matches the community; there is no implicit default guild.
2. **Public bot with owner self-service:** The host generates a Fernet key using `python tools/generate_encryption_key.py` and stores it as Railway `KAOS_KEY_ENCRYPTION_KEY`. Back it up privately and keep it unchanged across redeploys. Each server owner uses `/gamesadmin api action:set`; an owner-only Discord modal collects the KAOS token, validates it, and stores an encrypted, guild-bound copy in SQLite. Tokens never appear in slash-command parameters, public messages, configuration exports or reports. Discord still handles the form submission, so this is private key entry, not end-to-end storage outside Discord. Environment-managed keys take precedence and must be changed by the host in Railway.

The encryption key must be kept separate from the database backup and never committed to GitHub. Losing it makes saved tokens unreadable; owners must re-enter keys if it cannot be restored. Keep the host environment secure: a host with the master key and database can decrypt saved community tokens.

The client uses `Authorization: Bearer`, fixed base address `https://minor.ka0s.uk`, and these routes:

| Purpose | Route |
|---|---|
| Key check | GET `/v1/{guild}/whoami` |
| Player link | GET `/v1/{guild}/whois?uid=DISCORD_ID` |
| Kit bank deposit | POST `/v1/{guild}/{server_id}/bank/kit` |
| Item bank deposit | POST `/v1/{guild}/{server_id}/bank/item` |
| KAOS points | POST `/v1/{guild}/{server_id}/economy/credit` |

Mutation bodies use the Discord `uid` and a stable `idempotency_key` derived from the guild and immutable reward ID. Kit/item payloads include name and quantity; points use amount. Kits/items are bank deposits, not guaranteed immediate inventory delivery. HTTP success is reported as accepted; the player still needs to claim bank contents using KAOS.

`server_id` is the KAOS game-server number (S1 = 1), not the Discord community ID. Player links are cached for up to 15 minutes. Unknown/malformed link responses fail closed; role/manual records from the parser version are never used as proof of linking.

`/gamesadmin api action:check` checks the key; live `/gamesadmin test` verifies the particular reward permissions/names. Missing permissions or HTTP 4xx failures need correction and a manual retry. HTTP 429 honors Retry-After; network/5xx failures back off and reuse the original idempotency key. Local limits respect the supplied whoami 5/minute, lookup 120/minute, mutation 60/minute per community; other apps sharing KAOS can still consume those limits.

## Upgrade an existing parser deployment

See API_UPGRADE.md. Keep the same `/data` volume. Tickets, claims, game state, draws and ledger are preserved. The migration pauses reward delivery; add/check the key, inspect any held legacy sends, then explicitly enable delivery. Already-sent parser rewards are not replayed through the API.

## Tip4Serv ticket purchases

This integration uses Tip4Serv's documented `payment.success` webhook payload. It does NOT accept player-submitted receipts or ordinary channel messages as proof of payment.

1. In `/gamesadmin configure section:general`, set `purchase_store_id` to your actual Tip4Serv store ID. A store must map to exactly one Discord community in this bot.
2. In section `products`, choose Add entry and enter each Tip4Serv product code and tickets per unit. Prices are configured in Tip4Serv; the bot credits these ticket amounts times basket quantity.
3. Generate a random secret with at least 32 characters (recommended: `python -c "import secrets; print(secrets.token_urlsafe(48))"`). Add it as Railway `TIP4SERV_WEBHOOK_SECRET` and redeploy.
4. Enable Railway public networking on this service, using its provided PORT. Configure Tip4Serv's webhook URL as `https://YOUR-RAILWAY-DOMAIN/tip4serv/YOUR_SECRET`, event `payment.success`.
5. Treat the entire URL as a credential. The receiver checks its secret with a constant-time comparison. No unverified signature-header algorithm is assumed. HTTP access logging is disabled to avoid logging the secret URL. Rotate the secret and update the webhook if exposed.
6. Ensure checkout collects a linked Discord account; the payload must contain `data.user.discord_id`.
7. Test-mode events are acknowledged but DO NOT grant spendable tickets. Verify with a controlled live purchase before enabling public purchases. Reports should show one ticket credit even if Tip4Serv resends the payment.

Only one-time payments (`data.type = 1`) are supported. Subscriptions are ignored. Refunds/chargebacks need owner review and a reasoned ticket adjustment; spent or transferred balances are not automatically clawed back. Unconfigured products are ignored. Duplicate credits are prevented by store + payment ID + product, including new request IDs on seller resends. Purchase credits and all game reward deliveries are separate: rewards always use the KAOS API.

The selected store ID and products are owner settings. Confirm that your proposed paid-game products are permitted by your store/payment providers before selling them.

## Local checks

```
pip install -r requirements.txt
python -m unittest discover -s tests -v
python bot.py
```

For animation regeneration only, install Pillow then run `python tools/build_animations.py`. GIF assets are already included; Pillow is not needed to run the bot.

## Reliability and operational limits

- Transactions keep entry charges and results together, and stable IDs stop duplicate daily claims, purchase credits, game rewards and event payouts.
- Unfinished choice games resume with `/resume`. After 15 minutes without a move: Higher/Lower and Minefield collect the current earned tier, Deal or Keep keeps its offer, and unplayed RPS/Crate/Dig entries receive their full entry cost back.
- Open paid draws still settle if new games are paused. Turn off delivery separately to hold in-game rewards. After downtime, the existing open draw settles; the next draw is scheduled from the current time. Empty missed draws are not invented.
- API retries reuse the original immutable reward idempotency key. `accepted` means KAOS returned success; it is not proof of in-game bank claiming. Legacy parser records keep their original sent/held status and are never blindly replayed.
- Only held legacy parser rewards require read-only Transactions reconciliation. It scans the last 1,000 messages; absence from that window is not proof no post existed. Do not release an already processed parser reward to the API: API idempotency cannot deduplicate a prior parser command.
- Linked-only eligibility and all in-game reward delivery require a recognized KAOS API link. There is no role or owner-manual override of API verification.
- Rule changes apply to new sessions/draws. Existing entries keep a full settings snapshot. Panel descriptions refresh when `/gamesadmin panel` is run again.
- This is a tested software package, not a live deployment. Actual Discord permissions, KAOS API response compatibility and reward behavior and Tip4Serv purchase setup need the live verification in the owner guide.

## References

- Discord Python API: https://discordpy.readthedocs.io/en/stable/interactions/api.html
- Tip4Serv webhook payload: https://docs.tip4serv.com/webhooks-developers-only/webhook-data-structure
- Tip4Serv webhook setup: https://docs.tip4serv.com/webhooks-developers-only/configure-a-webhook
- KAOS API reference: community owner supplied kapi_minor API routes, permissions, fields and limits in the project conversation.
- Fernet authenticated encryption: https://cryptography.io/en/stable/fernet/
