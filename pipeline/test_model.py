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
    rng_ = url.split("dates=")[1].split("&")[0]; s, e = rng_.split("-")
    s = f"{s[:4]}-{s[4:6]}-{s[6:]}"; e = f"{e[:4]}-{e[4:6]}-{e[6:]}"
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
rows = b.analyze(g, [], {"nba": m})
r = rows[0]; print(r["model"], r["bets"])
assert "model" in r and any(x.get("basis") == "model-blend" and x["side"] == best for x in r["bets"])
# rest rule: back-to-back hurts
assert M._rest_adj("nba", 1) < 0 < M._rest_adj("nba", 4)
print("MODEL TESTS PASS")
