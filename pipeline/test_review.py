"""Regression tests for the independent code review's findings."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from datetime import datetime, timezone, timedelta
import build_slate as b, model as M, history as H

NOW = datetime(2026, 10, 1, tzinfo=timezone.utc)
START = "2026-10-12T20:00:00Z"

# finding 2: soccer game where one book lacks a draw price must stay three-way (drop that book), never become two-way
g = {"sport": "epl", "home": "Arsenal", "away": "Chelsea", "start": START, "books": {
    "A": {"home": -110, "draw": 280, "away": 300}, "B": {"home": -105, "draw": 270, "away": 290}, "C": {"home": -108, "away": 295}}}
r = b.analyze([g], [], now=NOW)[0]
assert r["threeWay"] and r["nBooks"] == 2 and abs(sum(r["fair"].values()) - 1) < 1e-3 and r["fair"]["draw"] > 0.15, r
assert b.analyze([dict(g, books={"C": {"home": -108, "away": 295}})], [], now=NOW) == [], "no draw price anywhere: skip, don't invent a 2-way market"
print("OK soccer 3-way")

# finding 3: prediction-market title filtering
game = {"home": "Boston Celtics", "away": "New York Knicks"}
pm = lambda t, **k: dict({"source": "kalshi", "title": t, "yes": 0.4, "url": ""}, **k)
ok = pm("Will the Celtics win against the Knicks?")
bad = [pm("Will the Celtics win by over 5.5 points against the Knicks?"), pm("Celtics vs Knicks: Spread -3.5"), pm("Celtics vs Knicks total points over 220"),
       pm("Will the Celtics win and the Knicks lose, yes or no?"), pm("Will Celtics win the NBA Championship, Knicks eliminated?")]
assert b.match_pm(game, [ok] + bad) == [ok], [m["title"] for m in b.match_pm(game, [ok] + bad)]
assert b.pm_prob_for(ok, "Boston Celtics") == 0.4 and b.pm_prob_for(ok, "New York Knicks") is None
assert b.pm_prob_for(bad[0], "Boston Celtics") is None
assert b.match_pm({"home": "Miami Heat", "away": "Phoenix Suns"}, [pm("Will Wheat win against Suns?")]) == [], "word boundaries: heat is not wheat"
poly = {"source": "polymarket", "title": "Celtics vs Knicks", "outcomes": ["Celtics", "Knicks"], "prices": [0.6, 0.4]}
assert b.pm_prob_for(poly, "Boston Celtics") == 0.6
print("OK pm matching")

# finding 9: live games are never analyzed
live = dict(g, sport="nba", start="2026-09-30T00:00:00Z", books={"A": {"home": -110, "away": -110}, "B": {"home": 105, "away": 105}})
assert b.analyze([live], [], now=NOW) == []
print("OK live games skipped")

# finding 12: best price is not judged against itself; consensus bets need 3 books
three = {"sport": "nba", "home": "H", "away": "A", "start": START, "books": {
    "A": {"home": -120, "away": 100}, "B": {"home": -118, "away": 102}, "C": {"home": -122, "away": 118}}}
r3 = b.analyze([three], [], now=NOW)[0]
away_bets = [x for x in r3["bets"] if x["side"] == "A"]
assert away_bets and away_bets[0]["book"] == "C", r3["bets"]
fair_all = r3["fair"]["away"]
assert away_bets[0]["fair"] <= fair_all + 1e-9, "a bet's fair price is the lower of the all-books and ex-best-book consensus, never more generous than either"
two = dict(three, books={"A": three["books"]["A"], "C": three["books"]["C"]})
assert b.analyze([two], [], now=NOW)[0]["bets"] == [], "two books: no consensus edge bet"
print("OK EV honesty")

# finding 5: model lookups survive accents, punctuation and short forms
games = [{"id": str(i), "date": f"2026-0{1 + i // 20}-{1 + i % 20:02d}", "home": h, "away": a, "hs": 3, "as": 2}
         for i, (h, a) in enumerate([("St. Louis Blues", "Montréal Canadiens"), ("Montréal Canadiens", "St. Louis Blues")] * 20)]
m = M.build("nhl", games)
d = datetime(2026, 8, 1).date()
p1 = M.predict("nhl", m, "St Louis Blues", "Montreal Canadiens", d)
p2 = M.predict("nhl", m, "St. Louis Blues", "Montréal Canadiens", d)
assert p1 is not None and abs(p1 - p2) < 1e-12, (p1, p2)
assert M.predict("nhl", m, "St Louis Blues", "Montreal Canadiens", d, {"St Louis Blues": -50}) < p1, "injury keys resolve through the same canon"
print("OK names in models")

# finding 8: no snapshot churn when nothing moved; moves are recorded
row = {"sport": "nfl", "home": "H", "away": "A", "start": "2026-10-12T20:00:00Z", "nBooks": 3, "fair": {"home": .58, "away": .42},
       "best": {"home": {"american": -140}, "away": {"american": 125}}}
h = {}
t0 = datetime(2026, 10, 12, 12, 0, tzinfo=timezone.utc)
assert H.record(h, [row], t0) == 1 and H.record(h, [row], t0 + timedelta(minutes=30)) == 0
assert H.record(h, [dict(row, fair={"home": .59, "away": .41})], t0 + timedelta(minutes=31)) == 1
assert H.record(h, [row], t0 + timedelta(minutes=95)) == 1, "an hour later, record a heartbeat snapshot even if nothing moved"
print("OK history churn")

# finding 11: holes in the ESPN history must stop the model
def flaky(url):
    raise OSError("boom")
try:
    M.fetch_results("nba", datetime(2026, 3, 1).date(), flaky); raise SystemExit("should have refused")
except RuntimeError as e:
    assert "refusing" in str(e)
print("OK incomplete history refused")

# cross-arb sanity flag
import markets as mk
row2 = {"best": {"home": {"decimal": 2.2, "book": "X", "american": 120}, "away": {"decimal": 2.2, "book": "Y", "american": 120}}}
arbs = mk.cross_arbs(row2, [{"source": "polymarket", "title": "t", "home": 0.30}])
assert arbs and arbs[0]["suspect"] and "mismatched" in arbs[0]["note"], arbs
print("REVIEW TESTS PASS")

# damaged files are never silently replaced by empty ones
import grade as G, tempfile, json as _j
d_ = tempfile.mkdtemp(); bad_ = f"{d_}/picks.json"; open(bad_, "w").write("{not json")
for loader in (G.load, H.load):
    try:
        loader(bad_); raise SystemExit("must refuse a corrupt file")
    except RuntimeError as e:
        assert "not overwriting" in str(e)
assert G.load(f"{d_}/missing.json") == {} and H.load(f"{d_}/missing.json") == {}
print("OK corrupt files refused")
# record.json is only rewritten when the numbers change (no commit every 30 minutes)
os.environ.update({"PICKS_PATH": f"{d_}/p.json", "RECORD_PATH": f"{d_}/r.json"})
b.grade_step([], {}, True, NOW); t1 = os.path.getmtime(f"{d_}/r.json"); c1 = open(f"{d_}/r.json").read()
b.grade_step([], {}, True, NOW + timedelta(hours=1)); assert open(f"{d_}/r.json").read() == c1, "unchanged summary must not rewrite record.json (timestamp included)"
print("OK record churn")
print("REVIEW TESTS PASS (final)")
