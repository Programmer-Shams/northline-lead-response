import { LeadForm } from "@/components/lead-form";
import { SERVICE_AREA } from "@/lib/lead";

export default function Home() {
  return (
    <div className="flex min-h-dvh flex-col">
      <header className="border-b border-seam">
        <div className="mx-auto flex max-w-6xl items-baseline justify-between gap-4 px-4 py-4 sm:px-8">
          <p className="font-heading text-xl font-bold tracking-wide text-patina">Northline Roofing &amp; Exteriors</p>
          <p className="hidden text-sm text-muted-foreground sm:block">Columbus, Ohio</p>
        </div>
      </header>

      <div className="bg-hivis text-[#262b2a]">
        <p className="mx-auto max-w-6xl px-4 py-2.5 text-sm font-medium sm:px-8">
          Active leak? We tarp roofs 24/7 inside our service area. Say so in your message and we prioritise it.
        </p>
      </div>

      <main className="mx-auto grid w-full max-w-6xl flex-1 gap-10 px-4 py-10 sm:px-8 lg:grid-cols-[1fr_minmax(0,30rem)] lg:gap-16 lg:py-16">
        <section className="order-2 max-w-xl lg:order-1">
          <h1 className="font-heading text-5xl leading-[0.95] font-bold tracking-tight text-balance sm:text-6xl lg:text-7xl">
            Tell us what&rsquo;s going on with your roof.
          </h1>
          <p className="mt-6 max-w-prose text-lg leading-relaxed text-muted-foreground">
            Roof repairs, replacements, storm and hail damage, gutters, siding and skylights. Send the details and
            we&rsquo;ll reply by email with next steps. If you&rsquo;re in our area, the reply includes a link to book
            a free inspection.
          </p>

          <dl className="mt-10 grid gap-6 border-t border-seam pt-8 sm:grid-cols-2">
            <div>
              <dt className="font-heading text-lg font-semibold">Inspections are free</dt>
              <dd className="mt-1 text-muted-foreground">Final prices come after we&rsquo;ve seen the roof.</dd>
            </div>
            <div>
              <dt className="font-heading text-lg font-semibold">Office hours</dt>
              <dd className="mt-1 text-muted-foreground">Monday to Saturday, 7 am to 6 pm Eastern.</dd>
            </div>
            <div className="sm:col-span-2">
              <dt className="font-heading text-lg font-semibold">Where we work</dt>
              <dd className="mt-1 leading-relaxed text-muted-foreground">
                {SERVICE_AREA.slice(0, -1).join(", ")} and {SERVICE_AREA.at(-1)}.
              </dd>
            </div>
          </dl>
        </section>

        <div className="order-1 lg:order-2">
          <LeadForm />
        </div>
      </main>

      <footer className="border-t border-seam">
        <p className="mx-auto max-w-6xl px-4 py-5 text-sm text-muted-foreground sm:px-8">
          A portfolio project: automated lead reply for Northline Roofing &amp; Exteriors.
        </p>
      </footer>
    </div>
  );
}
