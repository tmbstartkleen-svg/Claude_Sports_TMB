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
try:
    import markets as mk
except Exception:
    mk = None
try:
    import history as hist_mod
except Exception:
    hist_mod = None
try:
    import soccer as soccer_mod
except Exception:
    soccer_mod = None
try:
    import notify as notifier
except Exception:
    notifier = None
try:
    import grade as grader
except Exception:
    grader = None
from datetime import datetime, timedelta, timezone
try:
    from names import canon
except Exception:  # pragma: no cover
    canon = lambda s: str(s).lower()
import re
try:
    import network as net_mod
except ImportError:  # pragma: no cover
    net_mod = None
try:
    import whales as whale_mod
except ImportError:  # pragma: no cover
    whale_mod = None

try:
    import leagues as _lg
except ImportError:  # pragma: no cover
    from pipeline import leagues as _lg
SPORTS = {k: (v[1], v[2]) for k, v in _lg.OTHER.items()}  # key -> (Odds API key, ESPN path)
SPORTS.update({k: (v[1], "soccer/" + v[2]) for k, v in _lg.SOCCER.items()})
LABELS = {**{k: v[0] for k, v in _lg.OTHER.items()}, **{k: v[0] for k, v in _lg.SOCCER.items()}}
ALL_SPORTS = ",".join(SPORTS)
THREE_WAY = set(_lg.SOCCER)  # soccer: always home / draw / away
# The Odds API charges 1 credit per sport per market per region. Sports outside this list skip it and use the free sources.
ODDS_API_SPORTS = set(os.environ.get("ODDS_API_SPORTS", "nfl,nba,mlb,nhl").split(","))  # 4 sports x 1 market x 1 region = 4 credits per run; 2 runs a day = about 240 of the 500 free credits a month
REGIONS = os.environ.get("REGIONS", "us")  # "us,eu" adds Pinnacle and other sharp books but doubles Odds API credit use
# Books whose prices count more in the consensus fair price (substring match on the book name, case-insensitive).
SHARP_WEIGHTS = {"pinnacle": 4.0, "circa": 3.0, "betonline": 2.0, "lowvig": 2.0, "bookmaker": 2.0, "betcris": 2.0}
for _kv in filter(None, os.environ.get("SHARP_BOOKS", "").split(",")):  # e.g. SHARP_BOOKS="pinnacle=5,circa=3"
    try:
        _k, _v = _kv.split("=")
        SHARP_WEIGHTS[_k.strip().lower()] = float(_v)
    except ValueError:
        pass
MARKETS = os.environ.get("MARKETS", "h2h")  # add ",spreads,totals" to enable the middle scanner (costs more credits)
BANKROLL = float(os.environ.get("BANKROLL", 100))
KELLY_FRAC = float(os.environ.get("KELLY_FRAC", 0.35))
MAX_STAKE_PCT = float(os.environ.get("MAX_STAKE_PCT", 3))
DAY_BUDGET = float(os.environ.get("DAY_BUDGET", 6))
MIN_EDGE = float(os.environ.get("MIN_EDGE", 0.01))
MIN_BOOKS = int(os.environ.get("MIN_BOOKS", 3))  # consensus edge bets need this many books (fewer = noise and winner's curse)
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
def book_weight(name):
    n = (name or "").lower()
    for k, w in SHARP_WEIGHTS.items():
        if k in n:
            return w
    return 1.0


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
    if sport not in ODDS_API_SPORTS:
        raise RuntimeError("skipped to save Odds API credits (not in ODDS_API_SPORTS)")
    u = f"https://api.the-odds-api.com/v4/sports/{SPORTS[sport][0]}/odds/?" + urllib.parse.urlencode(
        {"apiKey": key, "regions": REGIONS, "markets": MARKETS, "oddsFormat": "american"})
    return parse_odds_api(sport, http_json(u))


