# UI v4 polish audit

Method. `python -m tools.screens <dir>` drives Chrome through its DevTools protocol and captures **every screen** (Overview, My Team, Matchup, Players, Trades, League, Assistant, More) at **390, 820, 1440 and 1920 px**, in **light and dark**: 64 screenshots per set, taken after the data loaded and the entrance animation ended, at full page height (capped at 2600 px). The tool also reports any horizontal overflow (page wider than the viewport). I read the screenshots, wrote down every problem, fixed them, and captured again.

* Before (the v3 UI): [`docs/ui-v4/before/`](ui-v4/before) (64 files, named `<screen>-<width>-<theme>.jpg`)
* After (this branch): [`docs/ui-v4/after/`](ui-v4/after) (64 files)
* Portrait contact sheet (48 real players at 36, 44, 72 and 104 px): [`docs/ui-v4/avatars-after.jpg`](ui-v4/avatars-after.jpg). Reproduce it at `/dev/avatars`.
* Contrast: `python tools/contrast.py` checks every text/background pair of the palette in both modes and exits non-zero on a failure (currently all pass).

Reading the captures: full-page screenshots of a page with a **fixed bottom nav, a sticky top bar and sticky side rails** draw those bars at the viewport position inside the long image (you will see the phone bottom nav in the middle of a long page, and the rails ending at the first screenful). That is how the capture works, not a layout bug. Images below the first screenful use `loading="lazy"` and may not have loaded in a long capture, so they show only their team-color backdrop (no text); the portrait contact sheet verifies the loaded state.

## What was wrong in the old UI (from the before set and your report)

| # | Issue | Where | Fix |
|---|---|---|---|
| 1 | The whole app was a narrow centered column (max ~1100 px): at 1440 and 1920 px about half the screen was empty on both sides | all screens, wide | Fluid three-zone layout: left rail, content, right panel (player details or "Next up"); icon rail on tablets; bottom nav on phones; edge-to-edge color bands |
| 2 | Every control and chip was a silver pill; no color, one shape, flat | everywhere | Six-color section palette, squircle cards and buttons, stickers, rings, blob accents, chunky pressable buttons |
| 3 | Player portraits: the team initials rendered behind the transparent PNG, and the face filled only part of the circle | all rows, cards, sheet | Initials render only when the image is missing or fails; photo fills the circle (`object-fit: cover`, anchored near the top); source chosen by displayed size |
| 4 | Eight icon+label tabs did not fit a phone | phone nav | Bottom nav with 5 tabs + a "More" menu |

## Problems found while building and auditing v4 (all fixed)

| # | Issue | Found in | Fix |
|---|---|---|---|
| 5 | The side rail still showed on phones (the mobile rule was overridden by a later base rule) and the page was ~500 px wide | 390 px, all screens | Responsive overrides moved after the base rules |
| 6 | Opponent team name in the scoreboard wrapped one letter per line | Overview and Matchup at 1440 with the right panel open | Scoreboard is a container (`container-type: inline-size`); it switches to one column by its own width; names break at word boundaries |
| 7 | First section heading overlapped the color band | Players, League, Assistant | Extra top spacing when a heading or chip row is the first child |
| 8 | Assistant had a duplicated heading that overlapped the band | Assistant | Heading removed (the band is the title); mascot moved into the chip row |
| 9 | The chat input bar ran underneath the right panel | Assistant, wide | Bar stops at the panel edge (`right` follows the panel width) |
| 10 | Icons `touch_app` and `rule` showed as plain words (missing from the subset icon font) | right panel, Assistant chips | Subset rebuilt with the full set used by the app (plus extras); every icon name in the source is checked against it |
| 11 | The trade request box lost its border (it used a removed color token) | Trades | Uses the shared input style; every `var(--token)` in the source is checked against the stylesheet |
| 12 | Contrast: success text on its tint was 3.5:1; white text on the dark-mode cobalt and grape bands was 3.3 to 3.6:1 | light and dark | `good` darkened to `#087a45`; dark cobalt `#4666f2`, grape `#7f52f0`; all pairs now at least 4.5:1 |
| 13 | Player names cut to 12 characters ("Jonathan Tay...") on phones; recommendation cards squeezed by two avatars and the gain | 390 px, My Team and Overview | Names wrap on phones; the avatar pair is hidden on phones so the text gets the width |
| 14 | On tablets the search box shared a row with the buttons and was tiny | 820 px | Search goes on its own full-width row |
| 15 | Long "Add X, drop Y" cards were squeezed into the 340 px panel | right panel | Panel uses compact rows (name, drop, gain) instead of full cards |
| 16 | Players filters (sort pills, search, toggle) wrapped into a ragged block | Players | One flexible row that wraps cleanly |
| 17 | The big portrait in the player sheet loaded a 157 KB image and appeared late | player sheet | Serve the 240 px version (about 38 KB), load the big portrait eagerly |
| 18 | Assistant page scrolled itself to the bottom on load when there were no messages | Assistant | Only auto-scroll when there are messages |
| 19 | Text lines of 200+ characters at 1920 px (news items, notices) | Overview at 1920 | Measure cap (`96ch`) on reading text only; the layout stays full width |
| 20 | Trade offers stacked in one long column on wide screens | Trades at 1440 and 1920 | Offers flow into a responsive grid (two columns when there is room) |
| 21 | Rank numbers in standings were plain; no sense of top teams | League | Medallions for places 1 to 3 |

Checks that came back clean in the final set: no horizontal overflow at any size, in either theme; no text rendered behind a loaded portrait (contact sheet of 48 players); focus rings visible on every control; all text pairs meet 4.5:1.

## Deliberately kept simple (for speed or honesty)

* No animation library: springs are CSS `linear()` easing (with a cubic-bezier fallback), transitions are CSS and the View Transitions API. Cost: 0 KB.
* Squircle corners use a plain `border-radius` (not `corner-shape`) so every browser looks the same; the squircle shape comes from a generous radius.
* The notched-card idea from the moodboard is not used on cards (a `clip-path` would clip their hard shadows); the tilted stickers and rotated-square band accents carry that role.
* Dense data (roster rows, stat tables, trade numbers) has no decoration beyond color on the section marker and the value panels.
* The player-portrait morph needs the View Transitions API (Chrome and Safari 18+); other browsers get the normal instant open.
