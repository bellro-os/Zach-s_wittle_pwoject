// NOTE: This copy is a plain-English draft for attorney review — not final legal language.
import type { Metadata } from "next";
import { Nav } from "@/components/compbird/nav";
import { Footer } from "@/components/compbird/footer";

export const metadata: Metadata = {
  title: "Terms of Service", // layout template appends "· compbird"
  description: "The terms that govern your use of compbird.",
};

const CONTACT_EMAIL =
  process.env.NEXT_PUBLIC_COMPBIRD_CONTACT_EMAIL?.trim() || "hello@ratifyly.com";

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mt-10">
      <h2 className="cb-eyebrow text-muted-foreground">{title}</h2>
      <div className="mt-3 space-y-3 text-sm leading-relaxed text-foreground/75">{children}</div>
    </section>
  );
}

export default function TermsPage() {
  return (
    <div className="cb-shell-paper min-h-screen bg-background">
      <Nav />
      <main className="mx-auto w-full max-w-2xl px-5 pb-24 pt-14 sm:px-6 sm:pt-20">
        <h1 className="font-display text-3xl font-bold tracking-tight text-foreground sm:text-4xl">
          Terms of Service
        </h1>
        <p className="mt-3 text-sm text-muted-foreground">Last updated: July 2, 2026</p>

        <Section title="1 · What compbird is">
          <p>
            compbird is a software tool that assembles comparable-sales analyses and
            market reports for residential real estate from public records and listing
            data. By creating an account or using the service you agree to these terms.
            If you use compbird on behalf of a brokerage or team, you confirm you have
            authority to bind that organization.
          </p>
        </Section>

        <Section title="2 · Not an appraisal">
          <p>
            Every estimate, comparable selection, adjustment, and market figure compbird
            produces is a model-driven opinion of value — not an appraisal, and not a
            substitute for one. compbird is not a licensed appraiser, and its output must
            not be represented as an appraisal or used where law or a lender requires
            one. You are responsible for reviewing reports before relying on them or
            sharing them with clients.
          </p>
        </Section>

        <Section title="3 · No warranty on estimates or data">
          <p>
            The service is provided &ldquo;as is.&rdquo; Underlying data comes from county
            assessors, recorded deeds, and MLS feeds, which contain errors, gaps, and lag.
            We do not warrant that any estimate, record, or report is accurate, complete,
            or current, and we are not liable for decisions made in reliance on them. To
            the maximum extent permitted by law, our total liability for any claim is
            limited to the amount you paid us in the twelve months before the claim.
          </p>
        </Section>

        <Section title="4 · Your account">
          <p>
            Keep your credentials confidential; you are responsible for activity under
            your account. We may suspend or terminate accounts that violate these terms.
            You may stop using the service at any time.
          </p>
        </Section>

        <Section title="5 · Subscriptions and billing">
          <p>
            The free plan includes a limited number of watermarked report downloads each
            month. Pro is a monthly subscription billed through Stripe. You can cancel
            anytime via the billing portal in the studio&rsquo;s account menu; access
            continues through the end of the paid period, and we do not offer partial-month
            refunds. Prices may change with at least 30 days&rsquo; notice before your next
            renewal.
          </p>
        </Section>

        <Section title="6 · Acceptable use">
          <p>
            Do not scrape, bulk-export, resell, or redistribute the underlying data or
            the service itself; do not probe, overload, or interfere with the service or
            attempt to access other users&rsquo; accounts or data; do not use reports to
            mislead, or in violation of MLS rules, fair-housing laws, or any other law.
            Reports you generate are for your professional use with your clients.
          </p>
        </Section>

        <Section title="7 · Your content and our software">
          <p>
            You keep ownership of the property details and branding you supply and the
            reports you generate. We keep ownership of the compbird software, models, and
            design. You grant us the limited license needed to store your inputs and
            render your reports.
          </p>
        </Section>

        <Section title="8 · Changes and contact">
          <p>
            We may update these terms; material changes will be posted here with a new
            &ldquo;last updated&rdquo; date, and continued use means acceptance. Questions —{" "}
            <a href={`mailto:${CONTACT_EMAIL}`} className="underline underline-offset-2 hover:text-foreground">
              {CONTACT_EMAIL}
            </a>
            .
          </p>
        </Section>
      </main>
      <Footer />
    </div>
  );
}
