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
out the obvious correlation case (two bets on the same game) by construction. It cannot detect
every cross-game correlation (e.g. two teams in the same conference both having a good week,
or a weather system affecting several outdoor games the same day) -- that's still a real, unflagged
gap. What it CAN detect for free, from data already on each bet, is the one correlation source this
pipeline itself creates: when two or more legs are priced off the SAME source of probability (our
own Elo model, "basis": "model-blend") rather than independent book consensus, a single systematic
error in that model hits every leg built from it at once. That's flagged as `correlationWarning`.

Each leg (and so each parlay) also gets a plain confidence tier, from what actually backs its price:
  "high"   -- market consensus from 2+ books (the most independently-verified number we have)
  "medium" -- a single book's own de-vigged price (real market, but only one book's opinion)
  "low"    -- our own Elo model blended in (a free, unproven estimate -- see Track Record for how
              model-blend bets have actually performed before trusting one)
A parlay's tier is its weakest leg's tier: one low-confidence leg makes the whole combo low-confidence,
the same way one unreliable number makes a sum unreliable.
"""
from itertools import combinations

PARLAY_SIZES = (2, 3)      # legs per suggested parlay
LEG_POOL = 10               # consider at most this many candidate legs (one per game, best EV first)
TOP_SINGLES = 10
TOP_PARLAYS = 6
MIN_PARLAY_EV = 0.0         # suggest parlays at/above this EV; never suggest a known-negative-EV parlay
TIER_ORDER = {"low": 0, "medium": 1, "high": 2}


def _dec(american):
    a = float(american)
    return 1 + a / 100 if a > 0 else 1 + 100 / abs(a)


def _dec_to_american(dec):
    return round((dec - 1) * 100) if dec >= 2 else round(-100 / (dec - 1))


def confidence_tier(basis, n_books):
    """What actually backs this price, in plain terms. See module docstring."""
    if basis == "model-blend":
        return "low"
    return "high" if (n_books or 0) >= 2 else "medium"


def _leg(r, b):
    basis = b.get("basis", "consensus")
    n_books = r.get("nBooks")
    item = {"sport": r["sport"], "home": r["home"], "away": r["away"], "start": r.get("start"),
            "side": b["side"], "book": b["book"], "american": b["american"], "fair": b["fair"], "evPct": b["evPct"],
            "basis": basis, "nBooks": n_books, "tier": confidence_tier(basis, n_books)}
    return item


def rank_singles(rows, top_n=TOP_SINGLES):
    """Flatten every row's already-flagged bets into one cross-game list, best EV first."""
    out = []
    for r in rows:
        for b in r.get("bets", []):
            item = _leg(r, b)
            item["stakePct"] = b.get("stakePct")
            item["stake"] = b.get("stake")
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
        legs.append(_leg(r, b))
    legs.sort(key=lambda x: -x["evPct"])
    return legs


def build_parlays(rows, bankroll, kelly_frac, max_stake_pct, sizes=PARLAY_SIZES, pool=LEG_POOL, top_n=TOP_PARLAYS):
    """Returns up to top_n suggested parlays, each {legs, combinedProb, combinedAmerican, evPct,
    stakePct, stake, tier, correlationWarning}, best EV first. Built only from each game's single
    best-EV flagged leg, so a combo can never put two bets on the same game."""
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
            tier = min((leg["tier"] for leg in combo), key=lambda t: TIER_ORDER[t])
            n_model = sum(1 for leg in combo if leg["basis"] == "model-blend")
            item = {"legs": list(combo), "nLegs": n, "combinedProb": round(p, 4), "combinedAmerican": _dec_to_american(dec),
                    "evPct": round(ev * 100, 2), "stakePct": round(pct, 2), "stake": round(bankroll * pct / 100, 2), "tier": tier}
            if n_model >= 2:
                item["correlationWarning"] = (f"{n_model} of {n} legs are priced from our own model rather than "
                    "independent book consensus -- a single model error could hit all of them at once, so treat this as riskier than the combined EV alone suggests.")
            out.append(item)
    out.sort(key=lambda x: -x["evPct"])
    return out[:top_n]


def build(rows, bankroll, kelly_frac, max_stake_pct):
    """Convenience wrapper: {"singles": [...], "parlays": [...]}."""
    return {"singles": rank_singles(rows), "parlays": build_parlays(rows, bankroll, kelly_frac, max_stake_pct)}
