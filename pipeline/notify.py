"""Push alerts for the things that vanish in minutes: arbitrage, prediction-market arbs, middles, and large edges.

Delivery is ntfy.sh (free, no account): set NTFY_TOPIC to a long random string, subscribe to the same topic in the ntfy app.
On public ntfy.sh anyone who knows the topic name can read it, so treat the name like a password (keep it in a GitHub secret).
Read-only information. Prices move fast: every alert says to confirm before acting.
"""
import json, os, re, urllib.parse, urllib.request
from datetime import datetime, timedelta, timezone

MIN_ARB_ROI = float(os.environ.get("ALERT_MIN_ARB", 0.5))        # percent
MIN_CROSS_ROI = float(os.environ.get("ALERT_MIN_CROSS", 1.0))    # percent, after estimated fees and slippage
MIN_MIDDLE_EV = float(os.environ.get("ALERT_MIN_MIDDLE", 2.0))   # percent expected value
MIN_EDGE_EV = float(os.environ.get("ALERT_MIN_EDGE", 6.0))       # percent, needs 3+ books
RESEND_HOURS = 6
MAX_LINES = 8


def build_alerts(rows):
    """[(value, id, text)] sorted best first."""
    out = []
    for r in rows:
        game = f"{r['away']} @ {r['home']} ({r['sport'].upper()})"
        gk = r.get("key") or game
        if r.get("arb") and r.get("arbRoiPct", 0) >= MIN_ARB_ROI:
            legs = ", ".join(f"{k} {v['american']:+g} {v['book']}" for k, v in r["best"].items())
            out.append((r["arbRoiPct"] + 100, f"arb|{gk}", f"ARB +{r['arbRoiPct']}%: {game}: {legs}"))
        for a in r.get("crossArbs", []) or []:
            if a["roiPct"] >= MIN_CROSS_ROI and not a.get("suspect"):
                out.append((a["roiPct"] + 90, f"xarb|{gk}|{a['pmSource']}|{a['bookSide']}",
                            f"BOOK vs {a['pmSource'].upper()} +{a['roiPct']}% (est.): {game}: {a['bookSide']} {a['american']:+g} @ {a['book']} + {a['pmSide']} at {a['pmPrice']}"))
        for m in r.get("middles", []) or []:
            if m["evPct"] >= MIN_MIDDLE_EV:
                out.append((m["evPct"] + 50, f"mid|{gk}|{m['kind']}|{m['legA']}",
                            f"MIDDLE EV +{m['evPct']}% (gap {m['gap']}, hit {m['pMiddle']*100:.0f}%, outer {m['outerPct']}%): {game}: {m['legA']} / {m['legB']}"))
        if r.get("nBooks", 0) >= 3:
            for b in r.get("bets", []):
                if b["evPct"] >= MIN_EDGE_EV:
                    out.append((b["evPct"], f"edge|{gk}|{b['side']}", f"EDGE +{b['evPct']}% EV: {game}: {b['side']} {b['american']:+g} @ {b['book']} (may be a stale line, check first)"))
    out.sort(key=lambda x: -x[0])
    return out


def filter_new(alerts, sent, now):
    """Drop alerts already sent within RESEND_HOURS. Updates `sent` in place; returns the fresh ones."""
    fresh = []
    for v, aid, text in alerts:
        t = sent.get(aid)
        if t and now - datetime.fromisoformat(t) < timedelta(hours=RESEND_HOURS):
            continue
        sent[aid] = now.isoformat(timespec="seconds")
        fresh.append((v, aid, text))
    for k in list(sent):
        if now - datetime.fromisoformat(sent[k]) > timedelta(days=2):
            del sent[k]
    return fresh


def send(topic, lines, post=None):
    body = "\n".join(lines[:MAX_LINES]) + ("\n+%d more on the Slate tab" % (len(lines) - MAX_LINES) if len(lines) > MAX_LINES else "")
    body += "\nConfirm live prices before acting."
    req = urllib.request.Request("https://ntfy.sh/" + urllib.parse.quote(topic, safe=""), data=body.encode("utf-8"),
                                 headers={"Title": "Edge Suite alert", "Priority": "high", "Tags": "chart_with_upwards_trend"})
    (post or urllib.request.urlopen)(req, timeout=15)


def run(rows, now, path=None, topic=None, post=None):
    """Returns (n_alerts_found, n_sent, status string). Never raises: alerts must not break the data build."""
    path = path or os.environ.get("ALERTS_PATH", "alerts.json")
    topic = (topic if topic is not None else os.environ.get("NTFY_TOPIC", "")).strip()
    if topic and not re.fullmatch(r"[A-Za-z0-9_-]{8,}", topic):
        return 0, 0, "NTFY_TOPIC is not valid (use 8+ letters, digits, - or _); alerts not sent"
    try:
        try:
            with open(path) as f:
                sent = json.load(f)
        except (OSError, ValueError):
            sent = {}
        found = build_alerts(rows)
        if not topic:
            return len(found), 0, "no NTFY_TOPIC set; alerts not sent"
        fresh = filter_new(found, sent, now)
        if fresh:
            send(topic, [t for _, _, t in fresh], post)
        with open(path, "w") as f:
            json.dump(sent, f, separators=(",", ":"))
        return len(found), len(fresh), "sent" if fresh else "nothing new"
    except Exception as e:  # noqa
        return 0, 0, "failed: " + type(e).__name__   # never include exception text: it can contain the secret topic
