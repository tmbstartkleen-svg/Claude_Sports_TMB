"""Today's best bets, ranked and combined (Phase 3 of 3: "add suggestions of parlays or singles
to keep an edge").

index.html already lets a person build their own parlays (the Week tab's filterable combo search,
and a same-day "Parlay candidates" list on Opportunities) -- those are exploratory tools. What was
missing was a plain answer to "what should I actually look at first, today": a server-computed,
EV-ranked shortlist of the best single bets and the best small parlays, done once per run instead
of re-derived by every viewer's browser, so it can also feed notify.py-style "here's the best thing
right now" thinking later without re-deriving anything.

Inputs are exactly what build_slate.py already built for the main slate: rows with their flagged
`bets` (already past the MIN_EDGE/MIN_BOOKS bar, each already carrying a Kelly stake). No network
calls, no new probabilities -- this module only ranks and combines numbers that already exist.

Parlay legs are restricted to one leg per game (the game's own best-EV flagged bet), which rules
out the obvious correlation case (two bets on the same game) by construction. It does not, and
cannot, detect correlation ACROSS games (e.g. two teams in the same conference both having a good
week) -- the same independence assumption the rest of the app's parlay tools already make, and the
same warning language applies.
"""
from itertools import combinations

PARLAY_SIZES = (2, 3)      # legs per suggested parlay
LEG_POOL = 10               # consider at most this many candidate legs (one per game, best EV first)
TOP_SINGLES = 10
TOP_PARLAYS = 6
MIN_PARLAY_EV = 0.0         # suggest parlays at/above this EV; never suggest a known-negative-EV parlay


def _dec(american):
    a = float(american)
    return 1 + a / 100 if a > 0 else 1 + 100 / abs(a)


def _dec_to_american(dec):
    return round((dec - 1) * 100) if dec >= 2 else round(-100 / (dec - 1))


def rank_singles(rows, top_n=TOP_SINGLES):
    """Flatten every row's already-flagged bets into one cross-game list, best EV first."""
    out = []
    for r in rows:
        for b in r.get("bets", []):
            item = {"sport": r["sport"], "home": r["home"], "away": r["away"], "start": r.get("start"),
                    "side": b["side"], "book": b["book"], "american": b["american"], "fair": b["fair"],
                    "evPct": b["evPct"], "stakePct": b.get("stakePct"), "stake": b.get("stake")}
            if b.get("timing"):
                item["timing"] = b["timing"]
            out.append(item)
    out.sort(key=lambda x: -x["evPct"])
    return out[:top_n]


def _best_leg_per_game(rows):
    legs = []
    for r in rows:
        bets = r.get("bets") or []
        if not bets:
            continue
        b = max(bets, key=lambda x: x["evPct"])
        legs.append({"sport": r["sport"], "home": r["home"], "away": r["away"], "start": r.get("start"),
                    "side": b["side"], "book": b["book"], "american": b["american"], "fair": b["fair"], "evPct": b["evPct"]})
    legs.sort(key=lambda x: -x["evPct"])
    return legs


def build_parlays(rows, bankroll, kelly_frac, max_stake_pct, sizes=PARLAY_SIZES, pool=LEG_POOL, top_n=TOP_PARLAYS):
    """Returns up to top_n suggested parlays, each {legs, combinedProb, combinedAmerican, evPct,
    stakePct, stake}, best EV first. Built only from each game's single best-EV flagged leg, so a
    combo can never put two bets on the same game."""
    cand = _best_leg_per_game(rows)[:pool]
    out = []
    for n in sizes:
        if n > len(cand):
            continue
        for combo in combinations(cand, n):
            p = 1.0
            dec = 1.0
            for leg in combo:
                p *= leg["fair"]
                dec *= _dec(leg["american"])
            ev = p * dec - 1
            if ev < MIN_PARLAY_EV:
                continue
            b = dec - 1
            kelly = max(0.0, (b * p - (1 - p)) / b) if b > 0 else 0.0
            pct = min(kelly * kelly_frac * 100, max_stake_pct)
            out.append({"legs": list(combo), "nLegs": n, "combinedProb": round(p, 4), "combinedAmerican": _dec_to_american(dec),
                        "evPct": round(ev * 100, 2), "stakePct": round(pct, 2), "stake": round(bankroll * pct / 100, 2)})
    out.sort(key=lambda x: -x["evPct"])
    return out[:top_n]


def build(rows, bankroll, kelly_frac, max_stake_pct):
    """Convenience wrapper: {"singles": [...], "parlays": [...]}."""
    return {"singles": rank_singles(rows), "parlays": build_parlays(rows, bankroll, kelly_frac, max_stake_pct)}
