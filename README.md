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
- **Injuries (rough):** ESPN's injury list, position-based and capped (NFL QB out = about -100 Elo; others small). It cannot tell NBA stars from bench players.
- **Closing lines:** capture runs every 30 minutes on game days (free sources only) save each game's market price to `history.json`.
  The last price seen before the start is the "closing line", so it can be up to ~30 min early. Edge Suite's Today's Slate tab can copy those into the CLV tab for bets you logged from the slate.
- **Netlify:** `netlify.toml` skips deploys when only `history.json` changed.
- **Tests** run before every build (`test_offline.py`, `test_model.py`, `test_extras.py`); a failing test stops the run.
