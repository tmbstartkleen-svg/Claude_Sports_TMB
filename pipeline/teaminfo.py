"""Matchup context for the games in a slate: head-to-head history, each side's
recent form (last N results) and this-season record.

All of it is derived from the same walk-forward results model.py already
fetched to build the Elo ratings (results_cache/<sport>.json) -- zero extra
network calls, zero extra API budget. No player bios here: that needs a
separate roster/athlete fetch per team that isn't wired up yet (see
TEAM.md/RESEARCH.md for why that's a bigger, separate piece of work).

A team's games-this-season W-L and its last-N form only reflect what's in
that sport's cached results window (model.py keeps roughly a season plus a
bit, via BACKFILL_DAYS/LOOKBACK_DAYS) -- not full franchise history.
"""
try:
    from names import canon
except ImportError:  # pragma: no cover
    canon = lambda s: str(s or "").lower()

H2H_LIMIT = 5
FORM_LIMIT = 10


def head_to_head(results, home, away, before_date=None, limit=H2H_LIMIT):
    ch, ca = canon(home), canon(away)
    if not ch or not ca:
        return []
    pair = {ch, ca}
    games = [g for g in results if {canon(g["home"]), canon(g["away"])} == pair]
    if before_date:
        games = [g for g in games if g["date"] < before_date]
    games.sort(key=lambda g: g["date"], reverse=True)
    return [{"date": g["date"], "home": g["home"], "away": g["away"], "homeScore": g["hs"], "awayScore": g["as"]}
            for g in games[:limit]]


def team_form(results, team, before_date=None, limit=FORM_LIMIT):
    ct = canon(team)
    if not ct:
        return {"record": "0-0", "last": []}
    games = [g for g in results if canon(g["home"]) == ct or canon(g["away"]) == ct]
    if before_date:
        games = [g for g in games if g["date"] < before_date]
    games.sort(key=lambda g: g["date"])
    seq = []
    for g in games:
        is_home = canon(g["home"]) == ct
        gf, ga = (g["hs"], g["as"]) if is_home else (g["as"], g["hs"])
        seq.append("T" if gf == ga else ("W" if gf > ga else "L"))
    w, l, t = seq.count("W"), seq.count("L"), seq.count("T")
    return {"record": f"{w}-{l}" + (f"-{t}" if t else ""), "last": seq[-limit:]}


def attach(rows, results_by_sport):
    """rows: slate game rows (need sport/home/away/start). results_by_sport: {sport: games}
    as returned by model.fetch_results -- the same list build_slate.py already fetched
    for Elo, passed through rather than re-fetched. Returns the number of rows annotated."""
    n = 0
    for r in rows:
        res = results_by_sport.get(r.get("sport"))
        if not res or not r.get("home") or not r.get("away"):
            continue
        before = (r.get("start") or "")[:10] or None
        h2h = head_to_head(res, r["home"], r["away"], before_date=before)
        home_form = team_form(res, r["home"], before_date=before)
        away_form = team_form(res, r["away"], before_date=before)
        if h2h or home_form["last"] or away_form["last"]:
            r["matchup"] = {"h2h": h2h, "home": {"name": r["home"], **home_form},
                             "away": {"name": r["away"], **away_form}}
            n += 1
    return n
