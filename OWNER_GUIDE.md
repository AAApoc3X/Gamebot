# Rust Games Bot owner guide

Use this guide after the separate Games Bot is online in your Discord community. Games and KAOS API delivery start paused. Your existing Kill Tracker is separate and is not changed.

## 1 Set up channels

Create/select existing text channels with these purposes. Names are examples.

| Channel | Purpose | Player permissions | Games Bot permissions |
|---|---|---|---|
| Games channel | Play games, view balances, give tickets and claim prizes | View Channel, Send Messages, Read Message History, Use Application Commands | View Channel, Send Messages, Read Message History, Embed Links, Attach Files |
| Daily claim channel | Daily claim button and/or `/daily` | View Channel, Read Message History; allow Send Messages and Use Application Commands if using `/daily` | View Channel, Send Messages, Read Message History |
| Results channel | Lottery numbers, Bingo and giveaway results | View Channel, Read Message History; can deny posting | View Channel, Send Messages, Read Message History |
| Admin channel | Private owner/staff controls | Deny View Channel to ordinary members; allow authorized staff | View Channel, Send Messages, Read Message History, Embed Links, Attach Files |

Allow the bot explicitly even where @everyone cannot send messages. A channel selects WHERE commands run; a role controls WHO may run them.

Run `/gamesadmin setup` and select:

- `games_channel`: Channel where members play games and run game commands.
- `daily_channel`: Channel with the free daily claim button/command. It may be the same as Games channel.
- `results_channel`: Where draw results and reminders appear.
- `admin_channel`: Your private management channel.
- `server_id`: KAOS game-server number, e.g. S1 = 1. This is not your Discord server ID.

## 2 Connect KAOS and decide who can play

Create your community-scoped KAOS API key at https://minor.ka0s.uk through `/kaos` → Integrations. Select `links:read`, plus `bank:kit` for kits, `bank:item` for items and `economy:credit` for points. Never post the token in a public channel.

If the bot host has enabled encrypted owner key entry, use `/gamesadmin api action:set` and paste your key into the private form. Otherwise ask the host to add `KAOS_API_KEY_YOUR_DISCORD_SERVER_ID` to Railway Variables. The key belongs to your Discord community, and game-server number 1 selects KAOS S1 inside that community.

Run `/gamesadmin api action:check` to verify the connection. This does not test every write permission; test a real kit/item/points reward before enabling public games. Remove a saved key with `/gamesadmin api action:remove`; this pauses delivery. A host-managed environment key must be removed by the host.

Games Bot uses the API directly. No Transactions channel, KAOS bot selection or parser command is required for this bot.

Use `/gamesadmin participation allow_unlinked:true` to let unlinked members play, or false to require a KAOS link. Player links are checked through KAOS automatically and cached for up to 15 minutes. `/link_check` refreshes your status; optional player selects another member. The old linked role and manual verify_link command are no longer used.

If unlinked players may play, their in-game prizes wait until they complete KAOS `/link`. The delivery worker checks again automatically. Tickets, refunds and transfers remain Games Bot currency; they are not KAOS points.

## 3 Name tickets and set daily claims

Use `/gamesadmin currency name:Tickets allow_transfers:true`. Substitute Tokens, Chips, Scrap or another name up to 30 characters. These tickets are separate from KAOS points.

Use `/gamesadmin daily_settings amount:1 reset:midnight method:both timezone:America/New_York`.

- `amount`: Whole tickets awarded per claim, 1–1,000,000.
- `reset`: `midnight` in the selected timezone, or `24h` after the last claim.
- `method`: `button`, `command`, or `both`.
- `timezone`: A regional name such as America/New_York, preserving daylight saving changes.

Run `/gamesadmin panel type:daily` to post/update the persistent button in Daily claim channel. Players use that button or `/daily`. Using both does not collect twice. Run panel again after changing the daily amount/name/method so the displayed text is current.

## 4 Configure prizes before enabling

There are three tiers: **Base → Elite → Premium**. Each tier supports a points amount and multiple kit/item alternatives. Exact KAOS kit names must already exist. Rust item short names, such as `stone.hatchet`, are used for items.

