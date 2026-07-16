import { memo } from "react";
import { Pill } from "@/components/compbird/ui";
import { usd, num, bedsBaths, sqft, acres, titleCase, propertyTypeLabel } from "@/lib/compbird/format";
import type { ProfileFacts, ActiveListingModel } from "@/lib/compbird/types";

/**
 * Subject identity block: the address as the headline, a row of dense facts, a
 * status pill, and the parcel id set in mono — the masthead of the dossier.
 *
 * ACTIVE-LISTING REALITY CHECK: when the subject is itself an active listing
 * with a list price, an instrument callout under the facts row reads the gap
 * between the ask and the estimate ("Listed $475,000 — 7.2% above the
 * estimate") — free-tier included, since facts + the estimate survive
 * redaction. When the engine's active-listing model rode the wire
 * (CMA_PRICING_SURFACE=1; redact.ts strips it for non-Pro viewers), a second
 * line adds the model's read at that price ("43 days on market; model
 * expected ~19 at this price · 68% cut probability"). Neutral framing on
 * purpose — a reality check, never an alarm.
 */

function statusTone(status: string | null): "ember" | "positive" | "neutral" {
  const s = (status ?? "").toLowerCase();
  if (s.includes("active") || s.includes("list")) return "ember";
  if (s.includes("pend") || s.includes("contract")) return "positive";
  return "neutral";
}

/** The subject reads as an on-market listing (same predicate as its status pill). */
function isActiveListing(status: string | null): boolean {
  const s = (status ?? "").toLowerCase();
  return s.includes("active") || s.includes("list");
}

function Fact({ children }: { children: React.ReactNode }) {
  return <span className="font-data text-foreground">{children}</span>;
}

function SubjectHeaderImpl({
  facts,
  estimateMid = null,
  activeModel = null,
}: {
  facts: ProfileFacts;
  /** Valuation mid, so the assessed line can show the honest delta. */
  estimateMid?: number | null;
  /**
   * Engine active-listing model read (subject.active_model) — Pro wire only
   * (redacted for FREE); absent ⇒ the callout keeps just the delta line.
   */
  activeModel?: ActiveListingModel | null;
}) {
  const factParts: React.ReactNode[] = [];
  const bb = bedsBaths(facts.beds, facts.full_baths, facts.half_baths);
  if (bb !== "—") factParts.push(<Fact key="bb">{bb}</Fact>);
  if (facts.sqft != null) factParts.push(<Fact key="sf">{sqft(facts.sqft)}</Fact>);
  if (facts.acres != null) factParts.push(<Fact key="ac">{acres(facts.acres)}</Fact>);
  if (facts.year_built != null)
    factParts.push(
      <Fact key="yr">
        Built <span className="tabular-nums">{facts.year_built}</span>
      </Fact>,
    );
  if (facts.property_type)
    factParts.push(
      // Render-boundary humanization: the feed's class enum ("RE_1") must
      // never leak verbatim (or half-cased, "Re_1") into the dossier.
      <span key="pt" className="text-muted-foreground">
        {propertyTypeLabel(facts.property_type)}
      </span>,
    );

  const locale = [facts.subdivision, titleCase(facts.county) && `${titleCase(facts.county)} County`]
    .filter(Boolean)
    .join(" · ");

  return (
    <header className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-2.5">
        <Pill tone={statusTone(facts.status)}>{titleCase(facts.status) || "Off-Market"}</Pill>
        {locale ? (
          <span className="text-sm text-muted-foreground">{locale}</span>
        ) : null}
      </div>

      <h2 className="font-display text-3xl font-bold leading-tight tracking-tight text-foreground text-balance sm:text-4xl">
        {facts.address}
      </h2>

      <div className="flex flex-wrap items-center gap-x-5 gap-y-2 text-sm">
        {factParts.map((part, i) => (
          <span key={i} className="inline-flex items-center gap-5">
            {i > 0 ? (
              <span aria-hidden className="text-border">
                /
              </span>
            ) : null}
            {part}
          </span>
        ))}
      </div>

      {/* active-listing reality check — ask vs estimate, plus the Pro model read */}
      {(() => {
        if (!isActiveListing(facts.status)) return null;
        const list = facts.list_price;
        if (list == null || !Number.isFinite(list) || list <= 0) return null;
        if (estimateMid == null || !Number.isFinite(estimateMid) || estimateMid <= 0) return null;
        const deltaPct = ((list - estimateMid) / estimateMid) * 100;
        const deltaClause =
          Math.abs(deltaPct) < 0.05
            ? "at the estimate"
            : `${Math.abs(deltaPct).toFixed(1)}% ${deltaPct > 0 ? "above" : "below"} the estimate`;
        const model =
          activeModel != null && Number.isFinite(activeModel.expected_dom_q50)
            ? activeModel
            : null;
        const feedDom =
          facts.feed_dom != null && Number.isFinite(facts.feed_dom) && facts.feed_dom >= 0
            ? facts.feed_dom
            : null;
        return (
          <div className="flex flex-col gap-1 rounded-lg border border-border bg-secondary/40 px-3 py-2 text-xs">
            <span>
              <span className="font-medium text-foreground">Listed {usd(list)}</span>{" "}
              <span className="font-data text-muted-foreground">— {deltaClause}</span>
            </span>
            {model ? (
              <span className="font-data text-muted-foreground">
                {feedDom != null ? `${num(feedDom)} days on market; ` : ""}
                model expected ~{num(model.expected_dom_q50)} at this price
                {typeof model.cut_probability === "number" &&
                model.cut_probability >= 0 &&
                model.cut_probability <= 1
                  ? ` · ${Math.round(model.cut_probability * 100)}% cut probability`
                  : ""}
              </span>
            ) : null}
          </div>
        );
      })()}

      <div className="flex flex-wrap items-center gap-x-6 gap-y-1 pt-1 text-xs text-muted-foreground">
        <span>
          Parcel{" "}
          <span className="font-data text-muted-foreground/90">{facts.parcel_id}</span>
        </span>
        {facts.assessed_value != null ? (
          <span>
            Assessed{" "}
            <span className="font-data text-muted-foreground/90">
              {facts.assessed_value.toLocaleString("en-US", {
                style: "currency",
                currency: "USD",
                maximumFractionDigits: 0,
              })}
            </span>
            {/* Honest gap between the tax roll and the market read — genuine
                listing intel, framed neutrally: assessed values are set for
                taxation and systematically trail market, so a bare "+58%"
                would read as an over-valuation alarm when it's the norm. */}
            {estimateMid != null && facts.assessed_value > 0
              ? (() => {
                  const d = Math.round(((estimateMid - facts.assessed_value!) / facts.assessed_value!) * 100);
                  return Math.abs(d) >= 2 ? (
                    <span
                      title="Tax-assessed values are set for taxation and typically sit below current market value — a gap here is normal, not an over-valuation flag."
                    >
                      <span className="font-data text-muted-foreground/90">
                        {" "}· estimate {Math.abs(d)}% {d > 0 ? "above" : "below"}
                      </span>
                      {d > 0 ? (
                        <span className="text-muted-foreground/70"> (typical — tax values trail market)</span>
                      ) : null}
                    </span>
                  ) : null;
                })()
              : null}
          </span>
        ) : null}
      </div>
    </header>
  );
}

/** Memoized: subject facts keep their identity across comp-tuning re-renders. */
export const SubjectHeader = memo(SubjectHeaderImpl);
