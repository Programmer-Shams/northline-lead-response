// At most one Slack message per lead (hot lead, invalid contact, lead failed), so n8n's retry covers it whole.
const s = $('Finish').first().json;
// Slack mrkdwn: escape lead and AI text so it can't ping @channel or plant links.
const esc = v => String(v ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
const link = s.crm_url ? `<${s.crm_url}|Open in HubSpot>` : 'not created (CRM step failed)';
const msg = esc(s.message.length > 300 ? s.message.slice(0, 300) + '…' : s.message);
const kinds = [], parts = [];
if (s.tier === 'hot' && !s.repeat && !s.duplicate) {
  kinds.push('hot');
  parts.push(`:fire: *Hot lead* - call within 1 business hour\n*Name:* ${esc(s.name)}\n*City:* ${esc(s.city)}\n` +
    `*Problem:* ${msg}\n*Why hot:* ${esc(s.reason)}\n*Phone:* ${esc(s.phone) || 'not given'}\n*CRM:* ${link}`);
}
if (!s.email_valid && s.tier && s.tier !== 'spam' && !s.repeat && !s.duplicate) {
  kinds.push('invalid_contact');
  parts.push(`:warning: *Invalid contact* - no reply could be sent\n*Name:* ${esc(s.name)} (${esc(s.city)})\n` +
    `*Email given:* \`${esc(s.email) || '(empty)'}\`\n*Phone:* ${esc(s.phone) || 'not given'}\n` +
    `*Tier:* ${esc(s.tier)} - ${esc(s.reason)}\n*CRM:* ${link}`);
}
if (s.status === 'failed') {
  kinds.push('lead_failed');
  parts.push(`:rotating_light: *Lead failed* - needs a person\n*Lead:* ${esc(s.name) || '(no name)'} ` +
    `(${esc(s.source)}, ${esc(s.submission_id)})\n*Reply sent:* ${s.replied}\n*Problems:* ${esc(s.problems.join('; '))}\n` +
    `Full row in the Lead log sheet.`);
}
return kinds.length ? [{ json: { kinds, text: parts.join('\n\n'), submission_id: s.submission_id } }] : [];
