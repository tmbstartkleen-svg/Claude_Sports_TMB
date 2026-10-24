#!/usr/bin/env python3
"""Offline tests for bovada.py: fake HTTP responses shaped like the documented bovada.lv feed, no network."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bovada as B


def outcome(desc, american=None, handicap=None):
    price = {}
    if american is not None:
        price["american"] = american
    if handicap is not None:
        price["handicap"] = handicap
    return {"description": desc, "price": price}


def event(home, away, start=1700000000000, live=False, moneyline=True, spread=False, total=False, props=False, home_odds="-150", away_odds="+130"):
    comps = [{"id": "1", "name": home, "home": True}, {"id": "2", "name": away, "home": False}]
    markets = []
    if moneyline:
        markets.append({"description": "Moneyline", "outcomes": [outcome(home, home_odds), outcome(away, away_odds)]})
    if spread:
        markets.append({"description": "Point Spread", "outcomes": [outcome(home, "-110", "-3.5"), outcome(away, "-110", "3.5")]})
    if total:
        markets.append({"description": "Total", "outcomes": [outcome("Over", "-110", "47.5"), outcome("Under", "-110", "47.5")]})
    groups = [{"description": "Game Lines", "markets": markets}]
    if props:
        groups.append({"description": "Player Props", "markets": [
            {"description": "Star Player Total Passing Yards", "outcomes": [outcome("Over", "-115", "275.5"), outcome("Under", "-105", "275.5")]}
        ]})
    return {"id": "ev1", "startTime": start, "live": live, "competitors": comps, "displayGroups": groups}


# ---- _american: strings, EVEN, garbage
assert B._american("+150") == 150
assert B._american("-180") == -180
assert B._american("EVEN") == 100
assert B._american(None) is None
assert B._american("not a number") is None
print("OK _american")

# ---- parse_event: moneyline only
ev = event("Example Home", "Example Away")
g = B.parse_event(ev)
assert g["home"] == "Example Home" and g["away"] == "Example Away"
assert g["books"]["Bovada"] == {"home": -150, "away": 130}
assert "spread" not in g and "total" not in g and "props" not in g
print("OK parse_event: moneyline only")

# ---- parse_event: no moneyline -> dropped (nothing gradeable)
ev_no_ml = event("A", "B", moneyline=False)
assert B.parse_event(ev_no_ml) is None
print("OK parse_event: no moneyline -> None")

# ---- parse_event: no two named competitors -> dropped
bad = event("A", "B")
bad["competitors"] = [{"id": "1", "name": "A", "home": True}]
assert B.parse_event(bad) is None
print("OK parse_event: missing a competitor -> None")

# ---- parse_event: spread + total + props all captured
full = event("Home Team", "Away Team", spread=True, total=True, props=True, live=True)
g2 = B.parse_event(full)
assert g2["live"] is True
assert g2["spread"]["home"]["handicap"] == -3.5 and g2["spread"]["away"]["handicap"] == 3.5
assert g2["total"]["over"]["handicap"] == 47.5 and g2["total"]["under"]["handicap"] == 47.5
assert len(g2["props"]) == 1 and g2["props"][0]["market"] == "Star Player Total Passing Yards"
assert g2["props"][0]["legs"][0]["name"] == "Over" and g2["props"][0]["legs"][0]["handicap"] == 275.5
print("OK parse_event: spread, total and props all parsed")

# ---- parse_event: a market with no matching side name is just skipped, never crashes
weird = event("Home Team", "Away Team")
weird["displayGroups"][0]["markets"].append({"description": "Point Spread", "outcomes": [outcome("Some Other Team", "-110", "-3.5")]})
g3 = B.parse_event(weird)
assert g3 is not None and "spread" not in g3
print("OK parse_event: unmatched side on a market is dropped, not crashed")

# ---- fetch: wraps fetch_raw, tags sport, one bad event never drops the rest
def fake_getter(url):
    assert "football/nfl" in url
    return [{"events": [event("Home A", "Away A"), {"garbage": True}, event("Home B", "Away B", moneyline=False)]}]
games = B.fetch("nfl", getter=fake_getter)
assert len(games) == 1 and games[0]["sport"] == "nfl" and games[0]["home"] == "Home A"
print("OK fetch: tags sport, drops unusable/malformed events, never raises")

# ---- fetch: unknown sport key -> empty, no crash, no HTTP attempted
assert B.fetch("curling") == []
print("OK fetch: unknown sport -> empty, no call made")

# ---- fetch: getter raising is NOT swallowed here (that's try_sources' job in build_slate.py)
def boom(url):
    raise RuntimeError("502")
try:
    B.fetch("nfl", getter=boom)
    raise AssertionError("expected the getter's exception to propagate")
except RuntimeError:
    pass
print("OK fetch: a transport failure propagates for try_sources to log")

print("BOVADA TESTS PASS")
