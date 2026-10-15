"""One-off in GitHub Actions (needs ESPN access): checks our Elo/soccer models' calibration and the 25% blend weight
against independently graded closing-line datasets (backtest/*.csv, from Hugging Face, CC-BY-4.0, minmaxxxer).
This is a real market, not our own backtest grading itself. Writes backtest_report.json."""
import csv, json, math, sys
from datetime import datetime, date, timedelta
sys.path.insert(0, "pipeline")
import model as M
import soccer as S
from names import same as same_team

DIRECT = {"nfl": ("nfl_2026_odds.csv", "home_team", "away_team", "date_et", "home_score", "away_score", "close_home_win_prob"),
          "nhl": ("nhl_2025_26_closing_odds.csv", "home_team", "away_team", "date_et", "home_score", "away_score", "close_home_win_prob"),
          "mlb": ("mlb_2025_closing_odds.csv", "home_team", "away_team", "date_et", "home_score", "away_score", "close_home_win_prob")}
SOCCER3 = {"epl": ("premier_league_2025_26_closing_odds.csv", None),
           "laliga": ("laliga_seriea_bundesliga_2025_26_closing_odds.csv", "LaLiga"),
           "seriea": ("laliga_seriea_bundesliga_2025_26_closing_odds.csv", "Serie A"),
           "bundesliga": ("laliga_seriea_bundesliga_2025_26_closing_odds.csv", "Bundesliga")}


def brier_ll(pairs):
    n = len(pairs)
    if not n:
        return None
    brier = sum((p - y) ** 2 for p, y in pairs) / n
    ll = -sum(math.log(max(1e-9, min(1 - 1e-9, p if y else 1 - p))) for p, y in pairs) / n
    return {"n": n, "brier": round(brier, 4), "logLoss": round(ll, 4)}


def best_weight(model_probs, market_probs, actuals):
    """Grid-search the blend weight that minimizes log-loss on this real market data (research flagged the fixed 25% as unfit)."""
    best, best_ll = None, None
    for w in [i / 20 for i in range(21)]:
        ll = 0.0
        for pm, pk, y in zip(model_probs, market_probs, actuals):
            p = max(1e-6, min(1 - 1e-6, w * pm + (1 - w) * pk))
            ll += -math.log(p if y else 1 - p)
        ll /= len(actuals)
        if best_ll is None or ll < best_ll:
            best_ll, best = ll, w
    return best, round(best_ll, 4)


report = {}
for sport, (fname, hcol, acol, dcol, hscol, ascol, pcol) in DIRECT.items():
    try:
        rows = list(csv.DictReader(open(f"backtest/{fname}")))
        res = M.fetch_results(sport, cache=True)
        mdl = M.build(sport, res)
        model_p, market_p, actual, matched, unmatched = [], [], [], 0, 0
        for r in rows:
            try:
                d = datetime.fromisoformat(r[dcol]).date()
            except ValueError:
                continue
            p_model = M.predict(sport, mdl, r[hcol], r[acol], d)
            if p_model is None:
                unmatched += 1
                continue
            try:
                y = 1 if float(r[hscol]) > float(r[ascol]) else 0
                pk = float(r[pcol])
            except (ValueError, TypeError):
                continue
            model_p.append(p_model); market_p.append(pk); actual.append(y); matched += 1
        pairs_model = list(zip(model_p, actual))
        pairs_market = list(zip(market_p, actual))
        w, ll = best_weight(model_p, market_p, actual) if matched else (None, None)
        report[sport] = {"matched": matched, "unmatched": unmatched, "ourModel": brier_ll(pairs_model), "market": brier_ll(pairs_market),
                         "bestBlendWeight": w, "bestBlendLogLoss": ll, "currentFixedWeight": M.MODEL_WEIGHT,
                         "currentBlendLogLoss": round(sum(-math.log(max(1e-6, min(1 - 1e-6, M.blend(pm, pk) if y else 1 - M.blend(pm, pk))))
                                                          for pm, pk, y in zip(model_p, market_p, actual)) / matched, 4) if matched else None}
    except Exception as e:  # noqa
        report[sport] = {"error": repr(e)[:300]}

for sport, (fname, league_filter) in SOCCER3.items():
    try:
        rows = [r for r in csv.DictReader(open(f"backtest/{fname}")) if not league_filter or r.get("league") == league_filter]
        res = M.fetch_results(sport, path=S.LEAGUES[sport], cache=True)
        mdl = S.build(res)
        model_h, model_d, model_a, mk_h, mk_d, mk_a, actual, matched, unmatched = [], [], [], [], [], [], [], 0, 0
        for r in rows:
            pr = S.predict(mdl, r["home_team"], r["away_team"])
            if not pr:
                unmatched += 1
                continue
            try:
                hg, ag = float(r["home_goals"]), float(r["away_goals"])
                y = "home" if hg > ag else "away" if ag > hg else "draw"
                ph, pd, pa = float(r["close_home_prob"]), float(r["close_draw_prob"]), float(r["close_away_prob"])
            except (ValueError, TypeError, KeyError):
                continue
            model_h.append(pr[0]); model_d.append(pr[1]); model_a.append(pr[2])
            mk_h.append(ph); mk_d.append(pd); mk_a.append(pa)
            actual.append(y); matched += 1

        def three_way_ll(hs, ds, as_):
            if not matched:
                return None
            ll = 0.0
            for h, d, a, y in zip(hs, ds, as_, actual):
                p = {"home": h, "draw": d, "away": a}[y]
                ll += -math.log(max(1e-6, p))
            return round(ll / matched, 4)
        report[sport] = {"matched": matched, "unmatched": unmatched, "ourModelLogLoss": three_way_ll(model_h, model_d, model_a),
                         "marketLogLoss": three_way_ll(mk_h, mk_d, mk_a)}
    except Exception as e:  # noqa
        report[sport] = {"error": repr(e)[:300]}

json.dump(report, open("backtest_report.json", "w"), indent=1)
print(json.dumps(report, indent=1))
