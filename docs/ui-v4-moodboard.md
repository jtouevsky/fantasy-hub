# UI v4 moodboard and design direction

Goal: make the app fun (bold color, playful shapes, springy motion) without touching the performance work, and without putting the fun inside the dense data.

How this research was done: web searches across design write-ups, game and sports-broadcast coverage, galleries and specs, then reading what came back. Two honesty notes up front:

* I could not find or open **inspora.design** through search (no results for it), so nothing below is attributed to it. The motion-gallery sites I did find (60fps.design, UI Movement, App Motion) are listed instead.
* Several sources are secondary (design-system "spec" sites, portfolio pages, reviews). Where a claim is secondhand I say so. Nothing here is copied; each line is an idea to borrow and rebuild in our own way. No third-party assets are used.

## References (what to borrow from each)

### Color, type and block layout
1. **Spotify Wrapped identity** ([It's Nice That, 2023](https://www.itsnicethat.com/features/spotify-wrapped-campaign-identity-2023-graphic-design-301123); [2024 breakdown](https://alexjimenezdesign.substack.com/p/three-design-elements-that-made-spotify)). Borrow: bold type placed on flat color fields (never on busy backgrounds), a limited high-contrast palette, and treating numbers and letters as shapes. Caution from the same critique: clashing colors with cramped type was the failure case.
2. **Nike Run Club** ([Collins case study](https://wearecollins.com/case-studies/nike-run-club); [review](https://www.designrush.com/best-designs/apps/nike-run-club)). Borrow: each run type gets its own visual treatment on one shared system (our per-section identity), and one neon accent reserved for the key action.
3. **Arc browser Spaces** ([design study](https://blakecrosley.com/blog/design-study-arc)). Borrow: every context owns a color and one saturated color sets the mood of the whole window; sidebar-first navigation with room for labels. (Arc is translucent/gradient; we keep only the "context = color" idea, flat.)
4. **NYT Connections** ([overview of the four difficulty colors](https://mabumbe.com/people/nyt-connections-today-march-19-answers-puzzle-breakdown/), secondary source). Borrow: a tiny fixed set of yellow/green/blue/purple where color carries meaning, and a correct-answer response that is brief ("letters light up"), not a show.
5. **Madden 20 UI** ([designer portfolio](https://creativepool.com/jonnysevern/projects/madden-20)). Borrow: a vibrant palette plus per-NFL-team themes carried into player-selection graphics. We keep team colors for team details (badges, portraits) only.
6. **NBA 2K UI** ([2K20](https://herms.tv/project-2k20.html), [2K22](https://cdn0.workingnotworking.com/projects/380955-nba-2k22), designer portfolios). Counter-example and a lesson: 2K20 was monochrome with one orange accent to direct attention (good restraint for dense data), and 2K22's mode transitions took about three seconds. We take the "one accent directs attention" idea and cap our transitions at 300 ms.
7. **Clash Royale** ([analysis, secondary](https://mechanicsofmagic.com/?p=15995)). Borrow: a single warm yellow reserved for action items, with the most essential information always visible.

### Shapes, buttons and depth
8. **Duolingo buttons** ([third-party spec](https://www.webdesignhot.com/design.md/duolingo/)). Borrow: a solid bottom shadow in a darker shade of the button color that the button sinks into on press (3 to 4 px, no blur), about 12 px radius. The lineage the source mentions (casual mobile games) is exactly the "pressable" feel we want.
9. **Neobrutalism** ([Made Good Designs](https://madegooddesigns.com/neobrutalism-web-design/); [UX Collective](https://uxdesign.cc/neubrutalism-is-taking-over-the-web-e9d09e0fe441)). Borrow: 2 to 4 px outlines, zero-blur offset shadows, flat saturated fills on a cream base, buttons that slide into their shadow. Caution from the sources: raw clashing color causes fatigue, so we limit the palette and keep outlines for frame elements, not data rows.
10. **Gumroad's relaunch** ([secondary spec](https://www.webdesignhot.com/api/design-md/gumroad.md)). Borrow: hot pink on cream with black outlines as proof that a loud palette can still be a product UI. (One source says the live site has since dropped the hard shadows, so treat it as a reference for the idea, not the current site.)
11. **Sticker badges** ([Framer Stickr](https://www.framer.com/marketplace/components/stickr/), a component listing). Borrow: thick outline, hard offset shadow and a small tilt of roughly 2 to 6 degrees; their warning that the style reads as clickable is why our stickers are decorative-only and our real buttons look different (chunky and pressable).
12. **CSS `corner-shape` / squircles** ([Smashing Magazine, 2026](https://www.smashingmagazine.com/2026/03/beyond-border-radius-css-corner-shape-property-ui/); [Frontend Masters](https://frontendmasters.com/blog/?p=6270)). Borrow: iOS-style continuous corners as a progressive enhancement (Chromium today) behind an `@supports` check, with plain `border-radius` as the fallback.
13. **Rocket League's squared-off Play menu** ([Psyonix post](https://devtrackers.gg/rocket-league/p/5f93f4a3-first-look-play-menu-changes-coming-to-rocket-league) and the [readability criticism](https://caniplaythat.com/?p=4020)). Borrow: a squared, streamlined layout per submenu; the lesson from the criticism is to keep font sizes and weights few and prompts clear.

### Sports, score and ring graphics
14. **ESPN Monday Night Football "Dashboard"** ([Sports Video Group write-up](https://www.sportsvideo.org/?p=85134)). Borrow: one fixed information band that other graphics never cover. Our version is the persistent scoreboard strip and the side panel, so detail never pushes the score off screen.
15. **Fox Sports college basketball scorebug** ([NewscastStudio](https://www.newscaststudio.com/2021/11/09/fox-sports-redesigns-college-basketball-look-enlarges-scorebug/)). Cautionary: an enlarged scorebug drew heavy criticism for crowding the picture. Our scoreboard stays compact on small screens.
16. **"Braves on Gray" broadcast package** ([NewscastStudio](https://www.newscaststudio.com/2025/03/27/braves-on-gray-media-broadcast-design/)). Borrow: motion-first but modular, and the designers' stated rule that the more disruptive a package is, the shorter its shelf life. That backs our "fun in the frame, calm in the data" rule.
17. **Apple Activity rings** ([HIG](https://developer-mdn.apple.com/design/human-interface-guidelines/components/status/activity-rings)). Borrow: a ring must make clear whose progress it shows (label, photo or avatar) and should sit enclosed in a circle with clear margin. We use rings for projections and confidence, always next to the team avatar or a label, and never imitate Apple's own ring colors.
18. **WHOOP home dials** ([WHOOP](https://www.whoop.com/thelocker/the-all-new-whoop-home-screen), [an independent review](https://the5krunner.com/2023/03/28/new-whoop-home-screen-looks-pretty-but-is-it-as-intuitive/)). Borrow: three big dials at the top that each open a deep dive. The review's complaint (too much data on one screen, hard to find detail) is the reason our side panel holds detail and our home stays summary-only.
19. **Fantasy sports concepts on Dribbble** ([FanWagon](https://dribbble.com/pons/projects/256142-Application-Platform), [Fantisserie](https://dribbble.com/oleg-zeltser), [Yahoo FF concept](https://dribbble.com/mckenna/tags/purple)). Borrow: FanWagon's framing of the product as a gaming platform rather than a utility, and the playful copy tone of the others. I could view titles and tags only, not the images, so these are directions to look at rather than analyzed designs.
20. **Strava's Start button** ([Pratt critique](https://ixd.prattsi.org/2025/09/design-critique-strava-ios-app-2/)). Borrow: one big circular primary action with an obvious signifier. Our counterpart is the single hero action on each screen.

### Motion
21. **View Transitions API** ([frontendchecklist](https://frontendchecklist.io/rules/css/view-transitions); [CSSWG issue on list to detail](https://lists.w3.org/Archives/Public/public-css-archive/2022Dec/0323.html)). Borrow: give the list thumbnail and the detail image the same `view-transition-name` and the browser morphs position and size (no FLIP math). Pitfalls to design around: names must be unique at any moment, fetch data before starting the transition, feature-detect and fall back, and honor reduced motion.
22. **Motion for React, LazyMotion** ([docs](https://motion.dev/docs/react-reduce-bundle-size)). Reference for the bundle rule: the full library is about 34 kb, `LazyMotion` with `m` components is under 4.6 kb initial. Decision: we do not add it. CSS springs (`linear()` and overshoot cubic-beziers), CSS transitions and the View Transitions API cover everything here with 0 kb.
23. **Motion galleries** ([60fps.design](https://uiuxshowcase.com/resources/60fps-design-animation-inspiration-for-mobile-web-apps/), [UI Movement](https://www.hongkiat.com/blog/interface-animations-ui-movement/), [App Motion](https://uiuxshowcase.com/resources/app-motion/)). Borrow: browse real app micro-interactions (button press, checkbox, selection, morph) and keep the ones that finish in about 200 ms.
24. **Mobbin and ESPN app patterns** ([ESPN app review](https://screensdesign.com/showcase/espn-live-sports-scores); [NBA vs ESPN game lists](https://medium.com/@makeshowlearn/material-design-exploration-nba-scores-aab151d169da)). Borrow: a secondary color for in-progress games (we use it for "locked / live" states) and tabs plus collapsible sections to keep dense stats organized.
25. **EA Sports FC menus** ([FC 24 review](https://www.windowscentral.com/gaming/ea-sports-fc-24-review-how-does-eas-first-non-fifa-game-compare)). Lesson only: reviewers criticized a menu that felt cluttered and sluggish; flashy menus must never slow navigation. That is the non-negotiable behind our performance rules.

Not verified (so not used as references): Sleeper's actual palette (searches returned only generic descriptions), Brawl Stars button and outline specifics, Rocket League palette details, inspora.design.

## Design direction

### Palette: color-blocking on warm cream or deep ink
Flat, saturated fills, no glows, no gradients except team-color backdrops behind portraits.

| Token | Light | Dark | Used for |
|---|---|---|---|
| Cream / Ink (base) | `#FBF5E8` | `#14131C` | page |
| Card | `#FFFFFF` | `#201F2E` | surfaces |
| Ink (text, outlines, hard shadows) | `#16130F` | `#F6F1E4` text / `#08080C` outline | text and frame |
| Cobalt | `#2D5BFF` | `#5B7DFF` | Overview, Assistant |
| Lime | `#C8F031` | `#C8F031` | My Team, primary action fills (always with ink text) |
| Coral | `#FF5D48` | `#FF7561` | Matchup |
| Sunflower | `#FFC83D` | `#FFC83D` | Players |
| Grape | `#7C4DFF` | `#9A74FF` | Trades |
| Teal | `#10B5A4` | `#2BD0BE` | League |

Semantic colors stay separate from the section colors and always come with an icon or word: good `#0B8F52`, bad `#C8102E` (a crimson that cannot be confused with coral because bad is only ever used for text, outlines and icons, never as a fill behind numbers), warning `#9A5B00` on a sunflower-tint chip. Every pair is checked for contrast (see the audit). Dark mode is designed, not inverted: lifted section colors, outlines and shadows in a near-black that reads against the lighter card surface.

### Shapes
* **Squircle** cards and buttons (`corner-shape: squircle` where supported, 22 to 28 px radius fallback).
* **Stadium / oval** for the nav rail items, search and filter pills (the only place long pills remain).
* **Blob** accents (organic `border-radius`) behind section titles and empty states.
* **Sticker** badges, tilted about -3 degrees, thick outline, hard shadow, decorative only.
* **Notched** header tabs and score plates (corner cut with `clip-path`, no shadows on clipped elements).
* **Big rings** for scores and projections, with labels beside them.
* Rule: no wall of identical pills. Each screen mixes at most three shapes on purpose.

### Type
* Display: **Barlow Condensed** 800/700 for scores, team names, section titles (sporty, narrow, tall).
* Body: **Geist** 400/600/700 for everything else, tabular numerals for all stats. Geist Mono only in the scoreboard digits.
* Self-hosted Latin subsets (woff2), the display weights preloaded, icons subset to the glyphs actually used.

### Motion principles
* Micro-interactions 120 to 200 ms with a springy overshoot on press and hover; transitions at most 300 ms.
* Only `transform` and `opacity` animate. Nothing loops. Nothing animates offscreen.
* Page changes use the View Transitions API (cross-fade plus a small slide); player portraits morph from list to detail with a shared element.
* Staggered entrance on the first load only; number tickers when values change; celebration moments (a win, a hit on the report card) are short, never block input and skip on any click or Esc.
* `prefers-reduced-motion`: calm static versions of everything (no springs, no confetti, instant transitions).

### Layout
* Fluid, full-width. Wide screens: left rail (icons and labels, section colors) + main + contextual right panel (player details or "your next moves"). Medium: icon rail + main, player details open as a panel. Mobile: single column and a bottom nav.
* Section color bands run edge to edge behind each screen's title. Reading text is capped by measure, the layout is not.

### Per-section plan
| Section | Color | Fun lives in | Stays clean |
|---|---|---|---|
| Overview | cobalt | cobalt scoreboard plate with lime rings and tickers, sticker status badges | news and move cards |
| My Team | lime | lime band, squircle slot tags, springy rows on hover | roster rows and stats |
| Matchup | coral | ink scoreboard with ticker digits, notched score plates | head-to-head rows |
| Players | sunflower | sunflower band, chunky filter chips | the virtualized list |
| Trades | grape | grape band, hero buttons, lime and sunflower value panels | numbers, week-by-week row, ladder |
| League | teal | rank medallions, standings band | table rows |
| Assistant | cobalt | blob mascot, squircle bubbles, chunky send button | answer text and move cards |
| More | ink | sticker section markers | all settings and tables |
