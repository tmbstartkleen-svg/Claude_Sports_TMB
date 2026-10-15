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
MODEL_WEIGHT = float(os.environ.get("MODEL_WEIGHT", 0.25))  # default when a sport has no validated weight below
# Per-sport blend weights, fit by log-loss against real closing-line datasets (backtest_report.json, Hugging Face
# minmaxxxer, point-in-time, no lookahead). Shrunk toward the 0.25 default rather than taking the fitted optimum
# outright: nfl's fitted weight (1.0) came from only 78 games of one still-open season and is not trusted at face value.
MODEL_WEIGHTS = {"nfl": 0.4, "nhl": 0.25, "mlb": 0.12, "epl": 0.12, "laliga": 0.1, "seriea": 0.1, "bundesliga": 0.12}
for _kv in filter(None, os.environ.get("MODEL_WEIGHTS", "").split(",")):  # e.g. MODEL_WEIGHTS="nfl=0.5,mlb=0.15"
    _k, _v = _kv.split("=")
    MODEL_WEIGHTS[_k.strip()] = float(_v)
LOOKBACK_DAYS = 430
WINDOW_DAYS = 14


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "edge-suite-slate/1.0", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.load(r)


CACHE_DIR = os.environ.get("RESULTS_CACHE", "results_cache")
BACKFILL_DAYS = int(os.environ.get("BACKFILL_DAYS", 200))   # first run fetches this many recent days; each later run extends backwards by this much until LOOKBACK_DAYS is covered


def _fetch_days(days, path, getter):
    """One ESPN request per day (ranges return HTTP 400, verified from a real run), 12 in parallel, each retried once.
    Returns (completed games, failed day strings with error text, number of days that had any events)."""
    import time
    from concurrent.futures import ThreadPoolExecutor

    def one(d):
        url = f"https://site.api.espn.com/apis/site/v2/sports/{path}/scoreboard?dates={d:%Y%m%d}&limit=300"
        for attempt in (0, 1):
            try:
                return d, getter(url), None
            except Exception as ex:  # noqa
                if attempt == 1:
                    return d, None, f"{d:%Y%m%d}: {ex!r}"[:160]
                time.sleep(0.5)
    with ThreadPoolExecutor(max_workers=12) as pool:
        fetched = list(pool.map(one, days))
    games, errors, with_events, completed = [], [], 0, 0
    for d, data, err in fetched:
        if err:
            errors.append((d, err))
            continue
        evs = data.get("events", [])
        with_events += bool(evs)
        for ev in evs:
            try:
                comp = ev["competitions"][0]
                if not (ev.get("status", {}).get("type", {}).get("completed") or comp.get("status", {}).get("type", {}).get("completed")):
                    continue
                t = {c["homeAway"]: c for c in comp["competitors"]}
                games.append({"id": ev["id"], "date": ev["date"][:10], "home": t["home"]["team"]["displayName"],
                              "away": t["away"]["team"]["displayName"], "hs": float(t["home"]["score"]), "as": float(t["away"]["score"])})
                completed += 1
            except (KeyError, ValueError, IndexError, TypeError):
                continue
    return games, errors, with_events, completed


def _load_cache(path):
    try:
        with open(path) as f:
            c = json.load(f)
        return date.fromisoformat(c["from"]), date.fromisoformat(c["through"]), c["games"]
    except (OSError, ValueError, KeyError, TypeError):
        return None


def fetch_results(sport, today=None, getter=_get, path=None, stats=None, cache=False):
    """Completed games [{date, home, away, hs, as}] oldest first.
    With cache=True the results are kept in results_cache/<sport>.json: later runs fetch only new days (plus a 3-day overlap) and extend backwards
    by BACKFILL_DAYS until LOOKBACK_DAYS is covered, so 70 leagues do not mean 30,000 requests a run.
    If nothing usable comes back, raises with the first real error and counts so the cause is visible in the logs."""
    path = path or CFG[sport]["espn"]
    today = today or date.today()
    start = today - timedelta(days=LOOKBACK_DAYS)
    cpath = os.path.join(CACHE_DIR, f"{sport}.json")
    c = _load_cache(cpath) if cache else None
    if c:
        have_from, have_through, cached = c
        days = [have_through - timedelta(days=2) + timedelta(days=i) for i in range((today - (have_through - timedelta(days=2))).days + 1)]
        if have_from > start:
            nf = max(start, have_from - timedelta(days=BACKFILL_DAYS))
            days += [nf + timedelta(days=i) for i in range((have_from - nf).days)]
            have_from = nf
        have_from = min(have_from, start) if have_from <= start else have_from
    else:
        cached = []
        first = max(start, today - timedelta(days=BACKFILL_DAYS)) if cache else start
        days = [first + timedelta(days=i) for i in range((today - first).days + 1)]
        have_from = first
    games, errs, with_events, completed = _fetch_days(days, path, getter)
    errors = [e for _, e in errs]
    windows = len(days)
    seen, out = set(), []
    for g in games + cached:
        if g["id"] not in seen and g["date"] >= f"{start:%Y-%m-%d}":
            seen.add(g["id"])
            out.append(g)
    if stats is not None:
        stats.update({"windows": windows, "withEvents": with_events, "completed": completed, "errors": len(errors), "total": len(out)})
    if not out:
        raise RuntimeError(f"refusing to build a model, no completed games: {windows} windows, {with_events} had events, {completed} completed, {len(errors)} errors"
                           + (f"; first error {errors[0]}" if errors else ""))
    if errors and len(errors) > windows * 0.2:
        raise RuntimeError(f"refusing to build a model, too many failed windows ({len(errors)} of {windows}); ratings would have holes; first error {errors[0]}")
    out.sort(key=lambda g: g["date"])
    if cache:
        # never mark a failed day as covered: stop 'through' just before the earliest failure so the next run retries it
        through = today if not errs else min(d for d, _ in errs) - timedelta(days=1)
        try:
            os.makedirs(CACHE_DIR, exist_ok=True)
            with open(cpath, "w") as f:
                json.dump({"from": have_from.isoformat(), "through": through.isoformat(), "games": out}, f, separators=(",", ":"))
        except OSError:
            pass
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


def blend(p_model, p_market, w=None, sport=None):
    w = (MODEL_WEIGHTS.get(sport, MODEL_WEIGHT) if sport else MODEL_WEIGHT) if w is None else w
    return w * p_model + (1 - w) * p_market
