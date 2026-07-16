"use client";

import type {
  ProfileFacts,
  Valuation,
  MarketContext,
  PricingSurface,
  ActiveListingModel,
} from "@/lib/compbird/types";
import type { SubjectOverrides } from "@/lib/cma/overrides";
import { SubjectHeader } from "./subject-header";
import { SubjectFactsEditor } from "./subject-facts-editor";
import { PricingStrategy } from "./pricing-strategy";

/**
 * ZONE 1 — subject identity. The masthead of the dossier: the address + record
 * facts, the pricing-strategy panel, and — on a LIVE Pro report — the what-if
 * editor anchored RIGHT here, so the agent corrects a fact where they read it
 * (the "intuitive placement" the manual-input goal calls for). Not a bordered
 * PanelCard: the outer ZONE 1 wrapper already frames it, so this stacks its
 * pieces with negative space rather than a second box.
 *
 * The pricing-strategy panel replaced the old Street View tile — dead weight
 * without a Google Maps key. It reads the engine's confidence interval + the
 * neighborhood pace to model what each list price costs in time on market, and
 * degrades honestly when the pace data is thin or redacted (see
 * ./pricing-strategy.tsx).
 *
 * `canEdit` gates the editor exactly as the old report-view derivation did —
 * sample + locked reports pass it false and render read-only, so no editors
 * appear where the pipeline can't accept overrides.
 */
export function SubjectCard({
  facts,
  estimateMid,
  valuation,
  marketContext,
  pricing = null,
  activeModel = null,
  canEdit,
  overrides,
  onOverridesChange,
}: {
  facts: ProfileFacts;
  /** Valuation mid, so the assessed line can show the honest delta. */
  estimateMid: number | null;
  /** Full valuation interval — anchors the pricing-strategy bands. */
  valuation: Valuation | null;
  /** Neighborhood market context — drives the pace/DOM model (null when redacted). */
  marketContext: MarketContext | null;
  /** Engine pricing-model surface — the pricing panel's model path (optional wire). */
  pricing?: PricingSurface | null;
  /** Engine active-listing model read — the header's Pro reality-check line. */
  activeModel?: ActiveListingModel | null;
  /** Live Pro report — mount the what-if subject editor. */
  canEdit: boolean;
  /** Current what-if overrides (only read when canEdit). */
  overrides?: SubjectOverrides;
  /** Emit changed overrides (only present when canEdit). */
  onOverridesChange?: (next: SubjectOverrides) => void;
}) {
  return (
    <div className="flex flex-col gap-6">
      <SubjectHeader facts={facts} estimateMid={estimateMid} activeModel={activeModel} />

      {/* what-if subject edits live WITH the facts they correct — live Pro only */}
      {canEdit && onOverridesChange ? (
        <SubjectFactsEditor
          facts={facts}
          value={overrides ?? EMPTY_OVERRIDES}
          onChange={onOverridesChange}
        />
      ) : null}

      {/* pricing strategy — bands from the estimate interval + a modeled
          time-on-market read (replaces the old key-less street view tile) */}
      <PricingStrategy
        valuation={valuation}
        marketContext={marketContext}
        pricing={pricing}
        areaName={facts.subdivision ?? facts.city}
        areaCounty={facts.county}
      />
    </div>
  );
}

const EMPTY_OVERRIDES: SubjectOverrides = {};

export default SubjectCard;
