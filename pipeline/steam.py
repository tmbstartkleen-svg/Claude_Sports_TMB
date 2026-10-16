"""Steam / line-velocity detection from our own closing-line snapshot history.

history.py already records the market's no-vig fair price for every game we track, roughly
every 30 minutes, purely so Edge Suite can compute closing-line value later. That same time
series is a second, free signal almost nobody retail-facing gives away: most "sharp money"
tools (Action Network, VSiN, the public-betting-percentage trackers) sell a sportsbook's own
bet-count/handle split, which costs real money to license and which we don't have and won't
fake. What we DO have, for free, from data we are already collecting for another purpose, is
how fast and how far the price itself moved before kickoff.

A big jump between two consecutive snapshots ("steam") usually means a book got hit hard
enough on one side that it had to reprice immediately -- the classic signal pro bettors chase,
whether the money behind it was sharp or just unusually large. A smaller move sustained across
many snapshots ("drift") is a slower-moving signal: the market quietly deciding one side is
more likely as more information (injury news, weather, lineup confirmations) comes in.

This module only reads a game's own historical snapshots that build_slate.py already loaded;
it makes no network calls of its own, so it is fully deterministic and unit-testable offline.
"""
from datetime import datetime

STEAM_PP = 4.0       # fair-probability swing (percentage points) within ONE snapshot gap that counts as steam
BIG_DRIFT_PP = 7.0   # total drift from the first snapshot to now that's worth flagging even with no single jump
MIN_SNAPS = 2        # need at least this many pre-game snapshots to say anything at all


def _parse(t):
    return datetime.fromisoformat(t.replace("Z", "+00:00"))


def analyze_game(snaps):
    """snaps: chronological list of {"t","fairHome",...}, pre-game only (caller filters).
    Returns None if there isn't enough history to say anything, else a dict describing the move,
    expressed as home-side probability points (positive = toward home, negative = toward away)."""
    pts = [s for s in snaps if s.get("fairHome") is not None]
    if len(pts) < MIN_SNAPS:
        return None
    biggest, biggest_at = 0.0, None
    for a, b in zip(pts, pts[1:]):
        d = (b["fairHome"] - a["fairHome"]) * 100
        if abs(d) > abs(biggest):
            biggest, biggest_at = d, b["t"]
    total = (pts[-1]["fairHome"] - pts[0]["fairHome"]) * 100
    is_steam = abs(biggest) >= STEAM_PP
    is_drift = abs(total) >= BIG_DRIFT_PP
    if not is_steam and not is_drift:
        return None
    lead = biggest if is_steam else total
    return {
        "kind": "steam" if is_steam else "drift",
        "side": "home" if lead > 0 else "away",
        "biggestMovePts": round(biggest, 1),
        "biggestMoveAt": biggest_at,
        "totalDriftPts": round(total, 1),
        "snapshots": len(pts),
        "firstSeen": pts[0]["t"],
        "lastSeen": pts[-1]["t"],
    }


def attach(rows, hist, now):
    """Mutates rows in place, adding row["steam"] where a game (already carrying row["key"] from
    history.game_key) has a meaningful pre-game move in its own snapshot history. Pre-game only:
    once a game has started this is the closing-line/CLV story, which grade.py already owns.
    Returns the number of rows flagged."""
    n = 0
    for r in rows:
        k, start_s = r.get("key"), r.get("start")
        if not k or not start_s:
            continue
        try:
            start = _parse(start_s)
        except ValueError:
            continue
        if now >= start:
            continue
        g = hist.get(k)
        if not g:
            continue
        pre = [s for s in g.get("snaps", []) if _parse(s["t"]) <= now]
        res = analyze_game(pre)
        if res:
            r["steam"] = res
            n += 1
    return n
