# Team findings (checked 14 Oct 2026)

Reports from the specialist agents (see TEAM.md). Sources are the agents' own; items marked "not verified" were not confirmed. Not legal or tax advice.

## Legal and compliance
- Kalshi sports contracts are in a federal court split: the Third Circuit sided with Kalshi (NJ open), the Ninth Circuit ruled against it (28 Aug 2026), and orders restrict Nevada, Michigan and Washington; several states are pending. [Finance Magnates](https://financemagnates.com/fintech/federal-courts-now-disagree-on-kalshis-sports-contracts-new-jersey-wants-the-supreme-court-to-settle-the-fight)
- Polymarket US is a CFTC-regulated exchange with KYC and a waitlist rollout; Tennessee and Nevada are in disputes (secondary source). [Gambling Insider](https://www.gamblinginsider.com/?p=106291)
- DraftKings bans "automated means (including scripts and third-party tools)" on its site. A tool that only reads public third-party data and never logs in to a sportsbook sits outside that clause as quoted. Other books' terms not verified. Expect account limits if you win. [ConductAtlas](https://conductatlas.com/platform/draftkings/draftkings-terms-of-use/provision/CA-P-039377/automated-means-to-interact-with-website-prohibited/)
- The Odds API allows display and commercial use but not reselling or redistributing the data as a feed or downloadable file. A public `slate.json` with raw per-book odds could count. Keep what you publish to derived numbers (fair price, best price, edges), which is what this project does. [Terms](https://the-odds-api.com/terms-and-conditions.html)
- ESPN's endpoints are unofficial and have no published terms; Kalshi and Polymarket terms were not found. Read them yourself.
- No personal-use license or certification was found. If you share or sell picks: FTC disclosure rules, state advertising rules and league data licensing apply; talk to a lawyer first.
- Tax: from tax year 2026, deductible gambling losses are capped at 90%, so a break-even bettor can owe tax. Prediction-market treatment is unsettled. Keep records and ask a CPA. [Haskell](https://attorneyhaskell.com/blog/2026-gambling-loss-tax-deduction), [NATP](https://www.natptax.com/news-insights/blog/prediction-market-contracts-are-showing-up-on-client-returns/)

## Free data sources (for the next builds)
- **NHL (verified):** `api-web.nhle.com/v1/gamecenter/{id}/landing` has goalie season stats but no starter flag. `club-stats/{TEAM}/now` has games started. For the likely starter, Daily Faceoff lists Confirmed / Likely / Unconfirmed (no API; page scraping is fragile). Fallback: backup goalie on the second night of a back-to-back.
- **MLB (verified):** `statsapi.mlb.com/api/v1/schedule?sportId=1&date=...&hydrate=probablePitcher,lineups` gives probables; lineups are empty until about 1-4 hours before first pitch. Pitcher ERA/WHIP/IP from `/people/{id}/stats?stats=season&group=pitching`.
- **NBA:** hourly injury-report PDFs on `ak-static.cms.nba.com` (not verified; PDF parsing not stdlib). **NFL:** nflverse release files (injuries, play-by-play with EPA; asset names not fully verified). **Soccer:** football-data.co.uk CSVs include Pinnacle closing odds for backtests (not verified from this sandbox). **Other sports:** Jeff Sackmann's tennis CSVs, Jolpica-F1, Cricsheet (all not verified).

## Modeling evidence
- Props are the softest market but low-limit; sides and totals at the close in top leagues are the most efficient. Realistic edge is low single digits at best. [Establish The Run](https://establishtherun.com/miller-why-prop-betting-is-profitable/)
- Plain NFL Elo beats the spread only about 51%, below break-even. [Neil Paine](https://neilpaine.substack.com/p/nfl-elo-ratings-are-back)
- CLV is only loosely tied to profit (one NBA study: only the top decile profited), so do not trust it alone. [Whelan](https://www.karlwhelan.com/?p=2595)
- Pick and tune models by calibration, not accuracy. [Bath](https://researchportal.bath.ac.uk/en/publications/machine-learning-for-sports-betting-should-model-selection-be-bas/)
- No source supports the 25% model weight; fit it by log-loss on your own picks. Staking 2x Kelly gives roughly zero growth. [Berkeley](https://www.stat.berkeley.edu/~aldous/157/Papers/Good_Bad_Kelly.pdf)
- Ranked upgrades: fit the blend weight on log-loss, shrink Kelly inputs, early-season and motivation flags, MLB pitcher and rest adjustments (done for pitchers), surface-blended tennis Elo, Dixon-Coles for soccer, stale-line detection, correlation-aware parlays.

## Odds feeds
- **The Odds API:** free 500 credits/month, $30/month for 20,000 credits, 100+ books; Pinnacle only in the `eu` region; Caesars paid-only. SportsGameOdds $99/month for 77 books; Odds-API.io and SharpAPI are priced by book count and cover too few books; OpticOdds is quote-only. Pinnacle closed its public API in July 2025. [Odds API pricing](https://the-odds-api.com)
- Zero-cost plan: free Odds API credits only (the workflow now polls 4 sports twice a day, about 240 credits a month). Under $30: the $30 plan. Delayed free feeds from other providers give false arbitrage signals.
- **Decision (15 Oct 2026):** no key was ever actually configured, so this was live on the free-fallback path (ESPN) the whole time. Removed the Odds API integration from `build_slate.py` entirely rather than leave dead, key-gated code sitting unused: the pipeline now runs only on ESPN, Kalshi, Polymarket and the collector network, no exceptions. Trade-off, stated plainly: this also removes the only path to per-book spread/total lines, so the spread/total middle scanner (`markets.find_middles`) has nothing to scan and always returns none. Re-adding a paid feed later is a matter of re-adding `odds_api()`/`parse_odds_api()` (still in git history) to the `try_sources` chain in `main()`, not a rebuild.

## What changed because of this
The independent code review found and I fixed: wrong-game grading in series, soccer games silently turning two-way, spread and total markets read as moneylines, stale or single-book closing lines inflating CLV, team-name mismatches, a possible leak of the alert topic into the public file, commit churn, live games leaking into the slate, an inflated edge definition, and silent holes in ESPN history. Each now has a regression test (`test_review.py`). Design findings applied: the app opens on Today's Slate, the tab order follows daily use, phone tap targets are 44px, and the top note is shorter. Not yet done: stacked game cards on phones, a "Best opportunities" list above the table, and plain-English labels on stats.
