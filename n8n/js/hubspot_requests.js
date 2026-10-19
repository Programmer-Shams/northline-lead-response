// HubSpot request bodies. Contacts are upserted by email; a lead without a valid email gets a new contact.
const s = $json;
const esc = v => String(v ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const props = { firstname: s.firstname, lastname: s.lastname, phone: s.phone, city: s.city,
                hs_lead_status: s.tier.toUpperCase() };
const contact = s.email_valid
  ? { url: 'https://api.hubapi.com/crm/v3/objects/contacts/batch/upsert',
      body: { inputs: [{ idProperty: 'email', id: s.email, properties: { ...props, email: s.email } }] } }
  : { url: 'https://api.hubapi.com/crm/v3/objects/contacts', body: { properties: props } };
const lines = [
  `<b>AI lead tier: ${esc(s.tier.toUpperCase())}</b>`,
  `Reason: ${esc(s.ai.reason)}`,
  `Service: ${esc(s.ai.service)} | Timeline: ${esc(s.ai.timeline)} | Language: ${esc(s.ai.language)}`,
  `Source: ${esc(s.source)} (${esc(s.submission_id)})`,
  `Message: "${esc(s.message)}"`,
];
if (!s.email_valid) lines.push(`Email given: "${esc(s.email)}" (invalid, no reply sent)`);
const note = { properties: { hs_timestamp: String(s.t0_ms), hs_note_body: lines.join('<br>') } };
const deal = { properties: { dealname: `${s.name} - ${s.ai.service}`.slice(0, 120),
                             pipeline: '__ENV_HUBSPOT_PIPELINE_ID__', dealstage: '__ENV_HUBSPOT_NEW_LEAD_STAGE_ID__' } };
const repeatNote = { properties: { hs_timestamp: String(s.t0_ms), hs_note_body: [
  `<b>Repeat enquiry within 24 h (no second reply sent)</b>`,
  `AI tier: ${esc(s.tier.toUpperCase())}. ${esc(s.reason)}`,
  `Source: ${esc(s.source)} (${esc(s.submission_id)})`,
  `Message: "${esc(s.message)}"`].join('<br>') } };
// Repeat enquiry: find the contact by email (upsert with only the email changes nothing on an existing
// contact, and still works if the first enquiry's run has not created it yet).
const findContact = { inputs: [{ idProperty: 'email', id: s.email, properties: { email: s.email } }] };
return [{ json: { ...s, hubspot: { contact, note, deal, repeatNote, findContact } } }];
