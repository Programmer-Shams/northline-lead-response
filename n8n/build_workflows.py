"""Generate the Northline lead workflows (BUILD_SPEC step 2).

The JSON holds no secrets: keys live in n8n credentials (created by deploy.py), and deploy-time
values use placeholders that deploy.py fills in:
  __CRED_<NAME>__   n8n credential ids
  __ENV_<KEY>__     values from .env (Sheet id, booking link, HubSpot ids, Slack webhook URL)
  __WF_ERROR__      id of the error-alert workflow

Code-node JavaScript lives in n8n/js/*.js. The AI prompt is n8n/system_prompt.md with
data/business.md pasted in, so changing the business facts = edit business.md and redeploy.

northline-lead-response (one execution per lead):
  Lead in (webhook, answers at once) -> Normalize lead -> Claim lead (append a "processing" row to the
  Lead log) -> Find previous leads (Lead log rows for the email) -> Check repeat -> Duplicate delivery?
  -> Build AI request -> Classify lead (GPT-5.5, strict JSON) -> Read AI result -> Route
     crm         -> [CRM box: upsert contact -> note -> deal if hot -> CRM result] -> Has valid email? -> Send reply
     repeat_note -> [CRM box: find contact -> note -> CRM result]
     finish      -> (spam or AI failed)
  -> Finish -> Slack alerts -> Post to Slack -> Slack log rows -> Log Slack sends
            -> Lead log row -> Log lead (updates the claimed row) -> Alert: log failed (on error)
northline-error-alert: any crash in the lead workflow -> Slack "lead workflow crashed".

Every external call retries 3 times, 2 s apart (n8n's built-in retry), then continues, so Finish can
record the problem, mark the lead failed and raise a Slack "lead failed" alert. The reply is still sent
if the CRM fails. Sheet writes use Google's append API (no row races) and RAW values (no formulas).
"""
import json
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
OUT = HERE / "workflows"
JS = HERE / "js"
BUSINESS = ROOT / "data" / "business.md"

MODEL = "gpt-5.5"
# GPT-5.5 rejects temperature 0 (only the default is allowed); low reasoning effort keeps replies fast.
REASONING_EFFORT = "low"
WEBHOOK_PATH = "northline-lead"
HTTP_TIMEOUT_MS = 30000
RETRY = {"retryOnFail": True, "maxTries": 4, "waitBetweenTries": 2000}
ROUTES = ["crm", "repeat_note", "finish"]

OPENAI_CRED = {"openAiApi": {"id": "__CRED_OPENAI__", "name": "Northline OpenAI"}}
HUBSPOT_CRED = {"hubspotAppToken": {"id": "__CRED_HUBSPOT__", "name": "Northline HubSpot"}}
GMAIL_CRED = {"gmailOAuth2": {"id": "__CRED_GMAIL__", "name": "Northline Gmail"}}
SHEETS_CRED = {"googleSheetsOAuth2Api": {"id": "__CRED_SHEETS__", "name": "Northline Google Sheets"}}
WEBHOOK_CRED = {"httpHeaderAuth": {"id": "__CRED_WEBHOOK__", "name": "Northline webhook key"}}

AI_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["tier", "reason", "service", "timeline", "language", "reply_subject", "reply_text"],
    "properties": {
        "tier": {"type": "string", "enum": ["hot", "warm", "cold", "spam"]},
        "reason": {"type": "string"},
        "service": {"type": "string"},
        "timeline": {"type": "string"},
        "language": {"type": "string"},
        "reply_subject": {"type": ["string", "null"]},
        "reply_text": {"type": ["string", "null"]},
    },
}


def js(name: str, **replace) -> str:
    text = (JS / f"{name}.js").read_text()
    for k, v in replace.items():
        text = text.replace(k, v)
    return text.strip()


def system_prompt() -> str:
    business = BUSINESS.read_text().replace("{BOOKING_LINK}", "__ENV_BOOKING_LINK__")
    return (HERE / "system_prompt.md").read_text().replace("{{BUSINESS}}", business.strip()).strip()


def node(name, type_, version, params, pos, **extra):
    return {"id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"northline/{name}")), "name": name, "type": type_,
            "typeVersion": version, "position": pos, "parameters": params, **extra}


def code(name, source, pos, **extra):
    return node(name, "n8n-nodes-base.code", 2, {"jsCode": source}, pos, **extra)


def http(name, pos, url, body_expr, cred_type, creds, *, full_response=False, **extra):
    """POST JSON with retries; on final failure the error goes out as a normal item for the next step to read."""
    options = {"timeout": HTTP_TIMEOUT_MS}
    if full_response:
        options["response"] = {"response": {"fullResponse": True}}
    params = {"method": "POST", "url": url, "sendBody": True, "specifyBody": "json", "jsonBody": body_expr,
              "options": options}
    if cred_type:
        params.update(authentication="predefinedCredentialType", nodeCredentialType=cred_type)
        extra["credentials"] = creds
    return node(name, "n8n-nodes-base.httpRequest", 4.2, params, pos, **RETRY, onError="continueRegularOutput",
                **extra)


