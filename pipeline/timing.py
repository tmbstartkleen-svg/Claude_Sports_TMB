"""Buy-in timing guidance: take this price now, or does it tend to get better later?

Two signals Edge Suite already computes for free, with no new network calls:

1. steam.py's own pre-game line-movement detection for THIS game (row["steam"], attached
   earlier in the pipeline) -- if the market is already moving toward the side we like, that
   price is disappearing; if it's moving the other way, it may still be there, or better,
   later.
2. grade.py's own graded history (record.json's bySport average CLV) -- the realized, evidence
   -based answer to "for edges like this one, has buying early actually beaten waiting for the
   close?" rather than a guess.

This is informational, not a guarantee: both signals describe what has happened, not what will.
When there isn't enough graded history yet, the module says so plainly instead of pretending to
know. No bets are placed; nothing here fetches anything new.
"""
from datetime import datetime

MIN_GRADED_N = 30        # fewer graded picks than this: history isn't a safe source of advice yet
CLV_MEANINGFUL = 0.01    # average CLV (fraction) big enough to call "beats the close" / "loses to the close"
CLOSING_SOON_HOURS = 2.0  # inside this window: "lock it in" regardless of other signals


def _parse(t):
    return datetime.fromisoformat(t.replace("Z", "+00:00"))


def _side_key(r, bet):
    if bet["side"] == r["home"]:
        return "home"
    if bet["side"] == r["away"]:
        return "away"
    return "draw"


def advise(r, bet, summary, now):
    """Returns a timing dict for one flagged bet on game row r, or None if it can't say anything
    (missing/unparseable start time, or the game has already started -- that's an in-play
    question, not a pre-game timing one)."""
    start_s = r.get("start")
    if not start_s:
        return None
    try:
        start = _parse(start_s)
    except ValueError:
        return None
    hours = (start - now).total_seconds() / 3600
    if hours <= 0:
        return None
    if hours <= CLOSING_SOON_HOURS:
        return {"advice": "closing_soon", "hoursToStart": round(hours, 1),
                "reasons": [f"Game starts in {hours:.1f}h -- lines tighten and liquidity dries up close to kickoff."]}
    reasons = []
    advice = None
    side = _side_key(r, bet)
    steam = r.get("steam")
    if steam:
        pts = abs(steam.get("biggestMovePts") or steam.get("totalDriftPts") or 0)
        if steam["side"] == side:
            advice = "buy_now"
            reasons.append(f"The market has already moved {pts:.1f} pts toward this side -- the price you're seeing is likely to get worse, not better.")
        else:
            advice = "wait_ok"
            reasons.append(f"The market has moved {pts:.1f} pts toward the other side -- this price may hold or improve if your view is right.")
    stats = (summary or {}).get("bySport", {}).get(r["sport"]) or {}
    avg_clv, n_clv = stats.get("avgClv"), stats.get("nClv", 0)
    if avg_clv is not None and n_clv >= MIN_GRADED_N:
        if avg_clv >= CLV_MEANINGFUL:
            reasons.append(f"Historically, {r['sport'].upper()} edges we've flagged have beaten the closing line by {avg_clv * 100:.1f}% on average (n={n_clv}) -- waiting has generally cost value.")
            advice = advice or "buy_now"
        elif avg_clv <= -CLV_MEANINGFUL:
            reasons.append(f"Historically, {r['sport'].upper()} edges we've flagged have lost {abs(avg_clv) * 100:.1f}% to the closing line on average (n={n_clv}) -- the price has tended to improve by waiting.")
            advice = advice or "wait_ok"
    elif not steam:
        reasons.append("Not enough graded history yet for this sport to say whether waiting tends to help or hurt.")
    return {"advice": advice or "no_strong_signal", "hoursToStart": round(hours, 1), "reasons": reasons}


def attach(rows, summary, now):
    """Mutates rows in place: each bet in row['bets'] gets bet['timing']. Returns count annotated."""
    n = 0
    for r in rows:
        for b in r.get("bets", []):
            t = advise(r, b, summary, now)
            if t:
                b["timing"] = t
                n += 1
    return n
