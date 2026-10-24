"""Bovada: a second, independent sportsbook, read off the same public JSON endpoint
bovada.lv's own site calls to render its pages. No account, no login, no key -- this is
the same class of source as ESPN's scoreboard (a public page's own data feed), not a
private or paid API. We only ever read it (odds, not placing bets).

This is the only way this project currently gets a second book alongside ESPN's
single DraftKings line, which is what actually unlocks cross-book EV, arbitrage and
middles for American sports (see build_slate.py's module docstring). It also carries
player props and alternate lines in the same response -- things ESPN's feed has never had.

Unverified against the live endpoint from this sandbox (outbound requests here are
restricted to package registries); the shape below matches what every public scraper
and open-source client (e.g. github.com/adayNU/bovada) documents. If bovada.lv changes
its response shape, every function here degrades to returning nothing -- never raises
past its own try/except -- so a break here can never take down the rest of the slate.
Health shows up the same way every other source does: in slate["sources"].
"""
import json, re, urllib.request

HOST = "www.bovada.lv"
# sport key (ours) -> bovada's own path segment. Confirmed segments come from the
# community-documented client above; the rest are our best guess from bovada.lv's own
# site navigation and may need correcting once a live run shows a 404 in slate["sources"].
PATHS = {
    "nfl": "football/nfl",
    "ncaaf": "football/college-football",
    "nba": "basketball/nba",
    "ncaab": "basketball/college-basketball",
    "mlb": "baseball/mlb",
    "nhl": "hockey/nhl",
}


def _url(path):
    return f"https://{HOST}/services/sports/event/v2/events/A/description/{path}?marketFilterId=def&preMatchOnly=false&lang=en"


def fetch_raw(sport, getter=None):
    """Raw bovada response for one of our sport keys, or [] if we don't have a path for it."""
    path = PATHS.get(sport)
    if not path:
        return []
    get = getter or _http_json
    return get(_url(path)) or []


def _http_json(url, timeout=20):
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0 edge-suite/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def _american(price):
    """Bovada prices arrive as strings: '+150', '-180', or 'EVEN'. None/garbage -> None."""
    if price is None:
        return None
    s = str(price).strip().upper()
    if s == "EVEN":
        return 100
    try:
        v = int(float(s))
    except (TypeError, ValueError):
        return None
    return v if v != 0 else None


def _outcome_price(o):
    p = (o or {}).get("price") or {}
    return _american(p.get("american"))


def _outcome_handicap(o):
    p = (o or {}).get("price") or {}
    h = p.get("handicap")
    try:
        return float(h) if h not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _match_side(outcome_desc, home, away):
    """Which side ('home'/'away'/None) an outcome's own description names."""
    d = (outcome_desc or "").strip().lower()
    if d and home and d == home.strip().lower():
        return "home"
    if d and away and d == away.strip().lower():
        return "away"
    return None


def parse_event(ev):
    """One bovada event -> {home, away, start, live, books:{'Bovada':{home,away}}, spread, total, props}.
    Returns None if the event doesn't have enough to be useful (no two named competitors, or no moneyline)."""
    comps = ev.get("competitors") or []
    home = next((c.get("name") for c in comps if c.get("home")), None)
    away = next((c.get("name") for c in comps if c.get("home") is False), None)
    if not home or not away:
        return None
    out = {"home": home, "away": away, "start": ev.get("startTime"), "live": bool(ev.get("live")),
           "bovadaId": ev.get("id")}
    ml_home = ml_away = None
    spread = None
    total = None
    props = []
    for grp in ev.get("displayGroups") or []:
        gdesc = (grp.get("description") or "").lower()
        for mkt in grp.get("markets") or []:
            mdesc = (mkt.get("description") or "")
            mlow = mdesc.lower()
            outcomes = mkt.get("outcomes") or []
            if mlow == "moneyline" or mlow.startswith("moneyline"):
                for o in outcomes:
                    side = _match_side(o.get("description"), home, away)
                    px = _outcome_price(o)
                    if side == "home" and px is not None:
                        ml_home = px
                    elif side == "away" and px is not None:
                        ml_away = px
            elif "point spread" in mlow or mlow == "spread":
                sides = {}
                for o in outcomes:
                    side = _match_side(o.get("description"), home, away)
                    if side:
                        sides[side] = {"handicap": _outcome_handicap(o), "american": _outcome_price(o)}
                if sides:
                    spread = sides
            elif mlow in ("total", "total points", "total goals", "total runs"):
                sides = {}
                for o in outcomes:
                    d = (o.get("description") or "").strip().lower()
                    if d.startswith("over"):
                        sides["over"] = {"handicap": _outcome_handicap(o), "american": _outcome_price(o)}
                    elif d.startswith("under"):
                        sides["under"] = {"handicap": _outcome_handicap(o), "american": _outcome_price(o)}
                if sides:
                    total = sides
            elif "prop" in gdesc or "prop" in mlow:
                legs = [{"name": o.get("description"), "handicap": _outcome_handicap(o), "american": _outcome_price(o)}
                        for o in outcomes if o.get("description")]
                if legs:
                    props.append({"market": mdesc, "legs": legs})
    if ml_home is None or ml_away is None:
        return None  # no usable moneyline: not worth carrying (props without a base line aren't gradeable here)
    out["books"] = {"Bovada": {"home": ml_home, "away": ml_away}}
    if spread:
        out["spread"] = spread
    if total:
        out["total"] = total
    if props:
        out["props"] = props[:40]  # cap: some events carry hundreds of prop legs, more than the dashboard needs
    return out


def fetch(sport, getter=None):
    """All usable games for one sport, defensively: any parse problem drops that one event, never the whole call."""
    raw = fetch_raw(sport, getter)
    games = []
    for block in raw or []:
        for ev in (block or {}).get("events") or []:
            try:
                g = parse_event(ev)
            except Exception:  # noqa  a single malformed event must never take the rest down
                g = None
            if g:
                g["sport"] = sport
                games.append(g)
    return games


def diag(sport, getter=None):
    """One-line diagnostic for when fetch() comes back empty: tells apart 'no response', 'response
    but no events' (wrong path segment, or genuinely no games) and 'events present but none parsed'
    (shape guess is wrong -- outcome descriptions aren't matching home/away, or no moneyline market)
    without needing a second live round trip to debug it."""
    try:
        raw = fetch_raw(sport, getter)
    except Exception as e:  # noqa
        return f"fetch_raw raised: {e!r}"
    if not raw:
        return "fetch_raw returned nothing (empty/non-list response -- check the path segment or query params)"
    n_blocks = len(raw)
    all_events = [ev for block in raw for ev in (block or {}).get("events") or []]
    if not all_events:
        paths = [p.get("description") for block in raw for p in (block or {}).get("path") or []]
        return f"{n_blocks} block(s), 0 events (path breadcrumbs: {paths[:5]}) -- likely no games right now, or wrong path segment"
    n_parsed = sum(1 for ev in all_events if parse_event(ev))
    return f"{n_blocks} block(s), {len(all_events)} events, {n_parsed} parsed as usable games"
