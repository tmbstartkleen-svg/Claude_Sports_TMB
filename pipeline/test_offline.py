"""Offline test: fake sources, verifies analysis, arb detection, PM matching, sim, and fallback order."""
import os, sys, json
from datetime import datetime, timezone
sys.path.insert(0, os.path.dirname(__file__))
import build_slate as b

games = [
 {"sport":"nfl","home":"Kansas City Chiefs","away":"Buffalo Bills","start":"2026-10-12T00:20:00Z",
  "books":{"DraftKings":{"home":-150,"away":130},"FanDuel":{"home":-140,"away":125},"BetMGM":{"home":-165,"away":150}}},
 {"sport":"nba","home":"Boston Celtics","away":"Miami Heat","start":"x",
  "books":{"A":{"home":+105,"away":+105},"B":{"home":-110,"away":-110}}},
]
pms=[{"source":"polymarket","title":"Chiefs vs. Bills","outcomes":["Chiefs","Bills"],"prices":[0.55,0.45],"url":"u"}]
rows=b.analyze(games,pms,now=datetime(2026,10,11,tzinfo=timezone.utc))
assert b.analyze(games,pms,now=datetime(2026,10,12,1,tzinfo=timezone.utc))[0:1] and all(r['home']!='Kansas City Chiefs' for r in b.analyze(games,pms,now=datetime(2026,10,12,1,tzinfo=timezone.utc))), 'started game must be dropped'
r0,r1=rows
assert r0["nBooks"]==3 and abs(r0["fair"]["home"]+r0["fair"]["away"]-1)<1e-6
assert r0["best"]["away"]["book"]=="BetMGM" and r0["best"]["away"]["american"]==150
assert r0["pm"] and "homeEdgePp" in r0["pm"][0]
# allBooks: every book's own price per outcome rides along, not just the single best one (lets the UI show a
# real DraftKings-vs-FanDuel-vs-BetMGM side-by-side, not just "here's the best price")
assert len(r0["allBooks"]["away"])==3
assert {x["book"]: x["american"] for x in r0["allBooks"]["away"]} == {"DraftKings": 130, "FanDuel": 125, "BetMGM": 150}
assert r1["arb"] and abs(r1["impliedSum"]-(1/2.05*2))<1e-3, r1  # +105 both sides
assert abs(r1["arbRoiPct"]-2.5)<0.01, r1["arbRoiPct"]
day=b.simulate_day(rows,N=4000)
assert day and day["var95"]<=b.DAY_BUDGET+0.5, day
# fallback order: primary fails, fallback used, logged
b.LOG.clear()
out=b.try_sources("t",[("p",lambda:(_ for _ in ()).throw(RuntimeError("down"))),("f",lambda:[1]),("g",lambda:[2])])
assert out==[1] and [l["ok"] for l in b.LOG]==[False,True], b.LOG
# ESPN shapes
espn={"events":[{"date":"d","competitions":[{"competitors":[{"homeAway":"home","team":{"displayName":"H"}},{"homeAway":"away","team":{"displayName":"A"}}],
 "odds":[{"provider":{"name":"DraftKings"},"moneyline":{"home":{"close":{"odds":"-150"}},"away":{"close":{"odds":"+130"}}}}]}]}]}
g=b._espn_events("nfl",espn); assert g[0]["books"]["DraftKings"]=={"home":-150.0,"away":130.0}, g
assert "venue" not in g[0], "no venue in the raw event -> no venue key, never a spurious empty one"
# venue: captured when ESPN's own event carries one, and rides through analyze() onto the output row
espn_v={"events":[{"date":"d","competitions":[{"competitors":[{"homeAway":"home","team":{"displayName":"H"}},{"homeAway":"away","team":{"displayName":"A"}}],
 "odds":[{"provider":{"name":"DraftKings"},"moneyline":{"home":{"close":{"odds":"-150"}},"away":{"close":{"odds":"+130"}}}}],
 "venue":{"fullName":"Arrowhead Stadium","address":{"city":"Kansas City","state":"MO"}}}]}]}
gv=b._espn_events("nfl",espn_v)
assert gv[0]["venue"]=={"name":"Arrowhead Stadium","location":"Kansas City, MO"}, gv[0]
rv=b.analyze(gv,[],now=datetime(2026,1,1,tzinfo=timezone.utc))[0]
assert rv["venue"]["name"]=="Arrowhead Stadium"
print("ALL OFFLINE TESTS PASS"); print(json.dumps(day))
