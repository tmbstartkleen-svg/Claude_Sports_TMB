"""One-off diagnostic run in GitHub Actions (the sandbox cannot reach these sites): tries URL variants and records the HTTP status of each in probe.json."""
import json, urllib.request, urllib.error
from datetime import date, timedelta
B = "https://site.api.espn.com/apis/site/v2/sports/"
t = date.today()
def f(d): return d.strftime("%Y%m%d")
variants = {}
for name, path in (("nba", "basketball/nba"), ("nfl", "football/nfl"), ("mlb", "baseball/mlb")):
    y = t - timedelta(days=1)
    variants[f"{name}_day"] = f"{B}{path}/scoreboard?dates={f(y)}"
    variants[f"{name}_range14"] = f"{B}{path}/scoreboard?dates={f(t-timedelta(days=14))}-{f(t)}"
    variants[f"{name}_range14_limit1000"] = f"{B}{path}/scoreboard?dates={f(t-timedelta(days=14))}-{f(t)}&limit=1000"
    variants[f"{name}_range14_limit300"] = f"{B}{path}/scoreboard?dates={f(t-timedelta(days=14))}-{f(t)}&limit=300"
    variants[f"{name}_range7"] = f"{B}{path}/scoreboard?dates={f(t-timedelta(days=7))}-{f(t)}"
    variants[f"{name}_old_range14_limit1000"] = f"{B}{path}/scoreboard?dates=20250811-20250824&limit=1000"
    variants[f"{name}_old_range14"] = f"{B}{path}/scoreboard?dates=20250811-20250824"
    variants[f"{name}_schedule"] = f"{B}{path}/scoreboard?dates={f(y)}&limit=100"
variants["nba_scoreboard_collector"] = "https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json"
variants["nba_espn_teams"] = f"{B}basketball/nba/teams"
out = {}
for k, u in variants.items():
    try:
        req = urllib.request.Request(u, headers={"User-Agent": "edge-suite-slate/1.0", "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=25) as r:
            d = json.load(r)
            ev = d.get("events") if isinstance(d, dict) else None
            out[k] = {"status": r.status, "events": len(ev) if ev is not None else None, "completed": sum(1 for e in (ev or []) if (e.get("status") or {}).get("type", {}).get("completed")), "url": u}
    except urllib.error.HTTPError as e:
        out[k] = {"status": e.code, "body": e.read()[:200].decode("utf8", "replace"), "url": u}
    except Exception as e:  # noqa
        out[k] = {"error": repr(e)[:200], "url": u}
json.dump(out, open("probe.json", "w"), indent=1)
print(json.dumps({k: (v.get("status"), v.get("events")) for k, v in out.items()}))
