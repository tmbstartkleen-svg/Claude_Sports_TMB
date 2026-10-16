import os, sys, tempfile, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from datetime import datetime, timedelta, timezone
import notify as N

now = datetime(2026, 10, 12, 12, 0, tzinfo=timezone.utc)
row = {"sport": "nba", "home": "H", "away": "A", "key": "nba|A|H|2026-10-12T23:00", "nBooks": 4, "arb": True, "arbRoiPct": 1.2,
       "best": {"home": {"american": 105, "book": "X"}, "away": {"american": 100, "book": "Y"}},
       "crossArbs": [{"roiPct": 2.5, "pmSource": "kalshi", "bookSide": "away", "american": 140, "book": "X", "pmSide": "home", "pmPrice": 0.55}, {"roiPct": 0.2, "pmSource": "polymarket", "bookSide": "home", "american": 100, "book": "Y", "pmSide": "away", "pmPrice": 0.5}],
       "middles": [{"kind": "spread", "legA": "H -2 @ X", "legB": "A +3 @ Y", "gap": 1.0, "pMiddle": 0.07, "outerPct": -4.3, "middlePct": 90.0, "evPct": 2.1}, {"kind": "total", "legA": "o", "legB": "u", "gap": 1.0, "pMiddle": 0.03, "outerPct": -4.5, "middlePct": 80, "evPct": 0.4}],
       "bets": [{"side": "A", "american": 150, "book": "Z", "evPct": 7.5}, {"side": "H", "american": -110, "book": "Z", "evPct": 2.0}]}
a = N.build_alerts([row])
kinds = [x[1].split("|")[0] for x in a]
assert kinds == ["arb", "xarb", "mid", "edge"], kinds                   # thresholds drop the 0.2% cross arb, 0.4% middle and 2% edge
assert N.build_alerts([dict(row, nBooks=2)])[-1][1].startswith("mid"), "edge alert needs 3+ books"
print("OK thresholds/order")

# ---- steam: only the fast "steam" kind alerts, never the slower "drift"; below-threshold moves are silent
steamed_row = {**row, "arb": False, "crossArbs": [], "middles": [], "bets": [], "nBooks": 1,
               "steam": {"kind": "steam", "side": "home", "biggestMovePts": 6.1, "biggestMoveAt": "2026-10-12T20:00:00", "totalDriftPts": 6.1, "snapshots": 4}}
a2 = N.build_alerts([steamed_row])
assert len(a2) == 1 and a2[0][1].startswith("steam|") and "STEAM 6.1pts toward H" in a2[0][2], a2
drift_row = {**steamed_row, "steam": {**steamed_row["steam"], "kind": "drift", "totalDriftPts": 8.0}}
assert N.build_alerts([drift_row]) == [], "drift never alerts, only fast steam moves"
small_row = {**steamed_row, "steam": {**steamed_row["steam"], "biggestMovePts": 2.0}}
assert N.build_alerts([small_row]) == [], "below ALERT_MIN_STEAM: silent"
print("OK steam alerts")

sent = {}
fresh = N.filter_new(a, sent, now)
assert len(fresh) == 4 and N.filter_new(a, sent, now + timedelta(hours=1)) == [], "no repeat within 6h"
assert len(N.filter_new(a, sent, now + timedelta(hours=7))) == 4, "resend after 6h"
old = {"x": (now - timedelta(days=3)).isoformat()}
N.filter_new([], old, now); assert old == {}, "stale ids pruned"
print("OK dedupe")

posted = []
class R:  # fake urlopen
    pass
def fake(req, timeout=0): posted.append((req.full_url, req.data.decode(), dict(req.header_items())))
tmp = tempfile.mkdtemp(); p = f"{tmp}/alerts.json"
assert N.run([row], now, p, "topicXYZ", fake) == (4, 4, "sent")
url, body, hdr = posted[0]
assert url == "https://ntfy.sh/topicXYZ" and "ARB +1.2%" in body and "Confirm live prices" in body, body
assert all(ord(c) < 128 for c in "".join(hdr.keys()) + "".join(hdr.values())), "headers must be ASCII"
assert N.run([row], now + timedelta(minutes=30), p, "topicXYZ", fake) == (4, 0, "nothing new") and len(posted) == 1
n, s, st = N.run([row], now, p, "", fake); assert (s, st) == (0, "no NTFY_TOPIC set; alerts not sent") and len(posted) == 1
def boom(req, timeout=0): raise OSError("network down")
q = f"{tmp}/a2.json"
n, s, st = N.run([row], now, q, "topic12345", boom); assert s == 0 and st.startswith("failed") and not os.path.exists(q), "failed send must not mark alerts as sent"
many = [dict(row, key=f"k{i}", arbRoiPct=1 + i) for i in range(12)]
posted.clear(); N.run(many, now, f"{tmp}/a3.json", "topic12345", fake); assert "more on the Slate tab" in posted[0][1] and posted[0][1].count("\n") <= N.MAX_LINES + 2
# reviewer finding 7: secret topic must never leak through error text, and bad topics are rejected
n_, s_, st_ = N.run([row], now, f"{tmp}/a4.json", "topic12345\n", boom)
assert "topic12345" not in st_ and st_ == "failed: OSError", st_
assert N.run([row], now, f"{tmp}/a5.json", "bad topic!", fake)[1] == 0 and "not valid" in N.run([row], now, f"{tmp}/a5.json", "bad topic!", fake)[2]
posted.clear(); N.run([row], now, f"{tmp}/a6.json", "topic12345\n", fake); assert posted[0][0] == "https://ntfy.sh/topic12345", "trailing newline stripped"
print("OK delivery"); print("NOTIFY TESTS PASS")
