#!/usr/bin/env python3
"""Builds slate.json: odds + prediction markets + edge/arb/sim analysis.

Every data need has a PRIMARY source and one or more FALLBACKS. The first source
that returns usable data wins; every attempt is logged in slate["sources"] so you
can see which one served the numbers.

  Sportsbook odds : The Odds API (needs ODDS_API_KEY; includes DraftKings)
                    -> ESPN scoreboard odds (free; provider is usually DraftKings)
                    -> sports-skills scoreboard odds (free, optional pip package)
  Kalshi          : public Kalshi API -> sports-skills kalshi
  Polymarket      : public gamma API  -> sports-skills polymarket

Read-only. No bets are placed. Stdlib only, plus optional `sports-skills`.
"""
import json, math, os, random, sys, time, urllib.parse, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import model as elo
except Exception:  # model is optional
    elo = None
from datetime import datetime, timezone

SPORTS = {  # key -> (Odds API key, ESPN path)
    "nfl": ("americanfootball_nfl", "football/nfl"),
    "nba": ("basketball_nba", "basketball/nba"),
    "mlb": ("baseball_mlb", "baseball/mlb"),
    "nhl": ("icehockey_nhl", "hockey/nhl"),
    "ncaaf": ("americanfootball_ncaaf", "football/college-football"),
    "ncaab": ("basketball_ncaab", "basketball/mens-college-basketball"),
}
BANKROLL = float(os.environ.get("BANKROLL", 100))
KELLY_FRAC = float(os.environ.get("KELLY_FRAC", 0.35))
MAX_STAKE_PCT = float(os.environ.get("MAX_STAKE_PCT", 3))
DAY_BUDGET = float(os.environ.get("DAY_BUDGET", 6))
MIN_EDGE = float(os.environ.get("MIN_EDGE", 0.01))
LOG = []


def log(source, ok, detail=""):
    LOG.append({"source": source, "ok": bool(ok), "detail": str(detail)[:200]})


def http_json(url, headers=None, timeout=20):
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "edge-suite-slate/1.0", **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def try_sources(label, attempts):
    """attempts: list of (name, callable). Return first non-empty result."""
    for name, fn in attempts:
        try:
            out = fn()
            if out:
                log(f"{label}:{name}", True, f"{len(out)} items")
                return out
            log(f"{label}:{name}", False, "empty")
        except Exception as e:  # noqa
            log(f"{label}:{name}", False, repr(e))
    return []


# ---------- odds math ----------
def am_to_dec(a):
    a = float(a)
    if abs(a) < 100:
        return None
    return 1 + a / 100 if a > 0 else 1 + 100 / abs(a)


def devig_shin(q):
    S = sum(q)
    if S <= 1.0000001:
        return [x / S for x in q]
    f = lambda z: [(math.sqrt(z * z + 4 * (1 - z) * x * x / S) - z) / (2 * (1 - z)) for x in q]
    lo, hi = 0.0, 0.4
    for _ in range(60):
        z = (lo + hi) / 2
        if sum(f(z)) > 1:
            lo = z
        else:
            hi = z
    p = f((lo + hi) / 2)
    t = sum(p)
    return [x / t for x in p]


# ---------- sportsbook sources -> [{sport,home,away,start,books:{name:{home:am,away:am}}}] ----------
def odds_api(sport):
    key = os.environ.get("ODDS_API_KEY")
    if not key:
        raise RuntimeError("ODDS_API_KEY not set")
    u = f"https://api.the-odds-api.com/v4/sports/{SPORTS[sport][0]}/odds/?" + urllib.parse.urlencode(
        {"apiKey": key, "regions": "us", "markets": "h2h", "oddsFormat": "american"})
    out = []
    for g in http_json(u):
        books = {}
        for b in g.get("bookmakers", []):
            for m in b.get("markets", []):
                if m["key"] != "h2h":
                    continue
                px = {o["name"]: o["price"] for o in m["outcomes"]}
                if g["home_team"] in px and g["away_team"] in px:
                    books[b["title"]] = {"home": px[g["home_team"]], "away": px[g["away_team"]]}
        if books:
            out.append({"sport": sport, "home": g["home_team"], "away": g["away_team"], "start": g["commence_time"], "books": books})
    return out


