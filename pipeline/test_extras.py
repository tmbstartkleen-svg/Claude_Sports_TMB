import os, sys, json, tempfile, random, math
from datetime import datetime, timedelta, timezone
sys.path.insert(0, os.path.dirname(__file__))
import model as M, history as H, build_slate as b

# ---- NHL / MLB models build and beat a coin flip on synthetic data with known strengths
def synth(sport, n_teams=30, days=300, per_day=8, sd_pts=2.2, spread=0.8, seed=5):
    rng = random.Random(seed); teams = [f"T{i}" for i in range(n_teams)]; true = {t: rng.gauss(0, spread) for t in teams}
    out, d0 = [], datetime(2025, 10, 1).date()
    for dd in range(days):
        d = d0 + timedelta(days=dd)
        for k in range(per_day):
            h, a = rng.sample(teams, 2); mu = true[h] - true[a] + 0.3
            hs = max(0, round(3 + mu / 2 + rng.gauss(0, sd_pts))); as_ = max(0, round(3 - mu / 2 + rng.gauss(0, sd_pts)))
            out.append({"id": f"{dd}-{k}", "date": str(d), "home": h, "away": a, "hs": hs, "as": as_})
    return out, true
for sp in ("nhl", "mlb"):
    g, true = synth(sp); m = M.build(sp, g); bt = m["backtest"]; print(sp, bt)
    assert bt["brier"] < 0.25 and bt["accuracy"] > 0.52, bt
    assert M._rest_adj(sp, 1) <= 0 and M.predict(sp, m, "T1", "T2", datetime(2026, 8, 1).date()) is not None
assert M._rest_adj("mlb", 0) == 0 and M._rest_adj("nhl", 1) < 0

# ---- injuries
espn = {"injuries": [
  {"displayName": "Kansas City Chiefs", "injuries": [
     {"status": "Out", "athlete": {"displayName": "QB One", "position": {"abbreviation": "QB"}}},
     {"status": "Questionable", "athlete": {"displayName": "WR One", "position": "WR"}},
     {"status": "Probable", "athlete": {"displayName": "TE One", "position": "TE"}}]},
  {"displayName": "Buffalo Bills", "injuries": [{"status": "Healthy", "athlete": {"displayName": "X"}}]}]}
inj = M.fetch_injuries("nfl", getter=lambda u: espn)
assert len(inj["Kansas City Chiefs"]) == 3
adj = M.injury_adj("nfl", inj)
kc = adj["Kansas City Chiefs"]; print(kc)
assert -110 < kc[0] < -100 and "QB One (QB) out" in kc[1][0], kc   # QB -100, WR q -1.5, TE -0.6
assert "Buffalo Bills" not in adj
many = {"X": [{"name": str(i), "pos": "WR", "status": "out"} for i in range(30)]}
assert M.injury_adj("nfl", many)["X"][0] == -36  # cap holds
m_nba = M.build("nba", [{"id": "1", "date": "2026-01-01", "home": "A", "away": "B", "hs": 100, "as": 90}] * 1)
# QB out lowers P(home)
g, _ = synth("nhl"); mm = M.build("nhl", g)
p0 = M.predict("nhl", mm, "T1", "T2", datetime(2026, 8, 1).date()); p1 = M.predict("nhl", mm, "T1", "T2", datetime(2026, 8, 1).date(), {"T1": -50})
assert p1 < p0

# ---- history -> closing lines
now = datetime(2026, 10, 12, 18, 0, tzinfo=timezone.utc)
row = lambda fh: {"sport": "nfl", "home": "H", "away": "A", "start": "2026-10-12T20:00:00Z", "nBooks": 3, "fair": {"home": fh, "away": 1 - fh},
                  "best": {"home": {"american": -140}, "away": {"american": 125}}}