def parse_odds_api(sport, data):
    out = []
    for g in data:
        books, spreads, totals = {}, {}, {}
        for b in g.get("bookmakers", []):
            for m in b.get("markets", []):
                outs = m.get("outcomes", [])
                if m["key"] == "h2h":
                    px = {o["name"]: o["price"] for o in outs}
                    if g["home_team"] in px and g["away_team"] in px:
                        d = {"home": px[g["home_team"]], "away": px[g["away_team"]]}
                        if "Draw" in px:
                            d["draw"] = px["Draw"]
                        books[b["title"]] = d
                elif m["key"] == "spreads":
                    d = {}
                    for o in outs:
                        if o.get("point") is None:
                            continue
                        side = "home" if o["name"] == g["home_team"] else "away" if o["name"] == g["away_team"] else None
                        if side:
                            d[side] = (float(o["point"]), o["price"])
                    if len(d) == 2:
                        spreads[b["title"]] = d
                elif m["key"] == "totals":
                    d = {}
                    for o in outs:
                        if o.get("point") is not None and o["name"] in ("Over", "Under"):
                            d[o["name"].lower()] = (float(o["point"]), o["price"])
                    if len(d) == 2:
                        totals[b["title"]] = d
        if books:
            out.append({"sport": sport, "home": g["home_team"], "away": g["away_team"], "start": g["commence_time"],
                        "books": books, "spreads": spreads, "totals": totals})
    return out


def _am(x):
    """ESPN odds value -> float American odds, or None."""
    if x is None:
        return None
    t = str(x).strip().upper().replace("EVEN", "100").replace("PK", "").replace("+", "")
    try:
        v = float(t)
    except ValueError:
        return None
    return v if am_to_dec(v) else None


def _espn_events(sport, data):
    if not isinstance(data, dict):
        raise RuntimeError(f"ESPN returned no usable data for {sport} (got {type(data).__name__})")
    out = []
    for ev in data.get("events", []):
        comp = ev["competitions"][0]
        comps = comp.get("competitors", [])
        names = {}
        for i, c in enumerate(comps):
            nm = (c.get("team") or {}).get("displayName") or (c.get("athlete") or {}).get("displayName")
            ha = c.get("homeAway") or ("home" if i == 0 else "away")  # combat sports have no home/away; keep ESPN order
            if nm:
                names[ha] = nm
        books = {}
        for o in comp.get("odds", []) or []:
            name = (o.get("provider") or {}).get("name", "ESPN")
            ml = o.get("moneyline") or {}
            h = _am(((ml.get("home") or {}).get("close") or {}).get("odds")) or _am((o.get("homeTeamOdds") or {}).get("moneyLine"))
            a = _am(((ml.get("away") or {}).get("close") or {}).get("odds")) or _am((o.get("awayTeamOdds") or {}).get("moneyLine"))
            d = _am(((ml.get("draw") or {}).get("close") or {}).get("odds")) or _am((o.get("drawOdds") or {}).get("moneyLine"))
            if h is not None and a is not None:
                px = {"home": h, "away": a}
                if d is not None:
                    px["draw"] = d
                books[name] = px
        pitchers = {}
        if sport == "mlb":
            for i, c in enumerate(comps):
                ha = c.get("homeAway") or ("home" if i == 0 else "away")
                for pr in c.get("probables", []) or []:
                    era = next((s.get("displayValue") for s in pr.get("statistics", []) or [] if (s.get("name") or "").upper() == "ERA"), None)
                    nm = (pr.get("athlete") or {}).get("displayName")
                    if nm:
                        pitchers[ha] = {"name": nm, "era": era}
                        break
        if books and "home" in names and "away" in names:
            g = {"sport": sport, "home": names["home"], "away": names["away"], "start": ev.get("date"), "books": books}
            if pitchers:
                g["pitchers"] = pitchers
            out.append(g)
    return out


ESPN_DAYS = int(os.environ.get("ESPN_DAYS", 7))


def espn_direct(sport, today=None, getter=None):
    """ESPN's undated scoreboard only lists the current day (verified from a real probe: NBA/NHL/MLB showed only finished games, no odds).
    Ask for each of the next ESPN_DAYS days, one request per day (ranges return HTTP 400), and merge."""
    from concurrent.futures import ThreadPoolExecutor
    getter = getter or http_json
    today = today or datetime.now(timezone.utc).date()
    base = f"https://site.api.espn.com/apis/site/v2/sports/{SPORTS[sport][1]}/scoreboard"
    urls = [f"{base}?dates={(today + timedelta(days=i)):%Y%m%d}" for i in range(-1, ESPN_DAYS)]

    def one(u):
        try:
            return getter(u)
        except Exception:  # noqa
            return None
    with ThreadPoolExecutor(max_workers=8) as pool:
        pages = list(pool.map(one, urls))
    if not any(isinstance(p, dict) for p in pages):
        raise RuntimeError(f"ESPN returned nothing usable for {sport} on {len(urls)} days")
    out, seen, bad = [], set(), []
    for d in pages:
        if not isinstance(d, dict):
            continue
        try:
            parsed = _espn_events(sport, d)
        except Exception as e:  # noqa  one odd event must not hide a whole day; keep the exact line for diagnosis
            import traceback
            tb = traceback.extract_tb(e.__traceback__)[-1]
            bad.append(f"{type(e).__name__}: {e} at line {tb.lineno}: {(tb.line or '')[:90]}")
            continue
        for g in parsed:
            k = (g.get("home"), g.get("away"), g.get("start"))
            if k not in seen:
                seen.add(k)
                out.append(g)
    if bad and not out:
        raise RuntimeError(f"ESPN parse failed for {sport}: {bad[0]}")
    return out


