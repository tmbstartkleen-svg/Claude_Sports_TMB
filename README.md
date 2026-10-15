# Slate pipeline

Builds `slate.json` (odds, de-vigged fair prices, best price per side, arbitrage, prediction-market gaps, edge bets, one-day Monte Carlo).
Edge Suite's **Today's Slate** tab reads it.

## Sources (first that works wins; every attempt is logged in `slate.json -> sources`)
| Need | Primary | Fallback 1 | Fallback 2 |
|---|---|---|---|
| Sportsbook odds | The Odds API (DraftKings, FanDuel, BetMGM...) | ESPN scoreboard odds | sports-skills scoreboard |
| Kalshi | Kalshi public API | sports-skills kalshi | |
| Polymarket | Polymarket gamma API | sports-skills polymarket | |

## Setup
1. Copy `pipeline/`, `.github/workflows/slate.yml` into the repo root (Claude_Sports).
2. Repo -> Settings -> Secrets and variables -> Actions -> New secret: `ODDS_API_KEY` (use a NEW key, not the one pasted in chat).
3. Actions tab -> "Build slate" -> Run workflow. A `slate.json` is committed; Netlify redeploys.
4. Without the secret it still runs on ESPN and the prediction markets.

Run locally: `ODDS_API_KEY=... python pipeline/build_slate.py`
Read-only: nothing here places bets.

## Models and extras
- **Elo + rest models:** NFL, NBA, NHL, MLB (free ESPN results). MLB is the weakest: it does not know who is pitching.
- **Soccer (3-way):** `soccer.py` runs Elo plus an explicit draw chance (base level = the draw rate seen in the data) for the EPL, La Liga, Bundesliga, Serie A, Ligue 1 and MLS, backtested against league-to-date frequencies. Edge bets can be on the draw. Champions League games get no model because ratings from different leagues are not comparable. Soccer is high-variance: expect only a small edge over the baseline.
- **Injuries (rough):** ESPN's injury list, position-based and capped (NFL QB out = about -100 Elo; others small). It cannot tell NBA stars from bench players.
- **Closing lines:** capture runs every 30 minutes on game days (free sources only) save each game's market price to `history.json`.
  The last price seen before the start is the "closing line", so it can be up to ~30 min early. Edge Suite's Today's Slate tab can copy those into the CLV tab for bets you logged from the slate.
- **Netlify:** `netlify.toml` skips deploys when only `history.json` changed.
- **All sports:** `SPORTS=all` covers NFL, NBA, MLB, NHL, NCAAF/NCAAB, WNBA, six soccer leagues (3-way markets with draw) and UFC via ESPN (free). The Odds API only spends credits on sports in `ODDS_API_SPORTS`.
- **Scanner:** `markets.py` finds 2- and 3-way arbs, cross-book vs Kalshi/Polymarket arbs (fees and 1c slippage included) and spread/total middles with exact EV. Middles need `MARKETS=h2h,spreads,totals` and an Odds API key.
- **Promo Converter tab:** free bet, deposit match, risk-free and profit-boost hedge math.
- **MLB starting pitchers (rough):** ESPN's probable starters and ERA adjust the Elo model (half the ERA gap vs a 4.2 league average, about 35 Elo per run, capped at 40). ERA is noisy and starters can change late; TBD starters get no adjustment. NHL goalies have no free feed wired in yet.
- **Alerts (optional):** set a repo secret `NTFY_TOPIC` to a long random string and subscribe to that topic in the free ntfy app. You get one push per run listing new arbitrage (0.5%+), book-vs-Kalshi/Polymarket arbs (1%+ after estimated fees), middles (+2% EV) and 3-book edges of 6%+ EV, never repeated within 6 hours. Anyone who knows the topic name can read it, so treat it like a password. Without the secret nothing is sent.
- **Bankroll guardrails (Bet Ledger tab):** daily and weekly loss stops (settled losses plus money still open) and automatic stake cuts after a drawdown from peak (half at 10%, quarter at 20% by default). They apply to bets logged from the slate: stakes are cut, trimmed to the remaining loss budget, or blocked. Set a limit to 0 to switch it off.
- **Health check:** `slate.json` carries per-sport counts (games, with odds, books per game, model matches, MLB starters, prediction-market matches) and warnings. The Slate tab shows them under "Health check", so a source that returned nothing or team names that do not match is obvious on the first run.
- **Track Record:** every edge bet is saved once (`picks.json`) at the first price seen, settled from ESPN final scores, and summarized in `record.json` (ROI, CLV, wins vs expected, by sport). Judge ROI against its standard error; under 100 settled picks it is mostly luck. MMA picks are not graded (no score feed).
- **Tests** run before every build (`test_offline.py`, `test_model.py`, `test_extras.py`, `test_markets.py`, `test_grade.py`, `test_notify.py`, `test_soccer.py`, `test_review.py`); a failing test stops the run.


See `SETUP.md` (no-terminal setup), `TEAM.md` (specialist roles) and `RESEARCH.md` (what the team found, with sources).

## Collector network (pipeline/network.json)
Each data feed is a JSON spec (url with {date}/{season}, `items` path, `fields` map, `required`). `network.py` runs them every build, records health in `network_health.json` (pauses a collector for 24h after 5 straight failures) and stores the response shape on failure so a bad spec can be fixed from the real run. Results show in Today's Slate > Data collectors. Specs marked `verified: false` have not been tested against the live endpoint.
Add a feed: `python pipeline/spawn.py add --id ... --sport ... --kind ... --url https://... --items ... --field name=path` (https only, no credentials, duplicate ids refused). Probe first with `spawn.py probe URL`.
