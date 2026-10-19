// The CRM box's only output: crm_id, crm_url and crm_problems. Swapping HubSpot for GoHighLevel, Zoho or
// Pipedrive means replacing the nodes in this box and keeping a node named "CRM result" with these fields.
const s = $('Read AI result').first().json;
const out = name => { try { return $(name).isExecuted ? $(name).first().json : null; } catch (e) { return null; } };
const errOf = j => j && j.error ? String(j.error.message || j.error.description || JSON.stringify(j.error)).slice(0, 200) : '';
const idOf = j => j ? String((j.results && j.results[0] && j.results[0].id) || j.id || '') : '';
const problems = [];
const contactNode = s.route === 'repeat_note' ? 'HubSpot: find contact' : 'HubSpot: upsert contact';
const contact = out(contactNode);
let crmId = '';
if (!contact) problems.push('HubSpot contact step did not run');
else if (errOf(contact)) problems.push(`HubSpot contact failed: ${errOf(contact)}`);
else if (!(crmId = idOf(contact))) problems.push('HubSpot returned no contact id');
for (const n of ['HubSpot: add note', 'HubSpot: create deal', 'HubSpot: note on existing contact']) {
  const j = out(n);
  if (j && errOf(j)) problems.push(`${n} failed: ${errOf(j)}`);
}
const crmUrl = crmId ? `https://__ENV_HUBSPOT_APP_HOST__/contacts/__ENV_HUBSPOT_PORTAL_ID__/record/0-1/${crmId}` : '';
return [{ json: { ...s, crm_id: crmId, crm_url: crmUrl, crm_problems: problems } }];
