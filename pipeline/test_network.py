import os, sys, json, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from datetime import datetime, timedelta, timezone
import network as N, spawn as S

now = datetime(2026, 10, 14, 12, 0, tzinfo=timezone.utc)
# path digging, list flattening
d = {"a": {"b": [{"c": 1}, {"c": 2}]}, "dates": [{"games": [{"x": 1}, {"x": 2}]}, {"games": [{"x": 3}]}]}
assert N.dig(d, "a.b[].c") == [1, 2] and N.dig(d, "dates[].games[].x") == [1, 2, 3] and N.first(d, "a.zzz") is None
print("OK dig")

mlb = {"dates": [{"games": [{"gameDate": "2026-10-14T23:05Z", "teams": {"home": {"team": {"name": "Red Sox"}, "probablePitcher": {"fullName": "Ace Arm"}}, "away": {"team": {"name": "Yankees"}}}}]}]}
spec = {"id": "mlb_probables", "sport": "mlb", "kind": "probables", "url": "https://x/s?date={date}", "dayOffsets": [0, 1], "items": "dates[].games[]",
        "required": ["home", "away"], "fields": {"home": "teams.home.team.name", "away": "teams.away.team.name", "homePitcher": "teams.home.probablePitcher.fullName", "awayPitcher": "teams.away.probablePitcher.fullName"}}
urls = []
def g(u): urls.append(u); return json.dumps(mlb)
r = N.run_one(spec, now, g)
assert r["ok"] and r["n"] == 2 and r["items"][0]["homePitcher"] == "Ace Arm" and r["items"][0]["awayPitcher"] is None
assert urls == ["https://x/s?date=2026-10-14", "https://x/s?date=2026-10-15"], urls
print("OK json collector")

# wrong spec: failure records the response shape so the spec can be fixed from the real run
bad = dict(spec, items="games[]")
r = N.run_one(bad, now, g); assert not r["ok"] and "no items matched" in r["error"] and "dates" in json.dumps(r["shape"])
bad2 = dict(spec, fields={"home": "nope.a", "away": "nope.b"})
r = N.run_one(bad2, now, g); assert not r["ok"] and "required fields" in r["error"]
r = N.run_one(spec, now, lambda u: (_ for _ in ()).throw(OSError("HTTP 403"))); assert not r["ok"] and "403" in r["error"]
print("OK failure diagnostics")

csvspec = {"id": "nfl_inj", "sport": "nfl", "kind": "injuries", "format": "csv", "url": "https://x/injuries_{season}.csv", "required": ["team", "player"],
           "fields": {"team": "team", "player": "full_name", "status": "report_status"}}
text = "team,full_name,report_status\nKC,QB One,Out\n,Nobody,Out\nBUF,X,Questionable\n"
seen = []
r = N.run_one(csvspec, now, lambda u: (seen.append(u), text)[1])
assert r["ok"] and r["n"] == 2 and seen == ["https://x/injuries_2026.csv"], (r, seen)   # row without a team is dropped
print("OK csv collector")

# health: failures counted, collector paused after 5, retried after the pause, recovery clears it
tmp = tempfile.mkdtemp(); hp = f"{tmp}/h.json"
fail = lambda u: (_ for _ in ()).throw(OSError("boom"))
t = now
for i in range(5):
    res, rows = N.run_all([spec], health_path=hp, now=t, getter=fail); t += timedelta(minutes=30)
assert rows[0]["status"] == "failing" and rows[0]["fails"] == 5
res, rows = N.run_all([spec], health_path=hp, now=t, getter=fail)
assert rows[0]["status"] == "paused" and spec["id"] not in res, "paused collector is not called"
t2 = now + timedelta(hours=26)
res, rows = N.run_all([spec], health_path=hp, now=t2, getter=g)
assert rows[0]["status"] == "ok" and json.load(open(hp))[spec["id"]]["fails"] == 0
res, rows = N.run_all([spec, dict(csvspec)], sports={"nfl"}, health_path=hp, now=t2, getter=lambda u: text)
assert [x["id"] for x in rows] == ["nfl_inj"], "sport filter"
assert N.run_all([dict(spec, enabled=False)], health_path=hp, now=t2, getter=g)[1] == []
print("OK health/pause")

# shipped specs are well formed
for s in N.load_specs():
    assert not S.validate(s), (s["id"], S.validate(s))
print("OK shipped specs")

# spawn: add validates, refuses duplicates and unsafe URLs, marks unverified
sp = f"{tmp}/n.json"; json.dump({"collectors": []}, open(sp, "w"))
new = {"id": "tennis_atp", "sport": "tennis", "kind": "results", "url": "https://example.com/{date}", "items": "events[]", "fields": {"home": "h", "away": "a"}, "required": ["home", "away"]}
added = S.add(dict(new), sp); assert added["verified"] is False and json.load(open(sp))["collectors"][0]["id"] == "tennis_atp"
for badspec, frag in ((dict(new), "already exists"), (dict(new, id="x2", url="http://insecure.example/x"), "https://"), (dict(new, id="x3", url="https://user:pw@example.com/x"), "credentials"),
                      (dict(new, id="Bad ID"), "id must"), (dict(new, id="x4", required=["zzz"]), "not in --field"), (dict(new, id="x5", items=""), "--items")):
    try:
        S.add(badspec, sp); raise SystemExit("should have refused: " + frag)
    except ValueError as e:
        assert frag in str(e), (frag, e)
print("OK spawn"); print("NETWORK TESTS PASS")