def espn_via_skills(sport):
    import sports_skills as ss
    mod = getattr(ss, {"ncaaf": "cfb", "ncaab": "cbb"}.get(sport, sport))
    r = mod.get_scoreboard()
    if not r.get("status"):
        raise RuntimeError(r.get("message"))
    return _espn_events(sport, r["data"])


# ---------- prediction markets -> [{source,title,yes,no,url}] (prices as 0..1 probabilities) ----------
def kalshi_direct():
    out, cursor = [], ""
    pages = []
    for _ in range(5):  # a few pages; the first one alone is mostly multi-leg parlays
        data = http_json("https://api.elections.kalshi.com/trade-api/v2/markets?status=open&limit=1000" + (f"&cursor={cursor}" if cursor else ""))
        pages += data.get("markets", [])
        cursor = data.get("cursor") or ""
        if not cursor:
            break
    for m in pages:
        if m.get("mve_collection_ticker") or m.get("mve_selected_legs"):
            continue  # multi-leg combo market, not a single-game price
        y = m.get("yes_ask_dollars")
        n = m.get("no_ask_dollars")
        if y is None:
            continue
        out.append({"source": "kalshi", "title": m.get("title", ""), "yes": float(y), "no": float(n) if n is not None else None,
                    "url": f"https://kalshi.com/markets/{(m.get('series_ticker') or '').lower()}"})
    return out


KALSHI_GAME_SERIES = ("KXNFLGAME", "KXNBAGAME", "KXNHLGAME", "KXMLBGAME", "KXNCAAFGAME", "KXNCAABGAME", "KXWNBAGAME", "KXEPLGAME",
                      "KXLALIGAGAME", "KXBUNDESLIGAGAME", "KXSERIEAGAME", "KXLIGUE1GAME", "KXMLSGAME", "KXUCLGAME")


_MON = {m: i + 1 for i, m in enumerate("JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC".split())}


def _kalshi_date(event_ticker):
    """KXNFLGAME-26OCT26DALPHI -> '2026-10-26' (the game date Kalshi encodes in the ticker), or None."""
    mt = re.search(r"-(\d{2})([A-Z]{3})(\d{2})", event_ticker or "")
    if not mt or mt.group(2) not in _MON:
        return None
    return f"20{mt.group(1)}-{_MON[mt.group(2)]:02d}-{mt.group(3)}"


def kalshi_games():
    """Single-game win markets (series KX<LEAGUE>GAME; shapes verified from a real Actions probe). One item per game:
    {source:'kalshi', title:'A vs B', teams:{name: yes ask 0..1}} so both teams are known and nothing is guessed from a one-sided title."""
    out, errs = [], []
    for ser in KALSHI_GAME_SERIES:
        try:
            data = http_json(f"https://api.elections.kalshi.com/trade-api/v2/markets?status=open&limit=500&series_ticker={ser}")
        except Exception as e:  # noqa
            errs.append(f"{ser}: {e!r}"[:80])
            continue
        ev, tk = {}, {}
        for m in data.get("markets", []):
            nm, y = m.get("yes_sub_title"), m.get("yes_ask_dollars")
            if not nm or y is None:
                continue
            try:
                et_ = m.get("event_ticker") or m.get("ticker")
                ev.setdefault(et_, {})[nm] = float(y)
                tk.setdefault(et_, {})[nm] = m.get("ticker")   # per-team market ticker, needed to pull that leg's own trade feed
            except ValueError:
                continue
        for et, teams in ev.items():
            names = [n for n in teams if n.lower() not in ("tie", "draw")]
            if len(names) == 2:
                out.append({"source": "kalshi", "title": " vs ".join(names), "teams": teams, "tickers": tk.get(et, {}), "yes": None, "date": _kalshi_date(et),
                            "url": f"https://kalshi.com/markets/{ser.lower()}"})
    if not out:
        raise RuntimeError("no Kalshi game markets returned" + (f" ({'; '.join(errs[:3])})" if errs else ""))
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
                            "conditionId": m.get("conditionId"), "url": f"https://polymarket.com/event/{e.get('slug','')}"})
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


