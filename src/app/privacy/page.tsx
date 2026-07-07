// NOTE: This copy is a plain-English draft for attorney review — not final legal language.
import type { Metadata } from "next";
import { Nav } from "@/components/compbird/nav";
import { Footer } from "@/components/compbird/footer";

export const metadata: Metadata = {
  title: "Privacy Policy", // layout template appends "· compbird"
  description: "What compbird collects, why, and how to reach us about it.",
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

export default function PrivacyPage() {
  return (
    <div className="cb-shell-paper min-h-screen bg-background">
      <Nav />
      <main className="mx-auto w-full max-w-2xl px-5 pb-24 pt-14 sm:px-6 sm:pt-20">
        <h1 className="font-display text-3xl font-bold tracking-tight text-foreground sm:text-4xl">
          Privacy Policy
        </h1>
        <p className="mt-3 text-sm text-muted-foreground">Last updated: July 6, 2026</p>

        <Section title="1 · What we collect">
          <p>
            Your account: email address, an optional display name, and a hashed password
            — we never store passwords in plain text. Your work: the subject-property
            details you enter, the comparables and settings you choose, and the reports
            you generate, so they are there when you come back. Standard operational
            logs (IP address, browser type, timestamps) for security and debugging.
          </p>
        </Section>

        <Section title="2 · Property data is public-records data">
          <p>
            The property information inside compbird — parcels, assessments, recorded
            sales, listing histories — comes from county assessors, recorded deeds, and
            MLS feeds. It describes properties, not our users, and it exists in the
            public record independently of compbird.
          </p>
        </Section>

        <Section title="3 · How we use it">
          <p>
            To run the service: authenticate you, generate and store your reports,
            meter free-plan downloads, and bill subscriptions. To communicate: account
            and billing email, and occasional product updates you can opt out of. We do
            not sell your personal information, and we do not use your account data to
            train third-party models.
          </p>
        </Section>

        <Section title="4 · Payments">
          <p>
            Subscriptions are processed by Stripe. Your card number goes directly to
            Stripe and never touches our servers; we store only the subscription status
            and Stripe&rsquo;s customer reference. Stripe&rsquo;s own privacy policy
            governs its handling of your payment details.
          </p>
        </Section>

        <Section title="5 · Cookies and advertising">
          <p>
            We use a session cookie to keep you signed in — it is essential and always
            on. With your consent (the cookie banner), we also use the Meta Pixel and
            Google advertising tags to measure our ads and reach people who visited
            compbird. These load only after you choose &ldquo;Accept,&rdquo; and you can
            decline them entirely with &ldquo;Essential only.&rdquo; To change your
            choice later, clear this site&rsquo;s cookies and the banner will reappear.
          </p>
        </Section>

        <Section title="6 · Sharing">
          <p>
            Personal data is shared only with the service providers that run compbird —
            payment processing (Stripe) and hosting infrastructure — under agreements
            that limit their use of it, or when the law requires disclosure. If you
            accept advertising cookies, Meta and Google receive the ad-measurement
            events described in section 5.
          </p>
        </Section>

        <Section title="7 · Retention and deletion">
          <p>
            Account data and reports are kept while your account is active. Email us to
            delete your account; we remove personal data within 30 days, except records
            we must keep for tax or legal reasons.
          </p>
        </Section>

        <Section title="8 · Changes and contact">
          <p>
            Material changes to this policy will be posted here with a new &ldquo;last
            updated&rdquo; date. Questions or deletion requests —{" "}
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
