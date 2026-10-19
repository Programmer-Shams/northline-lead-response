import { NextResponse } from "next/server";
import { checkLead, SERVICES, type LeadInput, type LeadResult } from "@/lib/lead";

// Forwards a form submission to the n8n lead webhook. The webhook secret stays on the server
// (web/.env.local, written by n8n/deploy.py) and never reaches the browser.
const WEBHOOK_URL = process.env.LEAD_WEBHOOK_URL;
const WEBHOOK_SECRET = process.env.N8N_WEBHOOK_SECRET;
const TIMEOUT_MS = 10_000;
const MAX_BODY_BYTES = 10_000;

// Each accepted request costs an AI call and sends an email, so cap them per sender IP and per address.
// In-memory: enough for one server process; a multi-instance deployment needs a shared store (and a captcha).
const LIMITS = { ip: { max: 5, windowMs: 10 * 60_000 }, email: { max: 3, windowMs: 60 * 60_000 } };
const hits = new Map<string, number[]>();

function overLimit(key: string, { max, windowMs }: { max: number; windowMs: number }): boolean {
  const now = Date.now();
  const recent = (hits.get(key) ?? []).filter((t) => now - t < windowMs);
  if (recent.length >= max) {
    hits.set(key, recent);
    return true;
  }
  hits.set(key, [...recent, now]);
  return false;
}

const text = (v: unknown) => (typeof v === "string" ? v.trim() : "");
const fail = (error: string, status: number) => NextResponse.json<LeadResult>({ ok: false, error }, { status });

export async function POST(req: Request): Promise<NextResponse<LeadResult>> {
  if (!WEBHOOK_URL || !WEBHOOK_SECRET) return fail("The form is not connected yet. Run n8n/deploy.py.", 500);

  const raw = await req.text();
  if (raw.length > MAX_BODY_BYTES) return fail("That request is too large. Shorten the message and send it again.", 413);
  let body: unknown;
  try {
    body = JSON.parse(raw);
  } catch {
    return fail("Send the form as JSON.", 400);
  }
  if (!body || typeof body !== "object" || Array.isArray(body)) return fail("Send the form as a JSON object.", 400);
  const b = body as Record<string, unknown>;

  const lead: LeadInput = {
    name: text(b.name),
    email: text(b.email),
    phone: text(b.phone),
    city: text(b.city),
    service: SERVICES.includes(text(b.service) as (typeof SERVICES)[number]) ? text(b.service) : "Other",
    message: text(b.message),
    company: text(b.company),
  };
  const submissionId = crypto.randomUUID();
  // Bots fill the hidden field; answer as if it worked and send nothing.
  if (lead.company) return NextResponse.json({ ok: true, submissionId });
  const problem = checkLead(lead);
  if (problem) return fail(problem, 400);

  const ip = req.headers.get("x-forwarded-for")?.split(",")[0].trim() || "local";
  if (overLimit(`ip:${ip}`, LIMITS.ip) || overLimit(`email:${lead.email.toLowerCase()}`, LIMITS.email)) {
    return fail("We already have several requests from you. We'll reply to those; please wait before sending more.", 429);
  }

  const payload = {
    source: "website",
    submission_id: submissionId,
    submitted_at: new Date().toISOString(),
    name: lead.name,
    email: lead.email,
    phone: lead.phone,
    city: lead.city,
    service: lead.service,
    message: lead.message,
  };
  try {
    const res = await fetch(WEBHOOK_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Northline-Key": WEBHOOK_SECRET },
      body: JSON.stringify(payload),
      signal: AbortSignal.timeout(TIMEOUT_MS),
    });
    if (!res.ok) throw new Error(`webhook answered ${res.status}`);
  } catch (err) {
    console.error("lead webhook failed:", err instanceof Error ? err.message : err);
    return fail("Your request did not go through. Check your connection and send it again.", 502);
  }
  return NextResponse.json({ ok: true, submissionId });
}