def skills_injuries(sport):
    """Fallback: sports-skills injuries wrapper (shape varies by sport, so parse defensively)."""
    import sports_skills as ss
    mod = getattr(ss, sport)
    r = mod.get_injuries()
    if not r.get("status"):
        raise RuntimeError(r.get("message"))
    d = r.get("data") or {}
    shaped = {"injuries": [{"displayName": t.get("team") or t.get("name"), "injuries": t.get("injuries", [])}
                           for t in (d.get("teams") or d.get("injuries") or []) if isinstance(t, dict)]}
    return elo.injury_adj(sport, elo.fetch_injuries(sport, getter=lambda _u: shaped))


# ---------- analysis ----------
def last_word(name):
    return name.lower().split()[-1]


BAD_TITLE = re.compile(r"\bby (over|more|at least)\b|\bspread\b|\btotal\b|\bo/u\b|\bover \d|\bunder \d|\bpoints?\b|\bruns?\b|\bgoals?\b|\bcover\b|,|\bmvp\b|\bchampion|\bplayoffs?\b|\bseries\b|\bseason\b", re.I)


def _has_word(text, word):
    return bool(word) and re.search(r"(?<![a-z])" + re.escape(word) + r"(?![a-z])", text) is not None


def kalshi_name_matches(kname, full):
    """Kalshi uses short names ('Philadelphia', 'Los Angeles C', 'Crystal Palace'). Match a city/club prefix; a trailing initial must match the nickname."""
    k, f = kname.lower().strip(), full.lower().strip()
    if k == f or f.startswith(k + " "):
        mt = re.match(r"^(.+) (\w)$", k)
        if not (mt and len(k.split()[-1]) == 1):
            return True
    mt = re.match(r"^(.+) (\w)$", k)
    if mt and len(k.split()[-1]) == 1 and f.startswith(mt.group(1) + " "):
        return f[len(mt.group(1)) + 1:][:1] == mt.group(2)
    return False


def _kalshi_same_day(m, game):
    """The same two teams can meet in several games (series, rematches). The ticker date must be within a day of this game's start, else skip."""
    if not m.get("date"):
        return False
    try:
        a = datetime.fromisoformat(m["date"]).date()
        b = datetime.fromisoformat((game.get("start") or "").replace("Z", "+00:00")).date()
    except ValueError:
        return False
    return abs((a - b).days) <= 1


def _kalshi_pick(m, team):
    hits = [v for n, v in m["teams"].items() if n.lower() not in ("tie", "draw") and kalshi_name_matches(n, team)]
    return hits[0] if len(hits) == 1 else None


def match_pm(game, pms):
    """Prediction-market titles that look like a plain who-wins question about exactly these two teams."""
    h, a = last_word(game["home"]), last_word(game["away"])
    hits = []
    for m in pms:
        if m.get("teams"):
            if _kalshi_pick(m, game["home"]) is not None and _kalshi_pick(m, game["away"]) is not None and _kalshi_same_day(m, game):
                hits.append(m)
            continue
        t = m["title"].lower()
        if BAD_TITLE.search(t):
            continue  # spreads, totals, props, multi-leg or futures: not a moneyline price
        if _has_word(t, h) and _has_word(t, a):
            hits.append(m)
    return hits


def pm_prob_for(m, team):
    """Return the market's price (0..1) of `team` winning, if determinable."""
    if m.get("teams"):
        return _kalshi_pick(m, team)
    t, w = m["title"].lower(), last_word(team)
    if BAD_TITLE.search(t):
        return None
    if m["source"] == "polymarket":
        for n, p in zip(m["outcomes"], m["prices"]):
            if _has_word(n.lower(), w):
                return p
        return None
    # kalshi yes/no market: only usable if the title asks "will <team> win"
    mt = re.match(r"^will (?:the )?(.+?) (?:win|beat|defeat)\b", t)
    if m.get("yes") is not None and mt and last_word(mt.group(1)) == w:
        return m["yes"]
    return None


