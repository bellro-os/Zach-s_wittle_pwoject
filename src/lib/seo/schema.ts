// Site-wide + reusable JSON-LD (schema.org) builders. Data-only so any server
// component can import it; rendered by src/components/seo/json-ld.tsx.
// Absolute URLs use the same origin as metadataBase (NEXT_PUBLIC_APP_URL), with
// the production canonical as the fallback so a missing env never ships a
// localhost entity graph to crawlers.

const SITE_URL = (process.env.NEXT_PUBLIC_APP_URL?.trim() || "https://www.compbird.com").replace(/\/+$/, "");
const CONTACT_EMAIL = process.env.NEXT_PUBLIC_COMPBIRD_CONTACT_EMAIL?.trim() || "support@compbird.com";

const organizationSchema = {
  "@context": "https://schema.org",
  "@type": "Organization",
  "@id": `${SITE_URL}/#organization`,
  name: "compbird",
  url: SITE_URL,
  description:
    "compbird builds appraisal-grade comparable sales and live neighborhood market reports for real estate agents in seconds.",
  contactPoint: {
    "@type": "ContactPoint",
    contactType: "customer support",
    email: CONTACT_EMAIL,
  },
};

const websiteSchema = {
  "@context": "https://schema.org",
  "@type": "WebSite",
  "@id": `${SITE_URL}/#website`,
  name: "compbird",
  url: SITE_URL,
  publisher: { "@id": `${SITE_URL}/#organization` },
};

const softwareAppSchema = {
  "@context": "https://schema.org",
  "@type": "SoftwareApplication",
  "@id": `${SITE_URL}/#software`,
  name: "compbird",
  applicationCategory: "BusinessApplication",
  operatingSystem: "Web",
  url: SITE_URL,
  description:
    "Instant CMA (comparative market analysis) software for real estate agents: appraisal-grade comparable sales, neighborhood market analytics, and branded PDF reports.",
  offers: [
    {
      "@type": "Offer",
      name: "Free",
      price: "0",
      priceCurrency: "USD",
      description: "Unlimited instant value estimates.",
    },
    {
      "@type": "Offer",
      name: "Pro",
      price: "20",
      priceCurrency: "USD",
      description:
        "Every comparable sale, neighborhood market analytics, and unlimited branded PDF reports.",
      priceSpecification: {
        "@type": "UnitPriceSpecification",
        price: "20",
        priceCurrency: "USD",
        // per-month recurring
        referenceQuantity: { "@type": "QuantitativeValue", value: "1", unitCode: "MON" },
      },
    },
  ],
};

/** Organization + WebSite + SoftwareApplication — rendered once, site-wide. */
export const siteSchema = [organizationSchema, websiteSchema, softwareAppSchema];

/** FAQPage from a {q,a}[] list — render on the page whose visible copy matches. */
export function faqSchema(items: { q: string; a: string }[]) {
  return {
    "@context": "https://schema.org",
    "@type": "FAQPage",
    mainEntity: items.map((i) => ({
      "@type": "Question",
      name: i.q,
      acceptedAnswer: { "@type": "Answer", text: i.a },
    })),
  };
}