def sheet_ref(tab):
    return {"documentId": {"__rl": True, "mode": "id", "value": "__ENV_LEAD_LOG_SHEET_ID__"},
            "sheetName": {"__rl": True, "mode": "name", "value": tab}}


# RAW: lead text is stored as typed, never parsed as a formula; ids stay strings.
# useAppend: Google's own append API. The default reads the sheet length and writes to that row number,
# so two leads finishing together overwrite each other's row (seen in eval run 1: L08 vs L09).
SHEET_WRITE_OPTIONS = {"cellFormat": "RAW", "useAppend": True}


def sheets_append(name, tab, pos, **extra):
    return node(name, "n8n-nodes-base.googleSheets", 4.5, {
        "authentication": "oAuth2", "operation": "append", **sheet_ref(tab),
        "columns": {"mappingMode": "autoMapInputData", "value": {}, "schema": []},
        "options": SHEET_WRITE_OPTIONS,
    }, pos, credentials=SHEETS_CRED, **RETRY, **extra)


def if_node(name, expr, pos):
    return node(name, "n8n-nodes-base.if", 2.2, {
        "conditions": {"options": {"caseSensitive": True, "leftValue": "", "typeValidation": "loose", "version": 2},
                       "conditions": [{"id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"northline/cond/{name}")),
                                       "leftValue": expr, "rightValue": "",
                                       "operator": {"type": "boolean", "operation": "true", "singleValue": True}}],
                       "combinator": "and"},
        "options": {},
    }, pos)


def sticky(name, content, pos, width, height, color=None):
    params = {"content": content, "width": width, "height": height}
    if color:
        params["color"] = color
    return node(name, "n8n-nodes-base.stickyNote", 1, params, pos)


def contact_id_expr(node_name):
    j = f"$('{node_name}').first().json"
    return f"String({j}.results ? {j}.results[0].id : {j}.id)"


def note_body(payload_expr, contact_node, assoc_type):
    return ("={{ JSON.stringify({ ..." + payload_expr + ", associations: [{ to: { id: " + contact_id_expr(contact_node) +
            " }, types: [{ associationCategory: 'HUBSPOT_DEFINED', associationTypeId: " + str(assoc_type) + " }] }] }) }}")


CONTACT_OK = "={{ !$json.error && ($json.results ? $json.results.length > 0 : !!$json.id) }}"


