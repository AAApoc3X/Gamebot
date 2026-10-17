# Update Games Bot to KAOS API delivery

This is a complete replacement package. It retains all games, tickets and existing settings, while replacing parser rewards and manual link checks with kapi_minor.

## What to upload

Extract the updated Games Bot ZIP. Upload ALL contents inside its rust-games-bot folder to the MAIN LEVEL of your existing Games Bot GitHub repository. Replace matching files and keep the assets/tools/tests folders. In particular, add the new `kaos_api.py` and replace `delivery.py`, `storage.py`, `engine.py`, `configuration.py`, `bot.py` and `requirements.txt`. Uploading the complete folder contents is easiest. Do not upload the ZIP, tokens, .env files or database.

Keep your existing Railway service, Discord application/token and `/data` persistent volume. Do not create another bot identity. Back up a populated volume before a major migration. Run only one replica; stop the old deployment before running the new one so parser and API workers are never active together.

## Railway variables

Keep:

- `DISCORD_BOT_TOKEN`: Existing Games Bot token, unchanged.
- `DATA_DIR`: `/data`, unchanged.
- Existing Tip4Serv settings, if used.

For your community, add:

- `KAOS_API_KEY_1212174166669922386`: Your KAOS community API key.

That is the Discord community ID you supplied for AAAPOCALYPSE. If configuring another community, use its own Discord server ID in the variable name. Each key must be scoped to that community. Do not paste the token into GitHub, a public channel or this chat.

Required KAOS permissions: `links:read`, and whichever reward types you use: `bank:kit`, `bank:item`, `economy:credit`. You may use the existing Kill Tracker's community key if it has those permissions, or create a separately labeled Games Bot key with only needed scopes. Shared applications consume shared KAOS rate limits.

Leave `DISCORD_GUILD_ID` unset for the public bot.

For other server owners to submit their own community keys without asking you to add Railway variables, generate a Fernet encryption key privately using `python tools/generate_encryption_key.py`. Set its output in Railway as `KAOS_KEY_ENCRYPTION_KEY`, save a private backup, and keep it stable on future deploys. They can then use `/gamesadmin api action:set`. Their keys are validated, encrypted, bound to their guild and excluded from settings/reports. You do not need this master key if all community keys are managed through Railway variables.

## After redeployment

1. Wait for the bot to come online. Command synchronization replaces the previous command list; refresh Discord if old setup fields remain visible.
2. Existing Games/Daily/Results/Admin channels stay configured. Setup now has only these channels and server_id; it no longer asks for Transactions, KAOS bot or linked role.
3. The migration pauses reward delivery. Your tickets, ledger, claims, active sessions and draws remain intact. New API-key/role settings do not erase these records.
4. Run `/gamesadmin api action:check`.
5. Run `/link_check player:NAME` for a KAOS-linked member.
6. Run `/gamesadmin test player:NAME tier:base reward:points`, review and confirm the REAL test reward.
7. Enable delivery with `/gamesadmin enable games:false delivery:true` during testing. The report should show accepted; confirm the player's KAOS balance/bank. Note that enabling delivery also resumes other pending rewards, so inspect the report first.
8. Review any migration_hold records in `/gamesadmin report`. Old sent parser rewards are never resent automatically. Unsent pending/choice rewards transfer to API. Old failed/sending/uncertain records require owner review of KAOS and old Transactions history before release.
9. When satisfied, use `/gamesadmin enable games:true delivery:true`. Games already enabled at migration keep their enabled state; explicitly set games:false if you want to close entry during testing. Open paid events always settle even while new entries are paused.

## Duplicate prevention

Each new API reward has one stable idempotency key, derived from its community and reward ID. Retries after a timeout/restart keep the same target, server, reward payload and key. API success is recorded as accepted. Kits/items are KAOS bank deposits, so accepted does not prove an in-game inventory claim.

An API key cannot deduplicate a reward that was previously issued by a parser message. That is why uncertain legacy sends are held. Inspect the old Transactions channel and KAOS before using legacy_release; otherwise use legacy_mark_sent after review.

## Secrets and exports

Never include actual keys in reports. Guided settings never display saved keys. Encrypted saved keys are stored in a separate database table; environment keys are never written to the database. A volume backup may contain encrypted keys, so protect it and keep the encryption master key separate.
