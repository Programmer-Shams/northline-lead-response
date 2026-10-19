# Northline lead response

Every new lead from a website form or a Facebook lead ad gets a personal email reply within seconds, is scored hot, warm or cold by AI, and lands in HubSpot with a note explaining the score. Hot leads alert the sales team in Slack, spam and repeat enquiries are filtered, and failures retry and raise an alert. Every lead is logged to a Google Sheet. ([Case study](docs/case-study.md))

Northline Roofing & Exteriors (Columbus, Ohio) is a fictional company. Its facts, prices and rules are in [`data/business.md`](data/business.md); the 20 test leads are in [`data/test-leads.csv`](data/test-leads.csv).

## How it works

![Architecture: lead sources, n8n webhook, claim and dedupe, GPT-5.5, HubSpot, Gmail, Slack and the Lead log](docs/architecture.png)

The diagram's source is `docs/architecture.html` (open it in a browser; export at 2x).

One n8n execution per lead (`n8n/workflows/northline-lead-response.json`):

1. **Lead in.** The webhook (header key required) answers at once and stamps t0. It accepts the website form's JSON and Facebook Lead Ads' `field_data` shape, normalizes both, and checks the email format.
2. **Claim and dedupe.** The lead claims a row in the Lead log straight away. If the same email already has a handled lead in the last 24 hours (or one still in progress), this lead is a repeat: it gets a HubSpot note and no second reply. The same lead id delivered twice is dropped.
3. **AI step.** GPT-5.5 gets only `data/business.md` as context and returns strict JSON: tier, reason, service, timeline, language, reply subject and reply text. The lead's own text is passed as data, never as instructions; it only sees the first name, city, service and message.
4. **CRM step (HubSpot).** Creates or updates the contact by email, sets Lead status to Hot, Warm or Cold, adds a note with the AI's reason, and for hot leads creates a deal in the "New lead" stage.
5. **Reply.** Gmail sends the reply in the lead's language, except for spam, repeats and invalid email addresses. A reply that contains any link other than the booking link is held. The reply still goes out if the CRM step fails.
6. **Alerts and log.** Slack gets one message per lead when needed: hot lead (name, city, problem, phone, HubSpot link), invalid contact details, or lead failed. The Lead log row is completed (t0, t1, seconds to reply, tier, reason, replied, CRM id, status) and every Slack post is logged in a "Slack log" tab.

Every external call (OpenAI, HubSpot, Gmail, Sheets, Slack) retries 3 times, 2 seconds apart. If it still fails, the lead is marked failed and Slack gets a "lead failed" alert. If anything crashes after the webhook has answered, a separate error workflow posts "lead workflow crashed" to Slack.

## Repository layout

