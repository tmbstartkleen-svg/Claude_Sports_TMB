"""One place that decides when two team-name strings mean the same team (ESPN vs The Odds API vs Kalshi, accents, punctuation)."""
import re, unicodedata

ALIASES = {  # canonical forms (after canon() cleanup) -> shared key
    "intermilan": "internazionale", "inter": "internazionale", "parissaintgermain": "parissg", "psg": "parissg",
    "manutd": "manchesterunited", "manchesterutd": "manchesterunited", "mancity": "manchestercity",
    "spurs": "tottenhamhotspur", "tottenham": "tottenhamhotspur", "wolves": "wolverhamptonwanderers",
    "newcastle": "newcastleunited", "brighton": "brightonandhovealbion", "westham": "westhamunited",
    "leeds": "leedsunited", "atleticomadrid": "atleticodemadrid", "athleticbilbao": "athleticclub",
    "bayern": "bayernmunich", "bayernmunchen": "bayernmunich", "dortmund": "borussiadortmund",
    "leverkusen": "bayerleverkusen", "mgladbach": "borussiamonchengladbach", "lagalaxy": "lagalaxy",
}
DROP = {"fc", "cf", "afc", "sc"}


def canon(s):
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower().replace("&", " and ")
    toks = [("st" if t == "saint" else t) for t in re.split(r"[^a-z0-9]+", s) if t and t not in DROP]
    c = "".join(toks)
    return ALIASES.get(c, c)


def same(a, b):
    ca, cb = canon(a), canon(b)
    if not ca or not cb:
        return False
    return ca == cb or (min(len(ca), len(cb)) >= 8 and (ca in cb or cb in ca))
