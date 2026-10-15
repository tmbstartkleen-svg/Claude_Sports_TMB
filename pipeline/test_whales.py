import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import whales as W

def kt(count, yes_price, side="yes", block=False):
    return {"count_fp": str(count), "yes_price_dollars": f"{yes_price:.4f}", "taker_side": side, "is_block_trade": block, "created_time": "2026-10-15T00:00:00Z"}

calls = []
def kalshi_getter(u):
    calls.append(u)
    return {"trades": [kt(10, 0.5), kt(5000, 0.47), kt(2, 0.9, block=True)]}
hits = W.kalshi_whale_trades("TICKER-A", kalshi_getter)
assert len(calls) == 1 and "ticker=TICKER-A" in calls[0]
assert len(hits) == 2, hits                         # the $10*0.5=$5 trade is below the $1500 floor; the big one and the flagged block both count
assert any(h["block"] for h in hits) and any(h["notional"] > 1500 for h in hits)
print("OK kalshi whale trades")

def pt(size, price, side="BUY"):
    return {"size": size, "price": price, "side": side, "proxyWallet": "0xabc123def456", "timestamp": 1700000000}
def poly_getter(u):
    assert "market=COND1" in u
    return [pt(10, 0.5), pt(5000, 0.5), pt(2, 0.9)]
hits = W.poly_whale_trades("COND1", poly_getter)
assert len(hits) == 1 and hits[0]["notional"] == 2500.0
print("OK poly whale trades")

def game(sport, bets=0, cross=0, pm=None):
    return {"sport": sport, "home": "H", "away": "A", "start": "2026-10-20T00:00:00Z",
            "bets": [{"side": "H"}] * bets, "crossArbs": [{}] * cross, "pm": pm or []}

kalshi_item = {"source": "kalshi", "tickers": {"H": "TK-H", "A": "TK-A"}}
poly_item = {"source": "polymarket", "conditionId": "COND1", "title": "H vs A"}
rows = [game("nfl", bets=1, pm=[kalshi_item]), game("nba", pm=[poly_item]), game("mlb", pm=[{"source": "kalshi"}])]  # no tickers: skipped, not crashed
seen = []
def mixed_getter(u):
    seen.append(u)
    if "trades?ticker=" in u:
        return {"trades": [kt(5000, 0.5)]}
    return [pt(5000, 0.5)]
n = W.attach_whales(rows, mixed_getter, max_markets=10)
assert n == 3, n                                     # TK-H, TK-A, and the poly market
assert rows[0]["whales"] and rows[0]["whales"][0]["team"] in ("H", "A")
assert rows[1]["whales"] and rows[1]["whales"][0]["source"] == "polymarket"
assert "whales" not in rows[2]
print("OK attach_whales wiring")

# the per-run cap is respected even with many markets
many = [game("nfl", bets=1, pm=[{"source": "kalshi", "tickers": {"H": f"T{i}", "A": f"U{i}"}}]) for i in range(30)]
n = W.attach_whales(many, mixed_getter, max_markets=5)
assert n == 5, n
print("OK whale cap respected")

# one bad market doesn't break the rest
def flaky(u):
    if "BAD" in u:
        raise OSError("boom")
    return {"trades": [kt(5000, 0.5)]}
rows2 = [game("nfl", bets=1, pm=[{"source": "kalshi", "tickers": {"H": "BAD", "A": "OK"}}])]
W.attach_whales(rows2, flaky, max_markets=10)
assert rows2[0].get("whales"), "the OK ticker's trade should still show up"
print("WHALE TESTS PASS")
