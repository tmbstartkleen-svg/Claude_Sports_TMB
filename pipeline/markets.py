"""Opportunity finders that sit on top of the odds data: spread/total middles and cross-venue arbitrage.

Everything here is arithmetic on prices that were quoted at a moment in time. Lines move, limits apply, and
prediction-market prices below are estimates (fees and slippage are approximated). Verify prices before acting.
"""
import math

# standard deviation of final margin / final total, by sport (rough, from typical game scoring)
MARGIN_SD = {"nfl": 13.2, "ncaaf": 15.0, "nba": 12.0, "ncaab": 11.0, "wnba": 11.0, "nhl": 2.3, "mlb": 4.3,
             "epl": 1.7, "laliga": 1.6, "bundesliga": 1.9, "seriea": 1.6, "ligue1": 1.7, "mls": 1.8, "ucl": 1.8}
TOTAL_SD = {"nfl": 13.0, "ncaaf": 17.0, "nba": 19.0, "ncaab": 15.0, "wnba": 15.0, "nhl": 2.4, "mlb": 4.4,
            "epl": 1.6, "laliga": 1.5, "bundesliga": 1.8, "seriea": 1.5, "ligue1": 1.6, "mls": 1.7, "ucl": 1.7}
KALSHI_FEE = 0.07        # per-contract fee ~ 0.07 * p * (1 - p)
SUSPECT_ROI_PCT = 10.0     # a 'free' return this big is much more likely a mismatched market than a real arb
PM_SLIPPAGE = 0.01       # 1 cent buffer: displayed prices are not always fillable


def am_to_dec(a):
    a = float(a)
    if abs(a) < 100:
        return None
    return 1 + a / 100 if a > 0 else 1 + 100 / abs(a)


def _cdf(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def p_integers_between(lo, hi, mu, sd):
    """P(lo < X < hi) for integer-valued X ~ N(mu, sd), lo/hi exclusive. 0 if no integer fits."""
    m_lo, m_hi = math.floor(lo) + 1, math.ceil(hi) - 1
    if m_hi < m_lo:
        return 0.0
    return max(0.0, _cdf((m_hi + 0.5 - mu) / sd) - _cdf((m_lo - 0.5 - mu) / sd))


def _middle_ev(d1, d2, p_mid):
    """Stake split that equalises both outer outcomes. Returns (s1, s2, outer, middle, ev) per $1 total staked."""
    s1, s2 = d2 / (d1 + d2), d1 / (d1 + d2)
    outer = s1 * d1 - 1
    middle = s1 * d1 + s2 * d2 - 1
    return s1, s2, outer, middle, p_mid * middle + (1 - p_mid) * outer


def find_middles(g, sport, min_gap=1.0, top=6):
    """g has optional g['spreads'] = {book: {'home': (pt, american), 'away': (pt, american)}}
    and g['totals'] = {book: {'over': (pt, american), 'under': (pt, american)}}."""
    out = []
    sp = g.get("spreads") or {}
    if len(sp) >= 2 and sport in MARGIN_SD:
        pts = [v["home"][0] for v in sp.values() if "home" in v]
        mu = -sum(pts) / len(pts) if pts else 0.0     # expected home margin from the consensus line
        for b1, v1 in sp.items():
            for b2, v2 in sp.items():
                if b1 == b2 or "home" not in v1 or "away" not in v2:
                    continue
                h, a = v1["home"][0], v2["away"][0]
                gap = a + h                            # home covers if margin > -h, away covers if margin < a
                d1, d2 = am_to_dec(v1["home"][1]), am_to_dec(v2["away"][1])
                if gap < min_gap or not d1 or not d2:
                    continue
                pm = p_integers_between(-h, a, mu, MARGIN_SD[sport])
                s1, s2, outer, mid, ev = _middle_ev(d1, d2, pm)
                out.append({"kind": "spread", "legA": f"{g['home']} {h:+g} @ {b1} ({v1['home'][1]:+g})", "legB": f"{g['away']} {a:+g} @ {b2} ({v2['away'][1]:+g})",
                            "gap": round(gap, 1), "pMiddle": round(pm, 4), "outerPct": round(outer * 100, 2), "middlePct": round(mid * 100, 1),
                            "evPct": round(ev * 100, 2), "splitA": round(s1, 3), "splitB": round(s2, 3)})
    tt = g.get("totals") or {}
    if len(tt) >= 2 and sport in TOTAL_SD:
        pts = [v["over"][0] for v in tt.values() if "over" in v]
        mu = sum(pts) / len(pts) if pts else 0.0
        for b1, v1 in tt.items():
            for b2, v2 in tt.items():
                if b1 == b2 or "over" not in v1 or "under" not in v2:
                    continue
                o, u = v1["over"][0], v2["under"][0]
                gap = u - o                            # over wins if total > o, under wins if total < u
                d1, d2 = am_to_dec(v1["over"][1]), am_to_dec(v2["under"][1])
                if gap < min_gap or not d1 or not d2:
                    continue
                pm = p_integers_between(o, u, mu, TOTAL_SD[sport])
                s1, s2, outer, mid, ev = _middle_ev(d1, d2, pm)
                out.append({"kind": "total", "legA": f"Over {o:g} @ {b1} ({v1['over'][1]:+g})", "legB": f"Under {u:g} @ {b2} ({v2['under'][1]:+g})",
                            "gap": round(gap, 1), "pMiddle": round(pm, 4), "outerPct": round(outer * 100, 2), "middlePct": round(mid * 100, 1),
                            "evPct": round(ev * 100, 2), "splitA": round(s1, 3), "splitB": round(s2, 3)})
    out.sort(key=lambda m: -m["evPct"])
    return out[:top]


def pm_cost(source, p):
    """Estimated all-in cost per $1 payout of a prediction-market contract priced p."""
    fee = KALSHI_FEE * p * (1 - p) if source == "kalshi" else 0.0
    return p + fee + PM_SLIPPAGE


def cross_arbs(row, pm_hits):
    """Book price on one side + prediction-market price on the other side of a 2-way game.
    pm_hits: [{'source','title','url','home': p or None,'away': p or None}]"""
    out = []
    if "draw" in row["best"]:
        return out  # 3-way games need a market for every outcome; not attempted
    for m in pm_hits:
        for side, other in (("home", "away"), ("away", "home")):
            p = m.get(side)
            if p is None or not (0 < p < 1):
                continue
            d = row["best"][other]["decimal"]
            cost = 1 / d + pm_cost(m["source"], p)
            if cost < 1:
                out.append({"bookSide": other, "book": row["best"][other]["book"], "american": row["best"][other]["american"],
                            "pmSide": side, "pmSource": m["source"], "pmTitle": m["title"], "pmPrice": round(p, 3), "url": m.get("url", ""),
                            "allInCost": round(cost, 4), "roiPct": round((1 / cost - 1) * 100, 2),
                            "suspect": (1 / cost - 1) * 100 > SUSPECT_ROI_PCT,
                            "note": "Estimate: includes approximate fees and 1c slippage. Confirm both prices before acting."
                                    + (" Unusually large: probably a mismatched market, check the title." if (1 / cost - 1) * 100 > SUSPECT_ROI_PCT else "")})
    out.sort(key=lambda a: -a["roiPct"])
    return out