Examples:

```
/gamesadmin prize action:add tier:base kind:kit name:starter quantity:1 weight:80
/gamesadmin prize action:add tier:base kind:kit name:farmer quantity:1 weight:20
/gamesadmin prize action:points tier:base quantity:100
/gamesadmin prize action:list tier:base
/gamesadmin prize action:remove tier:base option_number:2
```

The weight is relative within that tier: 80 and 20 mean 80%/20% when those are the only two alternatives. A player receives one randomly chosen alternative. An alternative may contain several rewards as a bundle; use the advanced `prize:base`, `prize:elite` or `prize:premium` editor to define bundles. An example is:

```json
{
  "points": {"amount": 100},
  "kits": [
    {"weight": 80, "rewards": [{"kind": "kit", "name": "starter", "quantity": 1}]},
    {"weight": 20, "rewards": [
      {"kind": "kit", "name": "farmer", "quantity": 1},
      {"kind": "item", "name": "stone.hatchet", "quantity": 2}
    ]}
  ]
}
```

Use `/gamesadmin reward_settings availability:both choice_timing:entry`.

- `availability`: `kits` (kits/items), `points`, or `both` (player chooses).
- `choice_timing`: `entry` or `after` winning.
- Points use KAOS economy credit; kits/items are deposited through the KAOS bank API.
- If using kits or both, configure all three tiers before enabling games/delivery. For a simple first test, choose `availability:points`.

Prize changes affect future games/draws. Existing entries keep their original prizes. To remove the last kit option while games are enabled, first pause games/delivery or switch availability to points.

## 5 Game costs and odds

Use `/gamesadmin game_settings` with game, level, cost, three percentage odds and enabled.

Example: `/gamesadmin game_settings game:supply_drop level:base cost:1 base_odds:80 elite_odds:18 premium_odds:2 enabled:true`.

Default entry costs are Base 1, Elite 3, Premium 5 tickets. Default initial tier odds are:

| Entry | Base prize | Elite prize | Premium prize |
|---|---:|---:|---:|
| Base | 80% | 18% | 2% |
| Elite | 60% | 33% | 7% |
| Premium | 40% | 45% | 15% |

Set each game separately. Percentages must total 100; entry costs must rise Base < Elite < Premium, and higher entry levels cannot have worse odds of Elite-or-better or Premium. If updating several related settings at once, use the full game editor so validation sees the complete intended configuration.

| Game | Rules |
|---|---|
| Supply Drop | Open a weighted prize drop. |
| Pick a Crate | Choose 1 of 3 crates. All have the displayed tier odds. |
| Scratch Card | Reveal a matching symbol combination representing the weighted prize tier. |
| Dice Challenge | Reveal a dice combination representing the weighted prize tier. These are prize symbols, not three independently uniform dice. |
| Prize Wheel | A weighted tier result. |
| Fishing | A catch reveals the weighted prize tier. |
| Treasure Dig | Pick 1 of 3 equal-odds locations. |
| Higher or Lower | Predict numbers 1–13; the next number differs. Two correct guesses reach Elite; four reach Premium. A weighted starting prize floor can be higher. Collect anytime; an incorrect guess awards Base. |
| Minefield | 2 mines among 9 squares. Two safe picks reach Elite; four reach Premium. A weighted starting floor can be higher. Collect anytime; hitting a mine awards Base. |
| Deal or Keep | Keep a revealed tier or trade once for a fresh weighted tier result. |
| Rock Paper Scissors | Pick, 3–2–1 countdown, reveal bot choice, animated outcome. Uniform independent bot choice. On a win, entry level directly sets Base/Elite/Premium prize; spending more does not change the chance of winning RPS. |

Configure RPS loss/draw ticket returns through `game:rps` using the settings editor. Other progress games award at least Base when a wrong choice/mine ends the round. There are no empty outcomes for instant reveal games.

An idle game settles after 15 minutes: progress games collect their current tier; Deal keeps the offer; RPS/Crate/Dig without a choice refunds the entry. Players can `/resume` before expiry.

## 6 Rust World Lottery

