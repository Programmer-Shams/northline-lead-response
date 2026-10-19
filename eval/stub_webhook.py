"""Stub of the lead workflow, for building and checking eval/run_leads.py before n8n exists.

Keyword rules instead of AI, fake CRM/inbox/Sheet/Slack kept in memory. Its results are never
reported; they only prove the runner measures and grades correctly.

  POST /lead     website or Facebook-style payload (same contract as the n8n webhook)
  GET  /_state   {"contacts", "mails", "lead_log", "slack_log"} for eval/observe.py StubObserver
  POST /_reset   clear everything

Usage: python3 eval/stub_webhook.py [--port 5679] [--fail-crm]
  --fail-crm  every CRM call fails: no contact, reply still sent, Sheet status=failed, Slack "lead_failed"
"""
import argparse
import json
import random
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

AREA = {"columbus", "dublin", "westerville", "hilliard", "grove city", "gahanna", "worthington",
        "upper arlington", "reynoldsburg", "pickerington"}
STUB_BOOKING_LINK = "https://stub.invalid/book"  # stub-only placeholder, never shown to a lead
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

LOCK = threading.Lock()
STATE = {"contacts": [], "mails": [], "lead_log": [], "slack_log": []}
FAIL_CRM = False


def now_ms():
    return int(time.time() * 1000)


def normalize(p):
    if p.get("source") == "facebook":
        f = {d["name"]: (d.get("values") or [""])[0] for d in p.get("field_data", [])}
        return {"source": "facebook", "submission_id": p.get("leadgen_id", ""), "name": f.get("full_name", ""),
                "email": f.get("email", ""), "phone": f.get("phone_number", ""), "city": f.get("city", ""),
                "service": f.get("what_service_do_you_need", ""), "message": f.get("tell_us_about_your_project", "")}
    return {k: p.get(k, "") for k in ("source", "submission_id", "name", "email", "phone", "city", "service",
                                      "message")}


def classify(lead):
    msg = lead["message"].lower()
    if re.search(r"backlink|seo|#1 on google", msg) or not re.search(
            r"\b(the|my|our|we|i|need|want|can|how|hola|roof)\b", msg):
        return "spam", "sales pitch or no real request"
    if lead["city"].lower() not in AREA:
        return "cold", "out of service area"
    if re.search(r"student|interview|year|no rush", msg):
        return "cold", "not a customer or timeline over 3 months"
    if re.search(r"leak|drip|storm|hail|asap|tree|rain|this week|two weeks|gotera|adjuster", msg):
        return "hot", "urgent problem in area"
    return "warm", "planned work in area"


def reply_text(lead, tier):
    if tier == "hot":
        extra = " We offer 24/7 emergency tarping for active leaks." if re.search(r"leak|drip|rain|gotera", lead["message"].lower()) else ""
        body = f"Thanks {lead['name']}. A team member will call within 1 business hour.{extra} Book: {STUB_BOOKING_LINK}"
    elif tier == "warm":
        prices = {"gutters": "$1,200 to $3,000", "skylight": "$1,400"}
        price = prices.get(lead["service"].lower(), "")
        if "guard" in lead["message"].lower():
            price = "$8 to $14 per linear foot"
        body = f"Thanks {lead['name']}." + (f" Typical price: {price}." if price else "") + f" Book: {STUB_BOOKING_LINK}"
    elif lead["city"].lower() not in AREA:
        body = f"Thanks {lead['name']}. Sorry, you are outside our service area."
    else:
        body = f"Thanks {lead['name']}, we appreciate you reaching out."
    return body + "\n\nThe Northline team"


def slack(sid, kind):
    STATE["slack_log"].append({"ts": str(now_ms()), "submission_id": sid, "kind": kind, "ok": "true"})


def process(lead, t0):
    time.sleep(random.uniform(0.3, 1.5))
    sid = lead["submission_id"]
    tier, reason = classify(lead)
    email_ok = bool(EMAIL_RE.match(lead["email"]))
    row = {"submission_id": sid, "source": lead["source"], "email": lead["email"], "t0": str(t0), "t1": "",
           "seconds_to_reply": "", "tier": tier, "reason": reason, "replied": "no", "crm_id": "", "status": "ok"}
    with LOCK:
        prior = [c for c in STATE["contacts"]
                 if email_ok and c["email"].lower() == lead["email"].lower() and now_ms() - c["created_ms"] < 86_400_000]
        if prior:
            prior[0]["notes"].append(f"Repeat enquiry: {lead['message']}")
            row.update(crm_id=prior[0]["id"], status="repeat")
            STATE["lead_log"].append(row)
            return
        if tier != "spam" and FAIL_CRM:
            row["status"] = "failed"
            if tier == "hot":
                slack(sid, "hot")
        elif tier != "spam":
            c = {"id": str(len(STATE["contacts"]) + 1), "name": lead["name"], "email": lead["email"] if email_ok else "",
                 "tier": tier, "notes": [f"AI tier {tier}: {reason}"], "deals": [], "created_ms": now_ms()}
            if tier == "hot":
                c["deals"].append({"name": f"{lead['name']} - {lead['service']}", "stage": "New lead"})
                slack(sid, "hot")
            STATE["contacts"].append(c)
            row["crm_id"] = c["id"]
        if not email_ok and tier != "spam":
            slack(sid, "invalid_contact")
        elif tier != "spam":
            t1 = now_ms()
            STATE["mails"].append({"id": f"m{len(STATE['mails']) + 1}", "internal_ms": t1 + random.randint(800, 4000),
                                   "to": lead["email"], "subject": "Thanks for contacting Northline",
                                   "body": reply_text(lead, tier), "labels": ["INBOX"]})
            row.update(t1=str(t1), seconds_to_reply=f"{(t1 - t0) / 1000:.2f}", replied="yes")
        if row["status"] == "failed":
            slack(sid, "lead_failed")
        STATE["lead_log"].append(row)


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/_state":
            with LOCK:
                return self._send(200, STATE)
        self._send(404, {"error": "not found"})

    def do_POST(self):
        if self.path == "/_reset":
            with LOCK:
                for v in STATE.values():
                    v.clear()
            return self._send(200, {"reset": True})
        if self.path != "/lead":
            return self._send(404, {"error": "not found"})
        t0 = now_ms()
        lead = normalize(json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}"))
        threading.Thread(target=process, args=(lead, t0), daemon=True).start()
        self._send(200, {"received": True, "submission_id": lead["submission_id"]})

    def log_message(self, *args):
        pass


def main():
    global FAIL_CRM
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=5679)
    ap.add_argument("--fail-crm", action="store_true")
    args = ap.parse_args()
    FAIL_CRM = args.fail_crm
    print(f"stub lead webhook on http://127.0.0.1:{args.port}/lead (fail-crm={FAIL_CRM})")
    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
