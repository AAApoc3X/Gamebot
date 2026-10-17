# Multiple game servers and player reward destinations

This update adds named KAOS reward destinations to Games Bot and Kill Tracker. Each Discord community configures its own list. Each option must use the ACTUAL KAOS game-server number under that community's key. Example:

- S1 — AAApocalypse 3x
- S2 — Doomsday 6x Solo Duo

Display names are customizable. Two different game servers within one KAOS community need their real distinct slots; naming two options S1 does not create separate destinations. Different Discord communities can each have their own S1.

## Games Bot owner setup

```
/gamesadmin servers action:add server_id:1 name:AAApocalypse 3x
/gamesadmin servers action:add server_id:2 name:Doomsday 6x Solo Duo
/gamesadmin servers action:timing timing:before
/gamesadmin servers action:list
```

Choose `timing:before` or `timing:after`. Add every server you want listed; up to 25 active destinations are supported. Reusing a slot updates its display name. `action:remove server_id:2` disables it for future entries; existing paid entries and earned rewards keep their frozen server options and destinations.

### Before playing

Players use `/server` to select a saved preference from a dropdown. `/play` and the Games panel request a server when necessary, and the review has **Change reward server** before tickets are spent. The selected server is shown in the review. All kit, item and points prizes from that game keep that destination.

Lottery entry similarly offers a server choice and Change reward server before confirmation. Each purchased combination retains its chosen server. With highest-only lottery payout, the winning combination supplies the destination; ties use the first highest-matching stored combination. Use after mode if players should choose only after seeing their result.

Bingo entries show a server dropdown before purchase. Free ticket giveaways do not need a game-server selection because tickets are internal to Games Bot.

### After winning

Use `/gamesadmin servers action:timing timing:after`. New entries retain that rule. When a player wins, their in-game reward waits until they open `/prizes` and click **Choose server**. Select the named server in the dropdown. `/reward_server reward_id:ID` handles older rewards by ID.

Kits versus points can be chosen independently, before entry or after winning using the existing reward-settings option. A player can choose prize type and server in either order, refreshing `/prizes` after making a selection. If a kit alternative contains several bundled rewards, all its children go to the same chosen server.

After selecting a server, it is fixed. Refreshing, changing a preference, retrying delivery or restarting cannot move that reward or pay it again. The API uses the selected slot in its route and retains the same reward idempotency key.

## Kill Tracker owner setup

```
/ktservers action:add server_id:1 name:AAApocalypse 3x
/ktservers action:add server_id:2 name:Doomsday 6x Solo Duo
/ktservers action:timing timing:before
/ktservers action:list
```

Only the actual Discord server owner can change this catalog. Stats channel permissions also apply to player commands. Each player must be KAOS-linked so the bot can verify their Discord account and in-game identity.

### Before earning rewards

Players run `/ktserver` and choose their preferred destination from a dropdown. Future normal streak and period rewards use that preference in before mode. They do not have to choose before every kill. If no preference is set, earned rewards wait for selection instead of being silently sent to the owner's default server.

### After earning rewards

Set timing to after. Players run `/ktrewards`, choose an earned reward, then choose a named server. `/ktrewards reward_id:ID` opens a particular reward. Each kit, item or currency reward can be claimed to its selected server. The bot verifies the requesting player's KAOS link; a player cannot claim another player's rewards.

Selected destinations cannot change after claiming. Retries preserve the server and original reward key. Normal reward enable/pause rules still apply. Owner giveaway tests continue to use their explicit test server slot rather than the player's preference.

The destination setting controls WHERE rewards are delivered. It does not split tracking/leaderboards by game server or add additional kill-feed channels; existing feed/statistics behavior is retained.

## Upgrade both deployments

1. Back up populated persistent volumes.
2. Replace the matching files in EACH bot's own GitHub repository with the complete contents of its matching ZIP. Keep Games Bot files separate from Kill Tracker files.
3. Preserve existing Railway services, Discord tokens, KAOS keys and data volumes. No new Railway variables are required by this server-selection update.
4. Redeploy one instance per bot. Refresh Discord command menus if needed.
5. Configure server names with gamesadmin servers and ktservers separately; the bots have separate databases and do not share preferences automatically.
6. Test a small points reward and kit on each actual KAOS slot. Kit/item names must be valid on each enabled destination.

Existing queued rewards and paid Games entries keep their original destinations. New behavior applies to new entries/rewards after the owner configures a catalog. Until a catalog is configured, each bot retains its previous single-server fallback behavior. Catalogs and preferences persist across restarts.

The catalog is managed through the server commands and stored in the persistent database. Preserve the persistent database and keep a record of the configured names/slots. Removing all active catalog entries blocks new game entries until the owner adds an available server.
