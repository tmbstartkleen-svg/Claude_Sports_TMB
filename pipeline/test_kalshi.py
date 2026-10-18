import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_slate as B

def mk(et, nm, y):  # event tickers carry the game date like the real ones
    return {"event_ticker": et, "ticker": et + "-" + nm[:3], "yes_sub_title": nm, "yes_ask_dollars": y}
fake = {"KXNFLGAME": [mk("KXNFLGAME-26OCT26DALPHI", "Philadelphia", "0.5300"), mk("KXNFLGAME-26OCT26DALPHI", "Dallas", "0.5000")],
        "KXNBAGAME": [mk("KXNBAGAME-26OCT26SACLAC", "Sacramento", "0.4300"), mk("KXNBAGAME-26OCT26SACLAC", "Los Angeles C", "0.6100")],
        "KXEPLGAME": [mk("KXEPLGAME-26OCT26CRYNEW", "Crystal Palace", "0.3700"), mk("KXEPLGAME-26OCT26CRYNEW", "Newcastle", "0.3900"), mk("KXEPLGAME-26OCT26CRYNEW", "Tie", "0.2800")]}
def fake_http(u, headers=None):
    ser = u.split("series_ticker=")[1]
    return {"markets": fake.get(ser, [])}
B.http_json = fake_http
items = B.kalshi_games()
assert len(items) == 3 and all(i["source"] == "kalshi" and i["teams"] for i in items)
epl = [i for i in items if "Newcastle" in i["title"]][0]
assert "Tie" in epl["teams"] and " vs " in epl["title"]
print("OK kalshi fetch")

def game(sport, home, away):
    return {"sport": sport, "home": home, "away": away, "start": "2026-10-26T00:15:00Z", "books": {"DK": {"home": -110, "away": -110}}}
g1 = game("nfl", "Philadelphia Eagles", "Dallas Cowboys")
hits = B.match_pm(g1, items)
assert len(hits) == 1 and B.pm_prob_for(hits[0], "Philadelphia Eagles") == 0.53 and B.pm_prob_for(hits[0], "Dallas Cowboys") == 0.50
g2 = game("nba", "Los Angeles Clippers", "Sacramento Kings")
assert B.pm_prob_for(B.match_pm(g2, items)[0], "Los Angeles Clippers") == 0.61
assert B.match_pm(game("nba", "Los Angeles Lakers", "Sacramento Kings"), items) == [], "initial C must not match Lakers"
assert B.match_pm(game("nfl", "Philadelphia Eagles", "Washington Commanders"), items) == [], "both teams must match"
g3 = game("epl", "Newcastle United", "Crystal Palace")
assert B.pm_prob_for(B.match_pm(g3, items)[0], "Newcastle United") == 0.39
assert B.match_pm(dict(g1, start="2026-11-20T18:00:00Z"), items) == [], "same teams, different date: no match"
print("OK kalshi matching")

def empty(u): return {"markets": []}
B.http_json = empty
try:
    B.kalshi_games(); raise SystemExit("should raise")
except RuntimeError as e:
    assert "no Kalshi game markets" in str(e)
try:
    B._espn_events("mma", None); raise SystemExit("should raise")
except RuntimeError as e:
    assert "no usable data" in str(e)


# ---- ESPN: one request per day, merged and de-duplicated
from datetime import date, timedelta
def ev(home, away, start):
    return {"date": start, "competitions": [{"competitors": [{"homeAway": "home", "team": {"displayName": home}}, {"homeAway": "away", "team": {"displayName": away}}],
            "odds": [{"provider": {"name": "DraftKings"}, "homeTeamOdds": {"moneyLine": -150}, "awayTeamOdds": {"moneyLine": 130}}]}]}
asked = []
def espn_get(u):
    asked.append(u); assert "dates=" in u and "-" not in u.split("dates=")[1]
    d = u.split("dates=")[1]
    if d.endswith("20"): raise OSError("one day fails")
    return {"events": [ev("Home " + d, "Away " + d, f"{d[:4]}-{d[4:6]}-{d[6:]}T23:00Z"), ev("Same", "Game", "2026-10-21T23:00Z")]}
games = B.espn_direct("nba", today=date(2026, 10, 18), getter=espn_get)
assert len(asked) == B.ESPN_DAYS + 1, asked
assert len({(g["home"], g["start"]) for g in games}) == len(games) and sum(1 for g in games if g["home"] == "Same") == 1, "duplicates merged"
assert len(games) >= B.ESPN_DAYS, len(games)
try:
    B.espn_direct("nba", today=date(2026, 10, 18), getter=lambda u: (_ for _ in ()).throw(OSError("down"))); raise SystemExit("should raise")
except RuntimeError as e:
    assert "nothing usable" in str(e)
print("OK espn week")
print("KALSHI TESTS PASS")
