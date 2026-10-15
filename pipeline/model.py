"""Own win-probability model: Elo + rest, built from free ESPN results (no API key).

Walks every completed game of the last ~14 months in date order. Before each game it
records the model's prediction (walk-forward, so the backtest has no look-ahead), then updates ratings.

Honest limits: no injuries, no lineups, no weather. A plain Elo rarely beats a sharp market,
so the slate blends it with the market's fair price (MODEL_WEIGHT) instead of trusting it alone.
"""
import json, math, os, sys, urllib.request
from datetime import date, datetime, timedelta
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from names import canon

CFG = {  # assumptions, all tunable
    "nfl": {"espn": "football/nfl", "k": 20, "home": 48, "regress": 1 / 3, "rest": {"bye": 25, "short": -25}, "elo_per_pt": 25},
    "nba": {"espn": "basketball/nba", "k": 20, "home": 100, "regress": 1 / 4, "rest": {"b2b": -46, "rested": 20}, "elo_per_pt": 28},
    # NHL/MLB: lower K (more games, more randomness), small home edge. MLB has no rest rule: the starting pitcher matters far
    # more than rest, and this model does not know who is pitching. Treat MLB output as the weakest of the four.
    "nhl": {"espn": "hockey/nhl", "k": 8, "home": 35, "regress": 1 / 3, "rest": {"b2b": -30, "rested": 10}, "elo_per_pt": 0},
    "mlb": {"espn": "baseball/mlb", "k": 5, "home": 24, "regress": 1 / 3, "rest": {}, "elo_per_pt": 0},
}
MODEL_WEIGHT = float(os.environ.get("MODEL_WEIGHT", 0.25))  # 25% model, 75% market
LOOKBACK_DAYS = 430
WINDOW_DAYS = 14


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "edge-suite-slate/1.0", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.load(r)


def fetch_results(sport, today=None, getter=_get, path=None, stats=None):
    """Completed games [{date, home, away, hs, as}] oldest first. Window-sized requests, each retried once.
    If nothing usable comes back, raises with the first real error and counts so the cause is visible in the logs."""
    import time
    path = path or CFG[sport]["espn"]
    today = today or date.today()
    start = today - timedelta(days=LOOKBACK_DAYS)
    out, seen, errors, with_events, completed = [], set(), [], 0, 0
    # ESPN rejects date ranges (HTTP 400, verified from a real Actions run), so ask one day at a time, in parallel
    days = [start + timedelta(days=i) for i in range((today - start).days + 1)]
    windows = len(days)

    def one(d):
        url = f"https://site.api.espn.com/apis/site/v2/sports/{path}/scoreboard?dates={d:%Y%m%d}&limit=300"
        for attempt in (0, 1):
            try:
                return d, getter(url), None
            except Exception as ex:  # noqa
                if attempt == 1:
                    return d, None, f"{d:%Y%m%d}: {ex!r}"[:160]
                time.sleep(0.5)
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=12) as pool:
        fetched = list(pool.map(one, days))
    for d, data, err in fetched:
        if err:
            errors.append(err)
            continue
        evs = data.get("events", [])
        with_events += bool(evs)
        for ev in evs:
            try:
                comp = ev["competitions"][0]
                if not (ev.get("status", {}).get("type", {}).get("completed") or comp.get("status", {}).get("type", {}).get("completed")):
                    continue
                t = {c["homeAway"]: c for c in comp["competitors"]}
                g = {"id": ev["id"], "date": ev["date"][:10], "home": t["home"]["team"]["displayName"],
                     "away": t["away"]["team"]["displayName"], "hs": float(t["home"]["score"]), "as": float(t["away"]["score"])}
            except (KeyError, ValueError, IndexError, TypeError):
                continue
            completed += 1
            if g["id"] not in seen:
                seen.add(g["id"])
                out.append(g)
    if stats is not None:
        stats.update({"windows": windows, "withEvents": with_events, "completed": completed, "errors": len(errors)})
    if not out:
        raise RuntimeError(f"refusing to build a model, no completed games: {windows} windows, {with_events} had events, {completed} completed, {len(errors)} errors"
                           + (f"; first error {errors[0]}" if errors else ""))
    if errors and len(errors) > windows * 0.2:
        raise RuntimeError(f"refusing to build a model, too many failed windows ({len(errors)} of {windows}); ratings would have holes; first error {errors[0]}")
    out.sort(key=lambda g: g["date"])
    return out


def _rest_adj(sport, days):
    r = CFG[sport]["rest"]
    if days is None or not r:
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
    return {"ratings": R, "last": last, "backtest": back, "canon": {canon(k): k for k in R}}


