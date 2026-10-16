from datetime import datetime as _dt, timezone as _tz
NOW = _dt(2026, 10, 1, tzinfo=_tz.utc)
import os, sys, math, json, tempfile
sys.path.insert(0, os.path.dirname(__file__))
import markets as mk, build_slate as b

# ---- p_integers_between vs brute-force normal pmf
def pmf(m, mu, sd): return math.exp(-((m - mu) ** 2) / (2 * sd * sd)) / (sd * math.sqrt(2 * math.pi))
for lo, hi, mu, sd in [(2.5, 3.5, 3, 13.2), (44.5, 46.5, 46, 13), (1.5, 4.5, 2, 2.3), (3, 4, 3, 13)]:
    brute = sum(pmf(m, mu, sd) for m in range(-200, 200) if lo < m < hi)
    got = mk.p_integers_between(lo, hi, mu, sd)
    assert abs(got - brute) < 0.004, (lo, hi, got, brute)      # normal-cdf continuity correction vs pmf: close, not exact
assert mk.p_integers_between(3, 4, 3, 13) == 0.0                # whole-number lines: no integer strictly between -> no middle

# ---- middle payoff algebra at -110/-110
s1, s2, outer, mid, ev = mk._middle_ev(1 + 100 / 110, 1 + 100 / 110, 0.1)
assert abs(s1 - .5) < 1e-9 and abs(outer + 0.04545) < 1e-4 and abs(mid - 0.90909) < 1e-4, (outer, mid)
assert abs(ev - (0.1 * mid + 0.9 * outer)) < 1e-12
# breakeven middle prob = -outer/(mid-outer) ~ 4.76%
be = -outer / (mid - outer); assert 0.045 < be < 0.05, be
g = {"home": "H", "away": "A", "spreads": {"B1": {"home": (-2.5, -110), "away": (2.5, -110)}, "B2": {"home": (-3.5, -110), "away": (3.5, -110)}}}
m = mk.find_middles(g, "nfl"); assert len(m) == 1 and m[0]["gap"] == 1.0 and "H -2.5 @ B1" in m[0]["legA"] and "A +3.5 @ B2" in m[0]["legB"], m
assert mk.find_middles({"home": "H", "away": "A", "spreads": {"B1": {"home": (-3, -110), "away": (3, -110)}, "B2": {"home": (-3, -110), "away": (3, -110)}}}, "nfl") == []
t = mk.find_middles({"home": "H", "away": "A", "totals": {"X": {"over": (44.5, -110), "under": (44.5, -110)}, "Y": {"over": (47.5, -110), "under": (46.5, -110)}}}, "nfl")
assert t and t[0]["kind"] == "total" and "Over 44.5 @ X" in t[0]["legA"] and "Under 46.5 @ Y" in t[0]["legB"], t

# ---- cross-venue arbitrage with fees
row = {"best": {"home": {"book": "DK", "american": -105, "decimal": 1.952}, "away": {"book": "FD", "american": 100, "decimal": 2.0}}}
a = mk.cross_arbs(row, [{"source": "polymarket", "title": "t", "home": None, "away": 0.45}])
assert a and a[0]["bookSide"] == "home" and a[0]["pmSide"] == "away" and 0.96 < a[0]["allInCost"] < 0.98, a
k = mk.cross_arbs(row, [{"source": "kalshi", "title": "t", "home": None, "away": 0.45}])
assert k and k[0]["allInCost"] > a[0]["allInCost"] and 0.5 < k[0]["roiPct"] < 2, k   # Kalshi fee shrinks the edge
assert mk.cross_arbs(row, [{"source": "polymarket", "title": "t", "home": None, "away": 0.49}]) == []   # edge gone after slippage
assert mk.cross_arbs({"best": {**row["best"], "draw": {"decimal": 3}}}, [{"source": "kalshi", "title": "t", "away": .3}]) == []  # 3-way skipped

# ---- ESPN-shaped soccer payload with draw, two books (no paid odds feed anywhere in this pipeline)
soccer2 = {"events": [{"date": "2026-10-12T14:00:00Z", "competitions": [{"competitors": [
    {"homeAway": "home", "team": {"displayName": "Arsenal"}}, {"homeAway": "away", "team": {"displayName": "Chelsea"}}],
   "odds": [
     {"provider": {"name": "DraftKings"}, "homeTeamOdds": {"moneyLine": 120}, "awayTeamOdds": {"moneyLine": 240}, "drawOdds": {"moneyLine": 230}},
     {"provider": {"name": "FanDuel"}, "homeTeamOdds": {"moneyLine": 130}, "awayTeamOdds": {"moneyLine": 230}, "drawOdds": {"moneyLine": 235}}]}]}]}
