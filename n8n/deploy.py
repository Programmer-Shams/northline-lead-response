"""Deploy the Northline lead workflow to local n8n through its public API.

1. Creates the n8n credentials from .env (all named "Northline ..."; other projects' are never touched).
   Secrets go straight from .env into n8n; they are never printed or written to the repo.
   N8N_WEBHOOK_SECRET is generated on first run. The two Google credentials still need one
   "Sign in with Google" click each in the n8n UI.
2. Builds the workflow JSON (build_workflows.py), fills deploy-time placeholders, creates or
   updates it by name, activates it and saves LEAD_WEBHOOK_URL to .env.

Ids are kept in n8n/.deploy-state.json (git-ignored).
Usage: .venv/bin/python n8n/deploy.py [--credentials-only] [--refresh-credentials]
                                       [--break-hubspot | --restore-hubspot]
  --break-hubspot    failure test: replace the HubSpot credential's token with an invalid one
  --restore-hubspot  put the real token from .env back
"""
import argparse
import json
import secrets
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(HERE))
from envfile import load_env, require, set_env  # noqa: E402
from leads import WEBHOOK_AUTH_HEADER  # noqa: E402
from net import SSL_CONTEXT  # noqa: E402

STATE = HERE / ".deploy-state.json"
WEB_ENV = ROOT / "web" / ".env.local"
WORKFLOWS_DIR = HERE / "workflows"
# Well-formed but not a real key, so HubSpot answers 401 (authentication) like a revoked token would.
BROKEN_HUBSPOT_TOKEN = "pat-eu1-" + "-".join("0" * n for n in (8, 4, 4, 4, 12))  # built at runtime: not a key


