"""One-off diagnostic for Actions: for each sport, how many scoreboard events exist, how many carry odds, and the first start time. Writes probe_odds.json."""
import json, urllib.request
from datetime import datetime, timezone
import sys; sys.path.insert(0, "pipeline")
import build_slate as B
out = {"checkedAt": datetime.now(timezone.utc).isoformat(timespec="seconds")}
for sp, (_, path) in B.SPORTS.items():
    try:
        d = B.http_json(f"https://site.api.espn.com/apis/site/v2/sports/{path}/scoreboard")
        evs = d.get("events", []) if isinstance(d, dict) else None
        if evs is None:
            out[sp] = {"error": f"non-dict {type(d).__name__}"}
            continue
        wo = [e for e in evs if (e.get("competitions") or [{}])[0].get("odds")]
        out[sp] = {"events": len(evs), "withOdds": len(wo), "states": sorted({(e.get("status") or {}).get("type", {}).get("state", "?") for e in evs}),
                   "firstStart": min([e.get("date", "") for e in evs], default=None), "leagues": [l.get("name") for l in d.get("leagues", [])][:1]}
    except Exception as e:  # noqa
        out[sp] = {"error": repr(e)[:160]}
json.dump(out, open("probe_odds.json", "w"), indent=1)
print(json.dumps(out))
