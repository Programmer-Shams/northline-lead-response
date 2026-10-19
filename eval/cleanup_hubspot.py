"""Delete the HubSpot records that test runs created (contacts plus their notes and deals).

Only touches leads listed in eval/.runs/<run>.json: contacts found by the run's plus-address emails,
and, for leads without a valid email, contacts with the lead's name created during that run.
Dry run by default.

Usage:
  .venv/bin/python eval/cleanup_hubspot.py --label smoke          # show what would be deleted
  .venv/bin/python eval/cleanup_hubspot.py --label smoke --yes    # delete
  .venv/bin/python eval/cleanup_hubspot.py --run r1019054406 --yes
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "eval"))
from envfile import load_env, require  # noqa: E402
from observe import EMAIL_PATTERN_OK, HubSpot, split_name  # noqa: E402

RUNS = ROOT / "eval" / ".runs"
RUN_WINDOW_MS = 30 * 60 * 1000


def contacts_for(hub, run, lead):
    if EMAIL_PATTERN_OK.match(lead["email"]):
        return hub.search([{"propertyName": "email", "operator": "EQ", "value": lead["email"]}])
    first, last = split_name(lead["name"])
    filters = [{"propertyName": "firstname", "operator": "EQ", "value": first},
               {"propertyName": "createdate", "operator": "BETWEEN", "value": str(run["run_start_ms"]),
                "highValue": str(run["run_start_ms"] + RUN_WINDOW_MS)}]
    if last:
        filters.append({"propertyName": "lastname", "operator": "EQ", "value": last})
    return hub.search(filters)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="append", default=[], help="run tag (repeatable)")
    ap.add_argument("--label", help="every run with this label, e.g. smoke")
    ap.add_argument("--yes", action="store_true", help="actually delete")
    args = ap.parse_args()
    if not args.run and not args.label:
        raise SystemExit("Pass --run TAG or --label LABEL")
    env = load_env()
    require(env, "HUBSPOT_TOKEN")
    hub = HubSpot(env["HUBSPOT_TOKEN"])

    runs = [json.loads(p.read_text()) for p in sorted(RUNS.glob("*.json"))]
    runs = [r for r in runs if r.get("observer") == "real" and (r["run_tag"] in args.run or r.get("label") == args.label)]
    seen = set()
    for run in runs:
        for lead in run["sent"]:
            for c in contacts_for(hub, run, lead):
                if c["id"] in seen:
                    continue
                seen.add(c["id"])
                notes = hub._assoc(c["id"], "notes")
                deals = hub._assoc(c["id"], "deals")
                print(f"{run['run_tag']} {lead['id']}: contact {c['id']} with {len(notes)} note(s), {len(deals)} deal(s)")
                if args.yes:
                    for obj, ids in (("notes", notes), ("deals", deals), ("contacts", [c["id"]])):
                        for i in ids:
                            hub.call("DELETE", f"/crm/v3/objects/{obj}/{i}")
    print(f"{len(seen)} contact(s) {'deleted' if args.yes else 'would be deleted (dry run; add --yes)'} "
          f"from {len(runs)} run(s)")


if __name__ == "__main__":
    main()
