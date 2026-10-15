"""One-off in GitHub Actions: download Hugging Face historical closing-odds datasets (CC-BY-4.0, minmaxxxer) to backtest/
so our models' calibration can be checked against real graded closing lines instead of only our own backtest."""
import os, urllib.request
FILES = {
    "nfl_2026_odds.csv": "nfl-odds-2026/resolve/main/nfl_2026_odds.csv",
    "nhl_2025_26_closing_odds.csv": "nhl-closing-odds-2025-26/resolve/main/nhl_2025_26_closing_odds.csv",
    "mlb_2025_closing_odds.csv": "mlb-closing-odds-2025/resolve/main/mlb_2025_closing_odds.csv",
    "premier_league_2025_26_closing_odds.csv": "premier-league-closing-odds-2025-26/resolve/main/premier_league_2025_26_closing_odds.csv",
    "laliga_seriea_bundesliga_2025_26_closing_odds.csv": "laliga-serie-a-bundesliga-closing-odds-2025-26/resolve/main/laliga_serie_a_bundesliga_2025_26_closing_odds.csv",
    "atp_wta_2025_closing_odds.csv": "atp-wta-closing-odds-2025/resolve/main/atp_wta_2025_closing_odds.csv",
}
os.makedirs("backtest", exist_ok=True)
ok, bad = [], []
for out, path in FILES.items():
    url = f"https://huggingface.co/datasets/minmaxxxer/{path}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "edge-suite-slate/1.0"})
        with urllib.request.urlopen(req, timeout=30) as r:
            data = r.read()
        open(f"backtest/{out}", "wb").write(data)
        ok.append((out, len(data)))
    except Exception as e:  # noqa
        bad.append((out, repr(e)[:150]))
print("OK:", ok)
print("FAILED:", bad)
