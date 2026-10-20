#!/usr/bin/env python3
"""Offline tests for the sports-skills fallback path (espn_via_skills / _skills_events).

sports_skills normalizes ESPN's scoreboard into a flatter shape than raw ESPN (see each sport
module's own _normalize_event + the shared _espn_base.normalize_odds) -- competitors[].team.name/
home_away instead of competitions[0].competitors, and a single `odds` dict instead of an `odds`
list. Passing that shape through our own _espn_events() (built for raw ESPN) raised
KeyError('competitions') for every single sport, silently killing this whole fallback. This file
locks in the fix: a dedicated _skills_events() parser for the normalized shape, offline, no network,
no real sports_skills install required.
"""
import os, sys, types
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_slate as B


def ev(home, away, start, home_odds=-150, away_odds=130, draw_odds=None, provider="DraftKings", home_logo="h.png"):
    comp = [{"team": {"name": home, "logo": home_logo}, "home_away": "home"},
            {"team": {"name": away, "logo": "a.png"}, "home_away": "away"}]
    odds = None
    if home_odds is not None:
        ml = {"home": home_odds, "away": away_odds}
        if draw_odds is not None:
            ml["draw"] = draw_odds
        odds = {"provider": provider, "moneyline": ml}
    return {"competitors": comp, "start_time": start, "odds": odds}


# ---- _skills_events: the normalized shape parses into our own game-dict format
events = [ev("Home FC", "Away FC", "2026-10-26T23:00Z")]
games = B._skills_events("nfl", events)
assert len(games) == 1, games
g = games[0]
assert g["sport"] == "nfl" and g["home"] == "Home FC" and g["away"] == "Away FC" and g["start"] == "2026-10-26T23:00Z"
assert g["books"] == {"DraftKings": {"home": -150.0, "away": 130.0}}, g["books"]
assert g["teamMeta"]["home"]["logo"] == "h.png"
print("OK _skills_events: basic two-way moneyline")

# ---- three-way (soccer) draw odds carried through
g3 = B._skills_events("epl", [ev("Home FC", "Away FC", "2026-10-26T23:00Z", draw_odds=240)])[0]
assert g3["books"]["DraftKings"]["draw"] == 240.0
print("OK _skills_events: draw odds")

# ---- no odds at all (common: ESPN hasn't posted a line yet) -> event dropped, never crashes
assert B._skills_events("nfl", [ev("H", "A", "2026-10-26T23:00Z", home_odds=None)]) == []
# ---- missing team name -> event dropped
broken = [{"competitors": [{"team": {}, "home_away": "home"}, {"team": {"name": "Away FC"}, "home_away": "away"}],
           "start_time": "2026-10-26T23:00Z", "odds": {"provider": "DraftKings", "moneyline": {"home": -150, "away": 130}}}]
assert B._skills_events("nfl", broken) == []
# ---- no events at all / None -> empty, never crashes
assert B._skills_events("nfl", []) == [] and B._skills_events("nfl", None) == []
print("OK _skills_events: missing odds/teams dropped cleanly, no crash")


def fake_skills_module(status=True, data=None, message=""):
    mod = types.SimpleNamespace()
    mod.get_scoreboard = lambda: {"status": status, "data": data or {}, "message": message}
    ss = types.SimpleNamespace(mlb=mod, cfb=mod, cbb=mod)
    return ss


# ---- espn_via_skills: wires sport-name remapping (ncaaf->cfb, ncaab->cbb), parses via _skills_events
sys.modules["sports_skills"] = fake_skills_module(data={"events": [ev("Home FC", "Away FC", "2026-10-26T23:00Z")]})
got = B.espn_via_skills("mlb")
assert len(got) == 1 and got[0]["home"] == "Home FC"
got2 = B.espn_via_skills("ncaaf")  # must resolve to the cfb module, not AttributeError
assert len(got2) == 1
print("OK espn_via_skills: sport remapping + successful parse")

# ---- espn_via_skills: a connector-level error (status False) raises with its message
sys.modules["sports_skills"] = fake_skills_module(status=False, message="rate limited")
try:
    B.espn_via_skills("mlb")
    raise SystemExit("should have raised")
except RuntimeError as e:
    assert "rate limited" in str(e)
print("OK espn_via_skills: connector error propagates")

# ---- espn_via_skills: status True but zero usable games raises (not a silent empty success)
sys.modules["sports_skills"] = fake_skills_module(data={"events": []})
try:
    B.espn_via_skills("mlb")
    raise SystemExit("should have raised")
except RuntimeError as e:
    assert "no usable odds" in str(e)
print("OK espn_via_skills: no usable games raises instead of silently succeeding empty")

del sys.modules["sports_skills"]
print("SKILLS TESTS PASS")
