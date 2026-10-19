#!/usr/bin/env python3
"""Offline tests for live.py: no network. Fakes match_pm/pm_prob_for the way build_slate.py's
real ones behave (match on team names, return a 0..1 home probability) so this module's own
record()/prune()/analyze() logic is exercised without importing build_slate."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from datetime import datetime, timedelta, timezone
import live as L

NOW = datetime(2026, 10, 18, 20, 0, tzinfo=timezone.utc)


def fake_match_pm(g, pms):
    return [m for m in pms if m["home"] == g["home"] and m["away"] == g["away"]]


def fake_pm_prob_for(m, team):
    return m["home_prob"] if team == m["home"] else (1 - m["home_prob"])


def live_game(home="Home", away="Away", sport="nba", start="2026-10-18T19:00:00Z", **kw):
    g = {"sport": sport, "home": home, "away": away, "start": start, "state": "in",
         "detail": "Q3 6:42", "homeScore": 61, "awayScore": 58}
    g.update(kw)
    return g


def pm(home, away, home_prob):
    return {"home": home, "away": away, "home_prob": home_prob}


# ---- record(): no match -> nothing added
store = {}
n = L.record(store, [live_game()], [], fake_match_pm, fake_pm_prob_for, NOW)
assert n == 0 and store == {}
print("OK no kalshi match -> no snapshot")

# ---- record(): a real match adds a snapshot
pms = [pm("Home", "Away", 0.62)]
n = L.record(store, [live_game()], pms, fake_match_pm, fake_pm_prob_for, NOW)
assert n == 1 and len(store) == 1
k = next(iter(store))
assert store[k]["snaps"][0]["fairHome"] == 0.62
print("OK first live snapshot recorded")

# ---- record(): unchanged price within the repeat window does not grow the store
n = L.record(store, [live_game()], pms, fake_match_pm, fake_pm_prob_for, NOW + timedelta(minutes=2))
assert n == 0 and len(store[k]["snaps"]) == 1
print("OK unchanged price within window: no duplicate snapshot")

# ---- record(): a moved price after the repeat window adds a new snapshot
pms2 = [pm("Home", "Away", 0.70)]
n = L.record(store, [live_game(homeScore=70, awayScore=60, detail="Q4 2:10")], pms2, fake_match_pm, fake_pm_prob_for, NOW + timedelta(minutes=12))
assert n == 1 and len(store[k]["snaps"]) == 2 and store[k]["snaps"][-1]["fairHome"] == 0.70
print("OK moved price adds a new snapshot")

# ---- record(): caps snapshot count
for i in range(70):
    pms_i = [pm("Home", "Away", 0.5 + (i % 10) * 0.01)]
    L.record(store, [live_game()], pms_i, fake_match_pm, fake_pm_prob_for, NOW + timedelta(minutes=20 + i * 6))
assert len(store[k]["snaps"]) <= L.MAX_SNAPS
print("OK snapshot list is capped")

# ---- prune(): drops games with no recent snapshot, keeps fresh ones
stale_k = "nba|stale|team|2026-10-01T00:00"
store[stale_k] = {"sport": "nba", "home": "Stale", "away": "Team", "start": "2026-10-01T00:00:00Z",
                   "snaps": [{"t": (NOW - timedelta(hours=20)).isoformat(timespec="seconds"), "fairHome": 0.5}]}
L.prune(store, NOW + timedelta(hours=2))
assert stale_k not in store and k in store
print("OK prune drops stale games, keeps live ones")

# ---- prune(): a game with zero snapshots (malformed) is dropped, never raises
store["broken"] = {"sport": "nba", "home": "X", "away": "Y", "start": None, "snaps": []}
L.prune(store, NOW)
assert "broken" not in store
print("OK prune handles an empty snapshot list without crashing")

# ---- analyze(): no closing data -> no swing field, but move/snapshot info present
fresh = {}
fresh_k = L.record(fresh, [live_game()], pms, fake_match_pm, fake_pm_prob_for, NOW)
items = L.analyze(fresh)
assert len(items) == 1
row = items[0]
assert row["kalshiHome"] == 0.62 and row["sport"] == "nba" and "swingPts" not in row
print("OK analyze() with no closing-line data: no swing claimed")

# ---- analyze(): with a closing line far from the live price -> swing flagged
from history import game_key
ck = game_key("nba", "Away", "Home", "2026-10-18T19:00:00Z")
closing = {ck: {"fairHome": 0.40}}
items = L.analyze(fresh, closing)
row = items[0]
assert row["swingPts"] == 22.0 and row["swingSide"] == "home" and row["closeHome"] == 0.40
print("OK analyze() flags a big live-vs-close swing")

# ---- analyze(): closing line close to live price -> no swing (below threshold)
closing2 = {ck: {"fairHome": 0.60}}
items2 = L.analyze(fresh, closing2)
assert "swingPts" not in items2[0]
print("OK analyze() does not flag a small, unremarkable swing")

# ---- analyze(): live "steam" detected via reused steam.py math across live snapshots
steamy = {}
L.record(steamy, [live_game()], [pm("Home", "Away", 0.50)], fake_match_pm, fake_pm_prob_for, NOW)
L.record(steamy, [live_game()], [pm("Home", "Away", 0.65)], fake_match_pm, fake_pm_prob_for, NOW + timedelta(minutes=15))
items3 = L.analyze(steamy)
assert items3[0].get("move") and items3[0]["move"]["kind"] == "steam" and items3[0]["move"]["side"] == "home"
print("OK in-game steam detected via reused steam.py logic")

print("LIVE TESTS PASS")