h = {}
assert H.record(h, [row(.58)], now) == 1
assert H.record(h, [row(.60)], now + timedelta(minutes=90)) == 1
assert H.record(h, [row(.61)], now + timedelta(minutes=121)) == 0        # started: in-play line must NOT be recorded
c = H.closing(h, now + timedelta(hours=3))
k = H.game_key("nfl", "A", "H", "2026-10-12T20:00:00Z"); assert k in c, c
assert c[k]["fairHome"] == .60 and c[k]["minutesBeforeStart"] == 30 and c[k]["firstFairHome"] == .58, c[k]
assert H.closing(h, now + timedelta(minutes=30)) == {}                    # not started yet -> no close
H.prune(h, now + timedelta(days=9)); assert h == {}
long = {}
for i in range(200): H.record(long, [row(.5)], now - timedelta(days=1) + timedelta(seconds=i))
assert len(next(iter(long.values()))["snaps"]) <= H.MAX_SNAPS

# ---- end-to-end main(): primary source, injuries, model, history, capture-only
tmp = tempfile.mkdtemp(); os.environ.update({"SLATE_OUT": f"{tmp}/slate.json", "HISTORY_PATH": f"{tmp}/history.json", "ALERTS_PATH": f"{tmp}/al.json", "PICKS_PATH": f"{tmp}/picks.json", "RECORD_PATH": f"{tmp}/record.json", "SPORTS": "nhl", "NETWORK_HEALTH": f"{tmp}/nh.json", "NO_NETWORK": "1", "NO_WHALES": "1"})
start = (datetime.now(timezone.utc) + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
games = [{"sport": "nhl", "home": "T1", "away": "T2", "start": start, "books": {"DK": {"home": -120, "away": 100}, "FD": {"home": -125, "away": 105}}}]
b.espn_direct = lambda sport: games                                          # primary (no key needed) serves
b.kalshi_direct = lambda: []; b.kalshi_via_skills = lambda: []; b.polymarket_direct = lambda: []; b.polymarket_via_skills = lambda: []
g, _ = synth("nhl"); M.fetch_results = lambda sp, *a, **k: g
M.fetch_injuries = lambda sp, getter=None: {"T1": [{"name": "G Star", "pos": "G", "status": "out"}]}
assert b.main() == 0
s = json.load(open(f"{tmp}/slate.json"))
assert s["games"][0]["key"] and s["games"][0]["model"], s["games"][0]
assert any("injuries" in x["source"] and x["ok"] for x in s["sources"]), s["sources"]
assert s["games"][0]["model"].get("injuries") and "T1" in s["games"][0]["model"]["injuries"][0]
assert any(x["source"] == "odds[nhl]:espn" and x["ok"] for x in s["sources"]), s["sources"]
assert json.load(open(f"{tmp}/history.json")), "history written"
assert "closing" in s
assert any(x["source"] == "steam" and x["ok"] for x in s["sources"]), s["sources"]  # ran, even with only 1 snapshot so far to look at
os.remove(f"{tmp}/slate.json"); os.environ["CAPTURE_ONLY"] = "1"
assert b.main() == 0 and not os.path.exists(f"{tmp}/slate.json")          # capture-only writes history only
assert len(list(json.load(open(f"{tmp}/history.json")).values())[0]["snaps"]) == 1, "unchanged price within an hour is not re-snapshotted"
games[0]["books"]["DK"]["home"] = -135                                      # price moved: a new snapshot is recorded
assert b.main() == 0
assert len(list(json.load(open(f"{tmp}/history.json")).values())[0]["snaps"]) == 2
print("EXTRAS TESTS PASS")

# ---- MLB starting pitchers
adj_, notes_ = M.pitcher_adj({"home": {"name": "Ace", "era": "2.40"}, "away": {"name": "Mop", "era": "6.10"}})
assert adj_["home"] > 0 > adj_["away"] and adj_["home"] == 31.5 and adj_["away"] == -33.2, adj_   # (4.2-2.4)*35*.5, (4.2-6.1)*35*.5
assert M.pitcher_adj({"home": {"name": "X", "era": "0.50"}, "away": {"name": "Y", "era": "-"}})[0] == {"home": 40.0 if False else min(40.0, (4.2 - .5) * 17.5), "away": 0.0}
assert M.pitcher_adj({"home": {"name": "Z", "era": "0.01"}})[0]["home"] <= 40.0     # cap
assert M.pitcher_adj({})[0] == {"home": 0.0, "away": 0.0}                              # TBD starters: no adjustment
espn_mlb = {"events": [{"date": "2026-10-12T23:05Z", "competitions": [{"competitors": [
    {"homeAway": "home", "team": {"displayName": "Boston Red Sox"}, "probables": [{"athlete": {"displayName": "Ace Arm"}, "statistics": [{"name": "ERA", "displayValue": "2.40"}]}]},
    {"homeAway": "away", "team": {"displayName": "New York Yankees"}, "probables": []}],
    "odds": [{"provider": {"name": "DraftKings"}, "moneyline": {"home": {"close": {"odds": "-130"}}, "away": {"close": {"odds": "+110"}}}}]}]}]}
ev = b._espn_events("mlb", espn_mlb)
assert ev[0]["pitchers"] == {"home": {"name": "Ace Arm", "era": "2.40"}}, ev
assert "pitchers" not in b._espn_events("nba", espn_mlb)[0]
# the Odds API path gets pitchers from ESPN by team + date
b.espn_direct = lambda s: ev
og = [{"sport": "mlb", "home": "Boston Red Sox", "away": "New York Yankees", "start": "2026-10-12T23:05:00Z", "books": {}}]
b.enrich_pitchers(og); assert og[0]["pitchers"]["home"]["name"] == "Ace Arm"
# a good home starter raises P(home) in analyze()
g_, _ = synth("mlb"); mm_ = M.build("mlb", g_); d_ = datetime(2026, 8, 1).date()
base = M.predict("mlb", mm_, "T1", "T2", d_)
pa_, _n = M.pitcher_adj({"home": {"name": "Ace", "era": "2.40"}, "away": {"name": "Mop", "era": "6.10"}})
assert M.predict("mlb", mm_, "T1", "T2", d_, {"T1": pa_["home"], "T2": pa_["away"]}) > base + 0.05
print("PITCHER TESTS PASS")

# ---- diagnostics
gm = [{"sport": "mlb", "home": "A", "away": "B", "start": None, "books": {}, "pitchers": {"home": {"name": "x", "era": "3"}}}, {"sport": "nba", "home": "C", "away": "D", "start": None, "books": {}}]
rw = [{"sport": "mlb", "nBooks": 1, "bets": [], "pm": []}]
dd = b.diagnostics(gm, rw, [])
assert dd["bySport"]["mlb"]["withPitchers"] == 1 and dd["bySport"]["mlb"]["avgBooks"] == 1.0
w = " | ".join(dd["warnings"]); assert "nba: 1 games but none had usable odds" in w and "only one book per game" in w and "no prediction-market data" in w, w
good = b.diagnostics(gm[:1], [{"sport": "mlb", "nBooks": 4, "bets": [1], "pm": [1], "model": {}}], [{"x": 1}])
assert good["warnings"] == [], good
print("DIAG TESTS PASS")

# ---- sharp-book weighting
assert b.book_weight("Pinnacle") == 4.0 and b.book_weight("DraftKings") == 1.0 and b.book_weight("Circa Sports") == 3.0
def one(books):
    return b.analyze([{"sport": "nba", "home": "H", "away": "A", "start": None, "books": books}], [], {}, {})[0]
sharp_bk = {"Pinnacle": {"home": -150, "away": 130}, "DraftKings": {"home": -120, "away": 100}, "FanDuel": {"home": -120, "away": 100}}
w = one(sharp_bk)
plain = one({k.replace("Pinnacle", "Other"): v for k, v in sharp_bk.items()})
assert w["fair"]["home"] > plain["fair"]["home"] + 0.015, (w["fair"], plain["fair"])      # pulled toward the sharp book's higher home price
assert abs(w["fair"]["home"] + w["fair"]["away"] - 1) < 1e-3 and w["sharpBooks"] == ["Pinnacle"] and "sharpBooks" not in plain
# weighted mean is exactly (4*p + 1*q + 1*r)/6 on the de-vigged probabilities
fp = b.devig_shin([1 / b.am_to_dec(-150), 1 / b.am_to_dec(130)])[0]; fd = b.devig_shin([1 / b.am_to_dec(-120), 1 / b.am_to_dec(100)])[0]
assert abs(w["fair"]["home"] - round((4 * fp + 2 * fd) / 6, 4)) < 1e-4, (w["fair"], fp, fd)
print("SHARP TESTS PASS")
