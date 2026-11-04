"""Offline tests for pipeline/oddsapi.py -- no real network calls, no real key needed."""
import os, sys
sys.path.insert(0, os.path.dirname(__file__))
import oddsapi as oa

# ---- available() follows the module-level KEY exactly (set from env at import time, same pattern
# as kalshi_auth's available()) -- this test process has no ODDS_API_KEY set, so it must be off.
assert oa.available() == bool(oa.KEY)

# ---- parse_event: a real-shaped Odds API event -> our standard {home,away,start,books} shape,
# recognized books only, display names mapped, unknown bookmakers skipped rather than guessed at
ev = {
    "home_team": "Kansas City Chiefs", "away_team": "Buffalo Bills", "commence_time": "2026-11-09T18:00:00Z",
    "bookmakers": [
        {"key": "fanduel", "markets": [{"key": "h2h", "outcomes": [
            {"name": "Kansas City Chiefs", "price": -150}, {"name": "Buffalo Bills", "price": 130}]}]},
        {"key": "draftkings", "markets": [{"key": "h2h", "outcomes": [
            {"name": "Kansas City Chiefs", "price": -145}, {"name": "Buffalo Bills", "price": 125}]}]},
        {"key": "some_unlisted_book", "markets": [{"key": "h2h", "outcomes": [
            {"name": "Kansas City Chiefs", "price": -140}, {"name": "Buffalo Bills", "price": 120}]}]},
    ],
}
g = oa.parse_event(ev)
assert g == {
    "home": "Kansas City Chiefs", "away": "Buffalo Bills", "start": "2026-11-09T18:00:00Z",
    "books": {"FanDuel": {"home": -150.0, "away": 130.0}, "DraftKings": {"home": -145.0, "away": 125.0}},
}, g

# ---- missing team names -> None, not a half-built row
assert oa.parse_event({"home_team": None, "away_team": "X", "bookmakers": []}) is None

# ---- a bookmaker with no h2h market (e.g. only spreads requested some other time) is skipped, not crashed on
ev2 = {"home_team": "H", "away_team": "A", "bookmakers": [{"key": "fanduel", "markets": [{"key": "spreads", "outcomes": []}]}]}
assert oa.parse_event(ev2) is None

# ---- one-sided price (outcome missing or unmatched name) never produces a half-complete book entry
ev3 = {"home_team": "H", "away_team": "A", "bookmakers": [{"key": "fanduel", "markets": [{"key": "h2h", "outcomes": [{"name": "H", "price": -110}]}]}]}
assert oa.parse_event(ev3) is None

# ---- garbage/zero prices -> None, never a fabricated 0
assert oa._american(0) is None and oa._american(None) is None and oa._american("not a number") is None
assert oa._american("-150") == -150.0 and oa._american(130) == 130.0

# ---- fetch() is a hard no-op with no key: never even tries the network, returns the same contract
# as every other optional source here (empty list, no raise)
oa.KEY = None
got, remaining, used = oa.fetch("americanfootball_nfl", getter=lambda url: (_ for _ in ()).throw(AssertionError("must not be called with no key")))
assert got == [] and remaining is None and used is None

# ---- fetch() with a key: calls the getter once, parses every usable event, carries through the
# rate-limit headers, and a single malformed event never drops the rest of the slate
oa.KEY = "test-key-not-real"


def fake_getter(url):
    assert "apiKey=test-key-not-real" in url and "markets=h2h" in url and "regions=us" in url
    return [ev, {"home_team": None}, "not even a dict"], "123", "377"


got, remaining, used = oa.fetch("americanfootball_nfl", getter=fake_getter)
assert len(got) == 1 and got[0]["home"] == "Kansas City Chiefs" and remaining == "123" and used == "377", got
oa.KEY = None  # restore: don't leak state into other test files run in the same process
print("ODDSAPI TESTS PASS")