Use `/gamesadmin configure section:lottery`. The editor contains all fields with current values. Edit values and keep the required fields.

| Field | Meaning |
|---|---|
| enabled | Opens future draws automatically while games are enabled. |
| min / max | Lowest/highest selectable numbers. Players choose 3 different numbers. |
| cost | Tickets per combination unless a matching entry bundle is configured. |
| bundles | Optional complete purchase prices, e.g. `{"3":2,"5":4}` means 3 combinations cost 2 tickets, 5 cost 4. |
| max_entries | Per-player combinations per draw; 0 means no configured limit, still bounded by available unique combinations. Purchases are up to 100 combinations at a time. |
| pick_mode | `manual`, `quick`, or `both`. |
| payout | `highest` pays only the best match per player; `each` pays every combination. |
| reward_tiers | Map 1, 2 and 3 matches to Base/Elite/Premium; default in that order. |
| zero_return | Ticket return when no numbers match, described below. |
| schedule | Draw interval or local calendar schedule. |
| cutoff_minutes | Entries close this many minutes before the scheduled draw. Manual draws have no scheduled cutoff; entry stops when owner confirms drawing. |
| reminder_minutes | Post a reminder this many minutes before the draw; 0 disables it. |
| announce_winners | Include up to 20 player results in the public result message. Complete results remain in the report. |

Example schedule values:

```json
{"mode":"interval","minutes":60,"time":"20:00","weekdays":[0,1,2,3,4,5,6]}
```

- `interval`: Every `minutes` minutes, measured from opening the next draw.
- `daily`: At `time` each day in the community timezone.
- `weekly`: At `time` on one weekday; set weekdays to a one-element list.
- `weekdays`: At `time` on the selected weekdays. 0 Monday through 6 Sunday.
- `manual`: Owner uses the draw control; no automatic deadline.

Matches count in any order. Every player's combinations are unique for that draw; different players may choose the same numbers and both win. Quick Pick generates unique combinations too. Buying more combinations improves the chance of matching; it does not change the drawn numbers or reduce other players' chances. One exact 3-match chance is `1 / combinations(number_pool_size, 3)`. For N unique combinations the chance of at least one exact three-match is N divided by that denominator. Lower-match bundle odds depend on overlap; they are not calculated as independent trials.

Default zero matches returns 100% of the entry cost. You may choose:

```json
{"mode":"full","amount":0,"round":"down"}
{"mode":"percent","amount":50,"round":"down"}
{"mode":"fixed","amount":1,"round":"down"}
{"mode":"none","amount":0,"round":"down"}
```

Use one object, not all four. `round` can be up/down for percentage returns. A fixed return can be larger than the entry cost if you intentionally want that. With `highest`, ticket return applies to the player's total draw spend only if all their combinations have zero matches. With `each`, it applies separately to each zero-match combination; actual bundle prices are split across combinations in whole tickets so full refunds never exceed the real purchase cost. A zero-ticket return is allowed only when you intentionally configure it.

Player entry example:

```
/lottery enter combinations:2 numbers:1,2,3;4,5,6 reward:kits
```

Leave numbers blank for Quick Pick. The player reviews cost/prize rules then confirms. `/lottery show` shows rules; `/lottery entries` downloads their entries.

Owner controls: `/gamesadmin event type:lottery action:open`, `draw`, or `cancel`. Actions require confirmation. Cancel refunds actual entry costs. Changes to lottery rules/schedule apply to the NEXT draw; an already open draw keeps its existing deadline, price and rules. Disable lottery AND cancel its current draw to stop it completely. Pausing new games alone does not cancel paid draws.

## 7 Bingo and giveaways

Set `bingo` or `giveaway` in the settings editor, then use `/gamesadmin event` to open/draw/cancel.

Bingo settings: cost, minutes until close, number pool, square card size (2–5), participation tier and winning tier. Players join through `/events`; one randomly generated card per player. At closing the bot draws a random number order until a row, column or diagonal completes. All first-finishing tied cards win. Other cards receive the participation tier. The drawn sequence is published; this is a scheduled card game, not a live number-by-number animation.