def analyze(games, pms, models=None, injuries=None, now=None):
    now = now or datetime.now(timezone.utc)
    models = models or {}
    injuries = injuries or {}
    rows = []
    for g in games:
        books = {k: v for k, v in g["books"].items() if am_to_dec(v.get("home")) and am_to_dec(v.get("away"))}
        if not books:
            continue
        if g.get("start"):
            try:
                if now >= datetime.fromisoformat(g["start"].replace("Z", "+00:00")):
                    continue  # started or finished: live prices disagree wildly and are not a pre-game edge
            except ValueError:
                pass
        draws = {k: v for k, v in books.items() if v.get("draw") is not None and am_to_dec(v["draw"])}
        if draws or g["sport"] in THREE_WAY:
            books = draws  # a three-outcome sport needs a draw price from every book used; never fall back to two-way
            if not books:
                continue
        three = all("draw" in v and am_to_dec(v["draw"]) for v in books.values())
        outcomes = ["home", "away"] + (["draw"] if three else [])
        label = lambda k: g[k] if k in ("home", "away") else "Draw"
        sides = {k: [] for k in outcomes}
        fair_by_book = []
        for book, px in books.items():
            decs = [am_to_dec(px[k]) for k in outcomes]
            fair_by_book.append(devig_shin([1 / d for d in decs]))
            for k, d in zip(outcomes, decs):
                sides[k].append((d, book, px[k]))
        n = len(fair_by_book)
        wts = [book_weight(bk) for bk in books]
        wsum = sum(wts)
        fair = {k: sum(w * f[i] for w, f in zip(wts, fair_by_book)) / wsum for i, k in enumerate(outcomes)}
        sharp = [bk for bk, w in zip(books, wts) if w > 1]
        best = {k: max(v) for k, v in sides.items()}
        implied_sum = sum(1 / best[k][0] for k in outcomes)
        row = {"key": hist_mod.game_key(g["sport"], g["away"], g["home"], g["start"]) if hist_mod else None,
               "sport": g["sport"], "home": g["home"], "away": g["away"], "start": g["start"], "nBooks": n, "threeWay": three,
               "fair": {k: round(v, 4) for k, v in fair.items()},
               "best": {k: {"book": best[k][1], "american": best[k][2], "decimal": round(best[k][0], 3)} for k in best},
               "arb": implied_sum < 1, "impliedSum": round(implied_sum, 4), "bets": [], "pm": []}
        if sharp:
            row["sharpBooks"] = sharp
        if row["arb"]:
            row["arbRoiPct"] = round((1 / implied_sum - 1) * 100, 2)
        names_ = list(books)

        def fair_excl(k):
            """Consensus fair price WITHOUT the book that offers the best price, so that price is not judged against its own opinion."""
            i = outcomes.index(k)
            pairs = [(w, f[i]) for w, f, nm in zip(wts, fair_by_book, names_) if nm != best[k][1]]
            ws = sum(w for w, _ in pairs)
            return sum(w * x for w, x in pairs) / ws if ws else fair[k]
        for k in outcomes:
            fx = min(fair[k], fair_excl(k))  # the lower of the two: a price must beat the consensus with AND without the book offering it
            ev = fx * best[k][0] - 1
            if n >= MIN_BOOKS and ev >= MIN_EDGE:
                b = best[k][0] - 1
                kelly = max(0.0, (b * fx - (1 - fx)) / b)
                pct = min(kelly * KELLY_FRAC * 100, MAX_STAKE_PCT)
                row["bets"].append({"side": label(k), "book": best[k][1], "american": best[k][2], "fair": round(fx, 4),
                                    "evPct": round(ev * 100, 2), "stakePct": round(pct, 2), "stake": round(BANKROLL * pct / 100, 2)})
        mdl = models.get(g["sport"])
        if mdl and mdl.get("kind") == "soccer" and soccer_mod and elo and three:
            pr = soccer_mod.predict(mdl, g["home"], g["away"])
            if pr:
                mp = dict(zip(("home", "draw", "away"), pr))
                bl3 = {k: elo.blend(mp[k], fair[k], sport=g["sport"]) for k in outcomes}
                row["model"] = {"home": round(mp["home"], 4), "draw": round(mp["draw"], 4), "away": round(mp["away"], 4),
                                "blendHome": round(bl3["home"], 4), "gapPp": round((mp["home"] - fair["home"]) * 100, 1), "weight": elo.MODEL_WEIGHTS.get(g["sport"], elo.MODEL_WEIGHT)}
                for k in outcomes:
                    evm = bl3[k] * best[k][0] - 1
                    if evm >= MIN_EDGE and not any(x["side"] == label(k) for x in row["bets"]):
                        b_ = best[k][0] - 1
                        kelly = max(0.0, (b_ * bl3[k] - (1 - bl3[k])) / b_)
                        pct = min(kelly * KELLY_FRAC * 100, MAX_STAKE_PCT)
                        row["bets"].append({"side": label(k), "book": best[k][1], "american": best[k][2], "fair": round(bl3[k], 4),
                                            "evPct": round(evm * 100, 2), "stakePct": round(pct, 2), "stake": round(BANKROLL * pct / 100, 2), "basis": "model-blend"})
        elif mdl and elo and not three and mdl.get("kind") != "soccer":
            try:
                start = datetime.fromisoformat(g["start"].replace("Z", "+00:00")).date() if g.get("start") else None
            except ValueError:
                start = None
            inj = injuries.get(g["sport"], {})
            adj = {t: v[0] for t, v in inj.items()}
            pnotes = []
            if g.get("pitchers") and hasattr(elo, "pitcher_adj"):
                pa, pnotes = elo.pitcher_adj(g["pitchers"])
                adj[g["home"]] = adj.get(g["home"], 0) + pa["home"]
                adj[g["away"]] = adj.get(g["away"], 0) + pa["away"]
            pm_home = elo.predict(g["sport"], mdl, g["home"], g["away"], start, adj)
            if pm_home is not None:
                bl = elo.blend(pm_home, fair["home"], sport=g["sport"])
                row["model"] = {"home": round(pm_home, 4), "away": round(1 - pm_home, 4), "blendHome": round(bl, 4),
                                "gapPp": round((pm_home - fair["home"]) * 100, 1), "weight": elo.MODEL_WEIGHTS.get(g["sport"], elo.MODEL_WEIGHT)}
                notes = []
                for t in (g["home"], g["away"]):
                    if t in inj and inj[t][0]:
                        notes.append(f"{t}: {inj[t][0]:+.0f} Elo" + (" (" + "; ".join(inj[t][1]) + ")" if inj[t][1] else ""))
                if notes:
                    row["model"]["injuries"] = notes
                if pnotes:
                    row["model"]["pitchers"] = pnotes
                for k, pk in (("home", bl), ("away", 1 - bl)):
                    evm = pk * best[k][0] - 1
                    if evm >= MIN_EDGE and not any(b["side"] == g[k] for b in row["bets"]):
                        b_ = best[k][0] - 1
                        kelly = max(0.0, (b_ * pk - (1 - pk)) / b_)
                        pct = min(kelly * KELLY_FRAC * 100, MAX_STAKE_PCT)
                        row["bets"].append({"side": g[k], "book": best[k][1], "american": best[k][2], "fair": round(pk, 4),
                                            "evPct": round(evm * 100, 2), "stakePct": round(pct, 2), "stake": round(BANKROLL * pct / 100, 2), "basis": "model-blend"})
        pm_hits = []
        for m in match_pm(g, pms)[:4]:
            e = {"source": m["source"], "title": m["title"], "url": m.get("url", "")}
            for k in ("home", "away"):
                p = pm_prob_for(m, g[k])
                if p is not None and abs(p - fair[k]) > 0.12:
                    e["suspect"] = True  # a price this far from every book is more likely a mismatched market than a real edge
                    p = None
                if p is not None:
                    e[k] = round(p, 3)
                    e[k + "EdgePp"] = round((fair[k] - p) * 100, 1)
            row["pm"].append(e)
            pm_hits.append(e)
        if mk:
            row["crossArbs"] = mk.cross_arbs(row, pm_hits)
            row["middles"] = mk.find_middles(g, g["sport"])
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


