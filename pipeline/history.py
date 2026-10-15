"""Line snapshots -> closing lines.

Every run stores the market's consensus fair price and best price for each upcoming game. Once a game has started,
the last snapshot taken BEFORE the start is its "closing line". Runs are scheduled every ~30 minutes on game days,
so the captured close can be up to ~30 minutes early (longer if a run failed). It is the last line we saw, not
necessarily the final line.
"""
import json, os
from datetime import datetime, timedelta, timezone

MAX_SNAPS = 80
MIN_REPEAT_MIN = 60
KEEP_DAYS = 5


try:
    from names import canon
except ImportError:  # pragma: no cover
    from pipeline.names import canon


def game_key(sport, away, home, start):
    return f"{sport}|{canon(away)}|{canon(home)}|{(start or '')[:16]}"


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


def save(path, hist):
    with open(path, "w") as f:
        json.dump(hist, f, separators=(",", ":"))


def record(hist, rows, now):
    """Append a pre-game snapshot for each row. Returns number of snapshots added."""
    added = 0
    for r in rows:
        if not r.get("start"):
            continue
        try:
            start = _parse(r["start"])
        except ValueError:
            continue
        if now >= start:
            continue  # never record in-play lines as a close
        k = game_key(r["sport"], r["away"], r["home"], r["start"])
        g = hist.setdefault(k, {"sport": r["sport"], "home": r["home"], "away": r["away"], "start": r["start"], "snaps": []})
        last = g["snaps"][-1] if g["snaps"] else None
        if last and last["fairHome"] == r["fair"]["home"] and last["bestHome"] == r["best"]["home"]["american"] \
                and last["bestAway"] == r["best"]["away"]["american"] and last["nBooks"] == r["nBooks"] \
                and (now - _parse(last["t"])).total_seconds() < MIN_REPEAT_MIN * 60:
            continue  # nothing moved: do not grow the file and churn the repo
        g["snaps"].append({"t": now.isoformat(timespec="seconds"), "fairHome": r["fair"]["home"], "fairAway": r["fair"]["away"],
                           "bestHome": r["best"]["home"]["american"], "bestAway": r["best"]["away"]["american"], "nBooks": r["nBooks"],
                           **({"fairDraw": r["fair"]["draw"]} if "draw" in r["fair"] else {})})
        if len(g["snaps"]) > MAX_SNAPS:  # thin the middle, keep first and the most recent
            g["snaps"] = g["snaps"][:1] + g["snaps"][-(MAX_SNAPS - 1):]
        added += 1
    return added


def prune(hist, now):
    for k in list(hist):
        try:
            if now - _parse(hist[k]["start"]) > timedelta(days=KEEP_DAYS):
                del hist[k]
        except (ValueError, KeyError):
            del hist[k]


def closing(hist, now):
    """{key: closing info} for games that have started."""
    out = {}
    for k, g in hist.items():
        try:
            start = _parse(g["start"])
        except ValueError:
            continue
        if now < start:
            continue
        pre = [s for s in g["snaps"] if _parse(s["t"]) <= start]
        if not pre:
            continue
        last = pre[-1]
        out[k] = {"sport": g["sport"], "home": g["home"], "away": g["away"], "start": g["start"], "capturedAt": last["t"],
                  "minutesBeforeStart": round((start - _parse(last["t"])).total_seconds() / 60), "fairHome": last["fairHome"],
                  "fairAway": last["fairAway"], "bestHome": last["bestHome"], "bestAway": last["bestAway"], "nBooks": last["nBooks"],
                  "firstFairHome": pre[0]["fairHome"], "snaps": len(pre),
                  **({"fairDraw": last["fairDraw"]} if "fairDraw" in last else {})}
    return out
