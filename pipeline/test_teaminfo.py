#!/usr/bin/env python3
"""Offline tests for teaminfo.py: no network, a small fake results list in -> h2h/form out."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import teaminfo as T

RESULTS = [
    {"id": "1", "date": "2026-09-01", "home": "Chiefs", "away": "Bills", "hs": 24.0, "as": 20.0},   # Chiefs win
    {"id": "2", "date": "2026-09-15", "home": "Bills", "away": "Chiefs", "hs": 17.0, "as": 27.0},   # Chiefs win (away)
    {"id": "3", "date": "2026-09-22", "home": "Chiefs", "away": "Jets", "hs": 10.0, "as": 10.0},    # tie
    {"id": "4", "date": "2026-10-01", "home": "Jets", "away": "Chiefs", "hs": 14.0, "as": 31.0},    # Chiefs win
    {"id": "5", "date": "2026-10-05", "home": "Chiefs", "away": "Dolphins", "hs": 13.0, "as": 20.0},  # Chiefs loss
    {"id": "6", "date": "2026-10-20", "home": "Chiefs", "away": "Bills", "hs": 21.0, "as": 24.0},   # future: after our cutoff
]

# ---- head-to-head: only Chiefs/Bills games, most recent first, respects before_date
h2h = T.head_to_head(RESULTS, "Chiefs", "Bills", before_date="2026-10-10")
assert len(h2h) == 2, h2h
assert h2h[0]["date"] == "2026-09-15" and h2h[1]["date"] == "2026-09-01", h2h

# ---- order of the two teams passed in doesn't matter
h2h_rev = T.head_to_head(RESULTS, "Bills", "Chiefs", before_date="2026-10-10")
assert h2h_rev == h2h

# ---- the future game is excluded once before_date cuts it off, included without a cutoff
assert len(T.head_to_head(RESULTS, "Chiefs", "Bills")) == 3

# ---- no shared games between two teams -> empty, no crash
assert T.head_to_head(RESULTS, "Chiefs", "Nobody") == []

# ---- team_form: Chiefs record/sequence through a cutoff (excludes the 10/20 game)
form = T.team_form(RESULTS, "Chiefs", before_date="2026-10-10")
assert form["record"] == "3-1-1", form   # W(9/1) W(9/15) T(9/22) W(10/1) L(10/5)
assert form["last"] == ["W", "W", "T", "W", "L"], form

# ---- a team with zero games gets a clean zero record, not a crash
assert T.team_form(RESULTS, "Nobody") == {"record": "0-0", "last": []}

# ---- attach(): wires sport -> results into each row's "matchup", skips sports with no cache
rows = [
    {"sport": "nfl", "home": "Chiefs", "away": "Bills", "start": "2026-10-10T18:00:00Z"},
    {"sport": "nfl", "home": "Nobody", "away": "AlsoNobody", "start": "2026-10-10T18:00:00Z"},  # no games -> no matchup
    {"sport": "nba", "home": "Chiefs", "away": "Bills", "start": "2026-10-10T18:00:00Z"},         # no cache for nba
    {"sport": "nfl", "home": None, "away": "Bills", "start": "2026-10-10T18:00:00Z"},             # missing name -> never crashes
]
n = T.attach(rows, {"nfl": RESULTS})
assert n == 1, n
assert "matchup" in rows[0] and rows[0]["matchup"]["home"]["record"] == "3-1-1"
assert len(rows[0]["matchup"]["h2h"]) == 2
assert "matchup" not in rows[1]
assert "matchup" not in rows[2]
assert "matchup" not in rows[3]

print("TEAMINFO TESTS PASS")