def _espn_events(sport, data):
    out = []
    for ev in data.get("events", []):
        comp = ev["competitions"][0]
        teams = {c["homeAway"]: c["team"]["displayName"] for c in comp["competitors"]}
        books = {}
        for o in comp.get("odds", []) or []:
            name = (o.get("provider") or {}).get("name", "ESPN")
            h = a = None
            ml = o.get("moneyline")
            if ml:
                h = ((ml.get("home") or {}).get("close") or {}).get("odds")
                a = ((ml.get("away") or {}).get("close") or {}).get("odds")
            h = h or (o.get("homeTeamOdds") or {}).get("moneyLine")
            a = a or (o.get("awayTeamOdds") or {}).get("moneyLine")
            try:
                if h is not None and a is not None and am_to_dec(str(h).replace("EVEN", "100")) and am_to_dec(str(a).replace("EVEN", "100")):
                    books[name] = {"home": float(str(h).replace("EVEN", "100")), "away": float(str(a).replace("EVEN", "100"))}
            except ValueError:
                pass
        if books and "home" in teams and "away" in teams:
            out.append({"sport": sport, "home": teams["home"], "away": teams["away"], "start": ev.get("date"), "books": books})
    return out


def espn_direct(sport):
    return _espn_events(sport, http_json(f"https://site.api.espn.com/apis/site/v2/sports/{SPORTS[sport][1]}/scoreboard"))


def espn_via_skills(sport):
    import sports_skills as ss
    mod = getattr(ss, {"ncaaf": "cfb", "ncaab": "cbb"}.get(sport, sport))
    r = mod.get_scoreboard()
    if not r.get("status"):
        raise RuntimeError(r.get("message"))
    return _espn_events(sport, r["data"])


# ---------- prediction markets -> [{source,title,yes,no,url}] (prices as 0..1 probabilities) ----------
def kalshi_direct():
    data = http_json("https://api.elections.kalshi.com/trade-api/v2/markets?status=open&limit=1000")
    out = []
    for m in data.get("markets", []):
        y = m.get("yes_ask_dollars")
        n = m.get("no_ask_dollars")
        if y is None:
            continue
        out.append({"source": "kalshi", "title": m.get("title", ""), "yes": float(y), "no": float(n) if n is not None else None,
                    "url": f"https://kalshi.com/markets/{(m.get('series_ticker') or '').lower()}"})
    return out


def kalshi_via_skills():
    import sports_skills as ss
    out = []
    for s in ("NFL", "NBA", "MLB", "NHL", "college"):
        r = ss.kalshi.search_markets(query=s, limit=100)
        if not r.get("status"):
            raise RuntimeError(r.get("message"))
        for m in (r.get("data") or {}).get("markets", []):
            y = m.get("yes_ask") or m.get("yes_price") or m.get("yes_ask_dollars")
            if y is None:
                continue
            y = float(y)
            y = y / 100 if y > 1 else y
            out.append({"source": "kalshi", "title": m.get("title", ""), "yes": y, "no": None, "url": m.get("url", "")})
    return out


def polymarket_direct():
    ev = http_json("https://gamma-api.polymarket.com/events?active=true&closed=false&limit=200")
    out = []
    for e in ev if isinstance(ev, list) else []:
        for m in e.get("markets", []):
            try:
                names = json.loads(m.get("outcomes") or "[]")
                prices = [float(x) for x in json.loads(m.get("outcomePrices") or "[]")]
            except ValueError:
                continue
            if len(names) == 2 and len(prices) == 2:
                out.append({"source": "polymarket", "title": m.get("question") or e.get("title", ""), "outcomes": names, "prices": prices,
                            "url": f"https://polymarket.com/event/{e.get('slug','')}"})
    return out


def polymarket_via_skills():
    import sports_skills as ss
    out = []
    for s in ("NFL", "NBA", "MLB", "NHL"):
        r = ss.polymarket.search_markets(query=s, limit=50)
        if not r.get("status"):
            raise RuntimeError(r.get("message"))
        for m in (r.get("data") or {}).get("markets", []):
            names, prices = m.get("outcomes"), m.get("prices") or m.get("outcome_prices")
            if isinstance(names, list) and isinstance(prices, list) and len(names) == 2:
                out.append({"source": "polymarket", "title": m.get("question") or m.get("title", ""), "outcomes": names,
                            "prices": [float(x) for x in prices], "url": m.get("url", "")})
    return out


# ---------- analysis ----------
def last_word(name):
    return name.lower().split()[-1]


