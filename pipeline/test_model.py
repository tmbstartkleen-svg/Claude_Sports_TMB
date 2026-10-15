import os, sys, random, math
from datetime import date, timedelta
sys.path.insert(0, os.path.dirname(__file__))
import model as M, build_slate as b

rng = random.Random(3)
teams = [f"Team {i}" for i in range(30)]
true = {t: rng.gauss(0, 5) for t in teams}  # points of strength
today = date(2026, 3, 1)
def mk_events(start, end):
    ev, d, n = [], start, 0
    while d <= end:
        for _ in range(6):
            h, a = rng.sample(teams, 2)
            mu = true[h] - true[a] + 3
            hs = 110 + mu / 2 + rng.gauss(0, 11); as_ = 110 - mu / 2 + rng.gauss(0, 11)
            n += 1
            ev.append({"id": f"{d}{n}", "date": f"{d}T00:00Z", "status": {"type": {"completed": True}},
                       "competitions": [{"competitors": [{"homeAway": "home", "team": {"displayName": h}, "score": str(round(hs))},
                                                       {"homeAway": "away", "team": {"displayName": a}, "score": str(round(as_))}]}]})
        d += timedelta(days=1)
    return ev
ALL = mk_events(today - timedelta(days=M.LOOKBACK_DAYS), today)
def getter(url):
    s = url.split("dates=")[1].split("&")[0]; assert "-" not in s, "ESPN rejects ranges"
    s = e = f"{s[:4]}-{s[4:6]}-{s[6:]}"
    return {"events": [x for x in ALL if s <= x["date"][:10] <= e]}

res = M.fetch_results("nba", today, getter)
assert len(res) > 2000 and len({g["id"] for g in res}) == len(res), len(res)
m = M.build("nba", res)
bt = m["backtest"]; print(bt)
assert bt["brier"] < 0.25 and bt["accuracy"] > 0.55, bt
# ratings should correlate with truth
xs = [true[t] for t in teams if t in m["ratings"]]; ys = [m["ratings"][t] for t in teams if t in m["ratings"]]
mx, my = sum(xs)/len(xs), sum(ys)/len(ys)
corr = sum((x-mx)*(y-my) for x, y in zip(xs, ys)) / math.sqrt(sum((x-mx)**2 for x in xs) * sum((y-my)**2 for y in ys))
print("rating/truth corr", round(corr, 3)); assert corr > 0.7  # K=20 tracks drifting real teams; fixed synthetic strengths favour lower K (checked: K=4 gives 0.90)
best, worst = max(teams, key=lambda t: true[t]), min(teams, key=lambda t: true[t])
p = M.predict("nba", m, best, worst, today); assert p > 0.7, p
assert M.predict("nba", m, "Nobody", worst) is None
assert abs(M.blend(0.8, 0.5) - 0.575) < 1e-9
# integration: single book game still gets a model bet when the book underprices the favourite
g = [{"sport": "nba", "home": best, "away": worst, "start": f"{today}T00:00:00Z", "books": {"OnlyBook": {"home": 100, "away": -120}}}]
from datetime import datetime as _dt, timezone as _tz, timedelta as _td
rows = b.analyze(g, [], {"nba": m}, now=_dt(2026, 2, 28, tzinfo=_tz.utc))
r = rows[0]; print(r["model"], r["bets"])
assert "model" in r and any(x.get("basis") == "model-blend" and x["side"] == best for x in r["bets"])
# rest rule: back-to-back hurts
assert M._rest_adj("nba", 1) < 0 < M._rest_adj("nba", 4)
print("MODEL TESTS PASS")

# ---- fetch_results: diagnostics instead of silent empties
import model as M2
from datetime import date as _d
def boom(u): raise OSError("HTTP Error 400: Bad Request")
try:
    M2.fetch_results("nba", today=_d(2026, 1, 1), getter=boom); raise SystemExit("should raise")
except RuntimeError as e:
    assert "first error" in str(e) and "400" in str(e) and "errors" in str(e), e
empty = lambda u: {"events": []}
try:
    M2.fetch_results("nba", today=_d(2026, 1, 1), getter=empty); raise SystemExit("should raise")
except RuntimeError as e:
    assert "0 had events" in str(e) and "0 errors" in str(e), e
ev = lambda i: {"id": str(i), "date": "2025-12-01T00:00Z", "status": {"type": {"completed": True}},
                "competitions": [{"competitors": [{"homeAway": "home", "score": "100", "team": {"displayName": "A"}}, {"homeAway": "away", "score": "90", "team": {"displayName": "B"}}]}]}
calls = {"n": 0}
def flaky(u):
    calls["n"] += 1
    if calls["n"] == 1: raise OSError("blip")          # one failure is retried and recovered
    return {"events": [ev(calls["n"])]}
st = {}
r = M2.fetch_results("nba", today=_d(2026, 1, 1), getter=flaky, stats=st)
assert r and st["errors"] == 0 and st["completed"] >= 1, st
print("FETCH DIAG PASS")

# ---- per-sport blend weights fit from the real-market backtest (validate_backtest.py), with a default fallback
assert abs(M.blend(0.6, 0.5, sport="mlb") - (0.12 * 0.6 + 0.88 * 0.5)) < 1e-9
assert abs(M.blend(0.6, 0.5, sport="unknownsport") - (M.MODEL_WEIGHT * 0.6 + (1 - M.MODEL_WEIGHT) * 0.5)) < 1e-9
assert M.blend(0.6, 0.5, w=0.9, sport="mlb") == 0.9 * 0.6 + 0.1 * 0.5, "explicit w overrides the per-sport table"
print("OK per-sport blend weights")
