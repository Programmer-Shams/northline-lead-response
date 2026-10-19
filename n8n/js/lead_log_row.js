// Final outcome for this lead's claimed Lead log row (matched on execution_id).
// A failed Slack post also marks the lead failed (the Slack log has the details).
const s = $('Finish').first().json;
const problems = [...s.problems];
let slackFailed = false;
try {
  if ($('Post to Slack').isExecuted) slackFailed = !!$('Post to Slack').first().json.error;
} catch (e) { /* no alert for this lead */ }
if (slackFailed) problems.push('Slack alert failed');
const status = slackFailed && s.status !== 'duplicate' ? 'failed' : s.status;
return [{ json: {
  execution_id: s.execution_id, submission_id: s.submission_id, source: s.source, name: s.name, email: s.email,
  t0: s.t0, t1: s.t1_ms ? new Date(s.t1_ms).toISOString() : '',
  seconds_to_reply: s.t1_ms ? ((s.t1_ms - s.t0_ms) / 1000).toFixed(2) : '',
  tier: s.tier, reason: s.reason, replied: s.replied, crm_id: s.crm_id, status, problems: problems.join('; '),
} }];
