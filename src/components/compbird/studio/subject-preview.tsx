"use client";

import { Pill } from "@/components/compbird/ui";
import { bedsBaths, sqft, acres, titleCase } from "@/lib/compbird/format";
import type { PropertyMatch } from "@/lib/compbird/types";
import { Bar, EstimateWorkingState, EvidenceSkeleton } from "./report-skeleton";

/**
 * Progressive first paint — "facts fast, the number upgrades in place."
 *
 * A cold lookup takes 8–15s server-side, but the search suggestion the user
 * clicked already carries a PropertyMatch (address, city, county, sqft, beds,
 * status), so those KNOWN facts paint immediately in the Zone-1 idiom while
 * the engine works. The estimate slot renders an explicit working state
 * (report-skeleton.tsx's EstimateWorkingState) — ONE NUMBER EVERYWHERE is
 * sacred: no provisional value ever shows, only "Running comp analysis…" until
 * the real ReportView replaces this in place.
 *
 * GEOMETRY CONTRACT: the header below mirrors subject-header.tsx element for
 * element (same wrapper paddings/grid as report-view.tsx's live ZONE 1, same
 * pill row / h2 / fact row / parcel row classes), so when the profile resolves
 * the address headline and fact line do not move — the surrounding shimmer
 * simply becomes real content. If SubjectHeader's classes change, change the
 * mirrored classes here too (another agent owns that file, so this cannot
 * import from it structurally — the duplication is the seam).
 *
 * STATE MACHINERY (pure, tested in subject-preview.test.ts): the studio holds
 * a PreviewState via `previewReducer`, stamped with the SAME subject epoch
 * createSubjectSession() hands every lookup:
 *   - "start"   — a new lookup began (post-beginSubjectChange): paint its
 *                 preview (or, identity-only, just the address for the
 *                 skeleton headline);
 *   - "settled" — THAT lookup finished (success, failure, or its aborted
 *                 fetch standing down): clear, epoch-guarded so a straggler
 *                 settling for a superseded lookup can never blank the newer
 *                 lookup's preview;
 *   - "reset"   — the shared subject-change reset / Escape cancel: clear
 *                 unconditionally, so no orphaned preview can survive a
 *                 subject change.
 */

/**
 * What every subject-changing selection hands the studio: identity for sure,
 * plus whatever record facts the surface knows. Search suggestions and preset
 * chips pass a full PropertyMatch; recents chips/palette rows pass identity +
 * stored facts (enriched once the subject resolves); deep links and retry pass
 * identity only (⇒ no preview, the enriched skeleton path).
 */
export type LookupSelection = Pick<PropertyMatch, "address" | "parcel_id"> &
  Partial<PropertyMatch>;

/** The facts a selection carried — everything the preview may paint early. */
export interface SubjectPreviewData {
  address: string;
  parcelId: string | null;
  city: string | null;
  county: string | null;
  subdivision: string | null;
  status: string | null;
  sqft: number | null;
  bedrooms: number | null;
  fullBaths: number | null;
  halfBaths: number | null;
  acres: number | null;
  yearBuilt: number | null;
}

/** A pending lookup shows the honesty line after this long (see the studio). */
export const SLOW_LOOKUP_MS = 6000;

const cleanStr = (v: string | null | undefined): string | null => {
  const t = (v ?? "").trim();
  return t ? t : null;
};
const cleanNum = (v: number | null | undefined): number | null =>
  typeof v === "number" && Number.isFinite(v) ? v : null;

/**
 * Pure: the preview payload for a selection, or null when the selection
 * carries no fact beyond identity (address/parcel) — the caller then keeps
 * the plain skeleton path. Facts are sanitized here once so the component
 * renders whatever is non-null without re-checking.
 */
export function buildSubjectPreview(
  selection: LookupSelection,
): SubjectPreviewData | null {
  const address = (selection.address ?? "").trim();
  if (!address) return null;
  const data: SubjectPreviewData = {
    address,
    parcelId: cleanStr(selection.parcel_id),
    city: cleanStr(selection.city),
    county: cleanStr(selection.county),
    subdivision: cleanStr(selection.subdivision),
    status: cleanStr(selection.status),
    sqft: cleanNum(selection.sqft),
    bedrooms: cleanNum(selection.bedrooms),
    fullBaths: cleanNum(selection.full_baths),
    halfBaths: cleanNum(selection.half_baths),
    acres: cleanNum(selection.acres),
    yearBuilt: cleanNum(selection.year_built),
  };
  // Identity alone isn't a preview — the skeleton already names the address.
  const enriched =
    data.city != null ||
    data.county != null ||
    data.subdivision != null ||
    data.status != null ||
    data.sqft != null ||
    data.bedrooms != null ||
    data.fullBaths != null ||
    data.acres != null ||
    data.yearBuilt != null;
  return enriched ? data : null;
}

/* ── Preview lifecycle state (useReducer in the studio; pure + tested) ─────── */

export interface PreviewState {
  /** The subject epoch (createSubjectSession) of the lookup being painted. */
  epoch: number;
  /** Facts to paint — null means the plain skeleton path for this lookup. */
  data: SubjectPreviewData | null;
  /** The looked-up address (skeleton headline), known even without a preview. */
  address: string | null;
}

export const INITIAL_PREVIEW_STATE: PreviewState = {
  epoch: 0,
  data: null,
  address: null,
};

export type PreviewAction =
  | {
      type: "start";
      epoch: number;
      data: SubjectPreviewData | null;
      address: string | null;
    }
  | { type: "settled"; epoch: number }
  | { type: "reset" };

