// Form fields shared by the page and the /api/lead route.

// Same service names as the dropdown values in data/test-leads.csv.
export const SERVICES = [
  "Roof repair",
  "Roof replacement",
  "Storm damage",
  "Flat roof",
  "Inspection",
  "Gutters",
  "Siding",
  "Skylight",
  "Other",
] as const;

// Service area from data/business.md (suggestions only; the AI decides what is in area).
export const SERVICE_AREA = [
  "Columbus",
  "Dublin",
  "Westerville",
  "Hilliard",
  "Grove City",
  "Gahanna",
  "Worthington",
  "Upper Arlington",
  "Reynoldsburg",
  "Pickerington",
] as const;

export type LeadInput = {
  name: string;
  email: string;
  phone: string;
  city: string;
  service: string;
  message: string;
  company?: string; // honeypot: real people never see or fill it
};

export type LeadResult = { ok: true; submissionId: string } | { ok: false; error: string };

export const LIMITS = { name: 120, email: 200, phone: 40, city: 80, message: 2000 } as const;

/** Returns a message for the first problem, or null when the lead can be sent. */
export function checkLead(lead: LeadInput): string | null {
  if (!lead.name.trim()) return "Add your name so we know who to reply to.";
  if (!lead.email.trim()) return "Add your email address. The reply goes there.";
  if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(lead.email.trim())) return "Check your email address. It should look like name@example.com.";
  if (!lead.city.trim()) return "Add the city where the property is.";
  if (!lead.message.trim()) return "Tell us briefly what is going on with the property.";
  for (const [key, max] of Object.entries(LIMITS)) {
    if ((lead[key as keyof typeof LIMITS] ?? "").length > max) return `Keep the ${key} under ${max} characters.`;
  }
  return null;
}
