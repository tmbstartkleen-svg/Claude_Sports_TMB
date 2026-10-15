"""Data collector network.

Each collector is a small JSON spec in network.json (url template, where the list of items is, which field means what).
One generic runner executes them all, so adding a source for a new sport is adding a spec, not writing code. The runner
keeps a health record per collector (network_health.json): consecutive failures, last error, and when a collector that
keeps failing is paused. When a collector's paths do not match the real response, it records the response's key
structure so the spec can be corrected from the real run instead of guessed.

Read-only: it only GETs public data. Never logs or sends credentials.
"""
import csv, io, json, os, sys, urllib.request
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC_PATH = os.environ.get("NETWORK_SPEC", os.path.join(HERE, "network.json"))
DISABLE_AFTER = 5            # consecutive failures before a collector is paused
PAUSE_HOURS = 24
MAX_ITEMS = 5000


def _get(url, timeout=25):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (edge-suite-network)", "Accept": "application/json,text/csv,*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def dig(obj, path):
    """Dotted path; a segment ending in [] flattens a list. 'a.b[].c' -> every c under every item of a.b."""
    cur = [obj]
    for seg in path.split("."):
        if not seg:
            continue
        flat = seg.endswith("[]")
        key = seg[:-2] if flat else seg
        nxt = []
        for c in cur:
            v = c.get(key) if isinstance(c, dict) and key else c
            if flat and isinstance(v, list):
                nxt.extend(v)
            elif v is not None:
                nxt.append(v)
        cur = nxt
    return cur


def first(obj, path):
    r = dig(obj, path)
    return r[0] if r else None


def shape(obj, depth=3, width=8):
    """Compact key tree of a response, used to correct a spec that did not match."""
    if depth == 0:
        return type(obj).__name__
    if isinstance(obj, dict):
        return {k: shape(v, depth - 1, width) for k, v in list(obj.items())[:width]}
    if isinstance(obj, list):
        return [shape(obj[0], depth - 1, width)] if obj else []
    return type(obj).__name__


def expand_urls(spec, now):
    url = spec["url"]
    if "{date}" in url:
        return [url.replace("{date}", (now + timedelta(days=d)).strftime(spec.get("dateFormat", "%Y-%m-%d"))) for d in spec.get("dayOffsets", [0])]
    return [url.replace("{season}", str(now.year)).replace("{season2}", f"{str(now.year)[2:]}{str(now.year + 1)[2:]}")]


def parse(spec, text):
    """Returns (items, sample_shape). items are dicts keyed by the spec's field names."""
    items, sample = [], None
    if spec.get("format") == "csv":
        rows = list(csv.DictReader(io.StringIO(text)))
        sample = {"columns": list(rows[0].keys())[:20]} if rows else {"columns": []}
        for r in rows[:MAX_ITEMS]:
            items.append({k: r.get(v) for k, v in spec["fields"].items()})
        return items, sample
    data = json.loads(text)
    sample = shape(data)
    for it in dig(data, spec["items"])[:MAX_ITEMS]:
        items.append({k: first(it, v) for k, v in spec["fields"].items()})
    return items, sample


def run_one(spec, now, getter=_get):
    """Returns dict: ok, n, items, error, shape."""
    out = {"ok": False, "n": 0, "items": [], "error": None, "shape": None}
    try:
        for url in expand_urls(spec, now):
            items, sample = parse(spec, getter(url))
            out["shape"] = sample
            req = spec.get("required", [])
            good = [i for i in items if all(i.get(f) not in (None, "") for f in req)]
            out["items"] += good
            if items and not good:
                out["error"] = f"{len(items)} items found but none had required fields {req}"
        out["n"] = len(out["items"])
        out["ok"] = out["n"] > 0 and out["error"] is None
        if not out["ok"] and not out["error"]:
            out["error"] = "no items matched the spec (could be an off day, or the item path is wrong)"
    except Exception as e:  # noqa
        out["error"] = repr(e)[:200]
    return out


def load_specs(path=None):
    with open(path or SPEC_PATH) as f:
        return json.load(f)["collectors"]


def load_health(path):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def run_all(specs, sports=None, health_path=None, now=None, getter=_get):
    """Run every enabled collector (for the given sports, if set). Returns (results by id, summary rows)."""
    now = now or datetime.now(timezone.utc)
    health_path = health_path or os.environ.get("NETWORK_HEALTH", "network_health.json")
    health = load_health(health_path)
    results, rows = {}, []
    for s in specs:
        if not s.get("enabled", True) or (sports and s["sport"] not in sports):
            continue
        h = health.setdefault(s["id"], {"fails": 0, "lastOk": None, "lastError": None, "pausedUntil": None})
        row = {"id": s["id"], "sport": s["sport"], "kind": s["kind"], "verified": bool(s.get("verified")), "note": s.get("note", "")}
        if h.get("pausedUntil") and now < datetime.fromisoformat(h["pausedUntil"]):
            row.update(ok=False, n=0, status="paused", error=h["lastError"])
            rows.append(row)
            continue
        r = run_one(s, now, getter)
        results[s["id"]] = r
        if r["ok"]:
            h.update(fails=0, lastOk=now.isoformat(timespec="seconds"), lastError=None, pausedUntil=None)
        else:
            h["fails"] += 1
            h["lastError"] = r["error"]
            if h["fails"] >= DISABLE_AFTER:
                h["pausedUntil"] = (now + timedelta(hours=PAUSE_HOURS)).isoformat(timespec="seconds")
        row.update(ok=r["ok"], n=r["n"], status="ok" if r["ok"] else "failing", error=r["error"], fails=h["fails"])
        if not r["ok"]:
            row["shape"] = r["shape"]   # lets the spec be corrected from the real response
        rows.append(row)
    try:
        with open(health_path, "w") as f:
            json.dump(health, f, separators=(",", ":"))
    except OSError:
        pass
    return results, rows


if __name__ == "__main__":
    # python pipeline/network.py            run all collectors and print a health table
    res, rows = run_all(load_specs(), health_path=os.environ.get("NETWORK_HEALTH", "/tmp/network_health.json"))
    for r in rows:
        print(("OK  " if r["ok"] else "FAIL"), r["id"], r["n"], (r["error"] or "")[:100])
