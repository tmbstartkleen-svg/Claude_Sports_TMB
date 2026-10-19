import os, sys, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from datetime import datetime, timedelta, timezone
import grade as g

now = datetime(2026, 10, 12, 12, 0, tzinfo=timezone.utc)
start = (now + timedelta(hours=5)).isoformat()
def row(sport="nfl", three=False, side="Away FC", am=150):
    return {"sport": sport, "home": "Home FC", "away": "Away FC", "start": start, "threeWay": three, "key": f"{sport}|Away FC|Home FC|{start[:16]}",
            "bets": [{"side": side, "book": "BookX", "american": am, "fair": 0.45, "evPct": 12.5, "stake": 2.0}]}
picks = {}
assert g.record_picks(picks, [row()], now) == 1
assert g.record_picks(picks, [row(am=170)], now) == 0, "same pick must not be re-added at a better later price"
assert list(picks.values())[0]["american"] == 150
past = now - timedelta(hours=1)
assert g.record_picks({}, [dict(row(), start=past.isoformat())], now) == 0, "started games are never recorded"
print("OK record")

later = now + timedelta(hours=9)
fin = {"nfl": [{"home": "Home FC", "away": "Away FC", "hs": 17, "as": 24, "start": start}]}
assert g.settle(picks, fin, now) == 0, "not settled before start"
assert g.settle(picks, fin, later) == 1
p = list(picks.values())[0]
assert p["res"] == "W" and abs(g.pnl(p) - 3.0) < 1e-9, (p, g.pnl(p))  # $2 at +150 wins $3
print("OK settle win, pnl", g.pnl(p))

# series games: same teams on consecutive days must NOT settle on each other's score (reviewer finding 1)
s0 = now + timedelta(hours=5)
def series_row(day):
    st = (s0 + timedelta(days=day)).isoformat()
    return dict(row(sport="mlb", side="Away FC"), start=st, key=f"k{day}")
ser = {}
now2 = now
for d in (0, 1):
    g.record_picks(ser, [series_row(d)], now2)
fins = {"mlb": [{"home": "Home FC", "away": "Away FC", "hs": 1, "as": 5, "start": s0.isoformat()},          # game 1: away won
                {"home": "Home FC", "away": "Away FC", "hs": 6, "as": 2, "start": (s0 + timedelta(days=1)).isoformat()}]}
g.settle(ser, fins, now + timedelta(days=3))
res = sorted((p["start"], p["res"], p["score"]) for p in ser.values())
assert [r[1] for r in res] == ["W", "L"] and [r[2] for r in res] == ["5-1", "2-6"], res
# names that differ only by accents/punctuation still match; different clubs sharing a last word do not
import names as N
assert N.same("St. Louis Blues", "St Louis Blues") and N.same("Montréal Canadiens", "Montreal Canadiens") and N.same("Brighton & Hove Albion", "Brighton and Hove Albion")
assert N.same("Inter Milan", "Internazionale") and N.same("Paris Saint-Germain", "Paris Saint Germain") and N.same("Arsenal FC", "Arsenal")
assert not N.same("Chicago White Sox", "Boston Red Sox") and not N.same("Manchester City", "Leicester City") and not N.same("Heat", "Wheat Kings")
print("OK series + names")

# loss, push and draw rules
t = {"side": "home", "american": -110, "stake": 1, "res": None, "sport": "nba", "start": start, "home": "A", "away": "B"}
assert g.result_of(t, {"hs": 100, "as": 90}) == "W" and g.result_of(t, {"hs": 90, "as": 100}) == "L"
assert g.result_of(t, {"hs": 90, "as": 90}) == "P"
assert g.result_of(dict(t, threeWay=True), {"hs": 1, "as": 1}) == "L"
assert g.result_of(dict(t, side="draw", threeWay=True), {"hs": 1, "as": 1}) == "W"
print("OK result rules")

