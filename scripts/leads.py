"""Test leads and the two webhook payload shapes (website form, Facebook lead ad).

data/test-leads.csv keeps the address as "{TEST}+L01". materialize() turns that into
"<local>+<run_tag>+L01@<domain>" from TEST_EMAIL_BASE in .env, so each run uses fresh
addresses (no 24 h dedupe collisions with earlier runs) and no real address is in the repo.
"""
import csv
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LEADS_CSV = ROOT / "data" / "test-leads.csv"
WEBHOOK_AUTH_HEADER = "X-Northline-Key"


def load_leads(path: Path = LEADS_CSV) -> list:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def materialize(leads: list, test_email_base: str, run_tag: str) -> list:
    local, at, domain = test_email_base.partition("@")
    if not at or not local or not domain:
        raise SystemExit("TEST_EMAIL_BASE in .env must be a full address, e.g. name@gmail.com")
    out = []
    for row in leads:
        row = dict(row)
        if "{TEST}" in row["email"]:
            row["email"] = row["email"].replace("{TEST}", f"{local}+{run_tag}") + "@" + domain
        out.append(row)
    return out


def website_payload(lead: dict, submission_id: str) -> dict:
    """What web/form.html posts."""
    return {
        "source": "website",
        "submission_id": submission_id,
        "submitted_at": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        "name": lead["name"],
        "email": lead["email"],
        "phone": lead["phone"],
        "city": lead["city"],
        "service": lead["service"],
        "message": lead["message"],
    }


def facebook_payload(lead: dict, leadgen_id: str) -> dict:
    """Shape of a Facebook Lead Ads lead as the Graph API returns it (field_data list)."""
    fields = [("full_name", lead["name"]), ("email", lead["email"]), ("phone_number", lead["phone"]),
              ("city", lead["city"]), ("what_service_do_you_need", lead["service"]),
              ("tell_us_about_your_project", lead["message"])]
    return {
        "source": "facebook",
        "leadgen_id": leadgen_id,
        "created_time": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+0000"),
        "field_data": [{"name": n, "values": [v]} for n, v in fields if v],
    }


def payload_for(lead: dict, submission_id: str = "") -> dict:
    submission_id = submission_id or uuid.uuid4().hex
    if lead["source"] == "facebook":
        return facebook_payload(lead, submission_id)
    return website_payload(lead, submission_id)


def submission_id_of(payload: dict) -> str:
    return payload.get("submission_id") or payload.get("leadgen_id") or ""
