"""One-off in GitHub Actions (needs ESPN access): checks our Elo/soccer models' calibration and the 25% blend weight
against independently graded closing-line datasets (backtest/*.csv, from Hugging Face, CC-BY-4.0, minmaxxxer).

Walks forward through OUR OWN results history in order and predicts each game with the ratings as they stood at
that point in time (same as a live run would have), matching it to the dataset row for that game, BEFORE updating
ratings with the result. This matters: calling model.predict() against the final, fully-updated model instead would
score games using ratings that already include their own outcome and every later game's outcome too (lookahead bias),
which a first version of this script did, and it made NFL (a short, still-open season) look implausibly good.
Writes backtest_report.json."""
import csv, json, math, sys
from datetime import datetime
sys.path.insert(0, "pipeline")
import model as M
import soccer as S
from names import same as same_team

DIRECT = {"nfl": ("nfl_2026_odds.csv", "home_team", "away_team", "date_et", "home_score", "away_score", "close_home_win_prob"),
          "nhl": ("nhl_2025_26_closing_odds.csv", "home_team", "away_team", "date_et", "home_score", "away_score", "close_home_win_prob"),
          "mlb": ("mlb_2025_closing_odds.csv", "home_team", "away_team", "date_et", "home_score", "away_score", "close_home_win_prob")}
SOCCER3 = {"epl": ("premier_league_2025_26_closing_odds.csv", None, "home_team", "away_team", "date_uk", "home_goals", "away_goals",
                   "close_home_prob", "close_draw_prob", "close_away_prob"),
           "laliga": ("laliga_seriea_bundesliga_2025_26_closing_odds.csv", "LaLiga", "home_team", "away_team", "date_uk", "home_goals", "away_goals",
                      "close_home_prob", "close_draw_prob", "close_away_prob"),
           "seriea": ("laliga_seriea_bundesliga_2025_26_closing_odds.csv", "Serie A", "home_team", "away_team", "date_uk", "home_goals", "away_goals",
                      "close_home_prob", "close_draw_prob", "close_away_prob"),
           "bundesliga": ("laliga_seriea_bundesliga_2025_26_closing_odds.csv", "Bundesliga", "home_team", "away_team", "date_uk", "home_goals", "away_goals",
                          "close_home_prob", "close_draw_prob", "close_away_prob")}


def _date(s):
    try:
        return datetime.fromisoformat(s).date()
    except ValueError:
        return None


def _match(g_date, g_home, g_away, pool):
    """pool: list of (row, used-flag box, date, home, away). Same two teams within 2 days, not already matched."""
    for row, used, d, h, a in pool:
        if used[0]:
            continue
        if d and g_date and abs((d - g_date).days) > 2:
            continue
        if same_team(g_home, h) and same_team(g_away, a):
            used[0] = True
            return row
    return None


def brier_ll(pairs):
    n = len(pairs)
    if not n:
        return None
    brier = sum((p - y) ** 2 for p, y in pairs) / n
    ll = -sum(math.log(max(1e-9, min(1 - 1e-9, p if y else 1 - p))) for p, y in pairs) / n
    return {"n": n, "brier": round(brier, 4), "logLoss": round(ll, 4)}


def best_weight(model_p, market_p, actual):
    """Grid-search the blend weight that minimizes log-loss on this held-out market data (research flagged the fixed 25% as unfit)."""
    best, best_ll = None, None
    for i in range(21):
        w = i / 20
        ll = 0.0
        for pm, pk, y in zip(model_p, market_p, actual):
            p = max(1e-6, min(1 - 1e-6, w * pm + (1 - w) * pk))
            ll += -math.log(p if y else 1 - p)
        ll /= len(actual)
        if best_ll is None or ll < best_ll:
            best_ll, best = ll, w
    return best, round(best_ll, 4)


report = {}

