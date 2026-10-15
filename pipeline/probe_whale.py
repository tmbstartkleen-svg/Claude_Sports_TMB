"""One-off diagnostic for Actions: do Kalshi/Polymarket expose public trade history or order books we could use for
large-trade ("whale") detection? Writes probe_whale.json."""
import json, urllib.request, urllib.error
def get(u):
    try:
        with urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "edge-suite-slate/1.0", "Accept": "application/json"}), timeout=30) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        return e.code, e.read()[:300].decode("utf8", "replace")
    except Exception as e:  # noqa
        return 0, repr(e)[:200]
out = {}
K = "https://api.elections.kalshi.com/trade-api/v2"
st, d = get(f"{K}/markets?status=open&limit=5&series_ticker=KXNFLGAME")
ticker = (d.get("markets") or [{}])[0].get("ticker") if isinstance(d, dict) else None
out["kalshi_market_sample_ticker"] = ticker
if ticker:
    st, d = get(f"{K}/markets/trades?ticker={ticker}&limit=50")
    out["kalshi_trades"] = {"status": st, "n": len(d.get("trades", [])) if isinstance(d, dict) else d, "sample": (d.get("trades") or [])[:3] if isinstance(d, dict) else d}
    st, d = get(f"{K}/markets/{ticker}/orderbook")
    out["kalshi_orderbook"] = {"status": st, "sample": d if isinstance(d, dict) else d}
P = "https://gamma-api.polymarket.com"
st, d = get(f"{P}/markets?active=true&closed=false&limit=5&tag_slug=sports")
cid = (d[0].get("clobTokenIds") if isinstance(d, list) and d else None)
out["poly_market_sample"] = {"status": st, "clobTokenIds": cid, "conditionId": (d[0].get("conditionId") if isinstance(d, list) and d else None)}
CLOB = "https://clob.polymarket.com"
if cid:
    try:
        tok = json.loads(cid)[0]
        st, d = get(f"{CLOB}/trades?market={tok}&limit=50")
        out["poly_clob_trades"] = {"status": st, "n": len(d) if isinstance(d, list) else d, "sample": d[:3] if isinstance(d, list) else d}
        st, d = get(f"{CLOB}/book?token_id={tok}")
        out["poly_clob_book"] = {"status": st, "sample": d}
    except Exception as e:  # noqa
        out["poly_clob_error"] = repr(e)[:200]
# Polymarket's data-api (positions/activity by wallet) - does it expose a general large-trades feed without a wallet address?
st, d = get(f"{P}/trades?limit=50&takerOnly=true")
out["poly_gamma_trades"] = {"status": st, "n": len(d) if isinstance(d, list) else d, "sample": d[:3] if isinstance(d, list) else d}
json.dump(out, open("probe_whale.json", "w"), indent=1)
print(json.dumps({k: (v.get("status") if isinstance(v, dict) else v) for k, v in out.items()}))
