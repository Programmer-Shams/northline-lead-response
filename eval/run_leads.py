"""Test runner for the Northline lead workflow (BUILD_SPEC step 4).

Sends the 20 leads in data/test-leads.csv in order (each repeat lead 2-5 min after the lead it
repeats), waits for the workflow to finish, then checks every expected column against what really
happened: HubSpot contacts/notes/deals, the reply in the Gmail inbox, the Slack log and the
"Lead log" Sheet. Writes a CSV for the manual review and prints the measured summary.

Seconds to inbox = Gmail's internalDate of the reply minus the moment the runner posted the lead. Gmail stores
internalDate to the whole second (truncated), so the runner reports the upper bound: internalDate + 1 s - post time.
The replies go to the sending account's own plus-addresses, so "inbox" means Gmail accepted and filed the message
in that mailbox, not delivery to another provider. The Sheet's seconds_to_reply (n8n t0 -> Gmail send, ms) is kept
alongside as a cross-check.
Auto grades and reply flags are hints; the manual review (BUILD_SPEC step 5) is final.

Webhook contract (n8n or stub):
  request : POST website payload or Facebook-style payload (scripts/leads.py),
            header X-Northline-Key: N8N_WEBHOOK_SECRET from .env (the stub ignores it)
  response: any 2xx; the work happens after the response

Usage:
  python3 eval/run_leads.py --stub http://127.0.0.1:5679 --out eval/results-stub.csv
  python3 eval/run_leads.py --label gpt-5.5 --log           # real workflow, LEAD_WEBHOOK_URL from .env
  python3 eval/run_leads.py --only L03 --expect-failure --label failure-test --out eval/failure-test.csv
  python3 eval/run_leads.py --grade r1018193012 ...            # re-check an earlier run without resending
"""
import argparse
import csv
import json
import re
import statistics
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "eval"))
from envfile import load_env, require  # noqa: E402
from leads import WEBHOOK_AUTH_HEADER, load_leads, materialize, payload_for  # noqa: E402
from net import SSL_CONTEXT  # noqa: E402
from observe import RealObserver, StubObserver  # noqa: E402

BUSINESS = ROOT / "data" / "business.md"
RUNS = ROOT / "eval" / ".runs"  # git-ignored: holds real addresses
LOG = ROOT / "eval" / "results-log.md"
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
REPEAT_RE = re.compile(r"send (\d+)\s*-\s*(\d+) min after (L\d+)", re.I)
DISCOUNT_RE = re.compile(r"discount|coupon|% off|percent off|financ|promo|descuento|cup[oó]n|financiaci", re.I)
SPANISH_RE = re.compile(r"\b(gracias|hola|equipo|techo|llamar[áa]|nuestro|usted)\b", re.I)
MAX_WORDS = 120
# "$1,200" or "$350" but not the comma after "$3,000," at the end of a clause.
PRICE_RE = re.compile(r"\$\d{1,3}(?:,\d{3})+(?:\.\d+)?|\$\d+(?:\.\d+)?")


def utc(ms):
    return datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat(timespec="milliseconds") if ms else ""


def allowed_prices():
    """Every dollar amount published in data/business.md; any other amount in a reply is flagged."""
    return set(PRICE_RE.findall(BUSINESS.read_text()))


# ---------- sending ----------

