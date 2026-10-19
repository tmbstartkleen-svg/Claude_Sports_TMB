"""Live, in-game edge tracking (Phase 1 of 3: "find the best bets at all times, even during
games").

build_slate.py's main slate rows are pre-game only: analyze() drops a game the moment it starts,
because a sportsbook moneyline without a live-odds feed is stale and misleading once the game is
underway. Kalshi's own event markets, though, keep trading live through the whole game -- that
price is a continuously updating, free win-probability feed, fetched from the exact same
(already-polled, every 15 minutes, 24/7) Kalshi endpoint build_slate.py already calls for
pre-game prediction-market prices. This module is what turns that into something useful without
inventing a live win-probability model this project doesn't have the data (box scores,
play-by-play) to build honestly:

1. A live snapshot history of its own. history.py deliberately never records in-play lines (its
   job is closing lines for CLV), so live snapshots need a separate small store, kept here.
2. Live "steam": reuses steam.py's own analyze_game() move-detection math (it's generic over any
   chronological {"t","fairHome"} series) against the live snapshot series -- a live Kalshi price
   that just jumped means something happened (injury, run, momentum shift), the same logic as a
   pre-game steam move, just in-play.
3. Live-vs-close swing: how far the market has moved, in probability points, from the price it
   closed at right before kickoff -- a cheap, honest "this game is playing out very differently
   than the market expected" signal, built entirely from numbers already captured elsewhere
   (history.py's closing()) plus the live snapshot itself. No new modeling claimed.

No network calls here: record() only matches games/markets build_slate.py already fetched this
run (live games from scores.py's weekScores + Kalshi markets from kalshi_games()/kalshi_direct())
using the matcher functions build_slate.py already has, passed in rather than imported, to avoid
a circular import.
"""
import json
from datetime import datetime, timedelta, timezone

try:
    import steam as steam_mod
except ImportError:  # pragma: no cover
    steam_mod = None
try:
    from history import game_key
except ImportError:  # pragma: no cover
    from pipeline.history import game_key

MAX_SNAPS = 60
MIN_REPEAT_SEC = 300      # don't grow the store if the price hasn't moved and it's been under 5 min
KEEP_HOURS = 10           # a live-tracked game with no new snapshot in this long is done; drop it
SWING_PP = 5.0            # live price vs pre-game close, in probability points, worth flagging


def _parse(t):
    return datetime.fromisoformat(t.replace("Z", "+00:00"))


def load(path):
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        raise RuntimeError(f"{path} exists but cannot be read ({type(e).__name__}); not overwriting it") from e


def save(path, store):
    with open(path, "w") as f:
        json.dump(store, f, separators=(",", ":"))


def record(store, live_games, pms, match_pm, pm_prob_for, now):
    """live_games: scores.py weekScores entries with state=='in'. pms: this run's prediction-market
    items. match_pm/pm_prob_for: build_slate.py's own matcher functions, passed in so this module
    never imports build_slate. Returns the number of snapshots added."""
    added = 0
    for g in live_games:
        if not g.get("home") or not g.get("away") or not g.get("sport"):
            continue
        try:
            hits = match_pm(g, pms)
        except Exception:  # noqa  a malformed live game must not break the whole run
            hits = []
        if not hits:
            continue
        m = hits[0]
        ph = pm_prob_for(m, g["home"])
        if ph is None:
            continue
        k = game_key(g["sport"], g["away"], g["home"], g.get("start") or "")
        rec = store.setdefault(k, {"sport": g["sport"], "home": g["home"], "away": g["away"], "start": g.get("start"), "snaps": []})
        last = rec["snaps"][-1] if rec["snaps"] else None
        if last and last.get("fairHome") == round(ph, 4) and (now - _parse(last["t"])).total_seconds() < MIN_REPEAT_SEC:
            continue
        rec["snaps"].append({"t": now.isoformat(timespec="seconds"), "fairHome": round(ph, 4),
                             "detail": g.get("detail"), "homeScore": g.get("homeScore"), "awayScore": g.get("awayScore")})
        if len(rec["snaps"]) > MAX_SNAPS:
            rec["snaps"] = rec["snaps"][:1] + rec["snaps"][-(MAX_SNAPS - 1):]
        added += 1
    return added


def prune(store, now):
    for k in list(store):
        snaps = store[k].get("snaps")
        try:
            last_t = _parse(snaps[-1]["t"]) if snaps else None
        except (ValueError, KeyError):
            last_t = None
        if not last_t or now - last_t > timedelta(hours=KEEP_HOURS):
            del store[k]


def analyze(store, closing=None):
    """Returns a list of live-edge dicts, newest-snapshot-first-ish (caller can re-sort), one per
    tracked game that still has at least one snapshot. closing: history.py's closing(hist, now)
    output, keyed the same way (history.game_key), used only to compute the live-vs-close swing
    when that game's pre-game close was captured."""
    closing = closing or {}
    out = []
    for k, g in store.items():
        snaps = g.get("snaps") or []
        if not snaps:
            continue
        last = snaps[-1]
        move = steam_mod.analyze_game(snaps) if steam_mod else None
        row = {"key": k, "sport": g["sport"], "home": g["home"], "away": g["away"], "start": g.get("start"),
               "kalshiHome": last["fairHome"], "detail": last.get("detail"), "homeScore": last.get("homeScore"),
               "awayScore": last.get("awayScore"), "lastSeen": last["t"], "snapshots": len(snaps)}
        if move:
            row["move"] = move
        c = closing.get(k)
        if c and c.get("fairHome") is not None:
            swing = (last["fairHome"] - c["fairHome"]) * 100
            if abs(swing) >= SWING_PP:
                row["closeHome"] = c["fairHome"]
                row["swingPts"] = round(swing, 1)
                row["swingSide"] = "home" if swing > 0 else "away"
        out.append(row)
    return out
