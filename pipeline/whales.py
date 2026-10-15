"""Large ("whale") trades on Kalshi and Polymarket for the games already in the slate.
Both endpoints are public and need no key or login (verified from a real Actions probe: probe_whale.json).
Not insider detection — just unusually large real trades, which a trader can use the same way the paid
whale-tracking tools do. Capped per run so 400+ games does not mean hundreds of extra requests."""
import json

KALSHI_TRADES = "https://api.elections.kalshi.com/trade-api/v2/markets/trades"
POLY_TRADES = "https://data-api.polymarket.com/trades"
MAX_MARKETS = int(__import__("os").environ.get("WHALE_MAX_MARKETS", 40))
KALSHI_MIN_NOTIONAL = 1500.0   # dollars risked on one trade
POLY_MIN_NOTIONAL = 2000.0


def kalshi_whale_trades(ticker, getter, limit=100, min_notional=KALSHI_MIN_NOTIONAL):
    """Notable trades on one Kalshi team-outcome market. A contract resolves to $1, so dollars risked = contracts * price paid."""
    data = getter(f"{KALSHI_TRADES}?ticker={ticker}&limit={limit}")
    out = []
    for t in data.get("trades", []) if isinstance(data, dict) else []:
        try:
            count = float(t.get("count_fp", 0))
            yes_p = float(t.get("yes_price_dollars", 0) or 0)
        except (TypeError, ValueError):
            continue
        side = t.get("taker_side") or "yes"
        price = yes_p if side == "yes" else max(0.0, 1 - yes_p)
        notional = count * price
        if t.get("is_block_trade") or notional >= min_notional:
            out.append({"side": side, "notional": round(notional, 2), "price": round(price, 3), "contracts": round(count, 1),
                        "block": bool(t.get("is_block_trade")), "time": t.get("created_time")})
    return out


def poly_whale_trades(condition_id, getter, limit=100, min_notional=POLY_MIN_NOTIONAL):
    """Notable trades on one Polymarket market (by conditionId), across both outcomes."""
    data = getter(f"{POLY_TRADES}?market={condition_id}&limit={limit}")
    out = []
    for t in data if isinstance(data, list) else []:
        try:
            size, price = float(t.get("size", 0)), float(t.get("price", 0))
        except (TypeError, ValueError):
            continue
        notional = size * price
        if notional >= min_notional:
            out.append({"side": t.get("side"), "notional": round(notional, 2), "price": round(price, 3), "size": round(size, 1),
                        "wallet": (t.get("proxyWallet") or "")[:10], "time": t.get("timestamp")})
    return out


def attach_whales(rows, getter, max_markets=MAX_MARKETS):
    """For the games with the most going on (flagged bets or a cross-arb first), pull notable trades on their
    matched Kalshi/Polymarket markets and attach row['whales']. Returns the number of markets actually queried."""
    ranked = sorted(rows, key=lambda r: (-(len(r.get("bets", [])) + len(r.get("crossArbs", []))), r.get("start") or ""))
    queried = 0
    for r in ranked:
        if queried >= max_markets or not r.get("pm"):
            continue
        whales = []
        for m in r["pm"][:2]:
            if queried >= max_markets:
                break
            try:
                if m.get("source") == "kalshi" and m.get("tickers"):
                    for team, tkr in m["tickers"].items():
                        if not tkr:
                            continue
                        try:
                            hits = kalshi_whale_trades(tkr, getter)
                        except Exception:  # noqa  one bad ticker must not hide another team's trades
                            queried += 1
                            continue
                        queried += 1
                        for h in hits:
                            whales.append({**h, "team": team, "source": "kalshi"})
                        if queried >= max_markets:
                            break
                elif m.get("source") == "polymarket" and m.get("conditionId"):
                    hits = poly_whale_trades(m["conditionId"], getter)
                    queried += 1
                    for h in hits:
                        whales.append({**h, "team": None, "source": "polymarket", "title": m.get("title")})
            except Exception:  # noqa  one bad market must not break the slate
                continue
        if whales:
            r["whales"] = sorted(whales, key=lambda w: -w["notional"])[:8]
    return queried
