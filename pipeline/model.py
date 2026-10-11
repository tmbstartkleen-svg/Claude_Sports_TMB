"""Own win-probability model: Elo + rest, built from free ESPN results (no API key).

Walks every completed game of the last ~14 months in date order. Before each game it
records the model's prediction (walk-forward, so the backtest has no look-ahead), then updates ratings.

Honest limits: no injuries, no lineups, no weather. A plain Elo rarely beats a sharp market,
so the slate blends it with the market's fair price (MODEL_WEIGHT) instead of trusting it alone.
"""
import json, math, os, urllib.request
from datetime import date, datetime, timedelta

CFG = {  # assumptions, all tunable
    "nfl": {"espn": "football/nfl", "k": 20, "home": 48, "regress": 1 / 3, "rest": {"bye": 25, "short": -25}, "elo_per_pt": 25},
    "nba": {"espn": "basketball/nba", "k": 20, "home": 100, "regress": 1 / 4, "rest": {"b2b": -46, "rested": 20}, "elo_per_pt": 28},
}
MODEL_WEIGHT = float(os.environ.get("MODEL_WEIGHT", 0.25))  # 25% model, 75% market
LOOKBACK_DAYS = 430


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "edge-suite-slate/1.0", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.load(r)


def fetch_results(sport, today=None, getter=_get):
    """Completed games [{date, home, away, hs, as}] oldest first. Month-sized requests."""
    path = CFG[sport]["espn"]
    today = today or date.today()
    start = today - timedelta(days=LOOKBACK_DAYS)
    out, seen = [], set()
    d = start
    while d <= today:
        e = min(d + timedelta(days=30), today)
        url = f"https://site.api.espn.com/apis/site/v2/sports/{path}/scoreboard?dates={d:%Y%m%d}-{e:%Y%m%d}&limit=1000"
        try:
            data = getter(url)
        except Exception:
            data = {"events": []}
        for ev in data.get("events", []):
            comp = ev["competitions"][0]
            if not ev.get("status", {}).get("type", {}).get("completed"):
                continue
            t = {c["homeAway"]: c for c in comp["competitors"]}
            try:
                g = {"id": ev["id"], "date": ev["date"][:10], "home": t["home"]["team"]["displayName"],
                     "away": t["away"]["team"]["displayName"], "hs": float(t["home"]["score"]), "as": float(t["away"]["score"])}
            except (KeyError, ValueError):
                continue
            if g["id"] not in seen:
                seen.add(g["id"])
                out.append(g)
        d = e + timedelta(days=1)
    out.sort(key=lambda g: g["date"])
    return out


def _rest_adj(sport, days):
    r = CFG[sport]["rest"]
    if days is None:
        return 0
    if sport == "nfl":
        return r["bye"] if days >= 12 else (r["short"] if days <= 5 else 0)
    return r["b2b"] if days <= 1 else (r["rested"] if days >= 3 else 0)


def _win_prob(diff):
    return 1 / (1 + 10 ** (-diff / 400))


def build(sport, games):
    c = CFG[sport]
    R, last = {}, {}
    prev_day = None
    preds = []  # (p_home, home_won)
    for g in games:
        d = datetime.strptime(g["date"], "%Y-%m-%d").date()
        if prev_day and (d - prev_day).days > 90:  # new season: pull ratings toward the mean
            for k in R:
                R[k] = 1500 + (R[k] - 1500) * (1 - c["regress"])
        prev_day = d
        h, a = g["home"], g["away"]
        rh, ra = R.get(h, 1500), R.get(a, 1500)
        dh = (d - last[h]).days if h in last else None
        da = (d - last[a]).days if a in last else None
        diff = rh - ra + c["home"] + _rest_adj(sport, dh) - _rest_adj(sport, da)
        p = _win_prob(diff)
        if g["hs"] != g["as"]:
            won = 1 if g["hs"] > g["as"] else 0
            if len(preds) >= 0 and h in R and a in R:  # only score games between already-rated teams
                preds.append((p, won))
            margin = abs(g["hs"] - g["as"])
            mult = math.log(margin + 1) * 2.2 / ((diff if won else -diff) * 0.001 + 2.2)
            delta = c["k"] * mult * (won - p)
            R[h] = rh + delta
            R[a] = ra - delta
        last[h] = last[a] = d
    n = len(preds)
    back = None
    if n:
        brier = sum((p - y) ** 2 for p, y in preds) / n
        acc = sum(1 for p, y in preds if (p > .5) == bool(y)) / n
        ll = -sum(math.log(max(1e-9, p if y else 1 - p)) for p, y in preds) / n
        back = {"n": n, "brier": round(brier, 4), "logLoss": round(ll, 4), "accuracy": round(acc, 3), "coinFlipBrier": 0.25}
    return {"ratings": R, "last": last, "backtest": back}


def predict(sport, m, home, away, on=None):
    """Model P(home wins) for an upcoming game, or None if either team is unrated."""
    c = CFG[sport]
    R, last = m["ratings"], m["last"]
    if home not in R or away not in R:
        return None
    on = on or date.today()
    dh = (on - last[home]).days if home in last else None
    da = (on - last[away]).days if away in last else None
    return _win_prob(R[home] - R[away] + c["home"] + _rest_adj(sport, dh) - _rest_adj(sport, da))


def blend(p_model, p_market, w=None):
    w = MODEL_WEIGHT if w is None else w
    return w * p_model + (1 - w) * p_market
