"""Pick grading: record every edge bet the pipeline flags, settle it from final scores, measure it.

picks.json   : one entry per (game, side), saved the FIRST time the pipeline flags it (first price seen, not the best later one).
record.json  : summary the Track Record tab reads (overall + by sport + by basis), with an honest significance note.

Nothing here places bets. Settlement uses ESPN's free scoreboard; CLV uses closing lines captured in history.json.
"""
import json, math, re
from datetime import datetime, timedelta, timezone

MAX_PICKS = 6000
MAX_CLOSE_AGE_MIN = 90
VOID_AFTER_DAYS = 4


def am_to_dec(a):
    a = float(a)
    if abs(a) < 100:
        return None
    return 1 + a / 100 if a > 0 else 1 + 100 / abs(a)


def _parse(t):
    return datetime.fromisoformat(t.replace("Z", "+00:00"))


try:
    from names import canon, same as same_team
except ImportError:  # pragma: no cover
    from pipeline.names import canon, same as same_team

MAX_START_GAP_H = 6   # a final only settles a pick for the same game: same teams AND a start time within this window


def pick_id(sport, away, home, start, side):
    return f"{sport}|{canon(away)}|{canon(home)}|{(start or '')[:10]}|{canon(side) if side not in ('home', 'away', 'draw') else side}"


def load(path):
    """{} if the file does not exist yet. A file that exists but cannot be parsed raises: never overwrite a damaged record with an empty one."""
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        raise RuntimeError(f"{path} exists but cannot be read ({type(e).__name__}); not overwriting it") from e


def save(path, obj):
    with open(path, "w") as f:
        json.dump(obj, f, separators=(",", ":"))


def record_picks(picks, rows, now):
    """Add each pre-game edge bet once. Returns number added."""
    added = 0
    for r in rows:
        if not r.get("start"):
            continue
        try:
            if now >= _parse(r["start"]):
                continue
        except ValueError:
            continue
        for b in r.get("bets", []):
            pid = pick_id(r["sport"], r["away"], r["home"], r["start"], b["side"])
            if pid in picks:
                continue
            if b["side"] == r["home"]:
                side = "home"
            elif b["side"] == r["away"]:
                side = "away"
            else:
                side = "draw"
            picks[pid] = {"sport": r["sport"], "home": r["home"], "away": r["away"], "start": r["start"], "side": side,
                          "team": b["side"], "book": b["book"], "american": b["american"], "fairAtPick": b["fair"],
                          "evPct": b["evPct"], "stake": b["stake"], "basis": b.get("basis", "consensus"),
                          "threeWay": bool(r.get("threeWay")), "seen": now.isoformat(timespec="seconds"), "key": r.get("key"), "res": None}
            added += 1
    return added


def result_of(p, final):
    """final: {'hs':int,'as':int}. Returns 'W','L' or 'P' for the pick."""
    hs, as_ = final["hs"], final["as"]
    out = "home" if hs > as_ else "away" if as_ > hs else "draw"
    if out == "draw" and p["side"] != "draw":
        # two-way markets (ties are rare; most books refund) vs three-way (a draw loses non-draw bets)
        return "L" if p.get("threeWay") else "P"
    return "W" if out == p["side"] else "L"


def settle(picks, finals_by_sport, now):
    """finals_by_sport: {sport: [{'home','away','hs','as','start'}]}. Returns count settled."""
    n = 0
    for p in picks.values():
        if p["res"] is not None:
            continue
        try:
            start = _parse(p["start"])
        except ValueError:
            p["res"] = "V"
            continue
        if now < start:
            continue
        hit = None
        for f in finals_by_sport.get(p["sport"], []):
            if not (same_team(f["home"], p["home"]) and same_team(f["away"], p["away"])):
                continue
            if f.get("start"):
                try:
                    if abs((_parse(f["start"]) - start).total_seconds()) > MAX_START_GAP_H * 3600:
                        continue  # a different game of the same series
                except ValueError:
                    continue
            hit = f
            break
        if hit:
            p["res"] = result_of(p, hit)
            p["score"] = f"{hit['as']}-{hit['hs']}"
            n += 1
        elif now - start > timedelta(days=VOID_AFTER_DAYS):
            p["res"] = "V"  # never found a final score; excluded from stats
    return n


def attach_clv(picks, closing):
    """CLV = price you'd have got x closing fair probability - 1. Only set once, from the last pre-game snapshot.

    The closing "fair" price is already devigged (build_slate.py's devig_shin), which works fine on a single
    book's own two-sided quote -- it just isn't a cross-market consensus. In practice this pipeline's free
    data sources cover most games with exactly one book, so requiring nBooks>=2 here (as an earlier version
    did) silently refused CLV for nearly every pick -- correct in principle, useless in practice. We now accept
    any closing line that actually exists (nBooks>=1) and record nBooks on the pick so single- vs multi-book
    CLV can be told apart later if that distinction turns out to matter."""
    n = 0
    for p in picks.values():
        if "clv" in p or not p.get("key"):
            continue
        c = closing.get(p["key"])
        if not c:
            continue
        if c.get("minutesBeforeStart", 0) > MAX_CLOSE_AGE_MIN or c.get("nBooks", 0) < 1:
            continue  # stale, or no closing line was ever captured
        fair = {"home": c.get("fairHome"), "away": c.get("fairAway"), "draw": c.get("fairDraw")}.get(p["side"])
        d = am_to_dec(p["american"])
        if fair and d:
            p["clv"] = round(d * fair - 1, 4)
            p["closeFair"] = round(fair, 4)
            p["clvNBooks"] = c.get("nBooks")
            n += 1
    return n