def models_ran(sp):
    return any(l["source"] == f"model[{sp}]" and l["ok"] for l in LOG)


def diagnostics(games, rows, pms):
    """Counts that make a broken live source obvious on the first run."""
    d = {"predictionMarketsFetched": len(pms), "bySport": {}, "warnings": []}
    for sp in sorted({g["sport"] for g in games}):
        gs = [g for g in games if g["sport"] == sp]
        rs = [r for r in rows if r["sport"] == sp]
        e = {"games": len(gs), "withOdds": len(rs), "avgBooks": round(sum(r["nBooks"] for r in rs) / len(rs), 1) if rs else 0,
             "withModel": sum(1 for r in rs if r.get("model")), "withPmMatch": sum(1 for r in rs if r.get("pm")),
             "edgeBets": sum(len(r["bets"]) for r in rs)}
        if sp == "mlb":
            e["withPitchers"] = sum(1 for g in gs if g.get("pitchers"))
        d["bySport"][sp] = e
        if gs and not rs:
            d["warnings"].append(f"{sp}: {len(gs)} games but none had usable odds")
        if rs and e["avgBooks"] < 2:
            d["warnings"].append(f"{sp}: only one book per game, so edge bets, arbitrage and middles cannot appear")
        if rs and (sp in (elo.CFG if elo else {}) or (soccer_mod and sp in soccer_mod.LEAGUES)) and models_ran(sp) and e["withModel"] < 0.9 * len(rs):
            d["warnings"].append(f"{sp}: model matched only {e['withModel']} of {len(rs)} games; team names may differ between sources")
    if pms and not any(e["withPmMatch"] for e in d["bySport"].values()):
        d["warnings"].append("prediction markets fetched but none matched a game (matching is conservative)")
    if not pms:
        d["warnings"].append("no prediction-market data from any source")
    return d


