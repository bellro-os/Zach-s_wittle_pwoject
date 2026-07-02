import { memo } from "react";
import { Pill } from "@/components/compbird/ui";
import { bedsBaths, sqft, acres, titleCase } from "@/lib/compbird/format";
import type { ProfileFacts } from "@/lib/compbird/types";

/**
 * Subject identity block: the address as the headline, a row of dense facts, a
 * status pill, and the parcel id set in mono — the masthead of the dossier.
 */

function statusTone(status: string | null): "ember" | "positive" | "neutral" {
  const s = (status ?? "").toLowerCase();
  if (s.includes("active") || s.includes("list")) return "ember";
  if (s.includes("pend") || s.includes("contract")) return "positive";
  return "neutral";
}

function Fact({ children }: { children: React.ReactNode }) {
  return <span className="font-data text-foreground">{children}</span>;
}

function SubjectHeaderImpl({
  facts,
  estimateMid = null,
}: {
  facts: ProfileFacts;
  /** Valuation mid, so the assessed line can show the honest delta. */
  estimateMid?: number | null;
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
      <span key="pt" className="text-muted-foreground">
        {titleCase(facts.property_type)}
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
                listing intel (assessments often trail the market by years). */}
            {estimateMid != null && facts.assessed_value > 0
              ? (() => {
                  const d = Math.round(((estimateMid - facts.assessed_value!) / facts.assessed_value!) * 100);
                  return Math.abs(d) >= 2 ? (
                    <span className="font-data text-muted-foreground/90">
                      {" "}· estimate {d > 0 ? "+" : ""}{d}%
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
