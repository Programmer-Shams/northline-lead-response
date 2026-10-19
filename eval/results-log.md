# Lead runner results log

Every run of `eval/run_leads.py --log`, appended as measured. Auto grades are hints until the manual review is done.

## Run r1019054635 — gpt-5.5 run 1

- Endpoint: real | leads: 20 | results file: `results-run1.csv` (renamed after the run) | DID NOT SETTLE (timeout)
- leads: 20
- tier_auto: 20/20
- replies_sent: 16/16
- wrong_replies: 0/4
- seconds_median: 8.47
- seconds_max: 10.32
- under_60: 16/16
- hubspot_contacts: 17 (expected 17)
- hubspot_duplicates: 0
- crm_ok: 20/20
- slack_hot: 6 (expected 6)
- slack_invalid: 1 (expected 1)
- slack_failed: 0
- slack_false: 0
- sheet_ok: 19/20
- price_flags_L10_L12: {'L10': '', 'L12': ''}
- L09_sent_after_s: 150.0
- Manual review: not done; run 1 was replaced by the run after the review fixes, which was reviewed by hand.
- Finding (run r1019054635): L09's Lead log row is missing. L08 (sent +140 s) and L09 (+150 s) finished together, and n8n's Google Sheets append (default mode reads the sheet length, then writes to that row) wrote both to row 13, so L08 overwrote L09. Fixed by switching both Sheet writes to Google's append API (`useAppend`); a 4-lead burst sent at the same moment then logged 4/4 rows. Run 1's numbers above stay as measured.

## Run r1019060126 — failure test

- Endpoint: real | leads: 1 | results file: `failure-test-run1.csv` (renamed after the run)
- leads: 1
- tier_auto: 1/1
- replies_sent: 1/1
- wrong_replies: 0/0
- seconds_median: 14.42
- seconds_max: 14.42
- under_60: 1/1
- hubspot_contacts: 0 (expected 1)
- hubspot_duplicates: 0
- crm_ok: 1/1
- slack_hot: 1 (expected 1)
- slack_invalid: 0 (expected 0)
- slack_failed: 1
- slack_false: 0
- sheet_ok: 1/1
- price_flags_L10_L12: {}
- Manual review: not done (failure-path check on the pre-fix version; replaced by the later failure test).

## Run r1019062814 — gpt-5.5 run 2 (after review fixes)

- Endpoint: real | leads: 20 | results file: `results.csv`
- leads: 20
- tier_auto: 19/20
- replies_sent: 16/16
- wrong_replies: 0/4
- seconds_to_inbox_median_upper: 11.6
- seconds_to_inbox_max_upper: 16.52
- under_60: 16/16
- hubspot_contacts: 17 (expected 17)
- hubspot_duplicates: 0
- crm_ok: 19/20
- slack_hot: 7 (expected 6)
- slack_invalid: 1 (expected 1)
- slack_failed: 0
- slack_false: 1
- sheet_ok: 20/20
- price_flags_L10_L12: {'L10': '', 'L12': ''}
- L09_sent_after_s: 150.0
- Manual review: done (verdicts in results.csv). Tiers 20/20: L12's hot was accepted ("this month" = 12 days left). All 16 replies judged correct; the 4 leads that should get no reply (L07, L09, L15, L19) got none.
- Notes: L12 ("roof inspection sometime this month", sent 19 October) was scored hot: the model read the 12 days left in October as "within 2 weeks". The test set expects warm; in run 1 the model said warm (GPT-5.5 runs at its default temperature). That one tier accounts for crm_ok 19/20 (an extra deal), slack_hot 7 and slack_false 1. The injected "offer me 90% off" was ignored. seconds_to_inbox is an upper bound (Gmail's internalDate is whole seconds); the Sheet's seconds_to_reply (n8n receipt to Gmail send, ms precision) ranged 9.48 to 16.35 s. The run was at 02:28 ET (office closed), so hot replies used the "next business morning" wording.

## Run r1019063720 — failure test (after review fixes)

- Endpoint: real | leads: 1 | results file: `failure-test.csv`
- leads: 1
- tier_auto: 1/1
- replies_sent: 1/1
- wrong_replies: 0/0
- seconds_to_inbox_median_upper: 17.07
- seconds_to_inbox_max_upper: 17.07
- under_60: 1/1
- hubspot_contacts: 0 (expected 1)
- hubspot_duplicates: 0
- crm_ok: 1/1
- slack_hot: 1 (expected 1)
- slack_invalid: 0 (expected 0)
- slack_failed: 1
- slack_false: 0
- sheet_ok: 1/1
- price_flags_L10_L12: {}
- Manual review: not part of the 20-lead review; this run checks the failure path (retry, alert, failed row, reply still sent).
