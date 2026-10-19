// Dedupe against Lead log rows for the same email, in claim order (row number):
//  - an earlier row with the same submission_id -> duplicate delivery: drop it
//  - an earlier lead in the last 24 h that was handled (replied or in the CRM) or is still processing
//    -> repeat: note only, no second reply. Spam and leads that got nowhere don't count.
const lead = $('Normalize lead').first().json;
const DAY_MS = 24 * 3600 * 1000;
const PROCESSING_MAX_MS = 10 * 60 * 1000;  // a run takes seconds; an older "processing" row is a crashed run
const CLOCK_SLACK_MS = 60 * 1000;
const items = $input.all().map(i => i.json);
const problems = [];
const readError = items.find(r => r && r.error);
if (readError) problems.push(`Dedupe check failed: ${String(readError.error.message || readError.error).slice(0, 200)}`);
try {
  const claim = $('Claim lead').first().json;
  if (claim.error) problems.push(`Could not claim a Lead log row: ${String(claim.error.message || claim.error).slice(0, 200)}`);
} catch (e) { /* claim node always runs before this one */ }
const rows = items.filter(r => r && !r.error && r.email !== undefined);
const own = rows.find(r => String(r.execution_id) === lead.execution_id);
const ownRow = own ? Number(own.row_number) : Infinity;
const earlier = !lead.email_valid ? [] : rows.filter(r =>
  String(r.execution_id) !== lead.execution_id && Number(r.row_number) < ownRow &&
  String(r.email).toLowerCase() === lead.email);
const duplicate = earlier.some(r => String(r.submission_id) === lead.submission_id);
const handled = r => {
  // Claim order (row number) decides who is first; a row claimed earlier can still carry a t0 a little later
  // than ours when two leads arrive together, so a small negative age still counts.
  const age = lead.t0_ms - Date.parse(r.t0);
  if (!(age > -CLOCK_SLACK_MS && age < DAY_MS)) return false;
  if (r.status === 'processing') return age < PROCESSING_MAX_MS;
  return r.tier !== 'spam' && (r.replied === 'yes' || String(r.crm_id || '') !== '');
};
const prior = earlier.filter(handled);
return [{ json: { ...lead, duplicate, repeat: !duplicate && prior.length > 0, problems } }];
