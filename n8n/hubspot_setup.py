"""One-time HubSpot setup for the lead workflow. Safe to re-run.

1. Adds Hot / Warm / Cold (values HOT, WARM, COLD) to the standard contact property
   "Lead status" (hs_lead_status), keeping HubSpot's default options.
2. Adds a "New lead" stage at the start of the default deal pipeline.
3. Saves HUBSPOT_PORTAL_ID, HUBSPOT_APP_HOST, HUBSPOT_PIPELINE_ID and HUBSPOT_NEW_LEAD_STAGE_ID
   to .env (account ids, not secrets) for the workflow's deal step and Slack record links.

Usage: .venv/bin/python n8n/hubspot_setup.py
"""
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from envfile import load_env, require, set_env  # noqa: E402
from net import SSL_CONTEXT  # noqa: E402

TIERS = [("HOT", "Hot"), ("WARM", "Warm"), ("COLD", "Cold")]
STAGE_LABEL = "New lead"


def call(token, method, path, body=None):
    req = urllib.request.Request("https://api.hubapi.com" + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30, context=SSL_CONTEXT) as r:
            raw = r.read().decode()
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        raise SystemExit(f"HubSpot {method} {path} -> HTTP {e.code}: {e.read().decode()[:400]}")


def main():
    env = load_env()
    require(env, "HUBSPOT_TOKEN")
    token = env["HUBSPOT_TOKEN"]

    prop = call(token, "GET", "/crm/v3/properties/contacts/hs_lead_status")
    have = {o["value"] for o in prop["options"]}
    if all(v in have for v, _ in TIERS):
        print("Lead status: Hot/Warm/Cold already present")
    else:
        options = [{k: o[k] for k in ("label", "value", "displayOrder", "hidden") if k in o} for o in prop["options"]]
        start = max((o.get("displayOrder", 0) for o in options), default=0) + 1
        options += [{"label": label, "value": value, "displayOrder": start + i, "hidden": False}
                    for i, (value, label) in enumerate(TIERS) if value not in have]
        call(token, "PATCH", "/crm/v3/properties/contacts/hs_lead_status", {"options": options})
        print("Lead status: added Hot/Warm/Cold")

    pipelines = call(token, "GET", "/crm/v3/pipelines/deals")["results"]
    pipeline = next((p for p in pipelines if p["id"] == "default"), pipelines[0])
    stage = next((s for s in pipeline["stages"] if s["label"].lower() == STAGE_LABEL.lower()), None)
    if stage:
        print(f"Deal stage '{STAGE_LABEL}' already in '{pipeline['label']}'")
    else:
        # displayOrder can't be negative: move every stage down one place, then insert at 0.
        for s in sorted(pipeline["stages"], key=lambda s: -s["displayOrder"]):
            call(token, "PATCH", f"/crm/v3/pipelines/deals/{pipeline['id']}/stages/{s['id']}",
                 {"displayOrder": s["displayOrder"] + 1})
        stage = call(token, "POST", f"/crm/v3/pipelines/deals/{pipeline['id']}/stages",
                     {"label": STAGE_LABEL, "displayOrder": 0, "metadata": {"probability": "0.1"}})
        print(f"Deal stage '{STAGE_LABEL}' added to '{pipeline['label']}'")

    account = call(token, "GET", "/account-info/v3/details")
    host = "app.hubspot.com" if account.get("dataHostingLocation", "na1") == "na1" else \
        f"app-{account['dataHostingLocation']}.hubspot.com"
    for k, v in [("HUBSPOT_PORTAL_ID", str(account["portalId"])), ("HUBSPOT_APP_HOST", host),
                 ("HUBSPOT_PIPELINE_ID", pipeline["id"]), ("HUBSPOT_NEW_LEAD_STAGE_ID", stage["id"])]:
        set_env(k, v)
    print("Saved HubSpot account ids to .env")


if __name__ == "__main__":
    main()
