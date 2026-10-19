// One "Slack log" row per alert kind in the (single) Slack message.
const alert = $('Slack alerts').first().json;
const r = $input.first().json;
const code = r.statusCode || (r.error && (r.error.httpCode || r.error.status)) || '';
const ok = !r.error && Number(code || 200) < 300;
const ts = new Date().toISOString();
return alert.kinds.map(kind => ({ json: { ts, submission_id: alert.submission_id, kind, ok: String(ok),
                                          http_status: String(code || (r.error ? 'error' : 200)) } }));