def match_pm(game, pms):
    h, a = last_word(game["home"]), last_word(game["away"])
    hits = []
    for m in pms:
        t = m["title"].lower()
        if h in t and a in t:
            hits.append(m)
    return hits


def pm_prob_for(m, team):
    """Return the market's price (0..1) of `team` winning, if determinable."""
    t, w = m["title"].lower(), last_word(team)
    if m["source"] == "polymarket":
        for n, p in zip(m["outcomes"], m["prices"]):
            if w in n.lower():
                return p
        return None
    # kalshi yes/no market: only usable if the title asks "will <team> win"
    if m.get("yes") is not None and f"{w}" in t.split(" win")[0] and "win" in t:
        first = t.split(" win")[0]
        if w in first and last_word(team) == first.split()[-1]:
            return m["yes"]
    return None


def analyze(games, pms, models=None):
    models = models or {}
    rows = []
    for g in games:
        sides = {"home": [], "away": []}
        fair_by_book = []
        for book, px in g["books"].items():
            dh, da = am_to_dec(px["home"]), am_to_dec(px["away"])
            if not dh or not da:
                continue
            fh, fa = devig_shin([1 / dh, 1 / da])
            fair_by_book.append((fh, fa))
            sides["home"].append((dh, book, px["home"]))
            sides["away"].append((da, book, px["away"]))
        if not fair_by_book:
            continue
        n = len(fair_by_book)
        fair = {"home": sum(f[0] for f in fair_by_book) / n, "away": sum(f[1] for f in fair_by_book) / n}
        best = {k: max(v) for k, v in sides.items()}
        implied_sum = 1 / best["home"][0] + 1 / best["away"][0]
        row = {"sport": g["sport"], "home": g["home"], "away": g["away"], "start": g["start"], "nBooks": n,
               "fair": {k: round(v, 4) for k, v in fair.items()},
               "best": {k: {"book": best[k][1], "american": best[k][2], "decimal": round(best[k][0], 3)} for k in best},
               "arb": implied_sum < 1, "impliedSum": round(implied_sum, 4), "bets": [], "pm": []}
        if row["arb"]:
            row["arbRoiPct"] = round((1 / implied_sum - 1) * 100, 2)
        for k in ("home", "away"):
            ev = fair[k] * best[k][0] - 1
            if n >= 2 and ev >= MIN_EDGE:
                b = best[k][0] - 1
                kelly = max(0.0, (b * fair[k] - (1 - fair[k])) / b)
                pct = min(kelly * KELLY_FRAC * 100, MAX_STAKE_PCT)
                row["bets"].append({"side": g[k], "book": best[k][1], "american": best[k][2], "fair": round(fair[k], 4),
                                    "evPct": round(ev * 100, 2), "stakePct": round(pct, 2), "stake": round(BANKROLL * pct / 100, 2)})
        mdl = models.get(g["sport"])
        if mdl and elo:
            try:
                start = datetime.fromisoformat(g["start"].replace("Z", "+00:00")).date() if g.get("start") else None
            except ValueError:
                start = None
            pm_home = elo.predict(g["sport"], mdl, g["home"], g["away"], start)
            if pm_home is not None:
                bl = elo.blend(pm_home, fair["home"])
                row["model"] = {"home": round(pm_home, 4), "away": round(1 - pm_home, 4), "blendHome": round(bl, 4),
                                "gapPp": round((pm_home - fair["home"]) * 100, 1), "weight": elo.MODEL_WEIGHT}
                for k, pk in (("home", bl), ("away", 1 - bl)):
                    evm = pk * best[k][0] - 1
                    if evm >= MIN_EDGE and not any(b["side"] == g[k] for b in row["bets"]):
                        b_ = best[k][0] - 1
                        kelly = max(0.0, (b_ * pk - (1 - pk)) / b_)
                        pct = min(kelly * KELLY_FRAC * 100, MAX_STAKE_PCT)
                        row["bets"].append({"side": g[k], "book": best[k][1], "american": best[k][2], "fair": round(pk, 4),
                                            "evPct": round(evm * 100, 2), "stakePct": round(pct, 2), "stake": round(BANKROLL * pct / 100, 2), "basis": "model-blend"})
        for m in match_pm(g, pms)[:4]:
            e = {"source": m["source"], "title": m["title"], "url": m.get("url", "")}
            for k in ("home", "away"):
                p = pm_prob_for(m, g[k])
                if p is not None:
                    e[k] = round(p, 3)
                    e[k + "EdgePp"] = round((fair[k] - p) * 100, 1)
            row["pm"].append(e)
        rows.append(row)
    return rows


