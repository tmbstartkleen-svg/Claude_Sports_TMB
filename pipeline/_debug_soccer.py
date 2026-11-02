#!/usr/bin/env python3
"""TEMPORARY debug script -- dumps the shape of Bovada's soccer catch-all response so we can see
why parse_event() finds 0 usable games out of 599 raw events. Deleted after use; not part of the
real pipeline."""
import json, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bovada as B

raw = B._http_json(B._url(B.SOCCER_PATH))
print("n blocks:", len(raw))
all_events = [ev for block in raw for ev in (block or {}).get("events") or []]
print("n events total:", len(all_events))
for ev in all_events[:3]:
    print("=" * 60)
    print("top-level keys:", list(ev.keys()))
    comps = ev.get("competitors") or []
    print("competitors:", [(c.get("name"), c.get("home")) for c in comps])
    for grp in (ev.get("displayGroups") or [])[:3]:
        print("  displayGroup desc:", grp.get("description"))
        for mkt in (grp.get("markets") or [])[:5]:
            print("    market desc:", repr(mkt.get("description")), "period:", mkt.get("period", {}).get("description") if isinstance(mkt.get("period"), dict) else mkt.get("period"))
            for o in (mkt.get("outcomes") or [])[:3]:
                print("      outcome desc:", repr(o.get("description")), "price:", o.get("price"))
