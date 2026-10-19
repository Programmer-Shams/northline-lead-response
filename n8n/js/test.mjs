// Tests for the workflow's Code-node JavaScript, run outside n8n with mocked $ / $input / $json.
// Run: node n8n/js/test.mjs
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));

/** Run a Code-node file. nodes: { 'Node name': json | Error-like {notExecuted:true} }, input: [json]. */
function run(file, { nodes = {}, input = [], json, executionId = '100', replace = {} } = {}) {
  let src = readFileSync(join(HERE, `${file}.js`), 'utf8');
  for (const [k, v] of Object.entries(replace)) src = src.replaceAll(k, v);
  const $ = name => {
    const n = nodes[name];
    if (n === undefined) throw new Error(`Referenced node doesn't exist: ${name}`);
    const items = Array.isArray(n) ? n : [n];
    return { isExecuted: !n.notExecuted, first: () => ({ json: items[0] }), all: () => items.map(j => ({ json: j })) };
  };
  const $input = { first: () => ({ json: input[0] }), all: () => input.map(j => ({ json: j })) };
  const fn = new Function('$', '$input', '$json', '$execution', src);
  return fn($, $input, json ?? input[0], { id: executionId }).map(i => i.json);
}

const NOT_RUN = { notExecuted: true };
const T0 = Date.parse('2026-10-19T14:00:00Z');  // Monday 10:00 Eastern
const lead = (over = {}) => ({ email: 'a@example.com', email_valid: true, submission_id: 's1', execution_id: '100',
                               t0_ms: T0, problems: [], ...over });
const row = (over = {}) => ({ row_number: 2, execution_id: '90', submission_id: 's0', email: 'a@example.com',
                              t0: new Date(T0 - 60_000).toISOString(), status: 'ok', tier: 'hot', replied: 'yes',
                              crm_id: '1', ...over });
const own = row({ row_number: 9, execution_id: '100', submission_id: 's1', status: 'processing', tier: '', replied: '',
                  crm_id: '', t0: new Date(T0).toISOString() });
const checkRepeat = (rows, over) => run('check_repeat', { nodes: { 'Normalize lead': lead(over), 'Claim lead': {} },
                                                         input: rows })[0];
let passed = 0;
const test = (name, fn) => { fn(); passed++; console.log(`ok - ${name}`); };

test('normalize: website lead, office open on a Monday 10:00 ET', () => {
  const realNow = Date.now; Date.now = () => T0;
  try {
    const out = run('normalize', { input: [{ body: { source: 'website', submission_id: 'x', name: 'Dana  Whitfield',
      email: 'Dana@Example.com ', city: 'upper arlington', message: 'Leak' } }] })[0];
    assert.equal(out.email, 'dana@example.com');
    assert.equal(out.city, 'Upper Arlington');
    assert.equal(out.firstname, 'Dana');
    assert.equal(out.office_open, true);
  } finally { Date.now = realNow; }
});

test('normalize: closed on Sunday and after 6 pm ET', () => {
  const realNow = Date.now;
  try {
    Date.now = () => Date.parse('2026-10-18T15:00:00Z');  // Sunday 11:00 ET
    assert.equal(run('normalize', { input: [{ body: {} }] })[0].office_open, false);
    Date.now = () => Date.parse('2026-10-19T22:30:00Z');  // Monday 18:30 ET
    assert.equal(run('normalize', { input: [{ body: {} }] })[0].office_open, false);
  } finally { Date.now = realNow; }
});

test('normalize: malformed Facebook payloads and a null body do not crash', () => {
  for (const body of [{ source: 'facebook', field_data: { name: 'x' } }, { field_data: [null, { values: [] }] }, null]) {
    const out = run('normalize', { input: [{ body }] })[0];
    assert.equal(out.email_valid, false);
  }
  const fb = run('normalize', { input: [{ body: { leadgen_id: '77', field_data: [{ name: 'email', values: ['b@x.io'] }] } }] })[0];
  assert.equal(fb.source, 'facebook');
  assert.equal(fb.submission_id, '77');
});

test('dedupe: earlier handled lead in 24 h -> repeat', () => {
  const r = checkRepeat([row(), own]);
  assert.equal(r.repeat, true);
  assert.equal(r.duplicate, false);
});

test('dedupe: same-email lead still processing (simultaneous) -> repeat; only the earliest claim replies', () => {
  assert.equal(checkRepeat([row({ status: 'processing', tier: '', replied: '', crm_id: '' }), own]).repeat, true);
  const first = checkRepeat([row({ row_number: 9, execution_id: '100', submission_id: 's1', status: 'processing' }),
                             row({ row_number: 10, execution_id: '101', status: 'processing' })]);
  assert.equal(first.repeat, false, 'the earlier claim is not a repeat of a later one');
});

test('dedupe: earlier claim whose t0 is a few ms later than ours (simultaneous arrival) -> repeat', () => {
  // Seen live: both leads arrived together; the one that claimed first got the later t0.
  const r = checkRepeat([row({ status: 'processing', tier: '', replied: '', crm_id: '', t0: new Date(T0 + 40).toISOString() }), own]);
  assert.equal(r.repeat, true);
});

test('dedupe: same submission_id delivered twice -> duplicate', () => {
  const r = checkRepeat([row({ submission_id: 's1' }), own]);
  assert.equal(r.duplicate, true);
  assert.equal(r.repeat, false);
});

