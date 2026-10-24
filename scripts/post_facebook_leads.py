"""Post Facebook Lead Ads-style leads (Graph API field_data shape) to the n8n lead webhook.

Stands in for the Facebook Lead Ads trigger in this project: same payload shape, source=facebook.
Takes the facebook rows from data/test-leads.csv; each run gets fresh plus-addresses.

Usage:
  .venv/bin/python scripts/post_facebook_leads.py            # all facebook leads
  .venv/bin/python scripts/post_facebook_leads.py L08 L18    # only these
"""
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from envfile import load_env, require  # noqa: E402
from leads import WEBHOOK_AUTH_HEADER, facebook_payload, load_leads, materialize  # noqa: E402
from net import SSL_CONTEXT  # noqa: E402


def main():
    env = load_env()
    require(env, "LEAD_WEBHOOK_URL", "N8N_WEBHOOK_SECRET", "TEST_EMAIL_BASE")
    run_tag = "fb" + datetime.now().strftime("%m%d%H%M%S")
    leads = [l for l in materialize(load_leads(), env["TEST_EMAIL_BASE"], run_tag) if l["source"] == "facebook"]
    if sys.argv[1:]:
        leads = [l for l in leads if l["id"] in sys.argv[1:]]
    for lead in leads:
        payload = facebook_payload(lead, f"{run_tag}-{lead['id']}")
        req = urllib.request.Request(env["LEAD_WEBHOOK_URL"], method="POST", data=json.dumps(payload).encode(),
                                     headers={"Content-Type": "application/json",
                                              WEBHOOK_AUTH_HEADER: env["N8N_WEBHOOK_SECRET"]})
        try:
            with urllib.request.urlopen(req, timeout=30, context=SSL_CONTEXT) as r:
                status = r.status
        except urllib.error.HTTPError as e:
            status = e.code
        print(f"{lead['id']} {lead['name']} ({lead['city']}) -> HTTP {status}")
        time.sleep(1)


if __name__ == "__main__":
    main()