def lead_workflow():
    state = "$('Read AI result').first().json"
    req = "$('HubSpot: build requests').first().json.hubspot"
    nodes = [
        sticky("Note: CRM step", "## CRM step (HubSpot)\nEverything CRM-specific is in this box. To use GoHighLevel, "
               "Zoho or Pipedrive, replace these nodes and keep a final node named \"CRM result\" that outputs "
               "crm_id, crm_url and crm_problems; nothing outside the box reads HubSpot.",
               [2180, -300], 1580, 620, color=4),
        node("Lead in", "n8n-nodes-base.webhook", 2.1,
             {"httpMethod": "POST", "path": WEBHOOK_PATH, "authentication": "headerAuth",
              "responseMode": "onReceived", "options": {"responseData": '{"received": true}'}},
             [0, 0], webhookId=str(uuid.uuid5(uuid.NAMESPACE_URL, "northline/webhook")), credentials=WEBHOOK_CRED),
        code("Normalize lead", js("normalize"), [220, 0]),
        code("Claim row", js("claim_row"), [440, 0]),
        sheets_append("Claim lead", "Lead log", [660, 0], onError="continueRegularOutput"),
        node("Find previous leads", "n8n-nodes-base.googleSheets", 4.5, {
            "authentication": "oAuth2", "operation": "read", **sheet_ref("Lead log"),
            "filtersUI": {"values": [{"lookupColumn": "email", "lookupValue":
                                      "={{ $('Normalize lead').first().json.email_valid ? "
                                      "$('Normalize lead').first().json.email : '(no valid email)' }}"}]},
            "options": {},
        }, [880, 0], credentials=SHEETS_CRED, **RETRY, alwaysOutputData=True, onError="continueRegularOutput"),
        code("Check repeat", js("check_repeat"), [1100, 0]),
        if_node("Duplicate delivery?", "={{ $json.duplicate }}", [1320, 0]),
        code("Build AI request", js("build_ai_request", __SYSTEM_PROMPT__=json.dumps(system_prompt()),
                                    __SCHEMA__=json.dumps(AI_SCHEMA), __MODEL__=json.dumps(MODEL),
                                    __REASONING_EFFORT__=json.dumps(REASONING_EFFORT)), [1540, 60]),
        http("Classify lead (GPT-5.5)", [1760, 60], "https://api.openai.com/v1/chat/completions",
             "={{ JSON.stringify($json.ai_request) }}", "openAiApi", OPENAI_CRED),
        code("Read AI result", js("read_ai"), [1980, 60]),
        node("Route", "n8n-nodes-base.switch", 3.2, {
            "mode": "expression", "numberOutputs": len(ROUTES),
            # Unknown routes go to "finish" (Switch throws on -1).
            "output": f"={{{{ {json.dumps(ROUTES)}.includes($json.route) ? {json.dumps(ROUTES)}.indexOf($json.route) "
                      f": {ROUTES.index('finish')} }}}}",
        }, [2200, 60]),
        # --- CRM box (HubSpot) ---
        code("HubSpot: build requests", js("hubspot_requests"), [2420, -140]),
        http("HubSpot: upsert contact", [2640, -140], "={{ $json.hubspot.contact.url }}",
             "={{ JSON.stringify($json.hubspot.contact.body) }}", "hubspotAppToken", HUBSPOT_CRED),
        if_node("HubSpot: contact saved?", CONTACT_OK, [2860, -140]),
        http("HubSpot: add note", [3080, -200], "https://api.hubapi.com/crm/v3/objects/notes",
             note_body(f"{req}.note", "HubSpot: upsert contact", 202), "hubspotAppToken", HUBSPOT_CRED),
        if_node("HubSpot: hot lead?", f"={{{{ {state}.tier === 'hot' }}}}", [3300, -200]),
        http("HubSpot: create deal", [3520, -240], "https://api.hubapi.com/crm/v3/objects/deals",
             note_body(f"{req}.deal", "HubSpot: upsert contact", 3), "hubspotAppToken", HUBSPOT_CRED),
        code("HubSpot: build repeat note", js("hubspot_requests"), [2420, 160]),
        http("HubSpot: find contact", [2640, 160], "https://api.hubapi.com/crm/v3/objects/contacts/batch/upsert",
             "={{ JSON.stringify($json.hubspot.findContact) }}", "hubspotAppToken", HUBSPOT_CRED),
        if_node("HubSpot: contact found?", CONTACT_OK, [2860, 160]),
        http("HubSpot: note on existing contact", [3080, 120], "https://api.hubapi.com/crm/v3/objects/notes",
             note_body("$('HubSpot: build repeat note').first().json.hubspot.repeatNote", "HubSpot: find contact", 202),
             "hubspotAppToken", HUBSPOT_CRED),
        code("CRM result", js("crm_result"), [3640, 60]),
        # --- reply ---
        if_node("Has valid email?", f"={{{{ {state}.route === 'crm' && {state}.email_valid && "
                                    f"!!(({state}.ai || {{}}).reply_text || '').trim() }}}}", [3880, 60]),
        node("Send reply", "n8n-nodes-base.gmail", 2.1, {
            "resource": "message", "operation": "send", "sendTo": f"={{{{ {state}.email }}}}",
            "subject": f"={{{{ {state}.ai.reply_subject || 'Thanks for contacting Northline Roofing & Exteriors' }}}}",
            "emailType": "text", "message": f"={{{{ {state}.ai.reply_text }}}}",
            "options": {"appendAttribution": False, "senderName": "__ENV_SENDER_NAME__"},
        }, [4100, 0], credentials=GMAIL_CRED, **RETRY, onError="continueRegularOutput"),
        # --- finish, alerts, logs ---
        code("Finish", js("finish"), [4340, 160]),
        code("Slack alerts", js("slack_alerts"), [4560, 40]),
        http("Post to Slack", [4780, 40], "__ENV_SLACK_WEBHOOK_URL__", "={{ JSON.stringify({ text: $json.text }) }}",
             None, None, full_response=True),
        code("Slack log rows", js("slack_log_rows"), [5000, 40]),
        sheets_append("Log Slack sends", "Slack log", [5220, 40], onError="continueRegularOutput"),
        code("Lead log row", js("lead_log_row"), [4560, 300]),
        node("Log lead", "n8n-nodes-base.googleSheets", 4.5, {
            "authentication": "oAuth2", "operation": "appendOrUpdate", **sheet_ref("Lead log"),
            "columns": {"mappingMode": "autoMapInputData", "value": {}, "matchingColumns": ["execution_id"],
                        "schema": []},
            "options": SHEET_WRITE_OPTIONS,
        }, [4780, 300], credentials=SHEETS_CRED, **RETRY, onError="continueErrorOutput"),
        http("Alert: log failed", [5000, 380], "__ENV_SLACK_WEBHOOK_URL__",
             "={{ JSON.stringify({ text: ':rotating_light: *Lead log failed* - could not write the Lead log row for ' + "
             "$('Lead log row').first().json.submission_id + '. Check the n8n execution.' }) }}", None, None),
    ]
    to = lambda name: [{"node": name, "type": "main", "index": 0}]  # noqa: E731
    conn = {
        "Lead in": {"main": [to("Normalize lead")]},
        "Normalize lead": {"main": [to("Claim row")]},
        "Claim row": {"main": [to("Claim lead")]},
        "Claim lead": {"main": [to("Find previous leads")]},
        "Find previous leads": {"main": [to("Check repeat")]},
        "Check repeat": {"main": [to("Duplicate delivery?")]},
        "Duplicate delivery?": {"main": [to("Finish"), to("Build AI request")]},
        "Build AI request": {"main": [to("Classify lead (GPT-5.5)")]},
        "Classify lead (GPT-5.5)": {"main": [to("Read AI result")]},
        "Read AI result": {"main": [to("Route")]},
        "Route": {"main": [to("HubSpot: build requests"), to("HubSpot: build repeat note"), to("Finish")]},
        "HubSpot: build requests": {"main": [to("HubSpot: upsert contact")]},
        "HubSpot: upsert contact": {"main": [to("HubSpot: contact saved?")]},
        "HubSpot: contact saved?": {"main": [to("HubSpot: add note"), to("CRM result")]},
        "HubSpot: add note": {"main": [to("HubSpot: hot lead?")]},
        "HubSpot: hot lead?": {"main": [to("HubSpot: create deal"), to("CRM result")]},
        "HubSpot: create deal": {"main": [to("CRM result")]},
        "HubSpot: build repeat note": {"main": [to("HubSpot: find contact")]},
        "HubSpot: find contact": {"main": [to("HubSpot: contact found?")]},
        "HubSpot: contact found?": {"main": [to("HubSpot: note on existing contact"), to("CRM result")]},
        "HubSpot: note on existing contact": {"main": [to("CRM result")]},
        "CRM result": {"main": [to("Has valid email?")]},
        "Has valid email?": {"main": [to("Send reply"), to("Finish")]},
        "Send reply": {"main": [to("Finish")]},
        # Slack branch is above the log branch, so n8n (v1 order) runs it first and the Lead log row,
        # which the test runner waits for, is written last.
        "Finish": {"main": [to("Slack alerts") + to("Lead log row")]},
        "Slack alerts": {"main": [to("Post to Slack")]},
        "Post to Slack": {"main": [to("Slack log rows")]},
        "Slack log rows": {"main": [to("Log Slack sends")]},
        "Lead log row": {"main": [to("Log lead")]},
        "Log lead": {"main": [[], to("Alert: log failed")]},
    }
    return {"name": "Northline lead response (GPT-5.5)", "nodes": nodes, "connections": conn,
            "settings": {"executionOrder": "v1", "saveManualExecutions": True, "errorWorkflow": "__WF_ERROR__"}}