def enrich_pitchers(games):
    """The Odds API has no starting pitchers; attach ESPN's probables to MLB games that lack them."""
    todo = [g for g in games if g["sport"] == "mlb" and not g.get("pitchers")]
    if not todo:
        return
    try:
        espn = [e for e in espn_direct("mlb") if e.get("pitchers")]
    except Exception as e:  # noqa
        log("pitchers[mlb]", False, repr(e))
        return
    n = 0
    for g in todo:
        for e in espn:
            if last_word(e["home"]) == last_word(g["home"]) and last_word(e["away"]) == last_word(g["away"]) and (e.get("start") or "")[:10] == (g.get("start") or "")[:10]:
                g["pitchers"] = e["pitchers"]
                n += 1
                break
    log("pitchers[mlb]", n > 0, f"{n} games matched")


def grade_step(rows, closing, capture_only, now):
    """Record new edge bets (full runs only), settle finished games, attach CLV, write record.json."""
    if not grader:
        return
    ppath = os.environ.get("PICKS_PATH", "picks.json")
    picks = grader.load(ppath)
    added = 0 if capture_only else grader.record_picks(picks, rows, now)
    need = {}
    for p in picks.values():
        if p["res"] is None and p["sport"] in SPORTS:
            try:
                st = datetime.fromisoformat(p["start"].replace("Z", "+00:00"))
            except ValueError:
                continue
            if st < now:
                for dd in (-1, 0, 1):
                    need.setdefault(p["sport"], set()).add((st + timedelta(days=dd)).strftime("%Y%m%d"))
    finals = {}
    for sp, dates in need.items():
        try:
            finals[sp] = grader.fetch_finals(sp, SPORTS[sp][1], sorted(dates), http_json)
        except Exception as e:  # noqa
            log(f"finals[{sp}]", False, repr(e))
    n_set = grader.settle(picks, finals, now)
    n_clv = grader.attach_clv(picks, closing)
    grader.prune(picks)
    grader.save(ppath, picks)
    rpath = os.environ.get("RECORD_PATH", "record.json")
    summary = grader.summarize(picks)
    try:
        prev = grader.load(rpath)
    except RuntimeError:
        prev = {}
    if {k: v for k, v in prev.items() if k != "generatedAt"} != summary:   # only rewrite when something changed: no commit and deploy every 30 minutes
        grader.save(rpath, {"generatedAt": now.isoformat(timespec="seconds"), **summary})
    log("grading", True, f"{added} picks added, {n_set} settled, {n_clv} CLV, {len(picks)} total")


