# Games Bot player entry update

Release date: 17 October 2026 Eastern time.

- Add Rust World Lottery to the player game menu and /play suggestions.
- /lottery enter opens a private guided menu with no typed command parameters.
- Combination count dropdown supports paging up to 100 per purchase, bounded by remaining draw eligibility.
- Manual picks use three number boxes per combination; invalid/repeated numbers and previously entered combinations are rejected.
- Quick Pick fills actual numbers before review; confirmation records exactly those numbers, with a stable purchase reference.
- Review includes full price, payout rule, no-win ticket return, reward type and destination. Large reviews attach a complete read-only text list.
- Rename /balance to /ticketsbalance. Existing balance panel button remains compatible.
- Clarify /give transfers existing tickets, and reject self-transfers before showing confirmation.
- Remove server_id from /gamesadmin setup. Existing saved defaults are preserved; server catalog and player preferences continue to work.
- Filter disabled instant games from player menus and /play autocomplete. Existing open lottery draws remain separately managed; pausing future automatic draws does not cancel paid entries.
- Preserve guided owner settings and the API-key modal fix max_length=4000.

## Update

Extract this complete package and upload its contents to the Games Bot GitHub repository. Include the new lottery_ui.py file. Keep Railway variables and the existing persistent volume. Redeploy; command synchronization registers /ticketsbalance and removes /balance for the configured registration scope. If an old development-guild command remains, check that the deployment uses the same command-registration scope.

There are no new environment variables or database schema changes for this update. Existing paid draws, entries, balances, keys and queued rewards are preserved. No changes to Kill Tracker are included.

## Verification

85 automated tests pass. After deployment, verify /play lists Lottery, manual entry has three boxes, Quick Pick displays numbers, cancel leaves the balance unchanged, and Confirm Entry charges once. Check /lottery entries for the exact purchased numbers. Test configured server choice and reward delivery with a controlled recipient before public use. No live Discord or KAOS calls were made during this release.