def error_workflow():
    """Safety net: a crash anywhere in the lead workflow (after the webhook already answered) alerts Slack."""
    text = ("={{ JSON.stringify({ text: ':rotating_light: *Lead workflow crashed* - a lead may not have been answered.\\n"
            "*Execution:* ' + ($json.execution.id || 'unknown') + '\\n*Node:* ' + ($json.execution.lastNodeExecuted || "
            "'unknown') + '\\n*Error:* ' + String(($json.execution.error || {}).message || 'unknown')"
            ".replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').slice(0, 300) + "
            "'\\nCheck the Lead log for a row stuck in processing.' }) }}")
    nodes = [
        node("On workflow error", "n8n-nodes-base.errorTrigger", 1, {}, [0, 0]),
        http("Alert: workflow crashed", [220, 0], "__ENV_SLACK_WEBHOOK_URL__", text, None, None),
    ]
    conn = {"On workflow error": {"main": [[{"node": "Alert: workflow crashed", "type": "main", "index": 0}]]}}
    return {"name": "Northline lead workflow error alert", "nodes": nodes, "connections": conn,
            "settings": {"executionOrder": "v1"}}


def build() -> dict:
    # Order matters: deploy.py creates the error workflow first so its id can fill __WF_ERROR__.
    return {"northline-error-alert": error_workflow(), "northline-lead-response": lead_workflow()}


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    for name, wf in build().items():
        (OUT / f"{name}.json").write_text(json.dumps(wf, indent=2, ensure_ascii=False) + "\n")
        print(f"wrote n8n/workflows/{name}.json ({len(wf['nodes'])} nodes)")
