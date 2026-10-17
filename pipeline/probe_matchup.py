"""One-off diagnostic run in GitHub Actions (the sandbox cannot reach ESPN): checks the shape of the
free endpoints a team/matchup panel would need - team record+form, team schedule (for head-to-head),
and the game summary endpoint (which sometimes carries a head-to-head/series block directly) - before
any production code is written against them. Results go to probe_matchup.json.
"""
import json, urllib.request, urllib.error
B = "https://site.api.espn.com/apis/site/v2/sports/"


def get(u):
    req = urllib.request.Request(u, headers={"User-Agent": "edge-suite-slate/1.0", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=25) as r:
        return r.status, json.load(r)


out = {}
for name, path in (("nfl", "football/nfl"), ("nba", "basketball/nba"), ("epl", "soccer/eng.1")):
    try:
        st, sb = get(f"{B}{path}/scoreboard")
        ev = (sb.get("events") or [None])[0]
        if not ev:
            out[name] = {"error": "no events on scoreboard right now"}
            continue
        comp = ev["competitions"][0]
        competitors = comp["competitors"]
        home = next(c for c in competitors if c.get("homeAway") == "home")
        away = next(c for c in competitors if c.get("homeAway") == "away")
        tid = home["team"]["id"]
        eid = ev["id"]
        out[name] = {"eventId": eid, "homeTeamId": tid, "homeName": home["team"].get("displayName"),
                     "scoreboard_competitor_keys": sorted(home.keys()), "team_block_keys": sorted(home["team"].keys()),
                     "records_sample": home.get("records")}

        # team detail endpoint
        try:
            st2, td = get(f"{B}{path}/teams/{tid}")
            team = td.get("team", {})
            out[name]["team_detail_keys"] = sorted(team.keys())
            out[name]["team_detail_record"] = team.get("record")
            out[name]["team_detail_sample"] = {k: team.get(k) for k in ("displayName", "location", "nickname", "color", "logos") if k in team}
        except Exception as e:  # noqa
            out[name]["team_detail_error"] = repr(e)[:200]

        # team schedule endpoint (for recent form + head-to-head by filtering opponent)
        try:
            st3, sched = get(f"{B}{path}/teams/{tid}/schedule")
            events = sched.get("events", [])
            out[name]["schedule_count"] = len(events)
            out[name]["schedule_sample_keys"] = sorted(events[0].keys()) if events else []
            if events:
                e0 = events[0]
                out[name]["schedule_event_sample"] = {k: e0.get(k) for k in ("id", "date", "name", "competitions") if k in e0}
        except Exception as e:  # noqa
            out[name]["schedule_error"] = repr(e)[:200]

        # game summary endpoint (sometimes has head-to-head/series block)
        try:
            st4, summ = get(f"{B}{path}/summary?event={eid}")
            out[name]["summary_top_keys"] = sorted(summ.keys())
            for k in ("headToHeadGames", "series", "pickcenter", "winprobability", "boxscore"):
                if k in summ:
                    v = summ[k]
                    out[name][f"summary_{k}_type"] = type(v).__name__
                    out[name][f"summary_{k}_sample"] = (v[:1] if isinstance(v, list) else v) if not isinstance(v, (list, dict)) or len(str(v)) < 2000 else "too large, present"
        except Exception as e:  # noqa
            out[name]["summary_error"] = repr(e)[:200]

    except Exception as e:  # noqa
        out[name] = {"error": repr(e)[:300]}

json.dump(out, open("probe_matchup.json", "w"), indent=1)
print(json.dumps({k: list(v.keys()) for k, v in out.items()}, indent=1))