ev = b._espn_events("epl", soccer2)[0]
assert ev["books"]["DraftKings"]["draw"] == 230.0 and ev["books"]["FanDuel"]["draw"] == 235.0, ev
rows = b.analyze([ev], [], now=NOW)
r = rows[0]; assert r["threeWay"] and set(r["fair"]) == {"home", "away", "draw"} and abs(sum(r["fair"].values()) - 1) < 1e-3, r["fair"]
assert r["best"]["home"]["book"] == "FanDuel" and "model" not in r
assert any(x["side"] == "Draw" or x["side"] in ("Arsenal", "Chelsea") for x in r["bets"]) or r["bets"] == []

# 3-way arbitrage detection: three outcomes at different books whose implied sum < 1
arb = {"sport": "epl", "home": "A", "away": "B", "start": "2026-10-12T14:00:00Z", "books": {
  "X": {"home": 260, "away": -150, "draw": -150}, "Y": {"home": -150, "away": 260, "draw": -150}, "Z": {"home": -150, "away": -150, "draw": 260}}}
ra = b.analyze([arb], [], now=NOW)[0]; assert ra["arb"] and abs(ra["impliedSum"] - 3 / 3.6) < 1e-3 and ra["arbRoiPct"] > 15, ra

# ---- ESPN soccer + MMA shapes
soccer = {"events": [{"date": "d", "competitions": [{"competitors": [{"homeAway": "home", "team": {"displayName": "Arsenal"}}, {"homeAway": "away", "team": {"displayName": "Chelsea"}}],
   "odds": [{"provider": {"name": "DraftKings"}, "homeTeamOdds": {"moneyLine": 120}, "awayTeamOdds": {"moneyLine": 240}, "drawOdds": {"moneyLine": 230}}]}]}]}
s = b._espn_events("epl", soccer)[0]; assert s["books"]["DraftKings"] == {"home": 120.0, "away": 240.0, "draw": 230.0}, s
mma = {"events": [{"date": "d", "competitions": [{"competitors": [{"athlete": {"displayName": "Fighter A"}}, {"athlete": {"displayName": "Fighter B"}}],
   "odds": [{"provider": {"name": "DraftKings"}, "moneyline": {"home": {"close": {"odds": "-180"}}, "away": {"close": {"odds": "+150"}}}}]}]}]}
m2 = b._espn_events("mma", mma)[0]; assert m2["home"] == "Fighter A" and m2["books"]["DraftKings"]["away"] == 150.0, m2
assert b._am("EVEN") == 100.0 and b._am("+130") == 130.0 and b._am("-50") is None and b._am(None) is None

# ---- end-to-end with SPORTS=all, no key anywhere, straight off ESPN
tmp = tempfile.mkdtemp(); os.environ.update({"ASOF": "2026-10-01T00:00:00+00:00", "SLATE_OUT": f"{tmp}/s.json", "HISTORY_PATH": f"{tmp}/h.json", "ALERTS_PATH": f"{tmp}/al.json", "PICKS_PATH": f"{tmp}/p.json", "RECORD_PATH": f"{tmp}/r.json", "SPORTS": "all", "NETWORK_HEALTH": f"{tmp}/nh.json", "NO_NETWORK": "1", "NO_WHALES": "1"})
calls = []
def fake_espn(sport):
    calls.append(sport)
    return [{"sport": sport, "home": "H" + sport, "away": "A" + sport, "start": "2099-01-01T00:00:00Z", "books": {"DraftKings": {"home": -150, "away": 130}}}]
b.espn_direct = fake_espn
b.kalshi_direct = lambda: []; b.kalshi_via_skills = lambda: []; b.polymarket_direct = lambda: []; b.polymarket_via_skills = lambda: []
import model as M; M.fetch_results = lambda *a, **k: []
assert b.main() == 0
sl = json.load(open(f"{tmp}/s.json")); sports = {g["sport"] for g in sl["games"]}
assert sports == set(b.SPORTS) - b.THREE_WAY, sports                       # every sport reached the slate straight off ESPN
assert set(calls) == set(b.SPORTS)                                         # ESPN was hit for every sport (mlb twice: odds, then pitcher enrichment)
assert not any("oddsapi" in x["source"] for x in sl["sources"]), "no paid odds feed anywhere in the pipeline"
print("MARKETS TESTS PASS")
