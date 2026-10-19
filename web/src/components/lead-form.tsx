"use client";

import { useEffect, useRef, useState } from "react";
import { CircleAlert, MailCheck } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { checkLead, LIMITS, SERVICE_AREA, SERVICES, type LeadInput, type LeadResult } from "@/lib/lead";

const EMPTY: LeadInput = { name: "", email: "", phone: "", city: "", service: "", message: "", company: "" };

type Sent = { email: string; sentAt: number };

// 44 px touch targets, white fields on the white card, 16 px text so iOS does not zoom on focus.
const FIELD = "h-11 bg-white px-3 text-base md:text-base";

export function LeadForm() {
  const [lead, setLead] = useState<LeadInput>(EMPTY);
  const [error, setError] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const [sent, setSent] = useState<Sent | null>(null);

  const set = (key: keyof LeadInput) => (value: string) => setLead((l) => ({ ...l, [key]: value }));

  async function submit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const problem = checkLead(lead);
    if (problem) return setError(problem);
    setError(null);
    setSending(true);
    const sentAt = Date.now();
    try {
      const res = await fetch("/api/lead", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...lead, service: lead.service || "Other" }),
      });
      const data = (await res.json()) as LeadResult;
      if (!data.ok) return setError(data.error);
      setSent({ email: lead.email, sentAt });
      setLead(EMPTY);
    } catch {
      setError("Your request did not go through. Check your connection and send it again.");
    } finally {
      setSending(false);
    }
  }

  if (sent) return <Received sent={sent} onAgain={() => setSent(null)} />;

  return (
    <form onSubmit={submit} noValidate className="gable rounded-b-xl bg-card px-6 pb-7 shadow-[0_1px_0_var(--seam),0_18px_40px_-24px_rgb(28_74_63/0.45)] sm:px-8">
      <h2 className="font-heading text-3xl font-bold">Request a free inspection</h2>
      <p className="mt-1 text-muted-foreground">We reply by email, so check the address before you send.</p>

      <div className="mt-6 grid gap-5 sm:grid-cols-2">
        <Field id="name" label="Name" className="sm:col-span-2">
          <Input id="name" className={FIELD} autoComplete="name" required maxLength={LIMITS.name} value={lead.name}
                 onChange={(e) => set("name")(e.target.value)} />
        </Field>
        <Field id="email" label="Email">
          <Input id="email" className={FIELD} type="email" autoComplete="email" required maxLength={LIMITS.email} value={lead.email}
                 onChange={(e) => set("email")(e.target.value)} />
        </Field>
        <Field id="phone" label="Phone" hint="optional">
          <Input id="phone" className={FIELD} type="tel" autoComplete="tel" maxLength={LIMITS.phone} value={lead.phone}
                 onChange={(e) => set("phone")(e.target.value)} />
        </Field>
        <Field id="city" label="City">
          <Input id="city" className={FIELD} list="service-area" autoComplete="address-level2" required maxLength={LIMITS.city}
                 value={lead.city} onChange={(e) => set("city")(e.target.value)} />
          <datalist id="service-area">
            {SERVICE_AREA.map((c) => <option key={c} value={c} />)}
          </datalist>
        </Field>
        <Field id="service" label="What do you need?">
          <Select value={lead.service} onValueChange={set("service")}>
            <SelectTrigger id="service" className={`${FIELD} w-full data-[size=default]:h-11`}>
              <SelectValue placeholder="Choose a service" />
            </SelectTrigger>
            <SelectContent>
              {SERVICES.map((s) => <SelectItem key={s} value={s}>{s}</SelectItem>)}
            </SelectContent>
          </Select>
        </Field>
        <Field id="message" label="What's happening?" className="sm:col-span-2">
          <Textarea id="message" className="min-h-28 bg-white px-3 py-2.5 text-base md:text-base" required rows={4} maxLength={LIMITS.message} value={lead.message}
                    placeholder="For example: water coming through the bedroom ceiling since last night's storm."
                    onChange={(e) => set("message")(e.target.value)} />
        </Field>
        {/* Honeypot: hidden from people and screen readers, filled by bots. */}
        <input type="text" name="company" tabIndex={-1} autoComplete="off" aria-hidden="true" className="hidden"
               value={lead.company} onChange={(e) => set("company")(e.target.value)} />
      </div>

      {error && (
        <p role="alert" className="mt-5 flex gap-2 text-sm font-medium text-destructive">
          <CircleAlert className="mt-0.5 size-4 shrink-0" aria-hidden /> {error}
        </p>
      )}

      <Button type="submit" disabled={sending}
              className="mt-6 h-12 w-full font-heading text-lg font-semibold tracking-wide hover:bg-patina">
        {sending ? "Sending your request…" : "Send request"}
      </Button>
    </form>
  );
}

function Field({ id, label, hint, className, children }: {
  id: string; label: string; hint?: string; className?: string; children: React.ReactNode;
}) {
  return (
    <div className={className}>
      <Label htmlFor={id} className="mb-2 flex items-baseline gap-1.5 text-sm font-semibold">
        {label}
        {hint && <span className="font-normal text-muted-foreground">{hint}</span>}
      </Label>
      {children}
    </div>
  );
}

/** Live stopwatch from the moment the request was sent, so a recording shows the reply time on screen. */
function Received({ sent, onAgain }: { sent: Sent; onAgain: () => void }) {
  const [now, setNow] = useState(sent.sentAt);
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    heading.current?.focus();
    const t = setInterval(() => setNow(Date.now()), 100);
    return () => clearInterval(t);
  }, []);
  const elapsed = Math.max(0, now - sent.sentAt) / 1000;
  const mm = Math.floor(elapsed / 60);
  const ss = (elapsed % 60).toFixed(1).padStart(4, "0");
  const at = new Date(sent.sentAt).toLocaleTimeString([], { hour: "numeric", minute: "2-digit", second: "2-digit" });

  return (
    <section className="gable rounded-b-xl bg-patina px-6 pb-8 text-white sm:px-8 animate-in fade-in duration-300">
      <MailCheck className="size-7 text-hivis" aria-hidden />
      <h2 ref={heading} tabIndex={-1} className="mt-3 font-heading text-3xl font-bold outline-none">Request received</h2>
      <p className="mt-2 leading-relaxed text-white/80">
        Sent at {at}. Your reply is on its way to <span className="font-semibold text-white break-all">{sent.email}</span>.
      </p>
      <p className="mt-8 text-sm text-white/70">Time since you sent it</p>
      <p className="tabular font-heading text-7xl leading-none font-bold sm:text-8xl" aria-hidden>
        {mm}:{ss}
      </p>
      <Button variant="secondary" onClick={onAgain} className="mt-8 h-11 px-4 font-semibold">
        Send another request
      </Button>
    </section>
  );
}