| Path | What it is |
| --- | --- |
| `BUILD_SPEC.md` | The approved spec: architecture, build steps, metrics, done criteria |
| `data/` | Business facts (the AI's only context) and the 20 test leads with expected outcomes |
| `n8n/` | Workflow builder (`build_workflows.py`), deployer (`deploy.py`), AI prompt (`system_prompt.md`), Code-node JavaScript with tests (`js/`), HubSpot and Sheet setup scripts, and the generated, importable workflow JSON (`workflows/`) |
| `eval/` | Test runner, stub webhook, HubSpot cleanup, manual review workbook, results and run log |
| `scripts/` | Shared helpers: `.env` reader, payload shapes, Google consent for the runner, Facebook lead sender |
| `web/` | Next.js + shadcn/ui lead form; its server route forwards to n8n with the webhook key |
| `docs/` | Architecture diagram and case study |

## Setup

You need Python 3.13+, Node 22, Docker, an OpenAI API key, a HubSpot account (free CRM), a Google account (Gmail and Sheets), a Slack incoming webhook and a Cal.com booking link.

1. **Secrets.** `cp .env.example .env` and fill it in as you go. `.env` is git-ignored; scripts read it directly and never print values.
2. **Python.** `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`.
3. **n8n.** Run n8n 2.43.7 locally (`docker run -d --name n8n -p 127.0.0.1:5678:5678 -v n8n_data:/home/node/.n8n docker.n8n.io/n8nio/n8n:2.43.7`), create the owner account, then Settings → n8n API → create a key and put it in `.env` as `N8N_API_KEY`.
4. **HubSpot.** In Development → Keys, create a service key (or a legacy private app token) with `crm.objects.contacts.read/write`, `crm.objects.deals.read/write` and `crm.schemas.contacts.read/write`. Put it in `.env` as `HUBSPOT_TOKEN`, then run `.venv/bin/python n8n/hubspot_setup.py`. It adds Hot, Warm and Cold to the Lead status property and a "New lead" deal stage (safe to rerun).
5. **Google.** In Google Cloud, enable the Gmail, Sheets and Drive APIs, set up the OAuth consent screen (Testing, add yourself as a test user) and create a Web application client with two redirect URIs: `http://localhost:5678/rest/oauth2-credential/callback` and `http://localhost:8765/`. Put the client id and secret in `.env`. Create a blank Google Sheet and put its id in `LEAD_LOG_SHEET_ID`. Run `.venv/bin/python scripts/google_auth.py` (consent for the test runner), then `.venv/bin/python n8n/sheet_setup.py` (creates the tabs and headers).
6. **Deploy.** Fill `SLACK_WEBHOOK_URL`, `BOOKING_LINK` and `TEST_EMAIL_BASE` (the Gmail inbox that receives test replies), then run `.venv/bin/python n8n/deploy.py`. It creates the n8n credentials, generates the webhook key, deploys and activates both workflows, and writes the webhook URL and key to `.env` and `web/.env.local`. In n8n, open the **Northline Gmail** and **Northline Google Sheets** credentials and click **Sign in with Google** once each.
7. **Form.** `cd web && npm install && npm run build && npm start`, then open http://127.0.0.1:3200.

## Changing the business facts

Edit `data/business.md` (services, service area, price ranges, tier rules, reply rules) and run `.venv/bin/python n8n/deploy.py`. The file is pasted into the AI prompt at deploy time, so the next lead uses the new facts. Keep the `{BOOKING_LINK}` placeholder; deploy fills it from `.env`. Prices in replies are checked against the dollar amounts in this file by the test runner.

## Swapping the CRM

Everything CRM-specific sits in the "CRM step (HubSpot)" box on the n8n canvas (`HubSpot: …` nodes, built in `build_workflows.py`, request bodies in `n8n/js/hubspot_requests.js`). The box ends in a node named **CRM result** (`n8n/js/crm_result.js`) that outputs three fields: `crm_id`, `crm_url` and `crm_problems`. Nothing outside the box reads HubSpot. To use GoHighLevel, Zoho or Pipedrive, replace the nodes in the box with that CRM's create-or-update contact, note and deal calls, and keep a final "CRM result" node with the same three fields.

## Evaluation

`eval/run_leads.py` sends the 20 test leads in order (L09 two and a half minutes after L01, so it lands inside the 2 to 5 minute window), waits for every lead to finish, then checks each one against the expected columns by reading HubSpot, the Gmail inbox and the Sheet directly. It never asks n8n. Each run uses fresh plus-addresses (`name+<run>+L01@gmail.com`), so reruns don't collide with the 24-hour dedupe.

```
.venv/bin/python eval/run_leads.py --label "gpt-5.5" --log           # 20 leads, writes eval/results.csv
.venv/bin/python n8n/deploy.py --break-hubspot                        # failure test: invalid HubSpot token
.venv/bin/python eval/run_leads.py --only L02 --expect-failure --out eval/failure-test.csv --log
.venv/bin/python n8n/deploy.py --restore-hubspot
.venv/bin/python eval/review_sheet.py export-google                   # manual review as a Google Sheet (or: export, for .xlsx)
.venv/bin/python eval/review_sheet.py import-google                   # verdicts back into results.csv (or: import)
.venv/bin/python eval/cleanup_hubspot.py --label "gpt-5.5" --yes      # delete a run's test contacts
```

Tests: `node n8n/js/test.mjs` (Code-node logic: dedupe, office hours, link hold, Slack escaping, failure paths) and `.venv/bin/python -m unittest eval/test_run_leads.py` (reply checks and masking).

Results and every run, including the earlier one and its bug, are in [`eval/results-log.md`](eval/results-log.md). The final run is `eval/results.csv`; the failure test is `eval/failure-test.csv`.

### Final run (20 leads, 19 October 2026, every reply read by hand)

| Measure | Result |
| --- | --- |
| Tier accuracy (manual review) | 20/20 (automatic check 19/20: L12 scored hot where the test set expected warm; the review accepted hot) |
| Replies sent to the 16 leads that should get one | 16/16 |
| Wrong replies (2 spam, 1 repeat within 24 h, 1 invalid email) | 0/4 |
| Seconds from submit to inbox | median 11.6 s, max 16.52 s (upper bounds); 16/16 under 60 s |
| HubSpot contacts | 17 as expected, 0 duplicates (the repeat enquiry added a note to the first contact) |
| Hot deals | 7: the 6 expected hot leads plus L12 |
| Slack | 7 hot alerts (6 expected + L12), 1 invalid-contact alert, no alerts for leads that weren't hot |
| Invented prices or discounts in replies | 0 (including the "90% off" injection in L12) |
| Lead log rows | 20/20 |
| Failure test (HubSpot key broken) | reply still sent in 17.07 s; Slack hot alert + "lead failed"; Sheet row failed; no contact created |

## Known limits

- **No temperature 0.** GPT-5.5 only accepts its default temperature (the API rejects 0), so tiers and wording can vary between runs. The tier rules in `business.md` leave some room: in the final run, "a roof inspection sometime this month" on 19 October was scored hot (12 days left in the month), while the test set expects warm.
- **Retries are fixed, not backoff.** n8n's built-in retry waits a fixed time, so every call retries 3 times, 2 seconds apart. A timeout after a call actually succeeded could repeat it (for example a second note).
- **Timing.** Seconds to inbox is Gmail's arrival time (whole seconds, so reported as an upper bound) minus the moment the test runner posted the lead. Test replies go to the sending account's own plus-addresses, so this measures arrival in that Gmail mailbox, not delivery to another email provider.
- **Office hours.** The final run happened while the office was closed, so hot replies said "first thing next business morning". The open/closed switch is computed in code and covered by tests; the "within 1 business hour" wording was not part of a measured run.
- **Leads without a valid email** are never deduped: a repeat creates another contact and another invalid-contact alert.
- **AI failure.** If the AI step fails after its retries, the lead gets no reply and no CRM record; Slack gets "lead failed" and the Sheet row says why.
- **Facebook.** The workflow accepts the lead object as the Graph API returns it (`field_data` with `full_name`, `email`, `phone_number`, `city`, `what_service_do_you_need`, `tell_us_about_your_project`). A real Lead Ads webhook only sends a lead id, so production needs one Graph API call to fetch the lead first.
- **Slack check.** The test runner checks the Slack log the workflow keeps (Slack answered HTTP 200), not the Slack channel itself.
- **Form.** The server route rate-limits per IP and per email in memory and has a honeypot field. A public deployment should add a captcha and a shared rate-limit store.
- **Secrets in n8n.** The webhook key appears in n8n's stored executions (request headers) and the Slack webhook URL is a node parameter. Keep the n8n editor private.

## Deviations from the spec

| Spec | Built | Why |
| --- | --- | --- |
| One HTML form page | Next.js + shadcn/ui form with a server route | Requested during the build; also keeps the webhook key off the browser |
| AI at temperature 0 | Default temperature, strict JSON schema | GPT-5.5 rejects temperature 0 |
| Retry 3x with backoff | 3 retries, 2 s apart | n8n's built-in retry has a fixed wait; chosen over a custom loop to keep the workflow readable |
| Repeat lead: add note, stop | Repeat still goes through the AI (for its tier), then note only | So all 20 leads get a tier to measure; no reply, no alert |
| CRM failure: alert + failed row | Same, and the reply is still sent | The customer still gets the 60-second answer; the team adds the contact by hand |
