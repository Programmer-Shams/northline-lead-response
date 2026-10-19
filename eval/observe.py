"""Where the test runner looks to see what the workflow actually did.

RealObserver reads the systems directly (HubSpot API, Gmail API, Google Sheets API) with its
own credentials, so a measurement never depends on the n8n workflow under test. It only reads; the Google
token also has Sheets write scope because n8n/sheet_setup.py uses it to create the tabs.
StubObserver reads the in-memory state of eval/stub_webhook.py through GET /_state.

Both return the same shapes:
  contact: {"id", "email", "tier", "notes": [str], "deals": [{"name", "stage"}], "created_ms"}
  mail:    {"id", "internal_ms", "to", "subject", "body", "labels": [str]}
  log row: dict keyed by the Sheet header row ("Lead log" / "Slack log" tabs)
"""
import base64
import html
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from net import SSL_CONTEXT  # noqa: E402

# Tier lives in HubSpot's standard "Lead status" property (options HOT/WARM/COLD added by n8n/hubspot_setup.py).
TIER_PROPERTY = "hs_lead_status"
LEAD_LOG_TAB = "Lead log"
# Same rule as the workflow's Normalize lead node.
EMAIL_PATTERN_OK = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
SLACK_LOG_TAB = "Slack log"


def split_name(full: str) -> tuple:
    """Same rule the workflow uses: first word is the first name, the rest is the last name."""
    parts = (full or "").split()
    return (parts[0] if parts else "", " ".join(parts[1:]))


def _http(method, url, headers=None, body=None, form=None, tries=4):
    data = None
    headers = dict(headers or {})
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    elif form is not None:
        data = urllib.parse.urlencode(form).encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    for attempt in range(tries):
        req = urllib.request.Request(url, method=method, data=data, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=30, context=SSL_CONTEXT) as r:
                raw = r.read().decode()
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and attempt < tries - 1:
                time.sleep(2 ** attempt)
                continue
            # The URL can carry ids but never secrets; tokens are in headers only.
            raise RuntimeError(f"{method} {url.split('?')[0]} -> HTTP {e.code}: {e.read().decode()[:300]}")
        except (urllib.error.URLError, TimeoutError) as e:
            if attempt < tries - 1:
                time.sleep(2 ** attempt)
                continue
            raise RuntimeError(f"{method} {url.split('?')[0]} -> {e}")


def _rows_to_dicts(values: list) -> list:
    if not values:
        return []
    header = [h.strip() for h in values[0]]
    return [dict(zip(header, row + [""] * (len(header) - len(row)))) for row in values[1:]]


class HubSpot:
    BASE = "https://api.hubapi.com"
    PROPS = ["email", "firstname", "lastname", "phone", TIER_PROPERTY, "createdate"]

    def __init__(self, token):
        self.headers = {"Authorization": f"Bearer {token}"}
        self._stages = None

    def call(self, method, path, body=None):
        return _http(method, self.BASE + path, self.headers, body=body)

    def search(self, filters):
        body = {"filterGroups": [{"filters": filters}], "properties": self.PROPS, "limit": 100}
        return self.call("POST", "/crm/v3/objects/contacts/search", body).get("results", [])

    def _assoc(self, contact_id, to_type):
        res = self.call("GET", f"/crm/v4/objects/contacts/{contact_id}/associations/{to_type}?limit=100")
        return [str(r["toObjectId"]) for r in res.get("results", [])]

    def _batch_read(self, obj, ids, props):
        if not ids:
            return []
        body = {"inputs": [{"id": i} for i in ids], "properties": props}
        return self.call("POST", f"/crm/v3/objects/{obj}/batch/read", body).get("results", [])

    def _stage_labels(self):
        if self._stages is None:
            self._stages = {}
            try:
                for p in self.call("GET", "/crm/v3/pipelines/deals").get("results", []):
                    for s in p.get("stages", []):
                        self._stages[s["id"]] = s["label"]
            except RuntimeError:
                pass  # token may lack pipeline read access; fall back to stage ids
        return self._stages

    def expand(self, c):
        p = c.get("properties", {})
        notes = self._batch_read("notes", self._assoc(c["id"], "notes"), ["hs_note_body"])
        deals = self._batch_read("deals", self._assoc(c["id"], "deals"), ["dealname", "dealstage"])
        stages = self._stage_labels()
        return {
            "id": str(c["id"]),
            "email": p.get("email") or "",
            "tier": (p.get(TIER_PROPERTY) or "").lower(),
            "notes": [html.unescape(re.sub(r"<[^>]+>", " ", n["properties"].get("hs_note_body") or "")).strip()
                      for n in notes],
            "deals": [{"name": d["properties"].get("dealname"),
                       "stage": stages.get(d["properties"].get("dealstage"), d["properties"].get("dealstage"))}
                      for d in deals],
            "created_ms": _iso_ms(p.get("createdate")),
        }


def _iso_ms(value):
    if not value:
        return 0
    from datetime import datetime
    return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() * 1000)


