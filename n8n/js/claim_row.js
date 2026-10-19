// Claim a Lead log row the moment the lead arrives (appended with Google's append API, so concurrent
// leads never collide). Dedupe reads these claims; the final outcome later updates this same row.
const s = $json;
return [{ json: { execution_id: s.execution_id, submission_id: s.submission_id, source: s.source, name: s.name,
                  email: s.email, t0: s.t0, status: 'processing' } }];