def predict(sport, m, home, away, on=None, adj=None):
    """Model P(home wins) for an upcoming game, or None if either team is unrated."""
    c = CFG[sport]
    R, last = m["ratings"], m["last"]
    cm = m.get("canon") or {canon(k): k for k in R}
    ch, ca = canon(home), canon(away)
    home, away = cm.get(ch, home), cm.get(ca, away)       # same team under another spelling (accents, "St." vs "St", etc.)
    if home not in R or away not in R:
        return None
    on = on or date.today()
    dh = (on - last[home]).days if home in last else None
    da = (on - last[away]).days if away in last else None
    adj = {canon(k): v for k, v in (adj or {}).items()}
    return _win_prob(R[home] - R[away] + c["home"] + _rest_adj(sport, dh) - _rest_adj(sport, da) + adj.get(ch, 0) - adj.get(ca, 0))


# ---------- injuries (rough, position-based; ESPN's injury feed has no player-quality data) ----------
STATUS_P = {"out": 1.0, "injured reserve": 1.0, "suspension": 1.0, "doubtful": 0.75, "questionable": 0.25, "day-to-day": 0.25, "probable": 0.1}
# (key position or None, Elo hit for that position at full probability), per-other-player hit, cap on others
INJ = {
    "nfl": {"key": {"QB": -100}, "other": -6, "cap": -36},
    "nba": {"key": {}, "other": -10, "cap": -50},   # cannot tell stars from bench players here
    "nhl": {"key": {"G": -50}, "other": -3, "cap": -24},
    "mlb": {"key": {}, "other": -3, "cap": -12},
}


def fetch_injuries(sport, getter=_get):
    """{team displayName: [{name, pos, status}]} from ESPN's injuries endpoint."""
    data = getter(f"https://site.api.espn.com/apis/site/v2/sports/{CFG[sport]['espn']}/injuries")
    out = {}
    for t in data.get("injuries", []):
        team = t.get("displayName") or (t.get("team") or {}).get("displayName")
        for i in t.get("injuries", []):
            a = i.get("athlete") or {}
            pos = a.get("position")
            pos = (pos.get("abbreviation") if isinstance(pos, dict) else pos) or ""
            st = (i.get("status") or (i.get("type") or {}).get("description") or "").lower()
            if team and st:
                out.setdefault(team, []).append({"name": a.get("displayName", "?"), "pos": pos.upper(), "status": st})
    return out


def injury_adj(sport, inj):
    """{team: (elo_delta, [notes])}. Deliberately small and capped: this is a rough guide, not a lineup model."""
    cfg, res = INJ[sport], {}
    for team, plist in inj.items():
        key_hit, other, notes = 0.0, 0.0, []
        for p in plist:
            prob = STATUS_P.get(p["status"], 0.0)
            if prob <= 0:
                continue
            if p["pos"] in cfg["key"]:
                key_hit += cfg["key"][p["pos"]] * prob
                notes.append(f"{p['name']} ({p['pos']}) {p['status']}")
            else:
                other += cfg["other"] * prob
        other = max(other, cfg["cap"])
        total = key_hit + other
        if total or notes:
            res[team] = (round(total, 1), notes)
    return res


# ---------- MLB starting pitchers (rough) ----------
LG_ERA = 4.2        # league-average ERA used as the baseline
ELO_PER_ERA = 35.0  # about 1 run of ERA is worth roughly 35 Elo points in win probability
ERA_SHRINK = 0.5    # an ERA is a noisy, small-sample number, so only half of the gap is trusted
PITCHER_CAP = 40.0


def pitcher_adj(pitchers):
    """pitchers: {'home': {'name','era'}, 'away': {...}} -> ({'home': elo, 'away': elo}, [notes]). Missing or bad ERA = no adjustment."""
    out, notes = {}, []
    for side in ("home", "away"):
        p = (pitchers or {}).get(side) or {}
        try:
            era = float(p.get("era"))
        except (TypeError, ValueError):
            out[side] = 0.0
            continue
        if not (0 < era < 15):
            out[side] = 0.0
            continue
        d = max(-PITCHER_CAP, min(PITCHER_CAP, (LG_ERA - era) * ELO_PER_ERA * ERA_SHRINK))
        out[side] = round(d, 1)
        notes.append(f"{p.get('name', '?')} {era:.2f} ERA ({d:+.0f} Elo)")
    return out, notes


def blend(p_model, p_market, w=None):
    w = MODEL_WEIGHT if w is None else w
    return w * p_model + (1 - w) * p_market
