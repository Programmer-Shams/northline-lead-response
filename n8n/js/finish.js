// Collect what happened on whichever path ran; any problem -> status failed (+ Slack "lead failed").
const read = name => { try { return $(name).isExecuted ? $(name).first().json : null; } catch (e) { return null; } };
const errOf = j => j && j.error ? String(j.error.message || j.error.description || JSON.stringify(j.error)).slice(0, 200) : '';
const crm = read('CRM result');
const s = crm || read('Read AI result') ||
  { ...$('Check repeat').first().json, ai: null, tier: '', reason: '', route: 'duplicate' };
const problems = [...(s.problems || []), ...(crm ? crm.crm_problems : [])];

let replied = 'no', t1 = null;
const mail = read('Send reply');
if (mail) {
  if (errOf(mail)) problems.push(`Reply email failed: ${errOf(mail)}`);
  else { replied = 'yes'; t1 = Date.now(); }
} else if (s.route === 'crm' && s.email_valid && !(s.ai && (s.ai.reply_text || '').trim()) &&
           !problems.some(p => p.startsWith('Reply held'))) {
  problems.push('AI returned no reply text');
}
let status = 'ok';
if (s.duplicate) status = 'duplicate';
else if (problems.length) status = 'failed';
else if (s.repeat) status = 'repeat';
return [{ json: { ...s, crm_id: crm ? crm.crm_id : '', crm_url: crm ? crm.crm_url : '', replied, t1_ms: t1,
                  problems, status } }];