class N8n:
    def __init__(self, env):
        self.base = env["N8N_BASE_URL"].rstrip("/") + "/api/v1"
        self.key = env["N8N_API_KEY"]

    def call(self, method, path, body=None):
        req = urllib.request.Request(self.base + path, method=method,
                                     data=json.dumps(body).encode() if body is not None else None,
                                     headers={"X-N8N-API-KEY": self.key, "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=60, context=SSL_CONTEXT) as r:
                raw = r.read().decode()
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as e:
            raise SystemExit(f"n8n API {method} {path} -> HTTP {e.code}: {e.read().decode()[:600]}")


def wait_for_api(api, timeout_s=90):
    """Right after a container start, n8n answers /healthz before its public API is mounted."""
    deadline = time.time() + timeout_s
    while True:
        try:
            req = urllib.request.Request(api.base + "/workflows?limit=1", headers={"X-N8N-API-KEY": api.key})
            urllib.request.urlopen(req, timeout=5, context=SSL_CONTEXT)
            return
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                raise SystemExit("n8n rejected N8N_API_KEY. Create a new key in n8n Settings > n8n API.")
        except (urllib.error.URLError, OSError):
            pass
        if time.time() > deadline:
            raise SystemExit(f"n8n API not reachable at {api.base} after {timeout_s}s. Is brightpan-n8n running?")
        time.sleep(2)


def ensure_webhook_secret(env):
    """Shared secret the form server and the test runner send in the X-Northline-Key header."""
    if not env.get("N8N_WEBHOOK_SECRET"):
        env["N8N_WEBHOOK_SECRET"] = secrets.token_urlsafe(32)
        set_env("N8N_WEBHOOK_SECRET", env["N8N_WEBHOOK_SECRET"])
        print("generated N8N_WEBHOOK_SECRET in .env")


def credential_specs(env, hubspot_token):
    google = {"clientId": env["GOOGLE_CLIENT_ID"], "clientSecret": env["GOOGLE_CLIENT_SECRET"]}
    return {
        "OPENAI": ("Northline OpenAI", "openAiApi", {"apiKey": env["OPENAI_API_KEY"]}),
        "HUBSPOT": ("Northline HubSpot", "hubspotAppToken", {"appToken": hubspot_token}),
        "GMAIL": ("Northline Gmail", "gmailOAuth2", google),
        "SHEETS": ("Northline Google Sheets", "googleSheetsOAuth2Api", google),
        "WEBHOOK": ("Northline webhook key", "httpHeaderAuth",
                    {"name": WEBHOOK_AUTH_HEADER, "value": env["N8N_WEBHOOK_SECRET"]}),
    }


def ensure_credentials(api, env, state, refresh, only=None, hubspot_token=None):
    creds = state.setdefault("credentials", {})
    for key, (name, ctype, data) in credential_specs(env, hubspot_token or env["HUBSPOT_TOKEN"]).items():
        if only and key not in only:
            continue
        if creds.get(key) and (refresh or only):
            if key in ("GMAIL", "SHEETS") and not refresh:
                continue
            # Recreating a credential keeps workflows working only if they are re-deployed with the new id.
            api.call("DELETE", f"/credentials/{creds[key]}")
            creds.pop(key)
        if not creds.get(key):
            creds[key] = api.call("POST", "/credentials", {"name": name, "type": ctype, "data": data})["id"]
            print(f"credential created: {name} ({ctype})")
        else:
            print(f"credential kept:    {name}")
    STATE.write_text(json.dumps(state, indent=2))
    return creds


def fill(wf: dict, values: dict) -> dict:
    # Escape each value as a JSON string body so quotes or backslashes can't break the document.
    text = json.dumps(wf)
    for k, v in values.items():
        text = text.replace(k, json.dumps(v)[1:-1])
    leftover = sorted({p for p in values if p in text} | {t for t in ("__CRED_", "__ENV_", "__WF_") if t in text})
    if leftover:
        raise SystemExit(f"Unfilled placeholders in {wf['name']}: {leftover}")
    return json.loads(text)


def upsert_workflow(api, state, key, wf):
    wfs = state.setdefault("workflows", {})
    body = {k: wf[k] for k in ("name", "nodes", "connections", "settings")}
    if wfs.get(key):
        api.call("PUT", f"/workflows/{wfs[key]}", body)
        print(f"workflow updated: {wf['name']} ({wfs[key]})")
    else:
        wfs[key] = api.call("POST", "/workflows", body)["id"]
        print(f"workflow created: {wf['name']} ({wfs[key]})")
    STATE.write_text(json.dumps(state, indent=2))
    api.call("POST", f"/workflows/{wfs[key]}/activate")
    return wfs[key]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--credentials-only", action="store_true")
    ap.add_argument("--refresh-credentials", action="store_true")
    ap.add_argument("--break-hubspot", action="store_true")
    ap.add_argument("--restore-hubspot", action="store_true")
    ap.add_argument("--rotate-webhook-secret", action="store_true")
    args = ap.parse_args()
    env = load_env()
    if args.rotate_webhook_secret:
        set_env("N8N_WEBHOOK_SECRET", "")
        env["N8N_WEBHOOK_SECRET"] = ""
    require(env, "N8N_BASE_URL", "N8N_API_KEY", "OPENAI_API_KEY", "HUBSPOT_TOKEN", "GOOGLE_CLIENT_ID",
            "GOOGLE_CLIENT_SECRET")
    ensure_webhook_secret(env)
    api = N8n(env)
    wait_for_api(api)
    state = json.loads(STATE.read_text()) if STATE.exists() else {}

    if args.break_hubspot or args.restore_hubspot:
        # Update the token in place so the credential id (and the deployed workflow) stays the same.
        token = BROKEN_HUBSPOT_TOKEN if args.break_hubspot else env["HUBSPOT_TOKEN"]
        api.call("PATCH", f"/credentials/{state['credentials']['HUBSPOT']}",
                 {"data": {"appToken": token}, "isPartialData": True})
        print("HubSpot credential is now", "BROKEN (failure test)" if args.break_hubspot else "restored")
        return
    elif args.rotate_webhook_secret:
        ensure_credentials(api, env, state, False, only={"WEBHOOK"})
    else:
        ensure_credentials(api, env, state, args.refresh_credentials)
    if args.credentials_only:
        return

    from build_workflows import build  # noqa: E402
    require(env, "LEAD_LOG_SHEET_ID", "BOOKING_LINK", "TEST_EMAIL_BASE", "HUBSPOT_PORTAL_ID", "HUBSPOT_APP_HOST",
            "HUBSPOT_PIPELINE_ID", "HUBSPOT_NEW_LEAD_STAGE_ID")
    slack_url = env.get("SLACK_WEBHOOK_URL", "")
    if not slack_url.startswith("https://hooks.slack.com/"):
        raise SystemExit("SLACK_WEBHOOK_URL must be a https://hooks.slack.com/ URL")
    values = {f"__CRED_{k}__": v for k, v in state["credentials"].items()}
    for k in ("LEAD_LOG_SHEET_ID", "BOOKING_LINK", "HUBSPOT_PORTAL_ID", "HUBSPOT_APP_HOST", "HUBSPOT_PIPELINE_ID",
              "HUBSPOT_NEW_LEAD_STAGE_ID", "SLACK_WEBHOOK_URL"):
        values[f"__ENV_{k}__"] = env[k]
    values["__ENV_SENDER_NAME__"] = "Northline Roofing & Exteriors"

    for key, wf in build().items():
        # The exported copy in the repo keeps placeholders, so it carries no ids, links or secrets.
        (WORKFLOWS_DIR / f"{key}.json").write_text(json.dumps(wf, indent=2, ensure_ascii=False) + "\n")
        # n8n 2.x only accepts a published (active) workflow as another workflow's error workflow.
        wf_id = upsert_workflow(api, state, key, fill(wf, values))
        if key == "northline-error-alert":
            values["__WF_ERROR__"] = wf_id

    url = env["N8N_BASE_URL"].rstrip("/") + "/webhook/northline-lead"
    set_env("LEAD_WEBHOOK_URL", url)
    # The Next.js form's server route forwards leads with the secret; the browser never sees it.
    set_env("LEAD_WEBHOOK_URL", url, WEB_ENV)
    set_env("N8N_WEBHOOK_SECRET", env["N8N_WEBHOOK_SECRET"], WEB_ENV)
    print(f"\nLead webhook: {url}  (header {WEBHOOK_AUTH_HEADER} required)")


if __name__ == "__main__":
    main()