Giveaway settings: ticket amount per winner, number of winners, minutes until close. Entry is free through `/events`; one entry per player. Winners are selected without replacement. Staff can also directly grant tickets with `/gamesadmin tickets`.

## 8 Test before opening to players

1. Save channels; select points-only rewards for the first test if kits are not configured yet.
2. Run `/gamesadmin api action:check`, then `/link_check player:NAME` for a real KAOS-linked player.
3. Run `/gamesadmin test player:NAME tier:base reward:points`. Review and confirm: this queues a REAL prize, without spending tickets.
4. Run `/gamesadmin enable games:false delivery:true` to deliver the queued test while games remain closed.
5. Inspect `/gamesadmin report`; the reward should become `accepted`. Ask the player to confirm the KAOS points or bank deposit. Accepted is not confirmation that a kit/item has been claimed into inventory.
6. Test one configured kit. If KAOS rejects a kit name, correct it before creating another test.
7. Grant a small test ticket balance, enable games and try RPS, daily claim, a short lottery, Bingo and a giveaway. Verify balances, refunds, API-linked/pending prizes and results.
8. Check permissions using a normal member: player commands work only in configured channels; admin configuration is refused.
9. Run `/gamesadmin panel type:games` and `type:daily`. Enable the Games and Delivery settings for normal use.

The secret Tip4Serv purchase URL is set up separately using README.md. Do not accept user-posted receipt screenshots as automatic credits. Staff can manually adjust tickets after reviewing an actual payment.

## 9 Access and reports

All setup/configuration, API-key management, event controls, live tests and delivery resolution require the actual server owner. Ordinary staff do not become owner by having a role named Owner.

Manage Server or the configured `staff_role` permits ticket grants/removals, reports and help in Admin channel. Set staff_role in general settings if needed. Normal members can use game, balance, transfer, history, prize and event commands in Games channel; `/daily` uses Daily claim channel. The owner bypasses the bot's channel restriction. Discord's own permissions still apply.

`/history` exports the player's ticket ledger, game results and recent reward IDs. `/gamesadmin report` exports community rewards, draws, recent ledger and audit rows (up to 2,000 per table). `/prizes` shows recent rewards; `/claim_prize` selects a kit/points reward by ID if it is older than the visible choice buttons.

Reward statuses:

- **choice:** Player must select kits or points.
- **pending:** Waiting to send, or retrying a temporary API/rate-limit problem.
- **waiting_link:** Waiting for a KAOS-confirmed player link.
- **accepted:** KAOS API accepted the credit or bank deposit.
- **failed:** Missing key/permission, invalid name or another rejection needs owner correction.
- **migration_hold:** A prior parser send has an uncertain outcome. Review before releasing it to the API.
- **sent:** Old parser record only; this version never creates new parser sends.

Use `/gamesadmin delivery reward_id:ID action:inspect`. Fix a failed API reward, then choose `retry`; it reuses the original reward ID and cannot select accepted rewards. Temporary connection/server/rate-limit failures retry automatically.

For a held legacy parser send only, inspect KAOS and old Transactions history. `legacy_reconcile` searches for the old post; `legacy_mark_sent` records that it was already sent; `legacy_release` queues it for API delivery after you confirm it was never processed. Releasing an already paid parser reward can duplicate it, because API duplicate protection cannot recognize old parser commands. Legacy decisions require owner confirmation. Already-sent legacy rewards are never automatically converted into a second payout.

## All commands

```
/games
/play
/daily
/balance
/give
/resume
/prizes
/claim_prize
/history
/events
/lottery show
/lottery enter
/lottery entries
/gamesadmin setup
/gamesadmin configure
/gamesadmin settings
/gamesadmin import_config
/gamesadmin enable
/gamesadmin panel
/gamesadmin tickets
/gamesadmin api
/link_check
/gamesadmin event
/gamesadmin report
/gamesadmin test
/gamesadmin delivery
/gamesadmin daily_settings
/gamesadmin participation
/gamesadmin currency
/gamesadmin game_settings
/gamesadmin prize
/gamesadmin reward_settings
/gamesadmin help
```