def main():
    sports = [s for s in os.environ.get("SPORTS", "nfl,nba,mlb,nhl").replace("all", ALL_SPORTS).split(",") if s in SPORTS]
    games = []
    for s in sports:
        got = try_sources(f"odds[{s}]", [("oddsapi", lambda s=s: odds_api(s)), ("espn", lambda s=s: espn_direct(s)),
                                          ("sports-skills", lambda s=s: espn_via_skills(s))])
        games += got
    enrich_pitchers(games)
    net_rows = []
    if net_mod and os.environ.get("NO_NETWORK") != "1":
        try:
            _res, net_rows = net_mod.run_all(net_mod.load_specs(), sports=set(sports))
            log("collectors", True, ", ".join(f"{r['id']}:{r['status']}" for r in net_rows) or "none enabled")
        except Exception as e:  # noqa
            log("collectors", False, repr(e))
    pms = try_sources("kalshi", [("games", kalshi_games), ("direct", kalshi_direct), ("sports-skills", kalshi_via_skills)])
    pms += try_sources("polymarket", [("direct", polymarket_direct), ("sports-skills", polymarket_via_skills)])
    capture_only = os.environ.get("CAPTURE_ONLY") == "1"
    models, backtests, injuries = {}, {}, {}
    if elo and not capture_only:
        for sp in [x for x in sports if x in elo.CFG]:
            try:
                res = elo.fetch_results(sp, cache=True)
                if len(res) < 50:
                    raise RuntimeError(f"only {len(res)} completed games found")
                models[sp] = elo.build(sp, res)
                backtests[sp] = models[sp]["backtest"]
                log(f"model[{sp}]", True, f"{len(res)} games, brier {backtests[sp] and backtests[sp]['brier']}")
            except Exception as e:  # noqa
                log(f"model[{sp}]", False, repr(e))
            if sp in models:
                got = try_sources(f"injuries[{sp}]", [("espn", lambda sp=sp: [elo.injury_adj(sp, elo.fetch_injuries(sp))] ),
                                                       ("sports-skills", lambda sp=sp: [skills_injuries(sp)])])
                if got and got[0]:
                    injuries[sp] = got[0]
    if soccer_mod and elo and not capture_only:
        for sp in [x for x in sports if x in soccer_mod.LEAGUES]:
            try:
                res = elo.fetch_results(sp, path=soccer_mod.LEAGUES[sp], cache=True)
                if len(res) < soccer_mod.MIN_GAMES:
                    raise RuntimeError(f"only {len(res)} completed games found")
                mdl_ = soccer_mod.build(res)
                bt_ = mdl_["backtest"]
                if not bt_ or bt_["brier"] >= bt_["coinFlipBrier"]:
                    raise RuntimeError(f"model does not beat the league-frequency baseline ({bt_ and bt_['brier']} vs {bt_ and bt_['coinFlipBrier']}); not used")
                models[sp] = mdl_
                backtests[sp] = bt_
                log(f"model[{sp}]", True, f"{len(res)} games, 3-way brier {backtests[sp] and backtests[sp]['brier']}")
            except Exception as e:  # noqa
                log(f"model[{sp}]", False, repr(e))
    now = datetime.fromisoformat(os.environ["ASOF"]) if os.environ.get("ASOF") else datetime.now(timezone.utc)
    rows = analyze(games, pms, models, injuries, now)
    rows.sort(key=lambda r: -max([b["evPct"] for b in r["bets"]] + [r.get("arbRoiPct", 0), -99]))
    slate = {"generatedAt": now.isoformat(timespec="seconds"),
             "settings": {"bankroll": BANKROLL, "kellyFrac": KELLY_FRAC, "maxStakePct": MAX_STAKE_PCT, "dayBudget": DAY_BUDGET, "minEdge": MIN_EDGE},
             "sources": LOG, "labels": LABELS, "network": net_rows, "modelBacktest": backtests, "diagnostics": diagnostics(games, rows, pms), "games": rows, "day": None if capture_only else simulate_day(rows),
             "disclaimer": "Edges are measured against the consensus of the books returned, not a private model. Informational only."}
    closing = {}
    if hist_mod:
        hpath = os.environ.get("HISTORY_PATH", "history.json")
        h = hist_mod.load(hpath)
        n_added = hist_mod.record(h, rows, now)
        hist_mod.prune(h, now)
        hist_mod.save(hpath, h)
        closing = hist_mod.closing(h, now)
        log("history", True, f"{n_added} snapshots added, {len(closing)} closing lines available")
    try:
        grade_step(rows, closing, capture_only, now)
    except Exception as e:  # noqa
        log("grading", False, repr(e))
    if whale_mod and not capture_only and os.environ.get("NO_WHALES") != "1":
        try:
            n_q = whale_mod.attach_whales(rows, http_json)
            log("whales", True, f"{n_q} markets checked, {sum(1 for r in rows if r.get('whales'))} games with a notable trade")
        except Exception as e:  # noqa
            log("whales", False, repr(e))
    if notifier:
        found, sent_n, status = notifier.run(rows, now)
        log("alerts", not status.startswith("failed"), f"{found} found, {sent_n} sent: {status}")
    if capture_only:
        print(f"capture-only: {len(rows)} games snapshotted")
        for l in LOG:
            print(("OK  " if l["ok"] else "FAIL"), l["source"], l["detail"])
        return 0
    slate["closing"] = closing
    out = os.environ.get("SLATE_OUT", "slate.json")
    with open(out, "w") as f:
        json.dump(slate, f, indent=1)
    print(f"wrote {out}: {len(rows)} games, {sum(len(r['bets']) for r in rows)} bets, {sum(1 for r in rows if r['arb'])} arbs")
    for l in LOG:
        print(("OK  " if l["ok"] else "FAIL"), l["source"], l["detail"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
