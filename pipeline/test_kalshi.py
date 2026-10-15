import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_slate as B

def mk(et, nm, y):
    return {"event_ticker": et, "ticker": et + "-" + nm[:3], "yes_sub_title": nm, "yes_ask_dollars": y}
fake = {"KXNFLGAME": [mk("E1", "Philadelphia", "0.5300"), mk("E1", "Dallas", "0.5000")],
        "KXNBAGAME": [mk("E2", "Sacramento", "0.4300"), mk("E2", "Los Angeles C", "0.6100")],
        "KXEPLGAME": [mk("E3", "Crystal Palace", "0.3700"), mk("E3", "Newcastle", "0.3900"), mk("E3", "Tie", "0.2800")]}
def fake_http(u):
    ser = u.split("series_ticker=")[1]
    return {"markets": fake.get(ser, [])}
B.http_json = fake_http
items = B.kalshi_games()
assert len(items) == 3 and all(i["source"] == "kalshi" and i["teams"] for i in items)
epl = [i for i in items if "Newcastle" in i["title"]][0]
assert "Tie" in epl["teams"] and " vs " in epl["title"]
print("OK kalshi fetch")

def game(sport, home, away):
    return {"sport": sport, "home": home, "away": away, "start": "2099-01-01T00:00:00Z", "books": {"DK": {"home": -110, "away": -110}}}
g1 = game("nfl", "Philadelphia Eagles", "Dallas Cowboys")
hits = B.match_pm(g1, items)
assert len(hits) == 1 and B.pm_prob_for(hits[0], "Philadelphia Eagles") == 0.53 and B.pm_prob_for(hits[0], "Dallas Cowboys") == 0.50
g2 = game("nba", "Los Angeles Clippers", "Sacramento Kings")
assert B.pm_prob_for(B.match_pm(g2, items)[0], "Los Angeles Clippers") == 0.61
assert B.match_pm(game("nba", "Los Angeles Lakers", "Sacramento Kings"), items) == [], "initial C must not match Lakers"
assert B.match_pm(game("nfl", "Philadelphia Eagles", "Washington Commanders"), items) == [], "both teams must match"
g3 = game("epl", "Newcastle United", "Crystal Palace")
assert B.pm_prob_for(B.match_pm(g3, items)[0], "Newcastle United") == 0.39
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
print("KALSHI TESTS PASS")
