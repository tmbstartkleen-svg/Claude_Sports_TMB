"""Soccer model: Elo ratings plus an explicit draw probability, for three-way markets (home / draw / away).

Built from free ESPN results, walk-forward like model.py. Draw probability peaks when teams are level and falls as the
rating gap grows; its base level is the draw rate actually observed in the data. Domestic leagues only: Champions League
games mix teams from different leagues whose ratings are not comparable, so they get no model.

Honest limits: no lineups, injuries, xG or schedule congestion. Treat it as a light nudge on the market, not a replacement.
"""
import math, os, sys
from datetime import datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from names import canon

try:
    import leagues as _lg
except ImportError:  # pragma: no cover
    from pipeline import leagues as _lg
LEAGUES = {k: "soccer/" + v[2] for k, v in _lg.SOCCER.items() if v[3]}  # key -> ESPN path (domestic leagues only)
K = 18
HOME_ELO = 65          # home advantage in rating points
REGRESS = 0.25         # pull toward 1500 after the off-season gap
DRAW_WIDTH = 450.0     # how fast the draw chance falls as the rating gap grows
MIN_GAMES = 100


def _e(diff):
    return 1 / (1 + 10 ** (-diff / 400))


def probs(diff, draw_base):
    """(pHome, pDraw, pAway) for a rating difference (home minus away, home advantage included)."""
    pd = draw_base * math.exp(-((diff / DRAW_WIDTH) ** 2))
    e = _e(diff)
    ph, pa = e - pd / 2, 1 - e - pd / 2
    ph, pa = max(ph, 0.01), max(pa, 0.01)
    s = ph + pd + pa
    return ph / s, pd / s, pa / s


def build(games):
    """games: [{date, home, away, hs, as}] oldest first."""
    R, prev = {}, None
    draws = total = 0
    for g in games:
        total += 1
        draws += g["hs"] == g["as"]
    base = draws / total if total else 0.26
    base = min(0.34, max(0.18, base))
    rows = []  # (p tuple, outcome index 0 home 1 draw 2 away) for rated-vs-rated games
    hist = [0, 0, 0]
    for g in games:
        d = datetime.strptime(g["date"], "%Y-%m-%d").date()
        if prev and (d - prev).days > 60:
            for k in R:
                R[k] = 1500 + (R[k] - 1500) * (1 - REGRESS)
        prev = d
        h, a = g["home"], g["away"]
        rh, ra = R.get(h, 1500), R.get(a, 1500)
        diff = rh - ra + HOME_ELO
        p = probs(diff, base)
        out = 0 if g["hs"] > g["as"] else 2 if g["hs"] < g["as"] else 1
        if h in R and a in R:
            rows.append((p, out, tuple(x / max(1, sum(hist)) for x in hist) if sum(hist) >= 30 else None))
        hist[out] += 1
        e = _e(diff)
        actual = 1.0 if out == 0 else 0.0 if out == 2 else 0.5
        mult = math.log(abs(g["hs"] - g["as"]) + 1) + 1 if out != 1 else 1.0   # bigger wins move ratings more
        R[h] = rh + K * mult * (actual - e)
        R[a] = ra - K * mult * (actual - e)
    n = len(rows)
    back = None
    scored = [r for r in rows if r[2]]
    if scored:
        def brier(p, o):
            return sum((p[i] - (1 if i == o else 0)) ** 2 for i in range(3))
        mb = sum(brier(p, o) for p, o, _ in scored) / len(scored)
        bb = sum(brier(c, o) for _, o, c in scored) / len(scored)   # climatology: league-to-date frequencies
        ll = -sum(math.log(max(1e-9, p[o])) for p, o, _ in scored) / len(scored)
        acc = sum(1 for p, o, _ in scored if max(range(3), key=lambda i: p[i]) == o) / len(scored)
        back = {"n": len(scored), "brier": round(mb, 4), "coinFlipBrier": round(bb, 4), "logLoss": round(ll, 4), "accuracy": round(acc, 3),
                "drawRate": round(base, 3), "baseline": "league-to-date frequencies (3-way)"}
    return {"kind": "soccer", "ratings": R, "draw": base, "backtest": back, "canon": {canon(k): k for k in R}}


def predict(m, home, away):
    R = m["ratings"]
    cm = m.get("canon") or {canon(k): k for k in R}
    home, away = cm.get(canon(home), home), cm.get(canon(away), away)
    if home not in R or away not in R:
        return None
    return probs(R[home] - R[away] + HOME_ELO, m["draw"])