# void after 4 days with no final
p2 = {}
g.record_picks(p2, [row()], now)
assert g.settle(p2, {}, now + timedelta(days=6)) == 0 and list(p2.values())[0]["res"] == "V"
assert g.summarize(p2)["overall"]["n"] == 0, "void picks excluded"
print("OK void")

# CLV: price 150 (dec 2.5), close fair 0.45 -> 2.5*0.45-1 = +12.5%
closing = {p["key"]: {"fairHome": 0.55, "fairAway": 0.45}}
assert g.attach_clv(picks, closing) == 0, "close with no book count or minutes info is refused"
closing = {p["key"]: {"fairHome": 0.55, "fairAway": 0.45, "nBooks": 3, "minutesBeforeStart": 200}}
assert g.attach_clv(picks, closing) == 0, "a close captured 200 minutes early is stale, so no CLV"
closing = {p["key"]: {"fairHome": 0.55, "fairAway": 0.45, "nBooks": 1, "minutesBeforeStart": 20}}
assert g.attach_clv(picks, closing) == 0, "a single-book close is refused"
closing = {p["key"]: {"fairHome": 0.55, "fairAway": 0.45, "nBooks": 3, "minutesBeforeStart": 20}}
assert g.attach_clv(picks, closing) == 1 and abs(p["clv"] - 0.125) < 1e-9
assert g.attach_clv(picks, closing) == 0, "CLV set once"
print("OK clv")

# summary math on a synthetic book of picks with a known true edge
import random
random.seed(5); big = {}
for i in range(400):
    am = random.choice([-110, 120, 150])
    d = g.am_to_dec(am); fair = 1 / d + 0.03
    big[str(i)] = {"sport": "nba" if i % 2 else "nfl", "home": "H", "away": "A", "start": start, "side": "home", "team": "H", "book": "B", "american": am,
                   "fairAtPick": fair, "evPct": 3, "stake": 1.0, "basis": "consensus", "res": "W" if random.random() < fair else "L"}
s = g.summarize(big)
o = s["overall"]
assert o["n"] == 400 and set(s["bySport"]) == {"nba", "nfl"}
ret = [(g.am_to_dec(p["american"]) - 1) if p["res"] == "W" else -1 for p in big.values()]
assert abs(o["flatRoi"] - sum(ret) / 400) < 1e-3
sd = math.sqrt(sum((x - sum(ret) / 400) ** 2 for x in ret) / 399)
assert abs(o["flatRoiSE"] - sd / 20) < 1e-3
assert abs(o["wins"] - o["expectedWins"]) < 4 * math.sqrt(400 * 0.25), "wins track the probabilities they were drawn from"
assert "standard error" in s["note"]
print("OK summary", o["roi"], o["flatRoiSE"])

# timeline: oldest-first, cumulative, independent of stake size
tl = s["timeline"]
assert all(tl[i]["date"] <= tl[i + 1]["date"] for i in range(len(tl) - 1)), "timeline must be oldest-first"
assert len(tl) == min(400, g.MAX_TIMELINE), "timeline caps to MAX_TIMELINE most-recent settled picks"
small = g.summarize({"a": {"sport": "nfl", "home": "H", "away": "A", "start": start, "side": "home", "american": 150, "fairAtPick": 0.4,
                            "stake": 1, "res": "W", "clv": 0.1, "basis": "consensus"},
                      "b": {"sport": "nfl", "home": "H", "away": "A", "start": (now + timedelta(days=1)).isoformat(), "side": "home",
                            "american": -110, "fairAtPick": 0.5, "stake": 1, "res": "L", "clv": 0.2, "basis": "consensus"}})["timeline"]
assert len(small) == 2 and small[0]["cumPnl"] == 1.5 and abs(small[1]["cumPnl"] - 0.5) < 1e-9
assert small[0]["cumAvgClv"] == 0.1 and abs(small[1]["cumAvgClv"] - 0.15) < 1e-9, small
assert g.summarize({})["timeline"] == []
print("OK timeline")
print("GRADE TESTS PASS")
