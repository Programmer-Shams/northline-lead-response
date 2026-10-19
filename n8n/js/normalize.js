// Website form or Facebook Lead Ads payload -> one flat lead. t0 = when n8n received it.
const t0 = Date.now();
const raw = $input.first().json.body;
const body = raw && typeof raw === 'object' ? raw : {};
const clean = (v, max = 500) => String(v ?? '').replace(/\s+/g, ' ').trim().slice(0, max);
let lead;
if (body.source === 'facebook' || 'field_data' in body) {
  const fields = Array.isArray(body.field_data) ? body.field_data : [];
  const f = Object.fromEntries(fields.filter(d => d && d.name).map(d => [d.name, (d.values || [])[0] ?? '']));
  lead = { source: 'facebook', submission_id: body.leadgen_id, name: f.full_name, email: f.email,
           phone: f.phone_number, city: f.city, service: f.what_service_do_you_need,
           message: f.tell_us_about_your_project };
} else {
  lead = { source: body.source === 'website' ? 'website' : 'unknown', submission_id: body.submission_id,
           name: body.name, email: body.email, phone: body.phone, city: body.city, service: body.service,
           message: body.message };
}
for (const k of Object.keys(lead)) lead[k] = clean(lead[k], k === 'message' ? 2000 : 200);
lead.email = lead.email.toLowerCase();
lead.email_valid = /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(lead.email);
lead.city = lead.city.toLowerCase().replace(/(^|[\s-])\p{L}/gu, c => c.toUpperCase());
const [first, ...rest] = lead.name.split(' ');
lead.firstname = first || '';
lead.lastname = rest.join(' ');
lead.submission_id = lead.submission_id || `n8n-${$execution.id}`;
lead.execution_id = String($execution.id);
lead.t0_ms = t0;
lead.t0 = new Date(t0).toISOString();
// Office hours from business.md: Monday to Saturday, 7:00 am to 6:00 pm Eastern.
const parts = Object.fromEntries(new Intl.DateTimeFormat('en-US', {
  timeZone: 'America/New_York', weekday: 'short', hour: 'numeric', hourCycle: 'h23' })
  .formatToParts(new Date(t0)).map(p => [p.type, p.value]));
lead.office_open = parts.weekday !== 'Sun' && Number(parts.hour) >= 7 && Number(parts.hour) < 18;
lead.now_eastern = new Date(t0).toLocaleString('en-US', {
  timeZone: 'America/New_York', weekday: 'long', year: 'numeric', month: 'long', day: 'numeric',
  hour: 'numeric', minute: '2-digit' });
return [{ json: lead }];
