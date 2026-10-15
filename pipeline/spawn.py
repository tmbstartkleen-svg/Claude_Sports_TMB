"""Add a new collector to the network without writing code.

  python pipeline/spawn.py probe URL                 show the structure of a response, to pick the paths
  python pipeline/spawn.py add --id tennis_atp --sport tennis --kind results \
      --url "https://example.com/api/{date}" --items "events[]" \
      --field home=home.name --field away=away.name --required home,away [--format csv] [--note "..."]
  python pipeline/spawn.py check ID                  dry-run one collector and print what it returned

New collectors are saved with verified=false until a real run proves them. Only https GET requests are allowed.
"""
import argparse, json, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import network as N
from datetime import datetime, timezone

ID_RE = re.compile(r"^[a-z0-9_]{3,40}$")


def validate(spec):
    errs = []
    if not ID_RE.match(spec.get("id", "")):
        errs.append("id must be 3-40 chars of a-z, 0-9, _")
    if not str(spec.get("url", "")).startswith("https://"):
        errs.append("url must start with https://")
    host = str(spec.get("url", "")).split("/")[2] if str(spec.get("url", "")).count("/") >= 2 else ""
    if "@" in host:
        errs.append("url must not contain credentials")
    if not spec.get("fields"):
        errs.append("at least one --field name=path is required")
    if spec.get("format") != "csv" and not spec.get("items"):
        errs.append("--items (path to the list) is required for JSON sources")
    for r in spec.get("required", []):
        if r not in spec.get("fields", {}):
            errs.append(f"required field '{r}' is not in --field")
    return errs


def add(spec, path=None):
    path = path or N.SPEC_PATH
    data = json.load(open(path))
    if any(c["id"] == spec["id"] for c in data["collectors"]):
        raise ValueError(f"collector '{spec['id']}' already exists")
    errs = validate(spec)
    if errs:
        raise ValueError("; ".join(errs))
    spec["verified"] = False
    data["collectors"].append(spec)
    with open(path, "w") as f:
        json.dump(data, f, indent=1)
    return spec


def main(argv=None):
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("probe"); p.add_argument("url")
    a = sub.add_parser("add")
    for k in ("id", "sport", "kind", "url"):
        a.add_argument("--" + k, required=True)
    a.add_argument("--items", default=""); a.add_argument("--field", action="append", default=[]); a.add_argument("--required", default="")
    a.add_argument("--format", default="json"); a.add_argument("--note", default="")
    c = sub.add_parser("check"); c.add_argument("id")
    args = ap.parse_args(argv)
    if args.cmd == "probe":
        text = N._get(args.url)
        try:
            print(json.dumps(N.shape(json.loads(text), depth=4), indent=1))
        except ValueError:
            print("not JSON; first lines:\n" + "\n".join(text.splitlines()[:3]))
    elif args.cmd == "add":
        spec = {"id": args.id, "sport": args.sport, "kind": args.kind, "url": args.url,
                "fields": dict(f.split("=", 1) for f in args.field), "required": [r for r in args.required.split(",") if r]}
        if args.items: spec["items"] = args.items
        if args.format == "csv": spec["format"] = "csv"
        if args.note: spec["note"] = args.note
        add(spec); print("added", spec["id"], "(unverified until a real run succeeds)")
    else:
        spec = next((s for s in N.load_specs() if s["id"] == args.id), None)
        if not spec: sys.exit("no such collector")
        r = N.run_one(spec, datetime.now(timezone.utc))
        print("ok" if r["ok"] else "FAILED", r["n"], r["error"] or ""); print(json.dumps(r["items"][:3], indent=1))
        if not r["ok"]: print("response shape:", json.dumps(r["shape"], indent=1)[:1500])


if __name__ == "__main__":
    main()
