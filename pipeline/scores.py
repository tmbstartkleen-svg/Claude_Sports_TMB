"""Week-of-games scoreboard: every game (any status) for the next few days, with live
scores where ESPN has them. Separate from build_slate.py's odds fetch, which only
keeps games that carry a price and drops anything already started — this module is
the opposite: it wants every game, especially the ones in progress or just finished,
regardless of whether a book priced it.

Free, keyless ESPN scoreboard endpoint, same one the odds fetch already uses.
"""
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

WEEK_DAYS = int(os.environ.get("WEEK_DAYS", 7))


def _link(ev, espn_path):
    for l in ev.get("links") or []:
        href = l.get("href")
        if href and "espn.com" in href:
            return href
    gid = ev.get("id")
    return f"https://www.espn.com/{espn_path.split('/')[0]}/game/_/gameId/{gid}" if gid else None


def _game(ev, sport, espn_path):
    comp = (ev.get("competitions") or [{}])[0]
    comps = comp.get("competitors", [])
    side = {}
    for i, c in enumerate(comps):
        ha = c.get("homeAway") or ("home" if i == 0 else "away")
        side[ha] = c
    home, away = side.get("home"), side.get("away")
    if not home or not away:
        return None
    nm = lambda c: (c.get("team") or {}).get("displayName") or (c.get("athlete") or {}).get("displayName")
    sc = lambda c: (int(c["score"]) if str(c.get("score", "")).lstrip("-").isdigit() else None)
    status = comp.get("status") or ev.get("status") or {}
    stype = status.get("type") or {}
    return {
        "sport": sport, "start": ev.get("date"), "link": _link(ev, espn_path),
        "home": nm(home), "away": away and nm(away), "homeScore": sc(home), "awayScore": sc(away),
        "state": stype.get("state") or "pre",          # "pre" | "in" | "post"
        "completed": bool(stype.get("completed")),
        "detail": stype.get("shortDetail") or stype.get("detail") or stype.get("description") or "",
        "clock": status.get("displayClock"), "period": status.get("period"),
    }


def fetch_day(sport, espn_path, day, getter):
    url = f"https://site.api.espn.com/apis/site/v2/sports/{espn_path}/scoreboard?dates={day:%Y%m%d}"
    data = getter(url)
    if not isinstance(data, dict):
        return []
    out = []
    for ev in data.get("events", []):
        try:
            g = _game(ev, sport, espn_path)
        except Exception:  # noqa  one malformed event must not drop the whole day
            g = None
        if g and g["home"] and g["away"]:
            out.append(g)
    return out


def fetch_week(sports, espn_paths, today=None, getter=None, days=None):
    """sports: iterable of sport keys to include. espn_paths: {sport: ESPN api path}.
    Returns a flat list of games across `days` days starting today, de-duplicated."""
    import build_slate as _b
    getter = getter or _b.http_json
    today = today or datetime.now(timezone.utc).date()
    days = days or WEEK_DAYS
    jobs = [(sp, d) for sp in sports if sp in espn_paths for d in range(days)]

    def one(job):
        sp, d = job
        try:
            return fetch_day(sp, espn_paths[sp], today + timedelta(days=d), getter)
        except Exception:  # noqa  one sport/day failing must not blank the week
            return []
    with ThreadPoolExecutor(max_workers=10) as pool:
        pages = list(pool.map(one, jobs))
    seen, out = set(), []
    for page in pages:
        for g in page:
            k = (g["sport"], g["home"], g["away"], g["start"])
            if k not in seen:
                seen.add(k)
                out.append(g)
    out.sort(key=lambda g: g.get("start") or "9999")
    return out