class Google:
    """Read-only Gmail + Sheets access with the refresh token from scripts/google_auth.py."""

    def __init__(self, client_id, client_secret, refresh_token):
        self.creds = (client_id, client_secret, refresh_token)
        self._token, self._expires = None, 0

    def _auth(self):
        if time.time() > self._expires - 60:
            cid, secret, refresh = self.creds
            tok = _http("POST", "https://oauth2.googleapis.com/token",
                        form={"client_id": cid, "client_secret": secret, "refresh_token": refresh,
                              "grant_type": "refresh_token"})
            self._token, self._expires = tok["access_token"], time.time() + tok.get("expires_in", 3600)
        return {"Authorization": f"Bearer {self._token}"}

    def gmail_search(self, q):
        url = "https://gmail.googleapis.com/gmail/v1/users/me/messages?" + urllib.parse.urlencode(
            {"q": q, "maxResults": 50, "includeSpamTrash": "true"})
        return [m["id"] for m in (_http("GET", url, self._auth()) or {}).get("messages", [])]

    def gmail_message(self, mid):
        url = f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{mid}?format=full"
        return _http("GET", url, self._auth())

    def sheet_rows(self, sheet_id, tab):
        rng = urllib.parse.quote(f"'{tab}'!A:Z")
        url = f"https://sheets.googleapis.com/v4/spreadsheets/{sheet_id}/values/{rng}"
        return _rows_to_dicts((_http("GET", url, self._auth()) or {}).get("values", []))


def _decode_part(data):
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode("utf-8", "replace")


def _message_body(payload):
    """text/plain if present, otherwise text/html with tags stripped."""
    plain, rich = [], []

    def walk(part):
        mime, data = part.get("mimeType", ""), part.get("body", {}).get("data")
        if data and mime == "text/plain":
            plain.append(_decode_part(data))
        elif data and mime == "text/html":
            rich.append(_decode_part(data))
        for p in part.get("parts", []) or []:
            walk(p)

    walk(payload)
    if plain:
        return "\n".join(plain).strip()
    text = re.sub(r"<br\s*/?>|</p>|</div>", "\n", "\n".join(rich), flags=re.I)
    return html.unescape(re.sub(r"<[^>]+>", "", text)).strip()


class RealObserver:
    def __init__(self, env):
        self.hubspot = HubSpot(env["HUBSPOT_TOKEN"])
        self.google = Google(env["GOOGLE_CLIENT_ID"], env["GOOGLE_CLIENT_SECRET"], env["GOOGLE_RUNNER_REFRESH_TOKEN"])
        self.sheet_id = env["LEAD_LOG_SHEET_ID"]

    def refresh(self):
        pass

    def contacts_by_email(self, email):
        found = self.hubspot.search([{"propertyName": "email", "operator": "EQ", "value": email}])
        return [self.hubspot.expand(c) for c in found]

    def contacts_by_name(self, full_name, since_ms):
        first, last = split_name(full_name)
        filters = [{"propertyName": "firstname", "operator": "EQ", "value": first},
                   {"propertyName": "createdate", "operator": "GTE", "value": str(since_ms)}]
        if last:
            filters.append({"propertyName": "lastname", "operator": "EQ", "value": last})
        return [self.hubspot.expand(c) for c in self.hubspot.search(filters)]

    def inbox(self, address, since_ms):
        out = []
        for mid in self.google.gmail_search(f"to:{address} after:{since_ms // 1000 - 60}"):
            m = self.google.gmail_message(mid)
            headers = {h["name"].lower(): h["value"] for h in m["payload"].get("headers", [])}
            if address.lower() not in headers.get("to", "").lower():
                continue  # Gmail search can match on related addresses; keep exact recipients only
            if int(m["internalDate"]) < since_ms:
                continue
            out.append({"id": m["id"], "internal_ms": int(m["internalDate"]), "to": headers.get("to", ""),
                        "subject": headers.get("subject", ""), "body": _message_body(m["payload"]),
                        "labels": m.get("labelIds", [])})
        return sorted(out, key=lambda x: x["internal_ms"])

    def lead_log(self):
        return self.google.sheet_rows(self.sheet_id, LEAD_LOG_TAB)

    def slack_log(self):
        return self.google.sheet_rows(self.sheet_id, SLACK_LOG_TAB)


class StubObserver:
    def __init__(self, stub_base):
        self.base = stub_base.rstrip("/")
        self.state = None

    def refresh(self):
        self.state = _http("GET", self.base + "/_state")

    def _s(self):
        if self.state is None:
            self.refresh()
        return self.state

    def contacts_by_email(self, email):
        return [c for c in self._s()["contacts"] if c["email"].lower() == email.lower()]

    def contacts_by_name(self, full_name, since_ms):
        return [c for c in self._s()["contacts"]
                if c["name"] == full_name and c["created_ms"] >= since_ms]

    def inbox(self, address, since_ms):
        return sorted([m for m in self._s()["mails"]
                       if m["to"].lower() == address.lower() and m["internal_ms"] >= since_ms],
                      key=lambda x: x["internal_ms"])

    def lead_log(self):
        return self._s()["lead_log"]

    def slack_log(self):
        return self._s()["slack_log"]
