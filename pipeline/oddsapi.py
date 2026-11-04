"""The Odds API (the-odds-api.com): the one real source in this project that needs a key, because it's
the only way to get actual FanDuel odds -- FanDuel's own site has no public, unauthenticated feed
(confirmed by research: its API needs a logged-in browser session's auth token, not a plain key; see
this repo's commit "Research FanDuel/BetMGM/Caesars free odds feeds"). The Odds API resells a real
licensing deal with the books, which is the legitimate way every paid competitor tool (OddsJam
included) actually gets FanDuel's lines.

Entirely optional and off by default: without ODDS_API_KEY set, nothing here is ever called, and the
rest of the pipeline (ESPN, Bovada, Kalshi, Polymarket -- all genuinely free and keyless) works exactly
as before. This is the one deliberate exception to "no paid key, anywhere": the project owner supplied
their own key after being told exactly what a free/keyless path could and couldn't get, so this uses
THEIR key, under THEIR account, on the FREE TIER (no credit card required to sign up) -- never bundled,
baked into the repo, or required for the project to run.

Credit budget: the free tier is 500 credits/month, and a /v4/sports/{sport}/odds call costs
`markets x regions` credits regardless of how many games or books it returns (confirmed from The Odds
API's own published pricing). We ask for exactly one market (h2h = moneyline, matching this project's
moneyline-only philosophy) and one region (us), so every call costs exactly 1 credit. build_slate.py
only calls this on full runs (not the 15-minute capture runs) and only for a sport that already has at
least one ESPN-sourced game today, so an off-season sport never wastes a call. At 3 full runs/day and
typically 3-6 sports in season at once, that lands well under 500/month -- see README for the math and
how to trim ODDS_API_SPORTS if actual usage (shown in slate["sources"]) runs hot.
"""
import json, os, urllib.parse, urllib.request

BASE = "https://api.the-odds-api.com/v4"
KEY = os.environ.get("ODDS_API_KEY")
# Bookmaker key (as The Odds API names it) -> our display name for the UI's book badges.
BOOK_NAMES = {
    "fanduel": "FanDuel", "draftkings": "DraftKings", "betmgm": "BetMGM", "caesars": "Caesars",
    "espnbet": "ESPN BET", "fanatics": "Fanatics", "betrivers": "BetRivers", "bovada": "Bovada",
    "ballybet": "Bally Bet", "windcreek": "Wind Creek", "hardrockbet": "Hard Rock Bet",
}


def available():
    return bool(KEY)


def _url(odds_api_sport, regions="us", markets="h2h", odds_format="american"):
    q = urllib.parse.urlencode({"apiKey": KEY, "regions": regions, "markets": markets, "oddsFormat": odds_format})
    return f"{BASE}/sports/{odds_api_sport}/odds?{q}"


def _http_json(url, timeout=20):
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "edge-suite-slate/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        remaining = r.headers.get("x-requests-remaining")
        used = r.headers.get("x-requests-used")
        return json.load(r), remaining, used


def _american(price):
    """The Odds API returns requested-format odds as a number already (e.g. -150, 130); a few edge
    cases arrive as strings. None/garbage -> None, same contract as every other source here."""
    if price is None:
        return None
    try:
        v = float(price)
    except (TypeError, ValueError):
        return None
    return v if v != 0 else None


def parse_event(ev):
    """One event -> {home, away, start, books:{DisplayName:{home,away}}}. Returns None if the event
    doesn't name both teams or no bookmaker carries a usable two-sided h2h price."""
    home, away = ev.get("home_team"), ev.get("away_team")
    if not home or not away:
        return None
    books = {}
    for bm in ev.get("bookmakers") or []:
        key = (bm.get("key") or "").lower()
        name = BOOK_NAMES.get(key)
        if not name:
            continue  # a book we don't recognize/display yet -- skip rather than guess a badge for it
        h2h = next((m for m in bm.get("markets") or [] if m.get("key") == "h2h"), None)
        if not h2h:
            continue
        h = a = None
        for o in h2h.get("outcomes") or []:
            if o.get("name") == home:
                h = _american(o.get("price"))
            elif o.get("name") == away:
                a = _american(o.get("price"))
        if h is not None and a is not None:
            books[name] = {"home": h, "away": a}
    if not books:
        return None
    return {"home": home, "away": away, "start": ev.get("commence_time"), "books": books}


def fetch(odds_api_sport, getter=None):
    """All usable games for one Odds API sport key. Never raises past this boundary -- a key problem,
    rate limit, or shape change degrades to [] (logged by the caller), same contract as every other
    optional source in this project."""
    if not KEY:
        return [], None, None
    get = getter or _http_json
    raw, remaining, used = get(_url(odds_api_sport))
    games = []
    for ev in raw or []:
        try:
            g = parse_event(ev)
        except Exception:  # noqa  one malformed event must never drop the rest
            g = None
        if g:
            games.append(g)
    return games, remaining, used
