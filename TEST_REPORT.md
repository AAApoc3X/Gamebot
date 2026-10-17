# Games Bot validation

Built October 16, 2026 for the separate Rust Console Games Bot.

## Automated checks

36 tests pass using local SQLite databases and simulated Discord/HTTP transports:

- Shared daily allowance between button and command; local-midnight and rolling 24-hour resets.
- Wallet conservation, insufficient balance rollback and duplicate transfer protection.
- Linked-role checks, explicit owner verification and community isolation.
- All seven instant prize games and all four interactive games.
- RPS prize tiers, invalid/repeated moves and another player's rejected actions.
- Higher entry prize floors, frozen prize rules and single-use post-win reward selection.
- Inactivity handling and full refund for unplayed RPS.
- Lottery unique Quick Pick, invalid manual picks, entry limits and cutoff.
- Lottery highest/each payouts, zero-match returns, exact bundle-cost cancellation refunds and repeat settlement rejection.
- Calendar schedules over daylight saving and weekly boundaries; probability calculations.
- Bingo, ticket giveaways and duplicate join rejection.
- Purchase-level deduplication across resends; test-mode payment rejection; secret webhook authentication.
- Parser formatting and bracket-injection rejection.
- State retained after database restart.
- Delayed unlinked delivery, successful send recording, paused delivery and ambiguous-send recovery.
- Discord command payload serialization, persistent panels, interactive views and owner/member permissions.

Local compilation and Discord registration payload checks also pass. There are 32 executable slash commands, including 19 owner/staff commands under /gamesadmin and 3 lottery commands.

Five original GIF files are included: rock, paper, scissors, draw and countdown. The three winning-action animations and draw graphics were inspected locally.

## Live checks still required

No real Discord bot token, KAOS access or Tip4Serv store credentials were used. This package has not been deployed to your Railway project or uploaded to your GitHub account.

After deployment, use OWNER_GUIDE.md section 8 to verify permissions, one real points reward, one existing kit, link verification, the game views/animations, a short lottery, Bingo and ticket giveaway. Validate one controlled live Tip4Serv purchase and its duplicate resend before using public purchases.

KAOS delivery reports indicate parser commands sent, not confirmed in-game delivery. A timeout/restart around a send requires owner inspection before retrying.
