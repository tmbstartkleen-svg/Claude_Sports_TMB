# Specialist team

These are roles, not running services. Each is a focused brief that Claude runs as a separate agent in a work session, reads the live web, and reports back with sources. Nothing here runs by itself in your repo. Ask Claude to "run the team" (or one role) and it launches them in parallel.

| Role | Question it answers | Output |
|---|---|---|
| Compliance and legal | Where is it legal and allowed to use sportsbooks and prediction markets? What do the terms of service and data terms say about bots, analytics and publishing data? What changes if you share or sell picks? Basic tax rules. Is any license or certification needed for personal use? | Sourced bullets, a short "what to actually do" list. Not legal advice. |
| Data sources | The best free, keyless feeds, verified: NHL goalies, MLB probable pitchers and lineups, NBA availability, NFL, soccer xG and lineups, tennis, MMA, free historical odds for backtests | Endpoint, fields, limits, one-line stdlib call, VERIFIED or NOT VERIFIED |
| Modeling evidence | What the evidence says about where edges exist, the best public model per sport, the right blend with the market, how many bets before skill shows | Ranked upgrade list with sources |
| Odds feeds | Cheapest way to get many books: free tiers, prices, whether Pinnacle and props are included, how to stay inside free credits | Comparison table and a free and a under-$30 plan |
| Code review | Independent read of the pipeline for math bugs, wrong assumptions about live data, name-matching failures, workflow and file-corruption risks, security | Up to 12 ranked findings with fixes; no edits |
| Design and UX | Open the app at phone and desktop width and judge clarity, navigation overload, empty states, contrast, wording for a non-expert | Ranked changes and a simpler tab layout |

More roles worth adding when needed: one per sport (a deep dive on one league's data and model), a tax and bookkeeping role, a security reviewer for secrets and tokens, and a data-quality auditor that checks the first live slate against the real games.

How findings get used: Claude reads all six reports, drops anything without a source, fixes real bugs, and changes the product only where the evidence supports it.