export function previewReducer(
  state: PreviewState,
  action: PreviewAction,
): PreviewState {
  switch (action.type) {
    case "start":
      return { epoch: action.epoch, data: action.data, address: action.address };
    case "settled":
      // Epoch-guarded: only the lookup that OWNS the painted preview may clear
      // it. A superseded lookup's finally (or a straggler response) settles
      // with an old epoch and must not blank the newer lookup's paint.
      if (action.epoch !== state.epoch) return state;
      if (state.data == null && state.address == null) return state;
      return { epoch: state.epoch, data: null, address: null };
    case "reset":
      // The shared subject-change reset / Escape cancel — unconditional, so a
      // cancelled or superseded lookup can never leave an orphaned preview.
      if (state.data == null && state.address == null) return state;
      return { epoch: state.epoch, data: null, address: null };
  }
}

/* ── The preview component ─────────────────────────────────────────────────── */

/**
 * Mirror of subject-header.tsx's statusTone — kept in lockstep by hand (that
 * file belongs to the valuation-area owner, so no shared export exists yet).
 */
function statusTone(status: string | null): "ember" | "positive" | "neutral" {
  const s = (status ?? "").toLowerCase();
  if (s.includes("active") || s.includes("list")) return "ember";
  if (s.includes("pend") || s.includes("contract")) return "positive";
  return "neutral";
}

/** Same fact styling as subject-header.tsx's Fact. */
function Fact({ children }: { children: React.ReactNode }) {
  return <span className="font-data text-foreground">{children}</span>;
}

export function SubjectPreview({
  data,
  slow = false,
}: {
  data: SubjectPreviewData;
  /** The lookup has been pending ~6s — show the honest first-analysis line. */
  slow?: boolean;
}) {
  // Locale recipe copied from subject-header.tsx so the line usually resolves
  // to the SAME text once the profile lands (no reflow under the headline).
  const locale = [
    data.subdivision,
    titleCase(data.county) && `${titleCase(data.county)} County`,
  ]
    .filter(Boolean)
    .join(" · ");

  // Same fact-row assembly as subject-header.tsx — parts only when KNOWN.
  const factParts: React.ReactNode[] = [];
  const bb = bedsBaths(data.bedrooms, data.fullBaths, data.halfBaths);
  if (bb !== "—") factParts.push(<Fact key="bb">{bb}</Fact>);
  if (data.sqft != null) factParts.push(<Fact key="sf">{sqft(data.sqft)}</Fact>);
  if (data.acres != null) factParts.push(<Fact key="ac">{acres(data.acres)}</Fact>);
  if (data.yearBuilt != null)
    factParts.push(
      <Fact key="yr">
        Built <span className="tabular-nums">{data.yearBuilt}</span>
      </Fact>,
    );

  return (
    <div className="flex flex-col gap-10">
      <p role="status" aria-live="polite" className="sr-only">
        Analyzing {data.address} — known record facts shown while the estimate
        is computed.
      </p>

      {/* ══ ZONE 1 idiom — same wrapper + grid as report-view.tsx (live) ════ */}
      <section
        aria-label="Subject and estimated value"
        className="relative rounded-3xl border border-border bg-card/60 p-4 sm:p-6"
      >
        <div className="grid gap-x-10 gap-y-8 lg:grid-cols-[1.05fr_0.95fr]">
          {/* LEFT — subject identity: subject-header.tsx geometry, real facts */}
          <div className="flex flex-col gap-6">
            <header className="flex flex-col gap-4">
              <div className="flex flex-wrap items-center gap-2.5">
                {data.status ? (
                  <Pill tone={statusTone(data.status)}>{titleCase(data.status)}</Pill>
                ) : (
                  // Status unknown until the record resolves — never fabricate
                  // "Off-Market"; a pill-shaped shimmer holds the slot.
                  <Bar className="h-[22px] w-20 rounded-full" />
                )}
                {locale ? (
                  <span className="text-sm text-muted-foreground">{locale}</span>
                ) : data.city ? (
                  <span className="text-sm text-muted-foreground">
                    {titleCase(data.city)}
                  </span>
                ) : null}
              </div>

              <h2 className="font-display text-3xl font-bold leading-tight tracking-tight text-foreground text-balance sm:text-4xl">
                {data.address}
              </h2>

              <div className="flex flex-wrap items-center gap-x-5 gap-y-2 text-sm">
                {factParts.length > 0 ? (
                  factParts.map((part, i) => (
                    <span key={i} className="inline-flex items-center gap-5">
                      {i > 0 ? (
                        <span aria-hidden className="text-border">
                          /
                        </span>
                      ) : null}
                      {part}
                    </span>
                  ))
                ) : (
                  <Bar className="h-4 w-1/2" />
                )}
              </div>

              <div className="flex flex-wrap items-center gap-x-6 gap-y-1 pt-1 text-xs text-muted-foreground">
                {data.parcelId ? (
                  <span>
                    Parcel{" "}
                    <span className="font-data text-muted-foreground/90">
                      {data.parcelId}
                    </span>
                  </span>
                ) : (
                  <Bar className="h-4 w-32" />
                )}
              </div>
            </header>

            {/* pricing-strategy panel stand-in */}
            <div className="flex flex-col gap-3">
              <Bar className="h-4 w-40" />
              <Bar className="h-28 w-full" />
            </div>
          </div>

          {/* RIGHT — the estimate slot as an HONEST working state + map slot */}
          <div className="flex flex-col gap-6">
            <EstimateWorkingState slow={slow} />
            <Bar className="min-h-[18rem] w-full flex-1 rounded-2xl" />
          </div>
        </div>
      </section>

      {/* ══ ZONE 2 stand-in — comps/analytics shimmer below the known facts ═ */}
      <EvidenceSkeleton />
    </div>
  );
}

export default SubjectPreview;
