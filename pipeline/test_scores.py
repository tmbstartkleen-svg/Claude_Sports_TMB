#!/usr/bin/env python3
"""Offline tests for scores.py: no network, fake ESPN scoreboard payloads in -> data out."""
import os, sys
from datetime import date, timedelta
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import scores as S


def ev(home, away, hs=None, as_=None, state="pre", completed=False, detail="", gid="1"):
    def comp(name, score, ha):
        c = {"team": {"displayName": name}, "homeAway": ha}
        if score is not None:
            c["score"] = str(score)
        return c
    return {
        "id": gid, "date": "2026-10-20T18:00Z",
        "links": [{"href": f"https://www.espn.com/nfl/game/_/gameId/{gid}"}],
        "competitions": [{
            "competitors": [comp(home, hs, "home"), comp(away, as_, "away")],
            "status": {"type": {"state": state, "completed": completed, "shortDetail": detail},
                       "displayClock": "5:00", "period": 2},
        }],
    }


# ---- a normal pre-game event parses cleanly, no score yet
g = S._game(ev("Chiefs", "Bills"), "nfl", "football/nfl")
assert g["home"] == "Chiefs" and g["away"] == "Bills"
assert g["homeScore"] is None and g["state"] == "pre" and not g["completed"]
assert g["link"].startswith("https://www.espn.com/")

# ---- a live game carries scores and state "in"
g2 = S._game(ev("Chiefs", "Bills", 14, 10, state="in", detail="Q2 5:00"), "nfl", "football/nfl")
assert g2["homeScore"] == 14 and g2["awayScore"] == 10 and g2["state"] == "in" and g2["detail"] == "Q2 5:00"

# ---- a finished game is marked completed
g3 = S._game(ev("Chiefs", "Bills", 27, 20, state="post", completed=True, detail="Final"), "nfl", "football/nfl")
assert g3["completed"] and g3["state"] == "post" and g3["homeScore"] == 27

# ---- a malformed event (no competitors) never crashes the day fetch
assert S._game({"competitions": [{}]}, "nfl", "football/nfl") is None


# ---- fetch_day tolerates a bad response shape and skips games missing a side
def fake_getter_ok(url):
    return {"events": [ev("Chiefs", "Bills", gid="1"), {"competitions": [{}]}, ev("Packers", "", gid="2")]}


out = S.fetch_day("nfl", "football/nfl", date(2026, 10, 20), fake_getter_ok)
assert len(out) == 1 and out[0]["home"] == "Chiefs", out

assert S.fetch_day("nfl", "football/nfl", date(2026, 10, 20), lambda url: None) == []


# ---- fetch_week: spans WEEK_DAYS days from today, dedupes, sorts earliest-first
def fake_getter_week(url):
    # vary the matchup by the requested date so each day returns a distinct game
    d = url.split("dates=")[1]
    return {"events": [ev(f"Home{d}", f"Away{d}", gid=d)]}


games = S.fetch_week(["nfl"], {"nfl": "football/nfl"}, today=date(2026, 10, 20), getter=fake_getter_week, days=3)
assert len(games) == 3, games
assert games[0]["start"] <= games[1]["start"] <= games[2]["start"]

# ---- one sport/day erroring doesn't blank the whole week
def flaky_getter(url):
    if "20261021" in url:
        raise RuntimeError("boom")
    d = url.split("dates=")[1]
    return {"events": [ev(f"Home{d}", f"Away{d}", gid=d)]}


games2 = S.fetch_week(["nfl"], {"nfl": "football/nfl"}, today=date(2026, 10, 20), getter=flaky_getter, days=3)
assert len(games2) == 2, games2  # the one bad day is skipped, not fatal

print("SCORES TESTS PASS")
