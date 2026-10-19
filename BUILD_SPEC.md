# Demo 2: 60-Second AI Lead Response — Build Spec

Portfolio demo for Shams's Upwork profile. Approved 2026-10-18. Time box: 2 working days, hard stop.

## What it must prove (from real Upwork posts)

Service businesses asked for: every new lead answered within a minute, qualified by AI, logged in the CRM without manual entry, with the sales team alerted for hot leads and nothing failing silently. Proof posts:
- https://www.upwork.com/jobs/~022110781592121312597 (real estate AI lead management, $1,000)
- https://www.upwork.com/jobs/~022110995751514430442 (GHL + n8n lead qualification and follow-up)
- https://www.upwork.com/jobs/~022109994135801227234 (AI lead qualification + booking + CRM)
- https://www.upwork.com/jobs/~022111472155209072281 (Facebook lead form instant reply)
- https://www.upwork.com/jobs/~022111624797640650069 (n8n lead qualification into HubSpot)

## Folder contents

| Path | What it is |
| --- | --- |
| `data/business.md` | Facts, service area, price ranges, tier rules and reply rules for the fictional company Northline Roofing & Exteriors (Columbus, Ohio) |
| `data/test-leads.csv` | 20 test leads with expected tier, reply, CRM and Slack outcomes: 7 hot (one is a repeat enquiry), 7 warm (one has an invalid email), 4 cold, 2 spam |

Replace `{TEST}` in the CSV with a Gmail plus-address you own (e.g. `yourname+demo@gmail.com` becomes `yourname+demo+L01@gmail.com`), so every reply lands in a real inbox you can time. Replace `{BOOKING_LINK}` with a free Cal.com link.

## Architecture

```
Website form (simple HTML) ─┐
Facebook-style lead payload ─┴─► n8n webhook (lead in, timestamp t0)
   ├─ validate + normalize (email format, city, source)
   ├─ dedupe: same email in last 24h? → add note to existing HubSpot contact, no second reply, stop
   ├─ AI step (temperature 0, JSON output): {tier, reason, service, timeline, language, reply_text or null}
   │     uses ONLY data/business.md as context
   ├─ HubSpot (free CRM): create/update contact by email; lead status = tier; note with AI reason
   │     hot → also create a deal in "New lead" stage
   ├─ Send reply email (Gmail node) unless tier = spam or email invalid  (timestamp t1)
   ├─ Slack: hot → alert with name, city, problem, phone, HubSpot link; invalid email → "invalid contact" alert
   └─ Google Sheet "Lead log": one row per lead: t0, t1, seconds_to_reply, tier, reason, replied, crm_id, status
Error branch on every external call: retry 3x with backoff → if still failing, Slack "lead failed" alert + Sheet row status=failed
```

Model: OpenAI or Claude, whichever performed better in Demo 1 (GPT-5.5 scored higher; Claude was faster). Run the 20 leads on one model only; time box is 2 days.

## CRM choice

HubSpot free CRM. Clients name GoHighLevel more often (5 vs 3 in the research), but GHL costs $97/month after its trial. The HubSpot step must be one clearly separated node group, so the case study can say "the CRM step swaps to GoHighLevel, Zoho or Pipedrive".

## Build steps

1. **Accounts:** HubSpot free (developer test account or free CRM) with a private app token (scopes: crm.objects.contacts read/write, crm.objects.deals read/write, crm.objects.notes write if listed); Gmail account for sending (n8n Gmail OAuth); Slack workspace with an incoming webhook (reuse Demo 1's); Google Sheet; Cal.com free booking link.
2. **n8n workflow** as above, exported to `n8n/workflows/`. Reuse Demo 1's local n8n.
3. **Form page:** one HTML page with name, email, phone, city, service dropdown, message → posts to the webhook with `source=website`. A small script posts the Facebook-style leads with `source=facebook`.
4. **Test runner** (`eval/run_leads.py`): sends the 20 leads in order (L09 sent 2–5 minutes after L01), waits, then checks each against the expected columns using HubSpot API, Gmail inbox (IMAP or Gmail API search by plus-address), Slack (log of webhook sends kept by n8n in the Sheet) and the Sheet. Writes `eval/results.csv`.
5. **Manual review:** read every reply email. Tier and reply verdicts by hand are final.

## Metrics to report (measured, never estimated)

- Tier accuracy: x/20
- Replies sent to the 16 leads that should get one: x/16; wrong replies sent (spam, repeat, invalid): x/4
- Seconds from form submit (t0) to email in inbox: median and max across the 16, and how many under 60 s
- HubSpot: 17 contacts expected, 0 duplicates (L09 updates L01)
- Slack: 6 hot alerts + 1 invalid-contact alert, 0 false alerts
- Failure test: run one lead with the HubSpot token deliberately broken; show the retry, the "lead failed" Slack alert and the Sheet row. Then restore it.
- Reply quality: 0 invented prices or discounts (check L10, L12)

## Done criteria

- [ ] 20 test leads run through the real workflow; results in `eval/results.csv`; every reply email reviewed by hand
- [ ] Failure test recorded
- [ ] 60–120 s video: submit a lead on the form → reply arriving in the inbox with a visible clock → HubSpot contact with the AI note → Slack hot alert → the Sheet log → the failure alert → the results table
- [ ] Architecture diagram
- [ ] Case study (problem → what was built → measured results)
- [ ] README: setup, how to change the business facts, how to swap the CRM, known limits
- [ ] Upwork portfolio item live with the video uploaded to Upwork; no outside links
- [ ] Every number came from `eval/results.csv`
- [ ] Repo has no secrets and no personal contact details (same checks as Demo 1)

## Portfolio item (fill numbers from the eval)

**Title:** AI Lead Response System: Every Lead Answered and in Your CRM in Under 60 Seconds
**Description:** New leads from a website form or Facebook ad get a personalized reply in [median] seconds, are scored hot, warm or cold by AI, and land in HubSpot with a note explaining the score. Hot leads alert the sales team in Slack; spam and repeat enquiries are filtered; failures retry and raise an alert. Tested on 20 leads: [x]/20 scored correctly, [x]/16 replies under 60 seconds, 0 duplicate contacts. Built with n8n, [model], HubSpot, Gmail, Slack and Google Sheets.

## Claude Code kickoff prompt

> Read BUILD_SPEC.md, data/business.md and data/test-leads.csv. We are building Demo 2 exactly as specified, time-boxed to 2 days. Reuse the local n8n and Slack webhook from Demo 1 (brightpan-support-agent). You do the setup and build yourself; stop only for things you cannot do (account sign-ups, OAuth consent clicks, keys I must paste).
> Rules: secrets only in `.env` (gitignored first); never print keys; do not touch Demo 1's workflows or Supabase project; build the test runner first (step 4) against a stub webhook so we measure from the first working version; do not invent values, results or numbers. After each step: 3 lines — what works, what's next, what you need from me.

## Things only Shams can do

1. HubSpot free account sign-up and creating the private app token.
2. Gmail OAuth consent in n8n (click through Google's consent screen).
3. Cal.com free account and booking link.
4. Paste keys into `.env` when asked.
5. Record the video, upload the portfolio item.
