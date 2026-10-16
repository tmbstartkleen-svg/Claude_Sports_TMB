#!/usr/bin/env python3
"""Offline tests for steam.py: no network, pure data in -> data out."""
import os, sys
from datetime import datetime, timedelta, timezone
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import steam as S

NOW = datetime(2026, 10, 20, 18, 0, tzinfo=timezone.utc)
START = (NOW + timedelta(hours=3)).isoformat()


def snap(mins_ago, fair_home):
    return {"t": (NOW - timedelta(minutes=mins_ago)).isoformat(timespec="seconds"), "fairHome": fair_home,
            "fairAway": 1 - fair_home, "bestHome": -110, "bestAway": -110, "nBooks": 3}


# ---- too little history: no signal, no crash
assert S.analyze_game([]) is None
assert S.analyze_game([snap(30, 0.55)]) is None

# ---- steady market, nothing worth flagging
quiet = [snap(120, 0.55), snap(90, 0.56), snap(60, 0.545), snap(30, 0.555)]
assert S.analyze_game(quiet) is None

# ---- a real steam move: one jump of 6 points in a single 30-min gap
steamed = [snap(120, 0.50), snap(90, 0.505), snap(60, 0.51), snap(30, 0.57)]  # last gap: +6pts
r = S.analyze_game(steamed)
assert r and r["kind"] == "steam" and r["side"] == "home" and r["biggestMovePts"] == 6.0, r

# ---- opposite direction steam is flagged toward away
steamed_away = [snap(90, 0.60), snap(60, 0.595), snap(30, 0.52)]  # last gap: -7.5pts
r2 = S.analyze_game(steamed_away)
assert r2 and r2["side"] == "away" and r2["biggestMovePts"] < 0, r2

# ---- slow drift: no single big jump, but total move clears the drift bar
drifted = [snap(240, 0.50), snap(180, 0.515), snap(120, 0.53), snap(60, 0.545), snap(10, 0.573)]  # total +7.3pts, biggest single gap 1.5-2.8pts
r3 = S.analyze_game(drifted)
assert r3 and r3["kind"] == "drift" and r3["side"] == "home" and r3["totalDriftPts"] >= S.BIG_DRIFT_PP, r3

# ---- attach(): wires row["key"] + history snapshots -> row["steam"], pre-game only, skips started games
hist = {
    "nfl|chiefs|bills|" + START[:16]: {"snaps": steamed},
    "nfl|packers|lions|" + START[:16]: {"snaps": quiet},
}
rows = [
    {"key": "nfl|chiefs|bills|" + START[:16], "start": START, "sport": "nfl", "home": "Bills", "away": "Chiefs"},
    {"key": "nfl|packers|lions|" + START[:16], "start": START, "sport": "nfl", "home": "Lions", "away": "Packers"},
    {"key": "nfl|nothing|here|" + START[:16], "start": START, "sport": "nfl", "home": "X", "away": "Y"},  # no history at all
    {"key": "nfl|already|started|" + START[:16], "start": (NOW - timedelta(hours=1)).isoformat(), "sport": "nfl", "home": "A", "away": "B"},  # in-play, must be skipped
]
hist["nfl|already|started|" + START[:16]] = {"snaps": steamed}
n = S.attach(rows, hist, NOW)
assert n == 1, n
assert rows[0]["steam"]["side"] == "home"
assert "steam" not in rows[1]   # quiet market, nothing flagged
assert "steam" not in rows[2]   # no history for this game
assert "steam" not in rows[3]   # already started: steam.py leaves this to CLV/grade.py

# ---- a row missing "key" or "start" never crashes attach()
assert S.attach([{"key": None, "start": START}, {"key": "x"}], hist, NOW) == 0

print("STEAM TESTS PASS")