def post(url, payload, secret):
    req = urllib.request.Request(url, method="POST", data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json", WEBHOOK_AUTH_HEADER: secret})
    try:
        with urllib.request.urlopen(req, timeout=30, context=SSL_CONTEXT) as r:
            r.read()
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except (urllib.error.URLError, TimeoutError):
        return 0


def send_all(leads, endpoint, secret, gap_s, repeat_extra_s, run_tag):
    sent, by_id = [], {}
    for i, lead in enumerate(leads):
        m = REPEAT_RE.search(lead.get("notes", ""))
        if m and m.group(3) in by_id:
            # Aim inside the 2-5 min window with margin: lower bound + repeat_extra_s.
            target = by_id[m.group(3)]["sent_ms"] / 1000 + int(m.group(1)) * 60 + repeat_extra_s
            wait = target - time.time()
            if wait > 0:
                print(f"  waiting {wait:.0f}s so {lead['id']} lands {int(m.group(1))}-{m.group(2)} min after {m.group(3)}")
                time.sleep(wait)
        elif i:
            time.sleep(gap_s)
        sid = f"{run_tag}-{lead['id']}"
        payload = payload_for(lead, sid)
        sent_ms = int(time.time() * 1000)
        status = post(endpoint, payload, secret)
        rec = {"id": lead["id"], "submission_id": sid, "email": lead["email"], "name": lead["name"],
               "sent_ms": sent_ms, "http_status": status}
        if m and m.group(3) in by_id:
            rec["after_ref_s"] = round((sent_ms - by_id[m.group(3)]["sent_ms"]) / 1000, 1)
        sent.append(rec)
        by_id[lead["id"]] = rec
        print(f"  sent {lead['id']} ({lead['source']}) -> HTTP {status}")
    return sent


# ---------- waiting ----------

def wait_until_settled(obs, sent, timeout_s, grace_s):
    """Done when every lead has a Lead log row and every row marked replied has its email in the inbox."""
    sids = {s["submission_id"] for s in sent}
    deadline = time.time() + timeout_s
    while True:
        obs.refresh()
        done = [r for r in obs.lead_log() if r.get("submission_id") in sids and r.get("status") != "processing"]
        rows = {r.get("submission_id") for r in done}
        replied = [r for r in done if r.get("replied") == "yes"]
        first_sent = min(s["sent_ms"] for s in sent)
        mails_missing = [r for r in replied if not obs.inbox(r["email"], first_sent)]
        if len(rows) == len(sids) and not mails_missing:
            print(f"  all {len(sids)} leads logged; waiting {grace_s}s grace for late or extra emails")
            time.sleep(grace_s)
            obs.refresh()
            return True
        if time.time() > deadline:
            print(f"  TIMEOUT: {len(rows)}/{len(sids)} leads logged, {len(mails_missing)} logged replies not in inbox")
            return False
        time.sleep(5)


# ---------- grading ----------

def reply_flags(lead, body, booking_link, prices):
    """Automatic hints for the manual review. Never final."""
    if not body:
        return []
    flags, low, exp = [], body.lower(), lead["expected_reply"].lower()
    invented = sorted(set(PRICE_RE.findall(body)) - prices)
    if invented:
        flags.append("price not in business.md: " + " ".join(invented))
    if DISCOUNT_RE.search(body):
        flags.append("mentions discount/financing")
    if len(body.split()) > MAX_WORDS:
        flags.append(f"over {MAX_WORDS} words ({len(body.split())})")
    if "tarping" in exp and not ("24/7" in body and "tarp" in low):
        flags.append("missing 24/7 tarping")
    if "no booking link" in exp and booking_link and booking_link.lower() in low:
        flags.append("has booking link (should not)")
    if "out of area" in exp and not re.search(r"outside|out of (our )?(service )?area", low):
        flags.append("does not say out of area")
    if "gutter guard price" in exp and not ("$8" in body and "$14" in body):
        flags.append("missing gutter guard range $8-$14")
    elif "gutter price" in exp and not ("$1,200" in body and "$3,000" in body):
        flags.append("missing gutter range $1,200-$3,000")
    if "skylight price" in exp and "$1,400" not in body:
        flags.append("missing skylight $1,400")
    if "spanish" in exp and not SPANISH_RE.search(body):
        flags.append("does not look Spanish")
    if lead["expected_tier"] in ("hot", "warm") and booking_link and booking_link.lower() not in low:
        flags.append("missing booking link")
    if "northline team" not in low and "equipo de northline" not in low:
        flags.append("no 'The Northline team' sign-off")
    return flags


def expected_slack_kinds(lead, expect_failure):
    exp = lead["expected_slack"].lower()
    kinds = ["hot"] if exp.startswith("hot") else ["invalid_contact"] if exp.startswith("invalid") else []
    # Failure test: the lead is still answered and alerted as usual, plus a "lead failed" alert.
    return kinds + ["lead_failed"] if expect_failure else kinds


def grade(leads, sent, obs, run_start_ms, booking_link, expect_failure):
    prices = allowed_prices()
    sent_by_id = {s["id"]: s for s in sent}
    lead_log = {}
    for r in obs.lead_log():  # a claim row ("processing") is replaced by its finished row when there is one
        if r.get("status") != "processing" or r.get("submission_id") not in lead_log:
            lead_log[r.get("submission_id")] = r
    slack_rows = obs.slack_log()
    # Leads that share an address (repeat enquiries): each owns the emails that arrive between its
    # own send and the next send to the same address.
    same_addr = {}
    for s in sent:
        same_addr.setdefault(s["email"].lower(), []).append(s)

    rows = []
    for lead in leads:
        s = sent_by_id.get(lead["id"])
        if not s:
            continue
        sheet = lead_log.get(s["submission_id"], {})
        email_valid = bool(EMAIL_RE.match(lead["email"]))

        # Reply
        mails = []
        if email_valid:
            group = same_addr[lead["email"].lower()]
            nxt = next((g["sent_ms"] for g in group if g["sent_ms"] > s["sent_ms"]), None)
            # Count only messages Gmail filed in the inbox (or spam), not a SENT-only copy.
            mails = [m for m in obs.inbox(lead["email"], s["sent_ms"]) if (nxt is None or m["internal_ms"] < nxt)
                     and {"INBOX", "SPAM"} & set(m.get("labels", []))]
        # A CRM failure must not stop the reply (failure test included).
        exp_reply = lead["expected_reply"].lower().startswith("yes")
        first = mails[0] if mails else None
        # Upper bound: internalDate is truncated to the second.
        secs = round((first["internal_ms"] + 1000 - s["sent_ms"]) / 1000, 2) if first else None
        # No inbox to search for an invalid address: trust the workflow's own log of whether it sent anything.
        replied = bool(mails) if email_valid else sheet.get("replied") == "yes"

        # CRM
        exp_crm = lead["expected_crm"].lower()
        contacts = obs.contacts_by_email(lead["email"]) if email_valid else \
            obs.contacts_by_name(lead["name"], run_start_ms)
        c = contacts[0] if contacts else None
        n_notes = len(c["notes"]) if c else 0
        n_deals = len(c["deals"]) if c else 0
        if expect_failure:
            crm_ok = not contacts
        elif exp_crm.startswith("none"):
            crm_ok = not contacts
        elif exp_crm.startswith("update"):
            crm_ok = len(contacts) == 1 and n_notes >= 2
        else:
            crm_ok = (len(contacts) == 1 and n_notes >= 1 and (n_deals >= 1) == (lead["expected_tier"] == "hot")
                      and (bool(c["email"]) == email_valid))

        # Slack
        kinds = sorted(r.get("kind", "") for r in slack_rows if r.get("submission_id") == s["submission_id"])
        exp_kinds = expected_slack_kinds(lead, expect_failure)
        slack_ok = kinds == sorted(exp_kinds) and all(
            str(r.get("ok", "")).lower() == "true" for r in slack_rows if r.get("submission_id") == s["submission_id"])

        # Sheet
        exp_status = "failed" if expect_failure else ("repeat" if exp_crm.startswith("update") else "ok")
        # Only this lead's own row counts; a shared contact's tier may come from an earlier enquiry.
        actual_tier = (sheet.get("tier") or "").lower()

        body = first["body"] if first else ""
        flags = reply_flags(lead, body, booking_link, prices)
        if len(mails) > 1:
            flags.append(f"{len(mails)} emails received")
        rows.append({
            "lead_id": lead["id"], "source": lead["source"],
            "expected_tier": lead["expected_tier"], "actual_tier": actual_tier,
            "tier_ok": actual_tier == lead["expected_tier"], "crm_tier": c["tier"] if c else "",
            "expected_reply": lead["expected_reply"], "replied": replied, "reply_count": len(mails),
            "reply_ok": replied == exp_reply,
            "sent_at_utc": utc(s["sent_ms"]), "inbox_at_utc": utc(first["internal_ms"]) if first else "",
            "seconds_to_inbox": secs if secs is not None else "",
            "under_60s": (secs < 60) if secs is not None else "",
            "sheet_seconds_to_reply": sheet.get("seconds_to_reply", ""),
            "landed_in": ",".join(l for l in (first or {}).get("labels", []) if l in ("INBOX", "SPAM", "TRASH")),
            "expected_crm": lead["expected_crm"], "crm_contacts": len(contacts), "crm_notes": n_notes,
            "crm_deals": n_deals, "crm_deal_stage": c["deals"][0]["stage"] if c and c["deals"] else "",
            "crm_ok": crm_ok,
            "expected_slack": lead["expected_slack"], "slack_kinds": " ".join(kinds), "slack_ok": slack_ok,
            "sheet_status": sheet.get("status", "(no row)"), "sheet_ok": sheet.get("status") == exp_status,
            "sheet_reason": sheet.get("reason", ""),
            "http_status": s["http_status"], "sent_after_ref_s": s.get("after_ref_s", ""),
            "auto_reply_flags": "; ".join(flags),
            "reply_subject": first["subject"] if first else "", "reply_text": body,
            "manual_tier_ok": "", "manual_reply_ok": "", "manual_notes": "",
            "_contact_ids": [x["id"] for x in contacts], "_email_valid": email_valid,
            "_exp_reply": exp_reply, "_slack_extra": [k for k in kinds if k not in exp_kinds],
        })
    return rows


def summarize(rows, leads_by_id, slack_rows, sids):
    n = len(rows)
    yes = [r for r in rows if r["_exp_reply"]]
    no = [r for r in rows if not r["_exp_reply"]]
    secs = [r["seconds_to_inbox"] for r in yes if r["seconds_to_inbox"] != ""]
    exp_contacts = sum(1 for r in rows if not leads_by_id[r["lead_id"]]["expected_crm"].lower().startswith(("none", "update")))
    contact_ids = {i for r in rows for i in r["_contact_ids"]}
    dups = sum(max(0, r["crm_contacts"] - 1) for r in rows)
    run_slack = [x for x in slack_rows if x.get("submission_id") in sids]
    s = {
        "leads": n,
        "tier_auto": f"{sum(r['tier_ok'] for r in rows)}/{n}",
        "replies_sent": f"{sum(r['replied'] for r in yes)}/{len(yes)}",
        "wrong_replies": f"{sum(r['replied'] for r in no)}/{len(no)}",
        "seconds_to_inbox_median_upper": round(statistics.median(secs), 2) if secs else None,
        "seconds_to_inbox_max_upper": round(max(secs), 2) if secs else None,
        "under_60": f"{sum(1 for x in secs if x < 60)}/{len(yes)}",
        "hubspot_contacts": f"{len(contact_ids)} (expected {exp_contacts})",
        "hubspot_duplicates": dups,
        "crm_ok": f"{sum(r['crm_ok'] for r in rows)}/{n}",
        "slack_hot": f"{sum(1 for x in run_slack if x.get('kind') == 'hot')} (expected "
                     f"{sum(1 for r in rows if leads_by_id[r['lead_id']]['expected_slack'].lower().startswith('hot'))})",
        "slack_invalid": f"{sum(1 for x in run_slack if x.get('kind') == 'invalid_contact')} (expected "
                         f"{sum(1 for r in rows if leads_by_id[r['lead_id']]['expected_slack'].lower().startswith('invalid'))})",
        "slack_failed": sum(1 for x in run_slack if x.get("kind") == "lead_failed"),
        "slack_false": sum(len(r["_slack_extra"]) for r in rows),
        "sheet_ok": f"{sum(r['sheet_ok'] for r in rows)}/{n}",
        "price_flags_L10_L12": {r["lead_id"]: r["auto_reply_flags"] for r in rows if r["lead_id"] in ("L10", "L12")},
    }
    return s


def mask(text, env, run_tag):
    """Keep the real inbox address and booking link out of files that get committed."""
    base = env.get("TEST_EMAIL_BASE", "")
    local, _, domain = base.partition("@")
    out = str(text)
    if local and domain:
        out = re.sub(re.escape(local) + r"\+" + re.escape(run_tag) + r"\+(L\d+)@" + re.escape(domain),
                     r"{TEST}+\1", out, flags=re.I)
        out = re.sub(re.escape(base), "{TEST_EMAIL_BASE}", out, flags=re.I)
    if env.get("BOOKING_LINK"):
        out = out.replace(env["BOOKING_LINK"], "{BOOKING_LINK}")
    return out


def write_csv(rows, path, env, run_tag):
    cols = [k for k in rows[0] if not k.startswith("_")]
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow({k: mask(r[k], env, run_tag) for k in cols})


def print_report(rows, s, settled):
    print("\nlead tier(exp/got)   reply  secs   crm  slack sheet flags")
    for r in rows:
        print(f"{r['lead_id']:4} {r['expected_tier']:>5}/{r['actual_tier'] or '-':<6} {'ok ' if r['tier_ok'] else 'BAD'} "
              f"{'ok ' if r['reply_ok'] else 'BAD'} {str(r['seconds_to_inbox']):>6} "
              f"{'ok ' if r['crm_ok'] else 'BAD'}  {'ok ' if r['slack_ok'] else 'BAD'}  {'ok ' if r['sheet_ok'] else 'BAD'}  "
              f"{r['auto_reply_flags'][:70]}")
    print("\nSummary (auto; manual review is final)" + ("" if settled else "  [run did NOT settle: timeout]"))
    for k, v in s.items():
        print(f"  {k}: {v}")


def append_log(s, meta, out, settled):
    LOG.parent.mkdir(exist_ok=True)
    new = not LOG.exists()
    with LOG.open("a", encoding="utf-8") as f:
        if new:
            f.write("# Lead runner results log\n\nEvery run of `eval/run_leads.py --log`, appended as measured. "
                    "Auto grades are hints until the manual review is done.\n")
        f.write(f"\n## Run {meta['run_tag']} — {meta['label']}\n\n")
        f.write(f"- Endpoint: {meta['observer']} | leads: {s['leads']} | results file: `{out.name}`"
                f"{'' if settled else ' | DID NOT SETTLE (timeout)'}\n")
        for k, v in s.items():
            f.write(f"- {k}: {v}\n")
        f.write("- Manual review: pending\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stub", help="stub base URL, e.g. http://127.0.0.1:5679 (sends to /lead, observes /_state)")
    ap.add_argument("--endpoint", help="override the lead webhook URL (default LEAD_WEBHOOK_URL)")
    ap.add_argument("--only", help="comma-separated lead ids, e.g. L03")
    ap.add_argument("--expect-failure", action="store_true", help="failure test (HubSpot broken): expect no contact, status=failed, Slack lead_failed, reply still sent")
    ap.add_argument("--gap", type=float, default=20, help="seconds between sends (default 20)")
    ap.add_argument("--repeat-extra", type=float, default=30,
                    help="repeat leads go this many seconds after the window's lower bound (default 30 -> 2.5 min)")
    ap.add_argument("--timeout", type=float, default=300, help="max seconds to wait after the last send")
    ap.add_argument("--grace", type=float, default=30, help="seconds to keep watching for extra emails once settled")
    ap.add_argument("--grade", metavar="RUN_TAG", help="re-check an earlier run from eval/.runs/ without sending")
    ap.add_argument("--label", default="")
    ap.add_argument("--out", help="results CSV (default eval/results.csv; with --grade, eval/results-<run>.csv)")
    ap.add_argument("--log", action="store_true", help="append the summary to eval/results-log.md")
    args = ap.parse_args()

    env = load_env()
    RUNS.mkdir(parents=True, exist_ok=True)
    if args.grade:
        meta = json.loads((RUNS / f"{args.grade}.json").read_text())
    else:
        require(env, "TEST_EMAIL_BASE")
        stub = args.stub.rstrip("/") if args.stub else ""
        endpoint = args.endpoint or (stub + "/lead" if stub else env.get("LEAD_WEBHOOK_URL", ""))
        if not endpoint:
            raise SystemExit("No endpoint: pass --stub or set LEAD_WEBHOOK_URL in .env")
        if not stub:
            require(env, "N8N_WEBHOOK_SECRET")
        run_tag = "r" + datetime.now().strftime("%m%d%H%M%S")
        meta = {"run_tag": run_tag, "label": args.label or ("stub" if stub else "real"), "stub": stub,
                "observer": "stub" if stub else "real", "expect_failure": args.expect_failure,
                "run_start_ms": int(time.time() * 1000), "only": args.only or ""}
        leads = materialize(load_leads(), env["TEST_EMAIL_BASE"], run_tag)
        if args.only:
            keep = set(args.only.split(","))
            leads = [l for l in leads if l["id"] in keep]
        print(f"run {run_tag}: sending {len(leads)} leads to {'stub' if stub else 'n8n webhook'}")
        meta["sent"] = send_all(leads, endpoint, env.get("N8N_WEBHOOK_SECRET", ""), args.gap, args.repeat_extra, run_tag)
        (RUNS / f"{run_tag}.json").write_text(json.dumps(meta, indent=2))

    run_tag = meta["run_tag"]
    if meta["observer"] == "stub":
        obs, booking = StubObserver(meta["stub"]), "https://stub.invalid/book"
    else:
        require(env, "HUBSPOT_TOKEN", "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_RUNNER_REFRESH_TOKEN",
                "LEAD_LOG_SHEET_ID", "BOOKING_LINK")
        obs, booking = RealObserver(env), env["BOOKING_LINK"]

    leads = materialize(load_leads(), env["TEST_EMAIL_BASE"], run_tag)
    sent_ids = {s["id"] for s in meta["sent"]}
    leads = [l for l in leads if l["id"] in sent_ids]
    print("waiting for the workflow to finish...")
    settled = wait_until_settled(obs, meta["sent"], 0 if args.grade else args.timeout, 0 if args.grade else args.grace)
    rows = grade(leads, meta["sent"], obs, meta["run_start_ms"], booking, meta["expect_failure"])
    s = summarize(rows, {l["id"]: l for l in leads}, obs.slack_log(), {x["submission_id"] for x in meta["sent"]})
    repeat = [x for x in meta["sent"] if "after_ref_s" in x]
    for x in repeat:
        s[f"{x['id']}_sent_after_s"] = x["after_ref_s"]
    out = Path(args.out) if args.out else ROOT / "eval" / ("results.csv" if not args.grade else f"results-{run_tag}.csv")
    write_csv(rows, out, env, run_tag)
    print_report(rows, s, settled)
    print(f"\nwrote {out}")
    if args.log:
        append_log(s, meta, out, settled)
        print(f"appended summary to {LOG}")


if __name__ == "__main__":
    main()
