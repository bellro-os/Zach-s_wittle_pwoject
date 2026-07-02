import { Nav } from "@/components/compbird/nav";
import { Footer } from "@/components/compbird/footer";
import { Hero } from "@/components/compbird/sections/hero";
import { TrustStrip } from "@/components/compbird/sections/trust-strip";
import { Accuracy } from "@/components/compbird/sections/accuracy";
import { HowItWorks } from "@/components/compbird/sections/how-it-works";
import { MarketReports } from "@/components/compbird/sections/market-reports";
import { FeaturesBento } from "@/components/compbird/sections/features-bento";
import { Coverage } from "@/components/compbird/sections/coverage";
import { FinalCTA } from "@/components/compbird/sections/cta";

export default function CompbirdLanding() {
  return (
    <div className="cb-shell-paper min-h-screen bg-background">
      <Nav />
      <main>
        <Hero />
        <TrustStrip />
        <Accuracy />
        <HowItWorks />
        <MarketReports />
        <FeaturesBento />
        <Coverage />
        {/* The pre-launch waitlist band was removed 2026-07-02: the product is
            live with instant signup + a paid plan, so lead capture leaked
            visitors out of the real funnel. waitlist.tsx is kept for a future
            "notify me when we reach your market" use. */}
        <FinalCTA />
      </main>
      <Footer />
    </div>
  );
}
