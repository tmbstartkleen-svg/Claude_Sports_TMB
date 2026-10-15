import os, sys, json, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from datetime import date, timedelta
import model as M

tmp = tempfile.mkdtemp(); M.CACHE_DIR = tmp; M.BACKFILL_DAYS = 100
today = date(2026, 10, 15)
def ev(i, d):
    return {"id": f"{d}-{i}", "date": f"{d}T20:00Z", "status": {"type": {"completed": True}},
            "competitions": [{"competitors": [{"homeAway": "home", "team": {"displayName": "H%d" % i}, "score": "2"}, {"homeAway": "away", "team": {"displayName": "A%d" % i}, "score": "1"}]}]}
calls = []
fail_days = set()
def getter(u):
    d = u.split("dates=")[1].split("&")[0]; calls.append(d)
    if d in fail_days: raise OSError("boom")
    iso = f"{d[:4]}-{d[4:6]}-{d[6:]}"
    return {"events": [ev(1, iso), ev(2, iso)]}

r1 = M.fetch_results("nba", today, getter, cache=True); n1 = len(calls)
assert n1 == 101 and len(r1) == 202, (n1, len(r1))              # first run: only the most recent BACKFILL_DAYS
c = json.load(open(f"{tmp}/nba.json")); assert c["through"] == "2026-10-15" and c["from"] == "2026-07-07", c["from"]
calls.clear(); r2 = M.fetch_results("nba", today, getter, cache=True)
assert len(r2) > len(r1) and len(calls) < 110 + 5, len(calls)   # second run: 3 new days + another 100 backwards, not 430
for _ in range(5):
    calls.clear(); r = M.fetch_results("nba", today, getter, cache=True)
assert len(calls) == 3 and len({g["id"] for g in r}) == len(r) and min(g["date"] for g in r) >= str(today - timedelta(days=M.LOOKBACK_DAYS)), (len(calls), min(g["date"] for g in r))
assert len(r) == 2 * (M.LOOKBACK_DAYS + 1), len(r)               # fully covered, then only 3 days a run
print("OK cache backfill")
# a failed day is not marked covered: the next run retries it
tmp2 = tempfile.mkdtemp(); M.CACHE_DIR = tmp2
fail_days.add("20261010")
calls.clear(); M.fetch_results("nba", today, getter, cache=True)
c = json.load(open(f"{tmp2}/nba.json")); assert c["through"] == "2026-10-09", c["through"]
fail_days.clear(); calls.clear(); M.fetch_results("nba", today, getter, cache=True)
assert "20261010" in calls and json.load(open(f"{tmp2}/nba.json"))["through"] == "2026-10-15"
print("OK failed day retried")
# damaged cache is ignored, not trusted
open(f"{tmp2}/nba.json", "w").write("{broken")
assert len(M.fetch_results("nba", today, getter, cache=True)) > 0
print("CACHE TESTS PASS")
