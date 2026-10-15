"""One-off diagnostic for GitHub Actions: what do Kalshi/Polymarket actually return for single-game sports markets? Writes probe_pm.json."""
import json, urllib.request, urllib.error
def get(u):
    try:
        with urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "edge-suite-slate/1.0", "Accept": "application/json"}), timeout=30) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        return e.code, e.read()[:200].decode("utf8", "replace")
    except Exception as e:  # noqa
        return 0, repr(e)[:200]
out = {}
K = "https://api.elections.kalshi.com/trade-api/v2"
st, d = get(f"{K}/markets?status=open&limit=200")
out["kalshi_plain"] = {"status": st, "n": len(d.get("markets", [])) if isinstance(d, dict) else d, "sample": [{k: m.get(k) for k in ("ticker", "event_ticker", "series_ticker", "title", "yes_ask_dollars", "yes_ask", "mve_collection_ticker")} for m in (d.get("markets", [])[:5] if isinstance(d, dict) else [])]}
for ser in ("KXNFLGAME", "KXNBAGAME", "KXNHLGAME", "KXMLBGAME", "KXEPLGAME", "KXMLSGAME", "KXNCAAFGAME"):
    st, d = get(f"{K}/markets?status=open&limit=100&series_ticker={ser}")
    ms = d.get("markets", []) if isinstance(d, dict) else []
    out[ser] = {"status": st, "n": len(ms), "sample": [{k: m.get(k) for k in ("ticker", "title", "yes_sub_title", "yes_ask_dollars", "yes_ask", "no_ask_dollars", "close_time")} for m in ms[:4]]}
st, d = get(f"{K}/series?category=Sports")
out["kalshi_series"] = {"status": st, "n": len(d.get("series", [])) if isinstance(d, dict) else d, "tickers": [s.get("ticker") for s in (d.get("series", []) if isinstance(d, dict) else [])][:80]}
P = "https://gamma-api.polymarket.com"
st, d = get(f"{P}/events?active=true&closed=false&limit=100&tag_slug=sports")
out["poly_sports_events"] = {"status": st, "n": len(d) if isinstance(d, list) else d, "sample": [{"title": e.get("title"), "slug": e.get("slug"), "markets": [{"q": m.get("question"), "outcomes": m.get("outcomes"), "prices": m.get("outcomePrices")} for m in (e.get("markets") or [])[:2]]} for e in (d[:6] if isinstance(d, list) else [])]}
json.dump(out, open("probe_pm.json", "w"), indent=1)
print({k: (v.get("status"), v.get("n")) for k, v in out.items()})
