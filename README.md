# Rust Games Bot

A separate Discord bot for Rust Console communities. It manages its own ticket currency and sends in-game kit, item and KAOS-point rewards only through KAOS log-parser commands in the Transactions channel. It does not modify the Kill Tracker.

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
- Linked-only participation or allow-unlinked with delivery held until staff/role verification.
- Tip4Serv one-time payment webhook with a secret endpoint and payment-level deduplication.
- Owner/staff controls, durable results and reward queue, owner-confirmed real reward tests, JSON reports and configuration export/import.
- Original local GIF animations and their generator. No external animation service required.

## Deploy to Railway from GitHub

1. Create a NEW Discord application and bot for Games. Do not replace the Kill Tracker token.
2. Invite it as a Guild/server installation with `bot` and `applications.commands` scopes.
3. Upload the extracted contents of this folder to a NEW GitHub repository. Keep these files at the repository root, including Dockerfile, requirements.txt, railway.toml and the assets folder. Do not upload the ZIP itself. Never upload secrets or a database.
4. In Railway, create a project/service from that repository. The included Dockerfile runs Python 3.12 and installs requirements.
5. Add Railway Variables: `DISCORD_BOT_TOKEN`, `DISCORD_GUILD_ID` (your Discord community ID, for quick guild command registration), and `DATA_DIR=/data`.
6. Attach ONE persistent Railway volume mounted at `/data`. The database is `/data/games.sqlite3`. Keep this volume for future deployments. Run only ONE replica with this SQLite database.
7. Deploy. Keep the bot token private. `.env.example` is a reference; the program reads environment variables and does not automatically load a local .env file.
8. Follow OWNER_GUIDE.md for channel setup, prize names, links, tests and enabling games. Defaults are deliberately paused; no in-game items are sent until configured/enabled.

The bot uses standard guild intents. Privileged Message Content and Server Members intents are not required. It fetches individual member records for link-role checks when needed. Ordinary messages and receipt screenshots never grant tickets.

Keep DISCORD_GUILD_ID consistent. With it set, commands register to that guild; with it absent, global commands are used and Discord propagation can take longer. Switching registration modes on an already used application can leave both sets visible; do not run multiple bot instances to fix it.

## KAOS prerequisites

In KAOS, run `/admin-channels` and set the Transactions channel to the same channel selected in Games setup. Enable parser ingress with `/set parser_use on`. Give Games permission to view, read history and send messages there. KAOS must be present and able to read the channel. Players must complete KAOS `/link` before KAOS will process rewards.

Commands are posted exactly in this form (preceded by a separate reward-ID line):

```
[KAOS][ADD][<@DISCORD_PLAYER_ID>][1]=[KIT][existing_kit_name][1] <@KAOS_BOT_ID>
[KAOS][ADD][<@DISCORD_PLAYER_ID>][1]=[ITEM][stone.hatchet][1] <@KAOS_BOT_ID>
[KAOS][ADD][<@DISCORD_PLAYER_ID>][1]=[POINTS][100] <@KAOS_BOT_ID>
```

The last mention is intentional: KAOS requires an external bot to ping it for parser commands. Server ID means the KAOS game-server number (S1 = 1), not the Discord guild ID. No KAOS API key is used by this bot. Ticket balances/returns/transfers stay within Games Bot, not KAOS points.

## Tip4Serv ticket purchases

This integration uses Tip4Serv's documented `payment.success` webhook payload. It does NOT accept player-submitted receipts or ordinary channel messages as proof of payment.

1. In `/gamesadmin configure section:general`, set `purchase_store_id` to your actual Tip4Serv store ID. A store must map to exactly one Discord community in this bot.
2. In section `products`, map Tip4Serv product IDs to tickets per unit, e.g. `{"104":10,"105":50}`. Prices are configured in Tip4Serv; the bot credits these ticket amounts times basket quantity.
3. Generate a random secret with at least 32 characters (recommended: `python -c "import secrets; print(secrets.token_urlsafe(48))"`). Add it as Railway `TIP4SERV_WEBHOOK_SECRET` and redeploy.
4. Enable Railway public networking on this service, using its provided PORT. Configure Tip4Serv's webhook URL as `https://YOUR-RAILWAY-DOMAIN/tip4serv/YOUR_SECRET`, event `payment.success`.
5. Treat the entire URL as a credential. The receiver checks its secret with a constant-time comparison. No unverified signature-header algorithm is assumed. HTTP access logging is disabled to avoid logging the secret URL. Rotate the secret and update the webhook if exposed.
6. Ensure checkout collects a linked Discord account; the payload must contain `data.user.discord_id`.
7. Test-mode events are acknowledged but DO NOT grant spendable tickets. Verify with a controlled live purchase before enabling public purchases. Reports should show one ticket credit even if Tip4Serv resends the payment.

Only one-time payments (`data.type = 1`) are supported. Subscriptions are ignored. Refunds/chargebacks need owner review and a reasoned ticket adjustment; spent or transferred balances are not automatically clawed back. Unconfigured products are ignored. Duplicate credits are prevented by store + payment ID + product, including new request IDs on seller resends. Purchase credits and all game reward deliveries are separate: rewards always use KAOS parser messages.

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
- A parser message has no documented idempotency key or reliable success callback. `sent` means Discord accepted the post, NOT that KAOS delivered the item. A crash/timeout during posting becomes `uncertain`, with no automatic resend. Owner must reconcile against Transactions and KAOS before retrying.
- The SDK/network may have ambiguous outcomes; this implementation avoids promising exactly-once external delivery. Reconciliation scans the last 1,000 messages, so absence from that window is not proof a post never existed.
- The local linked role/manual record is evidence maintained by the server owner. It is not an API query and does not create a KAOS link. Only choose a role controlled by your real KAOS linking workflow; never use a self-assignable role. If no such role exists, use owner verification after checking KAOS.
- Rule changes apply to new sessions/draws. Existing entries keep a full settings snapshot. Panel descriptions refresh when `/gamesadmin panel` is run again.
- This is a tested software package, not a live deployment. Actual Discord permissions, KAOS parser behavior and Tip4Serv purchase setup need the live verification in the owner guide.

## References

- Discord Python API: https://discordpy.readthedocs.io/en/stable/interactions/api.html
- Tip4Serv webhook payload: https://docs.tip4serv.com/webhooks-developers-only/webhook-data-structure
- Tip4Serv webhook setup: https://docs.tip4serv.com/webhooks-developers-only/configure-a-webhook
- KAOS parser reference: formats and setup instructions supplied by the community owner in the project conversation.
