"use client";

import { StreetView } from "@/components/geo/street-view";
import type { ProfileFacts } from "@/lib/compbird/types";
import type { SubjectOverrides } from "@/lib/cma/overrides";
import { SubjectHeader } from "./subject-header";
import { SubjectFactsEditor } from "./subject-facts-editor";

/**
 * ZONE 1 — subject identity. The masthead of the dossier: the address + record
 * facts, the street view, and — on a LIVE Pro report — the what-if editor
 * anchored RIGHT here, so the agent corrects a fact where they read it (the
 * "intuitive placement" the manual-input goal calls for). Not a bordered
 * PanelCard: the outer ZONE 1 wrapper already frames it, so this stacks its
 * pieces with negative space rather than a second box.
 *
 * `canEdit` gates the editor exactly as the old report-view derivation did —
 * sample + locked reports pass it false and render read-only, so no editors
 * appear where the pipeline can't accept overrides.
 */
export function SubjectCard({
  facts,
  estimateMid,
  canEdit,
  overrides,
  onOverridesChange,
}: {
  facts: ProfileFacts;
  /** Valuation mid, so the assessed line can show the honest delta. */
  estimateMid: number | null;
  /** Live Pro report — mount the what-if subject editor. */
  canEdit: boolean;
  /** Current what-if overrides (only read when canEdit). */
  overrides?: SubjectOverrides;
  /** Emit changed overrides (only present when canEdit). */
  onOverridesChange?: (next: SubjectOverrides) => void;
}) {
  return (
    <div className="flex flex-col gap-6">
      <SubjectHeader facts={facts} estimateMid={estimateMid} />

      {/* what-if subject edits live WITH the facts they correct — live Pro only */}
      {canEdit && onOverridesChange ? (
        <SubjectFactsEditor
          facts={facts}
          value={overrides ?? EMPTY_OVERRIDES}
          onChange={onOverridesChange}
        />
      ) : null}

      {/* street view — auto-loads from the proxy when coords are present */}
      <div className="flex flex-col gap-2">
        <span className="cb-eyebrow text-muted-foreground">Street view</span>
        <StreetView lat={facts.lat} lng={facts.lng} address={facts.address} />
      </div>
    </div>
  );
}

const EMPTY_OVERRIDES: SubjectOverrides = {};

export default SubjectCard;