def simulate_day(rows, rho=0.25, N=20000, seed=7):
    bets = [(b, r) for r in rows for b in r["bets"]]
    if not bets:
        return None
    rng = random.Random(seed)
    nd = lambda: rng.gauss(0, 1)
    cdf = lambda x: 0.5 * (1 + math.erf(x / math.sqrt(2)))
    stakes = [b["stake"] for b, _ in bets]
    decs = [am_to_dec(b["american"]) for b, _ in bets]
    ps = [b["fair"] for b, _ in bets]

    def run(scale):
        rng.seed(seed)
        out = []
        for _ in range(N):
            z = nd()
            t = 0.0
            for s, d, p in zip(stakes, decs, ps):
                win = cdf(math.sqrt(rho) * z + math.sqrt(1 - rho) * nd()) < p
                t += s * scale * (d - 1) if win else -s * scale
            out.append(t)
        out.sort()
        return out

    pnl = run(1.0)
    var95 = -pnl[int(0.05 * N)]
    scale = 1.0
    if var95 > DAY_BUDGET:
        lo, hi = 0.0, 1.0
        for _ in range(14):
            m = (lo + hi) / 2
            if -run(m)[int(0.05 * N)] <= DAY_BUDGET:
                lo = m
            else:
                hi = m
        scale = lo
        pnl = run(scale)
    mean = sum(pnl) / N
    return {"nBets": len(bets), "scale": round(scale, 3), "totalStake": round(sum(stakes) * scale, 2),
            "meanPnl": round(mean, 2), "var95": round(-pnl[int(0.05 * N)], 2),
            "pBreakEven": round(sum(1 for x in pnl if x >= -1e-9) / N, 3),
            "pProfit": round(sum(1 for x in pnl if x > 0) / N, 3), "best": round(pnl[-1], 2), "worst": round(pnl[0], 2),
            "note": "Independent-edge assumption: fair probabilities come from market consensus, not a private model. A positive mean here is only as good as that assumption."}


def main():
    sports = [s for s in os.environ.get("SPORTS", "nfl,nba,mlb,nhl").split(",") if s in SPORTS]
    games = []
    for s in sports:
        got = try_sources(f"odds[{s}]", [("oddsapi", lambda s=s: odds_api(s)), ("espn", lambda s=s: espn_direct(s)),
                                          ("sports-skills", lambda s=s: espn_via_skills(s))])
        games += got
    pms = try_sources("kalshi", [("direct", kalshi_direct), ("sports-skills", kalshi_via_skills)])
    pms += try_sources("polymarket", [("direct", polymarket_direct), ("sports-skills", polymarket_via_skills)])
    models, backtests = {}, {}
    if elo:
        for sp in [x for x in sports if x in elo.CFG]:
            try:
                res = elo.fetch_results(sp)
                if len(res) < 50:
                    raise RuntimeError(f"only {len(res)} completed games found")
                models[sp] = elo.build(sp, res)
                backtests[sp] = models[sp]["backtest"]
                log(f"model[{sp}]", True, f"{len(res)} games, brier {backtests[sp] and backtests[sp]['brier']}")
            except Exception as e:  # noqa
                log(f"model[{sp}]", False, repr(e))
    rows = analyze(games, pms, models)
    rows.sort(key=lambda r: -max([b["evPct"] for b in r["bets"]] + [r.get("arbRoiPct", 0), -99]))
    slate = {"generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
             "settings": {"bankroll": BANKROLL, "kellyFrac": KELLY_FRAC, "maxStakePct": MAX_STAKE_PCT, "dayBudget": DAY_BUDGET, "minEdge": MIN_EDGE},
             "sources": LOG, "modelBacktest": backtests, "games": rows, "day": simulate_day(rows),
             "disclaimer": "Edges are measured against the consensus of the books returned, not a private model. Informational only."}
    out = os.environ.get("SLATE_OUT", "slate.json")
    with open(out, "w") as f:
        json.dump(slate, f, indent=1)
    print(f"wrote {out}: {len(rows)} games, {sum(len(r['bets']) for r in rows)} bets, {sum(1 for r in rows if r['arb'])} arbs")
    for l in LOG:
        print(("OK  " if l["ok"] else "FAIL"), l["source"], l["detail"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