for sport, (fname, hcol, acol, dcol, hscol, ascol, pcol) in DIRECT.items():
    try:
        rows = list(csv.DictReader(open(f"backtest/{fname}")))
        pool = [(r, [False], _date(r[dcol]), r[hcol], r[acol]) for r in rows]
        res = M.fetch_results(sport, cache=True)
        c = M.CFG[sport]
        R, last = {}, {}
        prev_day = None
        model_p, market_p, actual = [], [], []
        for g in res:
            d = datetime.strptime(g["date"], "%Y-%m-%d").date()
            if prev_day and (d - prev_day).days > 90:
                for k in R:
                    R[k] = 1500 + (R[k] - 1500) * (1 - c["regress"])
            prev_day = d
            h, a = g["home"], g["away"]
            rh, ra = R.get(h, 1500), R.get(a, 1500)
            dh = (d - last[h]).days if h in last else None
            da = (d - last[a]).days if a in last else None
            diff = rh - ra + c["home"] + M._rest_adj(sport, dh) - M._rest_adj(sport, da)
            p = M._win_prob(diff)
            if h in R and a in R:  # same condition build() uses to count a prediction
                row = _match(d, h, a, pool)
                if row is not None:
                    try:
                        y = 1 if float(row[hscol]) > float(row[ascol]) else 0
                        pk = float(row[pcol])
                        model_p.append(p); market_p.append(pk); actual.append(y)
                    except (ValueError, TypeError):
                        pass
            if g["hs"] != g["as"]:
                won = 1 if g["hs"] > g["as"] else 0
                margin = abs(g["hs"] - g["as"])
                mult = math.log(margin + 1) * 2.2 / ((diff if won else -diff) * 0.001 + 2.2)
                delta = c["k"] * mult * (won - p)
                R[h] = rh + delta
                R[a] = ra - delta
            last[h] = last[a] = d
        matched = len(actual)
        w, ll = best_weight(model_p, market_p, actual) if matched else (None, None)
        cur_ll = round(sum(-math.log(max(1e-6, min(1 - 1e-6, M.blend(pm, pk) if y else 1 - M.blend(pm, pk))))
                           for pm, pk, y in zip(model_p, market_p, actual)) / matched, 4) if matched else None
        report[sport] = {"matched": matched, "unmatchedRows": len(rows) - matched, "ourModel": brier_ll(list(zip(model_p, actual))),
                         "market": brier_ll(list(zip(market_p, actual))), "bestBlendWeight": w, "bestBlendLogLoss": ll,
                         "currentFixedWeight": M.MODEL_WEIGHT, "currentBlendLogLoss": cur_ll,
                         "note": "point-in-time: each game used only ratings built from earlier games, like a live run would have"}
    except Exception as e:  # noqa
        report[sport] = {"error": repr(e)[:300]}

for sport, (fname, league_filter, hcol, acol, dcol, hgcol, agcol, phcol, pdcol, pacol) in SOCCER3.items():
    try:
        rows = [r for r in csv.DictReader(open(f"backtest/{fname}")) if not league_filter or r.get("league") == league_filter]
        pool = [(r, [False], _date(r[dcol]), r[hcol], r[acol]) for r in rows]
        res = M.fetch_results(sport, path=S.LEAGUES[sport], cache=True)
        draws = sum(1 for g in res if g["hs"] == g["as"])
        base = min(0.34, max(0.18, draws / len(res))) if res else 0.26
        R, prev = {}, None
        model_h, model_d, model_a, mk_h, mk_d, mk_a, actual = [], [], [], [], [], [], []
        for g in res:
            d = datetime.strptime(g["date"], "%Y-%m-%d").date()
            if prev and (d - prev).days > 60:
                for k in R:
                    R[k] = 1500 + (R[k] - 1500) * (1 - S.REGRESS)
            prev = d
            h, a = g["home"], g["away"]
            rh, ra = R.get(h, 1500), R.get(a, 1500)
            diff = rh - ra + S.HOME_ELO
            p = S.probs(diff, base)
            out = "home" if g["hs"] > g["as"] else "away" if g["hs"] < g["as"] else "draw"
            if h in R and a in R:
                row = _match(d, h, a, pool)
                if row is not None:
                    try:
                        y = out
                        ph, pd, pa = float(row[phcol]), float(row[pdcol]), float(row[pacol])
                        model_h.append(p[0]); model_d.append(p[1]); model_a.append(p[2])
                        mk_h.append(ph); mk_d.append(pd); mk_a.append(pa); actual.append(y)
                    except (ValueError, TypeError):
                        pass
            e = M._win_prob(diff) if False else S._e(diff)
            actual_pts = 1.0 if out == "home" else 0.0 if out == "away" else 0.5
            mult = math.log(abs(g["hs"] - g["as"]) + 1) + 1 if out != "draw" else 1.0
            R[h] = rh + S.K * mult * (actual_pts - e)
            R[a] = ra - S.K * mult * (actual_pts - e)
            prev = d

        def three_way_ll(hs, ds, as_):
            n = len(actual)
            if not n:
                return None
            ll = 0.0
            for h, d, a, y in zip(hs, ds, as_, actual):
                p = {"home": h, "draw": d, "away": a}[y]
                ll += -math.log(max(1e-6, p))
            return round(ll / n, 4)
        matched = len(actual)
        report[sport] = {"matched": matched, "unmatchedRows": len(rows) - matched,
                         "ourModelLogLoss": three_way_ll(model_h, model_d, model_a), "marketLogLoss": three_way_ll(mk_h, mk_d, mk_a),
                         "note": "point-in-time: each game used only ratings built from earlier games, like a live run would have"}
    except Exception as e:  # noqa
        report[sport] = {"error": repr(e)[:300]}

json.dump(report, open("backtest_report.json", "w"), indent=1)
print(json.dumps(report, indent=1))
