"""One-off diagnostic for Actions: which ESPN scoreboard paths exist, and do they carry odds? Writes probe_sports.json."""
import json, sys
from datetime import datetime, timezone, timedelta
sys.path.insert(0, "pipeline")
import build_slate as B
from concurrent.futures import ThreadPoolExecutor
soccer = "eng.2 eng.3 eng.4 eng.fa eng.league_cup sco.1 sco.2 ned.1 ned.2 por.1 bel.1 tur.1 gre.1 rus.1 aut.1 sui.1 den.1 swe.1 nor.1 pol.1 cze.1 cro.1 srb.1 rou.1 hun.1 ukr.1 isr.1 mex.1 bra.1 bra.2 arg.1 col.1 chi.1 uru.1 per.1 ecu.1 par.1 ven.1 bol.1 usa.nwsl usa.open usa.usl.1 uefa.europa uefa.europa.conf concacaf.champions concacaf.leagues.cup conmebol.libertadores conmebol.sudamericana ger.2 esp.2 ita.2 fra.2 esp.copa_del_rey ger.dfb_pokal ita.coppa_italia fra.coupe_de_france aus.1 jpn.1 kor.1 chn.1 sau.1 ind.1 fifa.world fifa.friendly uefa.nations uefa.euroq fifa.cwc fifa.worldq.uefa fifa.worldq.conmebol fifa.worldq.concacaf".split()
other = ["tennis/atp", "tennis/wta", "australian-football/afl", "hockey/mens-college-hockey", "hockey/womens-college-hockey", "baseball/college-baseball", "basketball/womens-college-basketball", "basketball/nba-development",
         "football/ufl", "football/cfl", "lacrosse/pll", "lacrosse/mens-college-lacrosse", "volleyball/mens-college-volleyball", "volleyball/womens-college-volleyball", "softball/college-softball", "rugby/164205", "rugby/267979", "rugby/242041",
         "cricket/8039", "boxing/boxing", "mma/pfl", "mma/bellator", "racing/f1", "golf/pga", "basketball/mens-olympics", "baseball/world-baseball-classic", "baseball/mexican-winter", "baseball/dominican-winter", "baseball/venezuelan-winter", "baseball/puerto-rican-winter", "basketball/fiba", "field-hockey/mens-field-hockey"]
paths = ["soccer/" + s for s in soccer] + other
today = datetime.now(timezone.utc).date()
def one(path):
    best = None
    for off in (0, 1, 2, 3, 4, 5, 6):
        d = f"{(today + timedelta(days=off)):%Y%m%d}"
        try:
            data = B.http_json(f"https://site.api.espn.com/apis/site/v2/sports/{path}/scoreboard?dates={d}")
        except Exception as e:  # noqa
            return path, {"error": repr(e)[:90]}
        evs = data.get("events", []) if isinstance(data, dict) else []
        wo = sum(1 for e in evs if (e.get("competitions") or [{}])[0].get("odds"))
        name = ((data.get("leagues") or [{}])[0].get("name") if isinstance(data, dict) else None)
        r = {"name": name, "events": len(evs), "withOdds": wo, "day": d}
        if best is None or wo > best["withOdds"] or (wo == best["withOdds"] and len(evs) > best["events"]):
            best = r
        if wo:
            break
    return path, best
with ThreadPoolExecutor(max_workers=10) as pool:
    out = dict(pool.map(one, paths))
json.dump(out, open("probe_sports.json", "w"), indent=1)
print(sum(1 for v in out.values() if v.get("withOdds")), "paths with odds of", len(out))
