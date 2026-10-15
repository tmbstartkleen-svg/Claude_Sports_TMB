import os, sys, math, random
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from datetime import datetime, timedelta
import soccer as S

def poisson(rng, lam):
    L, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= L: return k
        k += 1

def synth(n_teams=20, rounds=3, seed=3, spread=0.35):
    rng = random.Random(seed); teams = [f"T{i}" for i in range(n_teams)]; true = {t: rng.gauss(0, spread) for t in teams}
    out, d0, day = [], datetime(2025, 8, 1).date(), 0
    for r in range(rounds * 2):
        for i in range(0, n_teams, 2):
            h, a = rng.sample(teams, 2)
            hs = poisson(rng, math.exp(0.25 + 0.3 * (true[h] - true[a]) * 1.0 + 0.1)); as_ = poisson(rng, math.exp(0.0 - 0.3 * (true[h] - true[a]) * 1.0 + 0.1))
            out.append({"date": str(d0 + timedelta(days=day)), "home": h, "away": a, "hs": hs, "as": as_})
        day += 4
    return out, true

# probabilities: sum to one, draw peaks when level, home edge, monotone in strength
for diff in (-600, -200, 0, 65, 300, 800):
    p = S.probs(diff, 0.26); assert abs(sum(p) - 1) < 1e-9 and min(p) > 0, p
assert S.probs(0, .26)[1] > S.probs(300, .26)[1] > S.probs(800, .26)[1]
assert S.probs(65, .26)[0] > S.probs(65, .26)[2] and S.probs(300, .26)[0] > S.probs(65, .26)[0]
print("OK probs")

games, true = synth(rounds=60)
m = S.build(games); bt = m["backtest"]; print(bt)
assert bt["brier"] < bt["coinFlipBrier"], bt              # beats league-frequency baseline on data with real strength differences
assert bt["accuracy"] > 0.42 and 0.18 <= m["draw"] <= 0.34
best = max(true, key=true.get); worst = min(true, key=true.get)
assert m["ratings"][best] > m["ratings"][worst] + 40, "ratings recover true strength ordering"
ph, pd, pa = S.predict(m, best, worst); assert ph > pa and abs(ph + pd + pa - 1) < 1e-9
assert S.predict(m, "Nobody FC", best) is None
print("OK build/predict")

# draw base is learned from the data: a draw-heavy league gets a higher draw probability
dh = [dict(g, as_=g["hs"]) for g in games]
heavy = [dict(g, **{"as": g["hs"]}) if i % 2 else g for i, g in enumerate(games)]
assert S.build(heavy)["draw"] > m["draw"]
print("SOCCER TESTS PASS")

# ---- end to end through analyze(): 3-way game, model blends all three outcomes, bets can be on the draw
import build_slate as b
games_, true_ = synth(rounds=60, spread=0.8); mdl = S.build(games_)
best_t = max(true_, key=true_.get); worst_t = min(true_, key=true_.get)
fair_h, fair_d, fair_a = S.predict(mdl, best_t, worst_t)
# a book that badly underprices the home team the model likes (2 books so edge bets are allowed)
def am(p): d = 1 / p; return round((d - 1) * 100) if d >= 2 else -round(100 / (d - 1))
bk = {"X": {"home": am(fair_h * 0.8), "draw": am(fair_d), "away": am(fair_a)}, "Y": {"home": am(fair_h * 0.8), "draw": am(fair_d), "away": am(fair_a)}}
g = {"sport": "epl", "home": best_t, "away": worst_t, "start": "2026-10-12T15:00:00Z", "books": bk}
from datetime import timezone as _tz
NOW = datetime(2026, 10, 1, tzinfo=_tz.utc)
rows = b.analyze([g], [], {"epl": mdl}, {}, NOW)
r = rows[0]; assert r["threeWay"] and "draw" in r["fair"], r
m_ = r["model"]; assert abs(m_["home"] + m_["draw"] + m_["away"] - 1) < 2e-4 and "blendHome" in m_
assert any(x["side"] == best_t for x in r["bets"]), "underpriced home side must be flagged"
assert m_["blendHome"] > r["fair"]["home"], "blend moves toward the model, which likes the home side more than the book"
assert all(x["side"] in (best_t, worst_t, "Draw") for x in r["bets"])
assert b.analyze([dict(g, home="Nobody", away="Else")], [], {"epl": mdl}, {}, NOW)[0].get("model") is None
print("SOCCER WIRING PASS")
