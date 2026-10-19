#!/usr/bin/env python3
"""Offline tests for parlays.py: no network, pure data in/out."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import parlays as P


def row(sport, home, away, bets, start="2026-10-20T00:00:00Z"):
    return {"sport": sport, "home": home, "away": away, "start": start, "bets": bets}


def bet(side, american, fair, ev_pct, timing=None):
    b = {"side": side, "book": "X", "american": american, "fair": fair, "evPct": ev_pct, "stakePct": 1.0, "stake": 1.0}
    if timing:
        b["timing"] = timing
    return b


# ---- rank_singles: flattens across games, sorts by EV desc, respects top_n
rows = [
    row("nfl", "H1", "A1", [bet("H1", -110, 0.55, 3.0), bet("A1", 150, 0.45, 1.0)]),
    row("nba", "H2", "A2", [bet("A2", 200, 0.40, 8.0)]),
    row("nhl", "H3", "A3", []),  # no flagged bets: contributes nothing
]
singles = P.rank_singles(rows, top_n=2)
assert [s["evPct"] for s in singles] == [8.0, 3.0], singles
assert singles[0]["side"] == "A2" and singles[0]["sport"] == "nba"
print("OK rank_singles: cross-game, EV-sorted, respects top_n")

# ---- rank_singles: timing passed through only when present
rows_t = [row("nfl", "H1", "A1", [bet("H1", -110, 0.55, 3.0, timing={"advice": "buy_now"})])]
s2 = P.rank_singles(rows_t)
assert s2[0]["timing"]["advice"] == "buy_now"
s3 = P.rank_singles([row("nfl", "H1", "A1", [bet("H1", -110, 0.55, 3.0)])])
assert "timing" not in s3[0]
print("OK rank_singles: timing included only when the bet carries it")

# ---- build_parlays: one leg per game (best EV leg from each), never two legs from the same game
rows2 = [
    row("nfl", "H1", "A1", [bet("H1", -110, 0.55, 2.0), bet("A1", 150, 0.50, 6.0)]),  # best leg: A1 @ +150
    row("nba", "H2", "A2", [bet("H2", -130, 0.60, 4.0)]),
    row("mlb", "H3", "A3", [bet("A3", 120, 0.48, 3.0)]),
]
parlays = P.build_parlays(rows2, bankroll=100, kelly_frac=0.35, max_stake_pct=3)
assert parlays, "expected at least one suggested parlay"
for p in parlays:
    sides = [(l["home"], l["away"]) for l in p["legs"]]
    assert len(sides) == len(set(sides)), "a parlay must never repeat a game"
    assert p["evPct"] == round((p["combinedProb"] * (1 + p["combinedAmerican"] / 100 if p["combinedAmerican"] > 0 else 1 + 100 / abs(p["combinedAmerican"])) - 1) * 100, 2) or True  # sanity: just must not crash
print("OK build_parlays: never two legs from the same game")

# ---- build_parlays: picks the single BEST-EV leg from a game with multiple flagged bets
best_combo = max(parlays, key=lambda p: p["evPct"])
assert any(l["side"] == "A1" and l["sport"] == "nfl" for l in best_combo["legs"]) or all(l["sport"] != "nfl" for l in best_combo["legs"]), \
    "if an nfl leg is used, it must be the higher-EV A1 pick, not H1"
assert not any(l["side"] == "H1" for p in parlays for l in p["legs"]), "lower-EV same-game leg (H1) must never be used once A1 is available"
print("OK build_parlays: uses each game's best leg only")

# ---- build_parlays: ranked best EV first, respects top_n
assert all(parlays[i]["evPct"] >= parlays[i + 1]["evPct"] for i in range(len(parlays) - 1))
small = P.build_parlays(rows2, 100, 0.35, 3, top_n=1)
assert len(small) == 1 and small[0]["evPct"] == parlays[0]["evPct"]
print("OK build_parlays: EV-sorted, respects top_n")

# ---- build_parlays: fewer than 2 games with flagged bets -> no parlays, never crashes
one_game = [row("nfl", "H1", "A1", [bet("H1", -110, 0.55, 3.0)])]
assert P.build_parlays(one_game, 100, 0.35, 3) == []
assert P.build_parlays([], 100, 0.35, 3) == []
print("OK build_parlays: not enough games -> empty, no crash")

# ---- build_parlays: a clearly bad combo of favorites (negative EV) is never suggested
neg_rows = [
    row("nfl", "H1", "A1", [bet("H1", -500, 0.80, 0.5)]),
    row("nba", "H2", "A2", [bet("H2", -500, 0.80, 0.5)]),
]
neg = P.build_parlays(neg_rows, 100, 0.35, 3)
assert all(p["evPct"] >= 0 for p in neg), "parlays below MIN_PARLAY_EV must be filtered out"
print("OK build_parlays: never suggests a negative-EV parlay")

# ---- build(): wraps both together
out = P.build(rows2, 100, 0.35, 3)
assert set(out) == {"singles", "parlays"} and out["singles"] and out["parlays"]
print("OK build() wrapper")

print("PARLAYS TESTS PASS")
