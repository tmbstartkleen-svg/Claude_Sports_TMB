#!/usr/bin/env python3
"""Offline tests for timing.py: no network, no files -- pure data in, data out."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from datetime import datetime, timedelta, timezone
import timing as T

NOW = datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc)


def game(sport="nba", home="Home Team", away="Away Team", hours_out=24, steam=None):
    start = NOW + timedelta(hours=hours_out)
    r = {"sport": sport, "home": home, "away": away, "start": start.isoformat().replace("+00:00", "Z")}
    if steam:
        r["steam"] = steam
    return r


def bet(side):
    return {"side": side}


# ---- missing/invalid start: no advice
assert T.advise({"sport": "nba", "home": "H", "away": "A"}, bet("H"), {}, NOW) is None
assert T.advise({"sport": "nba", "home": "H", "away": "A", "start": "not-a-date"}, bet("H"), {}, NOW) is None

# ---- already started: a pre-game timing call doesn't apply
r = game(hours_out=-0.5)
assert T.advise(r, bet("Home Team"), {}, NOW) is None
print("OK no-op cases")

# ---- inside the closing window: always "closing_soon", regardless of other signals
r = game(hours_out=1.0, steam={"side": "away", "biggestMovePts": 10})
t = T.advise(r, bet("Home Team"), {"bySport": {"nba": {"avgClv": 0.05, "nClv": 500}}}, NOW)
assert t["advice"] == "closing_soon" and t["hoursToStart"] == 1.0
print("OK closing_soon overrides other signals")

# ---- steam moving toward our side: buy now, price is disappearing
r = game(hours_out=10, steam={"side": "home", "biggestMovePts": 5.5, "totalDriftPts": 5.5})
t = T.advise(r, bet("Home Team"), {}, NOW)
assert t["advice"] == "buy_now" and "5.5" in t["reasons"][0]
print("OK steam toward our side -> buy_now")

# ---- steam moving away from our side: wait is plausible, price may hold/improve
r = game(hours_out=10, steam={"side": "away", "biggestMovePts": 5.5, "totalDriftPts": 5.5})
t = T.advise(r, bet("Home Team"), {}, NOW)
assert t["advice"] == "wait_ok"
print("OK steam away from our side -> wait_ok")

# ---- no steam, strong positive historical CLV with enough sample: buy_now, cites the stat
r = game(hours_out=10)
t = T.advise(r, bet("Home Team"), {"bySport": {"nba": {"avgClv": 0.03, "nClv": 200}}}, NOW)
assert t["advice"] == "buy_now" and "3.0%" in t["reasons"][0]
print("OK positive historical CLV -> buy_now")

# ---- no steam, strong negative historical CLV: wait_ok, cites the stat
t = T.advise(r, bet("Home Team"), {"bySport": {"nba": {"avgClv": -0.02, "nClv": 200}}}, NOW)
assert t["advice"] == "wait_ok" and "2.0%" in t["reasons"][0]
print("OK negative historical CLV -> wait_ok")

# ---- not enough graded history yet: says so, doesn't fabricate a direction
t = T.advise(r, bet("Home Team"), {"bySport": {"nba": {"avgClv": 0.05, "nClv": 5}}}, NOW)
assert t["advice"] == "no_strong_signal" and "Not enough graded history" in t["reasons"][0]
t = T.advise(r, bet("Home Team"), {}, NOW)
assert t["advice"] == "no_strong_signal" and "Not enough graded history" in t["reasons"][0]
print("OK insufficient sample -> no_strong_signal, says why")

# ---- steam present but small/ambiguous historical CLV: steam signal still used, no contradiction in reasons
r = game(hours_out=10, steam={"side": "home", "biggestMovePts": 4.0})
t = T.advise(r, bet("Home Team"), {"bySport": {"nba": {"avgClv": 0.001, "nClv": 500}}}, NOW)
assert t["advice"] == "buy_now"  # steam decided it; the tiny CLV isn't meaningful either way
print("OK steam wins when historical CLV is negligible")

# ---- draw side resolves correctly (three-way markets)
r = game(hours_out=10, steam={"side": "away", "biggestMovePts": 6})
t = T.advise(r, bet("Draw"), {}, NOW)
assert t["advice"] == "wait_ok"  # draw isn't home or away, so side_key falls through to "draw", steam side is "away" -> not toward us
print("OK three-way draw side handled")

# ---- attach(): mutates rows, returns count, skips games it can't say anything about
rows = [
    {**game(hours_out=10, steam={"side": "home", "biggestMovePts": 5}), "bets": [{"side": "Home Team"}, {"side": "Away Team"}]},
    {"sport": "nba", "home": "H2", "away": "A2", "bets": [{"side": "H2"}]},  # no start: skipped
]
n = T.attach(rows, {}, NOW)
assert n == 2, n
assert rows[0]["bets"][0]["timing"]["advice"] == "buy_now"
assert rows[0]["bets"][1]["timing"]["advice"] == "wait_ok"
assert "timing" not in rows[1]["bets"][0]
print("OK attach() wiring")

print("TIMING TESTS PASS")
