// Parse the model's JSON and pick the route: crm (new lead), repeat_note, or finish (spam / AI failed).
const lead = $('Build AI request').first().json;
const res = $input.first().json;
const BOOKING_LINK = '__ENV_BOOKING_LINK__';
const problems = [...lead.problems];
let ai = null;
if (res.error) {
  problems.push(`AI step failed: ${String(res.error.message || JSON.stringify(res.error)).slice(0, 200)}`);
} else {
  try {
    ai = JSON.parse(res.choices[0].message.content);
    if (!['hot', 'warm', 'cold', 'spam'].includes(ai.tier)) throw new Error(`unknown tier "${ai.tier}"`);
  } catch (e) {
    problems.push(`AI output unreadable: ${e.message}`);
    ai = null;
  }
}
// Hold any reply carrying a link other than the booking link (the lead's own text must never become a link we send).
if (ai && ai.reply_text) {
  const links = (ai.reply_text.match(/(https?:\/\/|www\.)[^\s)>\]]+/gi) || []).filter(u => !u.startsWith(BOOKING_LINK));
  if (links.length) {
    problems.push(`Reply held: it contains a link that is not the booking link (${links.join(' ').slice(0, 120)})`);
    ai = { ...ai, reply_text: null };
  }
}
let route = 'finish';
if (ai && lead.repeat) route = 'repeat_note';
else if (ai && ai.tier !== 'spam') route = 'crm';
const { ai_request, ...rest } = lead;
return [{ json: { ...rest, ai, tier: ai ? ai.tier : '', reason: ai ? ai.reason : '', route, problems } }];
