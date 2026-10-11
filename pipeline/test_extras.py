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

# ---- end-to-end main(): fallbacks, injuries, model, history, capture-only
tmp = tempfile.mkdtemp(); os.environ.update({"SLATE_OUT": f"{tmp}/slate.json", "HISTORY_PATH": f"{tmp}/history.json", "SPORTS": "nhl"})
start = (datetime.now(timezone.utc) + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
games = [{"sport": "nhl", "home": "T1", "away": "T2", "start": start, "books": {"DK": {"home": -120, "away": 100}, "FD": {"home": -125, "away": 105}}}]
b.odds_api = lambda sport: (_ for _ in ()).throw(RuntimeError("no key"))   # primary fails
b.espn_direct = lambda sport: games                                          # fallback serves
b.kalshi_direct = lambda: []; b.kalshi_via_skills = lambda: []; b.polymarket_direct = lambda: []; b.polymarket_via_skills = lambda: []
g, _ = synth("nhl"); M.fetch_results = lambda sp, *a, **k: g
M.fetch_injuries = lambda sp, getter=None: {"T1": [{"name": "G Star", "pos": "G", "status": "out"}]}
assert b.main() == 0
s = json.load(open(f"{tmp}/slate.json"))
assert s["games"][0]["key"] and s["games"][0]["model"], s["games"][0]
assert any("injuries" in x["source"] and x["ok"] for x in s["sources"]), s["sources"]
assert s["games"][0]["model"].get("injuries") and "T1" in s["games"][0]["model"]["injuries"][0]
assert any(x["source"] == "odds[nhl]:oddsapi" and not x["ok"] for x in s["sources"]) and any(x["source"] == "odds[nhl]:espn" and x["ok"] for x in s["sources"])
assert json.load(open(f"{tmp}/history.json")), "history written"
assert "closing" in s
os.remove(f"{tmp}/slate.json"); os.environ["CAPTURE_ONLY"] = "1"
assert b.main() == 0 and not os.path.exists(f"{tmp}/slate.json")          # capture-only writes history only
assert len(list(json.load(open(f"{tmp}/history.json")).values())[0]["snaps"]) == 2
print("EXTRAS TESTS PASS")