test('dedupe: prior spam, prior that got nowhere, stale processing, older than 24 h -> not a repeat', () => {
  assert.equal(checkRepeat([row({ tier: 'spam', replied: 'no', crm_id: '' }), own]).repeat, false);
  assert.equal(checkRepeat([row({ status: 'failed', replied: 'no', crm_id: '' }), own]).repeat, false);
  assert.equal(checkRepeat([row({ status: 'processing', t0: new Date(T0 - 3600_000).toISOString() }), own]).repeat, false);
  assert.equal(checkRepeat([row({ t0: new Date(T0 - 25 * 3600_000).toISOString() }), own]).repeat, false);
});

test('dedupe: failed lead that was still replied to counts (no second reply)', () => {
  assert.equal(checkRepeat([row({ status: 'failed', replied: 'yes', crm_id: '' }), own]).repeat, true);
});

test('dedupe: invalid email never dedupes; Sheet read error is a problem', () => {
  assert.equal(checkRepeat([row({ email: 'not-an-email@@' }), own], { email: 'not-an-email@@', email_valid: false }).repeat, false);
  const r = checkRepeat([{ error: { message: 'quota' } }]);
  assert.equal(r.repeat, false);
  assert.match(r.problems[0], /Dedupe check failed: quota/);
});

const aiState = { problems: [], repeat: false };
const aiReply = text => ({ choices: [{ message: { content: JSON.stringify({ tier: 'warm', reason: 'r', service: 's',
  timeline: 't', language: 'en', reply_subject: 'Hi', reply_text: text }) } }] });
const readAi = (res, over = {}) => run('read_ai', { nodes: { 'Build AI request': { ...aiState, ...over } }, input: [res],
                                                    replace: { __ENV_BOOKING_LINK__: 'https://cal.com/x/inspect' } })[0];

test('read_ai: booking link allowed, any other link holds the reply', () => {
  const ok = readAi(aiReply('Book here: https://cal.com/x/inspect'));
  assert.equal(ok.route, 'crm');
  assert.ok(ok.ai.reply_text);
  const held = readAi(aiReply('See www.evil.example or https://cal.com/x/inspect'));
  assert.equal(held.ai.reply_text, null);
  assert.match(held.problems[0], /Reply held/);
});

test('read_ai: AI error -> finish with a problem; repeat -> repeat_note', () => {
  const failed = readAi({ error: { message: 'timeout' } });
  assert.equal(failed.route, 'finish');
  assert.match(failed.problems[0], /AI step failed: timeout/);
  assert.equal(readAi(aiReply('Hi'), { repeat: true }).route, 'repeat_note');
});

const S = { name: 'Eve <!channel>', city: 'Columbus', message: '<https://phish|Open in HubSpot> & more', reason: 'r',
            phone: '', email: 'e@x.io', email_valid: true, source: 'website', submission_id: 's', problems: [],
            repeat: false, duplicate: false, crm_url: 'https://app/hs/1', replied: 'yes' };

test('slack: lead text is escaped; one message carries every alert kind', () => {
  const [msg] = run('slack_alerts', { nodes: { Finish: { ...S, tier: 'hot', status: 'failed', problems: ['x'] } } });
  assert.deepEqual(msg.kinds, ['hot', 'lead_failed']);
  assert.ok(!msg.text.includes('<!channel>'));
  assert.ok(!msg.text.includes('<https://phish'));
  assert.ok(msg.text.includes('<https://app/hs/1|Open in HubSpot>'));
  assert.deepEqual(run('slack_alerts', { nodes: { Finish: { ...S, tier: 'warm', status: 'ok' } } }), []);
  assert.deepEqual(run('slack_alerts', { nodes: { Finish: { ...S, tier: 'hot', status: 'repeat', repeat: true } } }), []);
});

test('finish: CRM failure still replied -> failed; duplicate path -> duplicate', () => {
  const base = { ...S, route: 'crm', tier: 'warm', ai: { reply_text: 'Hi' } };
  const f = run('finish', { nodes: { 'CRM result': { ...base, crm_id: '', crm_url: '', crm_problems: ['HubSpot contact failed: 401'] },
                                     'Read AI result': base, 'Send reply': { id: 'm1' } } })[0];
  assert.equal(f.status, 'failed');
  assert.equal(f.replied, 'yes');
  const d = run('finish', { nodes: { 'CRM result': NOT_RUN, 'Read AI result': NOT_RUN, 'Send reply': NOT_RUN,
                                     'Check repeat': { ...S, duplicate: true } } })[0];
  assert.equal(d.status, 'duplicate');
  assert.equal(d.replied, 'no');
});

test('crm_result: empty HubSpot result counts as a failure', () => {
  const r = run('crm_result', { nodes: { 'Read AI result': { route: 'crm', problems: [] },
    'HubSpot: upsert contact': { results: [] }, 'HubSpot: add note': NOT_RUN, 'HubSpot: create deal': NOT_RUN,
    'HubSpot: note on existing contact': NOT_RUN } })[0];
  assert.equal(r.crm_id, '');
  assert.deepEqual(r.crm_problems, ['HubSpot returned no contact id']);
});

console.log(`\n${passed} tests passed`);
