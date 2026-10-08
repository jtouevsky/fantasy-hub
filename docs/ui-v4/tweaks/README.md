# UI v4 tweaks: before and after

Screenshots (1440 px, light and dark): `before/` is the merged UI v4, `after/` is this branch. Files: `overview-*`, `matchup-*`, `trades-*`.

## 1. Palette toned down about 13%
Done at the color-token level in `web/src/styles.css`, so every use follows. Saturation of the six section colors was reduced by 13% and brightness by up to 4%, in both modes; cobalt and grape were darkened a little further only as much as needed to keep white text at 4.5:1. Team colors and semantic colors (good, warning, bad, info) are unchanged.

| Token | Light before | Light after | Dark before | Dark after |
|---|---|---|---|---|
| cobalt | `#2d5bff` | `#446bf2` | `#4666f2` | `#556ddd` |
| lime | `#c8f031` | `#c5e647` | `#c8f031` | `#c5e647` |
| coral | `#ff5d48` | `#f56d5c` | `#ff7561` | `#f58271` |
| sunflower | `#ffc83d` | `#f5c753` | `#ffc83d` | `#f5c753` |
| grape | `#7c4dff` | `#805be8` | `#7f52f0` | `#835edd` |
| teal | `#10b5a4` | `#24aea0` | `#2bd0be` | `#3ec8b9` |

`python tools/contrast.py` (also run by `make test`) passes in both modes: every text pair is at least 4.5:1 (it reads the same hex values as the stylesheet, and the lime and sunflower value-panel checks now use the new colors).

## 2. Matchup order
Scoreboard, "yet to play" chips, then **Starters head to head** (both lineups, slot by slot), then Game environment, then the AI button. Phones use the same DOM order, so head-to-head is also first there.

## Tab-switch performance (16 switches across all tabs, same method as `docs/performance.md`)
| | min | median | max |
|---|---|---|---|
| Before this branch | 4.4 ms | 8.3 ms | 29.4 ms |
| After (second run) | 2.4 ms | 6.7 ms | 25 ms |

One earlier run had a single first visit to More wait on the news data (a cold server cache, not rendering); the same switch took 5 to 8 ms on every other run. Nothing else changed: same JS, same fonts, same animation rules.