def pnl(p):
    d = am_to_dec(p["american"])
    if not d or p["res"] in (None, "V"):
        return None
    return p["stake"] * (d - 1) if p["res"] == "W" else -p["stake"] if p["res"] == "L" else 0.0


def summarize(picks):
    def agg(items):
        s = [p for p in items if p["res"] in ("W", "L", "P")]
        wl = [p for p in s if p["res"] in ("W", "L")]
        staked = sum(p["stake"] for p in s)
        total = sum(pnl(p) for p in s)
        # per-unit returns (flat 1 unit) for a standard error on ROI
        rets = []
        for p in wl:
            d = am_to_dec(p["american"])
            rets.append(d - 1 if p["res"] == "W" else -1.0)
        n = len(rets)
        mean = sum(rets) / n if n else 0.0
        sd = math.sqrt(sum((x - mean) ** 2 for x in rets) / (n - 1)) if n > 1 else 0.0
        se = sd / math.sqrt(n) if n > 1 else None
        clvs = [p["clv"] for p in items if "clv" in p]
        brier = sum((p["fairAtPick"] - (1 if p["res"] == "W" else 0)) ** 2 for p in wl) / n if n else None
        exp_wins = sum(p["fairAtPick"] for p in wl)
        return {"n": len(s), "open": sum(1 for p in items if p["res"] is None), "staked": round(staked, 2), "pnl": round(total, 2),
                "roi": round(total / staked, 4) if staked else None, "flatRoi": round(mean, 4) if n else None,
                "flatRoiSE": round(se, 4) if se is not None else None, "wins": sum(1 for p in wl if p["res"] == "W"),
                "expectedWins": round(exp_wins, 1), "brier": round(brier, 4) if brier is not None else None,
                "avgClv": round(sum(clvs) / len(clvs), 4) if clvs else None, "nClv": len(clvs)}
    ps = list(picks.values())
    out = {"overall": agg(ps), "bySport": {}, "byBasis": {}}
    for k in sorted({p["sport"] for p in ps}):
        out["bySport"][k] = agg([p for p in ps if p["sport"] == k])
    for k in sorted({p["basis"] for p in ps}):
        out["byBasis"][k] = agg([p for p in ps if p["basis"] == k])
    n = out["overall"]["n"]
    out["note"] = ("Fewer than 100 settled picks: results are mostly luck either way. Look at average CLV first; it settles faster than ROI."
                   if n < 100 else "Judge ROI against its standard error (flatRoiSE): a result inside two standard errors of zero is not evidence of an edge.")
    out["recent"] = sorted([{k: p[k] for k in ("sport", "home", "away", "start", "team", "book", "american", "stake", "res", "clv", "score") if k in p}
                            for p in ps if p["res"] in ("W", "L", "P")], key=lambda x: x["start"], reverse=True)[:40]
    out["timeline"] = _timeline(ps)
    return out


MAX_TIMELINE = 300


def _timeline(ps):
    """Oldest-first running P&L and CLV, for the Track Record chart. Flat units (not $) so it
    reads the same regardless of stake sizing; cumPnl is in units of 1 (i.e. flat-staked P&L),
    cumAvgClv is the running mean of every CLV seen so far (independent of pnl/settlement)."""
    settled = sorted([p for p in ps if p["res"] in ("W", "L", "P")], key=lambda p: p["start"])
    if len(settled) > MAX_TIMELINE:
        settled = settled[-MAX_TIMELINE:]
    out, cum, clv_sum, clv_n = [], 0.0, 0.0, 0
    for p in settled:
        d = am_to_dec(p["american"])
        unit_pnl = (d - 1 if p["res"] == "W" else -1.0 if p["res"] == "L" else 0.0) if d else 0.0
        cum += unit_pnl
        if "clv" in p:
            clv_sum += p["clv"]
            clv_n += 1
        out.append({"date": p["start"][:10], "cumPnl": round(cum, 3),
                     "cumAvgClv": round(clv_sum / clv_n, 4) if clv_n else None})
    return out


def prune(picks):
    if len(picks) > MAX_PICKS:
        keep = sorted(picks.items(), key=lambda kv: kv[1]["start"], reverse=True)[:MAX_PICKS]
        picks.clear()
        picks.update(dict(keep))


def fetch_finals(sport, espn_path, dates, http_json):
    """Final scores from ESPN's scoreboard for a list of YYYYMMDD dates."""
    out = []
    for d in dates:
        try:
            data = http_json(f"https://site.api.espn.com/apis/site/v2/sports/{espn_path}/scoreboard?dates={d}")
        except Exception:
            continue
        for ev in data.get("events", []):
            comp = (ev.get("competitions") or [{}])[0]
            if not (comp.get("status") or ev.get("status") or {}).get("type", {}).get("completed"):
                continue
            h = a = None
            for i, c in enumerate(comp.get("competitors", [])):
                nm = (c.get("team") or {}).get("displayName") or (c.get("athlete") or {}).get("displayName")
                ha = c.get("homeAway") or ("home" if i == 0 else "away")
                try:
                    sc = int(float(c.get("score")))
                except (TypeError, ValueError):
                    sc = None
                if ha == "home":
                    h = (nm, sc)
                else:
                    a = (nm, sc)
            if h and a and h[1] is not None and a[1] is not None:
                out.append({"home": h[0], "away": a[0], "hs": h[1], "as": a[1], "start": ev.get("date")})
    return out
