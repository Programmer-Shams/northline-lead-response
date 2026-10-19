"""One-time setup of the Google Sheet the workflow logs to. Safe to re-run.

Creates the "Lead log" tab (renaming the blank first tab) and the "Slack log" tab, writes the header
rows and freezes them. Uses the runner's Google token from scripts/google_auth.py.

Usage: .venv/bin/python n8n/sheet_setup.py
"""
import sys
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "eval"))
from envfile import load_env, require  # noqa: E402
from observe import LEAD_LOG_TAB, SLACK_LOG_TAB, Google, _http  # noqa: E402

LEAD_LOG_COLUMNS = ["submission_id", "source", "name", "email", "t0", "t1", "seconds_to_reply", "tier", "reason",
                    "replied", "crm_id", "status", "problems", "execution_id"]
SLACK_LOG_COLUMNS = ["ts", "submission_id", "kind", "ok", "http_status"]


def main():
    env = load_env()
    require(env, "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_RUNNER_REFRESH_TOKEN", "LEAD_LOG_SHEET_ID")
    g = Google(env["GOOGLE_CLIENT_ID"], env["GOOGLE_CLIENT_SECRET"], env["GOOGLE_RUNNER_REFRESH_TOKEN"])
    base = f"https://sheets.googleapis.com/v4/spreadsheets/{env['LEAD_LOG_SHEET_ID']}"
    tabs = {s["properties"]["title"]: s["properties"]["sheetId"]
            for s in _http("GET", base + "?fields=sheets.properties", g._auth())["sheets"]}

    requests = []
    if LEAD_LOG_TAB not in tabs:
        if len(tabs) == 1 and "Sheet1" in tabs:
            requests.append({"updateSheetProperties": {"properties": {"sheetId": tabs["Sheet1"], "title": LEAD_LOG_TAB},
                                                       "fields": "title"}})
        else:
            requests.append({"addSheet": {"properties": {"title": LEAD_LOG_TAB}}})
    if SLACK_LOG_TAB not in tabs:
        requests.append({"addSheet": {"properties": {"title": SLACK_LOG_TAB}}})
    if requests:
        _http("POST", base + ":batchUpdate", g._auth(), body={"requests": requests})
        print(f"created tabs: {[r.get('addSheet', r.get('updateSheetProperties'))['properties']['title'] for r in requests]}")

    tabs = {s["properties"]["title"]: s["properties"]["sheetId"]
            for s in _http("GET", base + "?fields=sheets.properties", g._auth())["sheets"]}
    for tab, cols in [(LEAD_LOG_TAB, LEAD_LOG_COLUMNS), (SLACK_LOG_TAB, SLACK_LOG_COLUMNS)]:
        rng = urllib.parse.quote(f"'{tab}'!A1")
        _http("PUT", f"{base}/values/{rng}?valueInputOption=RAW", g._auth(), body={"values": [cols]})
    _http("POST", base + ":batchUpdate", g._auth(), body={"requests": [
        {"updateSheetProperties": {"properties": {"sheetId": tabs[t], "gridProperties": {"frozenRowCount": 1}},
                                   "fields": "gridProperties.frozenRowCount"}} for t in (LEAD_LOG_TAB, SLACK_LOG_TAB)]})
    print(f"headers written: {LEAD_LOG_TAB} ({len(LEAD_LOG_COLUMNS)} columns), {SLACK_LOG_TAB} ({len(SLACK_LOG_COLUMNS)})")


if __name__ == "__main__":
    main()
