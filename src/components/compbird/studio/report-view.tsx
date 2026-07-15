"use client";

import { useMemo, useRef } from "react";
import { toast } from "sonner";
import { Pill } from "@/components/compbird/ui";
import { LeafletMap, type GeoMapPoint } from "@/components/geo/leaflet-map";
import { AerialMap } from "@/components/compbird/graphics";
import { dateLong, usd } from "@/lib/compbird/format";
import { readFreshness } from "@/lib/compbird/freshness";
import type { ProfileResult, ProfileComp } from "@/lib/compbird/types";
import { SubjectCard } from "./subject-card";
import { DataFreshness } from "./data-freshness";
import {
  ValuationPanel,
  ADD_COMP_SECTION_ID,
  COMPS_SECTION_ID,
  computeMethodDeltas,
  largestMoverSentence,
  type MethodSnapshot,
} from "./valuation-panel";
import { CompsTable, compKey, retainExcludedComps, type CachedComp } from "./comps-table";
import { AddCompSearch } from "./add-comp-search";
import { PpsfBars } from "./ppsf-bars";
import { LiveAnalytics, hasAnalytics } from "./live-analytics";
import { MarketPanel } from "./market-panel";
import { LockedPanel } from "./locked-panel";
import { ReportActions } from "./report-actions";
import { SummaryEditor } from "./summary-editor";
import type { SubjectOverrides, ReportConfig } from "@/lib/cma/overrides";

/**
 * Composes a full dossier from a ProfileResult. Restructured into three reading
 * ZONES rather than a stack of identical bordered cards:
 *
 *   ZONE 1 — SUBJECT + VALUE. The editable subject block sits beside the
 *     valuation, which is the single FOCAL POINT (largest type on the page);
 *     the data-freshness stamp + record→adjusted disclosure + map live here too.
 *   ZONE 2 — EVIDENCE. Comps table, $/sqft bars, live analytics and the
 *     neighborhood market read as ONE connected panel divided by hairline rules,
 *     not four sibling cards at the same weight.
 *   ZONE 3 — OUTPUT. Talking points + the exec-summary override + report actions.
 *
 * A client component: it mounts the real Leaflet map, and on LIVE reports the
 * what-if subject editor + "add a comparable" search so the comp set is fully
 * user-controllable. The studio swaps this in once a profile resolves.
 */

/** Build map points from the subject facts + every comp that carries coords. */
function mapPoints(profile: ProfileResult): GeoMapPoint[] {
  const pts: GeoMapPoint[] = [];
  const f = profile.facts;
  if (f && f.lat != null && f.lng != null) {
    pts.push({ lat: f.lat, lng: f.lng, kind: "subject", label: f.address || "Subject" });
  }
  for (const c of profile.comps ?? []) {
    if (c.lat != null && c.lng != null) {
      pts.push({ lat: c.lat, lng: c.lng, kind: "comp", label: c.address, atypical: c.atypical });
    }
  }
  return pts;
}

function MapLegend() {
  return (
    <div className="flex items-center gap-4 rounded-full border border-border bg-card/85 px-3 py-1.5 text-[0.7rem] text-muted-foreground backdrop-blur">
      <span className="flex items-center gap-1.5">
        <span className="h-2.5 w-2.5 rounded-full bg-[var(--cb-ember)]" aria-hidden /> Subject
      </span>
      <span className="flex items-center gap-1.5">
        <span className="h-2 w-2 rounded-full bg-foreground/70" aria-hidden /> Comps
      </span>
      <span className="flex items-center gap-1.5">
        <span className="h-2 w-2 rounded-full border border-[var(--negative)] bg-[var(--negative)]/30" aria-hidden />{" "}
        Atypical
      </span>
    </div>
  );
}

/** ZONE section header — eyebrow + heading, used to open ZONE 2 / ZONE 3. */
function ZoneHeading({
  eyebrow,
  title,
  aside,
}: {
  eyebrow: string;
  title: string;
  aside?: React.ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-3">
      <div className="flex flex-col gap-1">
        <span className="cb-eyebrow text-muted-foreground">{eyebrow}</span>
        <h3 className="font-display text-xl font-semibold text-foreground">{title}</h3>
      </div>
      {aside}
    </div>
  );
}

/** Anchor id on the ZONE-3 report actions — the ZONE-1 "Download PDF" pill jumps here. */
const REPORT_ACTIONS_SECTION_ID = "cb-report-actions";

/**
 * Smooth-scroll to the report actions (the download button — or, for an
 * evidence-locked viewer, the upgrade CTA that stands in for it). A wayfinding
 * affordance only: the generate logic stays in ReportActions.
 */
function scrollToReportActions(): void {
  if (typeof document === "undefined") return;
  const el = document.getElementById(REPORT_ACTIONS_SECTION_ID);
  if (!el) return;
  const reduceMotion =
    typeof window !== "undefined" &&
    window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
  el.scrollIntoView({ behavior: reduceMotion ? "auto" : "smooth", block: "center" });
}

const OVERRIDE_DIFF_LABELS: Record<string, string> = {
  sqft: "Finished area",
  bedrooms: "Bedrooms",
  full_baths: "Full baths",
  half_baths: "Half baths",
  acres: "Acreage",
  year_built: "Year built",
  property_type: "Property type",
  appearance: "Condition",
};

function fmtDiffVal(v: unknown): string {
  if (v == null || v === "") return "record";
  if (typeof v === "number") return v.toLocaleString();
  return String(v);
}

/**
 * Non-suppressible record→adjusted disclosure — the on-screen twin of the engine's
 * _override_disclosure_html, so a screenshot of the studio carries the same honesty
 * as the downloaded PDF (the adjusted value never stands alone, unlabeled).
 */
function OverrideDisclosure({
  diff,
  value,
}: {
  diff: Record<string, { from: unknown; to: unknown }>;
  value?: { record: number | null; adjusted: number | null } | null;
}) {
  const entries = Object.entries(diff);
  if (!entries.length) return null;
  const showValue =
    value != null &&
    value.record != null &&
    value.adjusted != null &&
    value.record !== value.adjusted;
  return (
    <div className="rounded-xl border border-border bg-secondary/40 px-4 py-3 text-xs text-muted-foreground">
      <p className="font-medium text-foreground">Estimate based on agent-adjusted subject details</p>
      {showValue ? (
        <p className="mt-1 font-medium text-foreground">
          Record-basis estimate {usd(value!.record)} <span aria-hidden>→</span>{" "}
          <span className="text-[var(--cb-ember-text)]">agent-adjusted {usd(value!.adjusted)}</span>
        </p>
      ) : null}
      <ul className="mt-1.5 flex flex-col gap-0.5">
        {entries.map(([k, d]) => (
          <li key={k}>
            {OVERRIDE_DIFF_LABELS[k] ?? k}: <span>{fmtDiffVal(d.from)}</span>
            {" → "}
            <span className="font-medium text-[var(--cb-ember-text)]">{fmtDiffVal(d.to)}</span>
          </li>
        ))}
      </ul>
      <p className="mt-1.5">Estimate reflects agent-adjusted subject details, not the public record.</p>
    </div>
  );
}

export function ReportView({
  profile,
  isSample,
  excluded,
  forced,
  onToggleComp,
  onAddComp,
  onRemoveForced,
  overrides,
  reportConfig,
  onOverridesChange,
  onReportConfigChange,
  engineMid,
  onResetTuning,
  tuning = false,
}: {
  profile: ProfileResult;
  isSample: boolean;
  /** Comp keys dropped from the valuation (live tuning). */
  excluded?: Set<string>;
  /** Addresses the user pinned IN via search — force-included as comps. */
  forced?: Set<string>;
  /** Toggle a comp in/out — absent on sample reports (read-only table). */
  onToggleComp?: (key: string, exclude: boolean) => void;
  /** Pin a searched address IN as a comp — absent on sample reports. */
  onAddComp?: (address: string) => void;
  /** Drop a previously-pinned address back out of the set. */
  onRemoveForced?: (address: string) => void;
  /** The FIRST unmodified engine mid for this subject — the delta ticker's baseline. */
  engineMid?: number | null;
  /** Clear every pin/exclusion and recompute — absent on sample/locked reports. */
  onResetTuning?: () => void;
  /** Agent what-if subject overrides (all 8 fields) — live reports only. */
  overrides?: SubjectOverrides;
  /** Report composition / exec-summary override — live reports only. */
  reportConfig?: ReportConfig;
  /** Emit changed subject overrides — absent on sample reports. */
  onOverridesChange?: (next: SubjectOverrides) => void;
  /** Emit a changed report config — absent on sample reports. */
  onReportConfigChange?: (next: ReportConfig) => void;
  /** A live recompute is in flight; dims the tuned area + disables toggles. */
  tuning?: boolean;
}) {
  const { facts, valuation, marketContext, meta } = profile;
  // Referential stability matters below: every array/object derived from the
  // profile is memoized so the React.memo children (LeafletMap, LiveAnalytics,
  // PpsfBars, MarketPanel, CompsTable, ValuationPanel) actually skip when the
  // profile hasn't changed — e.g. when only the `tuning` flag flips. A bare
  // `?? []` here would mint a fresh array per render and defeat all of them.
  // (ReportView itself is deliberately NOT memo'd: the studio derives nearly
  // every prop from state that changes together with the profile, so a memo
  // wrapper would compare a dozen props and almost never hit.)
  const comps = useMemo(() => profile.comps ?? [], [profile.comps]);
  const saleHistory = useMemo(() => profile.saleHistory ?? [], [profile.saleHistory]);
  // Evidence-locked: the server redacted comps/market/methods for a non-Pro
  // viewer (src/lib/compbird/redact.ts). The SAMPLE dossier is never locked —
  // it is the demo, and its richness IS the pitch.
  const locked = Boolean(profile.locked) && !isSample;
  // Closest comp distance — caps the valuation confidence when comps aren't local.
  const nearestMi = useMemo(
    () =>
      comps.reduce<number | null>((min, c) => {
        const d = c.distance_mi;
        if (d == null || !Number.isFinite(d)) return min;
        return min == null || d < min ? d : min;
      }, null),
    [comps],
  );
  // Farthest comp distance — the measured high-confidence gate bounds the whole
  // comp set (confidence.ts), not just the closest sale.
  const farthestMi = useMemo(
    () =>
      comps.reduce<number | null>((max, c) => {
        const d = c.distance_mi;
        if (d == null || !Number.isFinite(d)) return max;
        return max == null || d > max ? d : max;
      }, null),
    [comps],
  );
  // Share of the comp pool that is public-records (supplemental) evidence —
  // a primitive, so the memo'd ValuationPanel only re-renders on real change.
  const supplementalShare = useMemo(
    () =>
      comps.length
        ? comps.filter((c) => c.source === "supplemental").length / comps.length
        : 0,
    [comps],
  );
  // Map pins keyed to the profile: LeafletMap is memo'd, and a stable points
  // array is what keeps the map subtree from re-rendering (and re-diffing its
  // marker signature) on every unrelated studio state change.
  const points = useMemo(() => mapPoints(profile), [profile]);
  // Built once per profile — rendered in the panel AND read by the Copy button.
  const summary = useMemo(() => dossierSummary(profile, nearestMi), [profile, nearestMi]);
  // Honest freshness stamp — newest comp close_date (falls back to meta.as_of),
  // memoized so the DataFreshness line is stable across tuning re-renders.
  const freshness = useMemo(() => readFreshness(profile), [profile]);

  const excludedCount = excluded?.size ?? 0;
  const forcedSet = forced ?? EMPTY_SET;

  // Excluded-row retention: a recompute response DROPS excluded comps (the
  // engine filters + backfills — they aren't down-weighted rows), so the table
  // would silently lose the row the user just excluded. Cache every comp seen
  // for THIS subject (stamped with its first-seen displayed index) and re-seat
  // excluded ones AT THAT INDEX, so they stay visible dimmed, in place, with
  // their Include toggle. The cache resets on a new subject (comp addresses
  // are only meaningful per lookup); ref mutation during render is the
  // standard cache pattern — no effects, no extra renders.
  const compCacheRef = useRef(new Map<string, CachedComp>());
  const cacheSubjectRef = useRef<string | null>(null);
  // Aria-live method-delta narration (the panel's row deltas are aria-hidden;
  // THIS is the accessible story): track the previous methods per subject and
  // name the largest mover when a recompute settles — same render-phase ref
  // pattern as the comp cache above.
  const methodSnapRef = useRef<MethodSnapshot[] | null>(null);
  const narratedValuationRef = useRef<ProfileResult["valuation"]>(null);
  const moverRef = useRef<string | null>(null);
  const subjectKey = facts ? `${facts.parcel_id ?? ""}|${facts.address ?? ""}` : "";
  if (cacheSubjectRef.current !== subjectKey) {
    cacheSubjectRef.current = subjectKey;
    compCacheRef.current = new Map();
    methodSnapRef.current = null;
    narratedValuationRef.current = null;
    moverRef.current = null;
  }
  if (narratedValuationRef.current !== (valuation ?? null)) {
    const snap: MethodSnapshot[] = (valuation?.methods ?? []).map((m) => ({
      name: m.name,
      value: m.value,
    }));
    // First sight of a subject (no prior snapshot) never narrates a delta.
    moverRef.current =
      methodSnapRef.current && narratedValuationRef.current
        ? largestMoverSentence(computeMethodDeltas(methodSnapRef.current, snap))
        : null;
    methodSnapRef.current = snap;
    narratedValuationRef.current = valuation ?? null;
  }
  const displayComps = useMemo(
    () => retainExcludedComps(comps, excluded, compCacheRef.current),
    [comps, excluded],
  );

  // Live UNLOCKED reports only: the user can pin/unpin comps and add new ones.
  // (The studio already withholds these callbacks on locked profiles — the
  // `!locked` here is defense-in-depth.)
  const canControl = !isSample && !locked && typeof onAddComp === "function";
  // Live unlocked reports only: the agent-control editors (what-if subject +
  // narrative). The studio route is account-walled, so every Pro viewer may edit.
  const canEdit =
    !isSample &&
    !locked &&
    typeof onOverridesChange === "function" &&
    typeof onReportConfigChange === "function";

  // Show pinned comps as removable chips — match each forced address back to a
  // resolved comp row when present so we can show its city alongside the address.
  const forcedComps: { address: string; comp: ProfileComp | null }[] = useMemo(
    () =>
      canControl
        ? Array.from(forcedSet).map((address) => ({
            address,
            comp: comps.find((c) => compKey(c) === address) ?? null,
          }))
        : [],
    [canControl, forcedSet, comps],
  );

  if (!facts) {
    return (
      <p className="rounded-2xl border border-border bg-card/60 p-8 text-sm text-muted-foreground">
        This property has no record we can profile yet.
      </p>
    );
  }

  const asOf = meta?.as_of ?? meta?.generated ?? null;

  return (
    <div className="flex flex-col gap-10">
      {/* ══ ZONE 1 — SUBJECT + VALUE ══════════════════════════════════════════
          The subject you can correct + the answer. One wrapper carries the
          SAMPLE treatment (tinted ring + corner banner) over the modeled
          figures. The value is the page's single focal point. */}
      <section
        aria-label="Subject and estimated value"
        className={
          isSample
            ? "relative rounded-3xl bg-card/40 p-4 ring-1 ring-inset ring-[var(--cb-ember)]/25 sm:p-6"
            : "relative rounded-3xl border border-border bg-card/60 p-4 sm:p-6"
        }
      >
        {isSample ? (
          <>
            <div
              aria-hidden
              className="pointer-events-none absolute inset-0 -z-10 rounded-3xl bg-[var(--cb-tint)]/40"
            />
            <div className="absolute -top-3 left-5 z-10">
              <span className="inline-flex items-center gap-1.5 rounded-full border border-[var(--cb-ember)]/30 bg-[var(--cb-tint)] px-3 py-1 text-xs font-semibold uppercase tracking-wide text-[var(--cb-ember-text)] shadow-[0_8px_30px_-18px_var(--cb-glow)] backdrop-blur">
                <span className="h-1.5 w-1.5 rounded-full bg-[var(--cb-ember)]" aria-hidden />
                Sample
              </span>
            </div>
          </>
        ) : null}

        {/* identity (+ editable what-if) beside the value focal point */}
        <div className="grid gap-x-10 gap-y-8 lg:grid-cols-[1.05fr_0.95fr]">
          {/* LEFT — subject identity + the what-if editor anchored to the facts */}
          <SubjectCard
            facts={facts}
            estimateMid={valuation?.mid ?? null}
            valuation={valuation ?? null}
            marketContext={marketContext ?? null}
            canEdit={canEdit}
            overrides={overrides}
            onOverridesChange={canEdit ? onOverridesChange : undefined}
          />

          {/* RIGHT — the HERO: the value, its freshness stamp, disclosure, map */}
          <div className="flex flex-col gap-6">
            {valuation ? (
              <div
                className={tuning ? "opacity-60 transition-opacity" : "transition-opacity"}
                aria-busy={tuning}
              >
                <ValuationPanel
                  valuation={valuation}
                  nearestMi={locked ? profile.compsSummary?.nearest_mi ?? null : nearestMi}
                  farthestMi={locked ? profile.compsSummary?.farthest_mi ?? null : farthestMi}
                  compCount={locked ? profile.compsSummary?.count ?? null : comps.length}
                  supplementalShare={supplementalShare}
                  locked={locked}
                  engineMid={engineMid}
                  tunedCount={(excluded?.size ?? 0) + (forced?.size ?? 0)}
                  onResetTuning={onResetTuning}
                  busy={tuning}
                  subjectKey={subjectKey}
                  canPinComp={canControl}
                  canReviewComps={!isSample && !locked}
                />
              </div>
            ) : null}

            {/* ZONE-3 wayfinding: the PDF is the deliverable but lives below
                the fold — this pill jumps to the download (or, locked, the
                upgrade CTA standing in for it). No generate logic here. */}
            {valuation ? (
              <div className="-mt-2">
                <button
                  type="button"
                  onClick={scrollToReportActions}
                  className="inline-flex items-center gap-1.5 rounded-full border border-border px-3 py-1 text-xs font-medium text-foreground transition-colors hover:border-[var(--cb-ember)]/40 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--cb-ember)]"
                >
                  Download PDF
                  <svg viewBox="0 0 16 16" className="h-3 w-3 text-[var(--cb-ember)]" fill="none" aria-hidden>
                    <path
                      d="M8 3v10m0 0 4-4m-4 4-4-4"
                      stroke="currentColor"
                      strokeWidth="1.7"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    />
                  </svg>
                </button>
              </div>
            ) : null}

            {/* honest provenance — sits right under the value it describes */}
            <DataFreshness freshness={freshness} sample={isSample} />

            {profile.overrideDiff ? (
              <OverrideDisclosure diff={profile.overrideDiff} value={profile.overrideValue} />
            ) : null}

            {/* Map of the subject + comps. Sample reports draw the pure-SVG
                aerial (fabricated comps must not sit on a real OSM basemap, and
                it skips the Leaflet runtime + tile fetches on first paint); live
                reports get the real OSM map. */}
            <div className="relative flex min-h-[18rem] flex-1 flex-col">
              {/* Locked: the comps array is redacted, so only the subject pin
                  renders — say so instead of showing a legend for pins that
                  aren't there. */}
              <div className="absolute right-4 top-4 z-[500]">
                {locked ? (
                  <Pill tone="ember" className="bg-card/85 backdrop-blur">
                    Comp locations — Pro
                  </Pill>
                ) : (
                  <MapLegend />
                )}
              </div>
              {isSample ? (
                // The illustrative SVG aerial has no semantics of its own —
                // give it an image role + honest name (fabricated pins must
                // not read as a real map to AT either).
                <div
                  role="img"
                  aria-label="Illustrative aerial map of the sample subject and comparable sales"
                  className="h-full min-h-[18rem]"
                >
                  <AerialMap points={points} height={360} className="h-full min-h-[18rem]" />
                </div>
              ) : (
                <LeafletMap points={points} height={360} className="h-full min-h-[18rem]" />
              )}
            </div>
          </div>
        </div>
      </section>

      {/* ══ ZONE 2 — EVIDENCE ═════════════════════════════════════════════════
          Comps, $/sqft spread, live analytics and the neighborhood market read
          as ONE connected panel divided by hairline rules — not four sibling
          cards. On a locked live report the server stripped every comp/market
          row, so LockedPanel stand-ins take the whole zone. */}
      {locked ? (
        <section aria-label="Evidence" className="flex flex-col gap-6">
          <LockedPanel title="Comparable sales" teaser={lockedCompsTeaser(profile)} />
          <LockedPanel
            title="Live analytics"
            teaser="Sale-price timeline, $/sqft by distance, and the method-convergence read for this exact lookup."
          />
          <LockedPanel
            title="Neighborhood market"
            teaser="The local market read — median $/sqft, price trend, days on market, inventory."
          />
        </section>
      ) : (
        <section
          aria-label="Evidence"
          className="flex flex-col gap-8 rounded-2xl border border-border bg-card/70 p-5 sm:p-7"
        >
          {/* comps — the evidence the value rests on. Anchored + focusable:
              the STANDARD-tier "Review the comp set" chip jumps here. */}
          <div
            id={COMPS_SECTION_ID}
            tabIndex={-1}
            className="flex scroll-mt-6 flex-col gap-5 outline-none"
          >
            <ZoneHeading
              eyebrow="Evidence"
              title={
                comps.length
                  ? `The ${comps.length} comp${comps.length === 1 ? "" : "s"} the value rests on`
                  : "Comparable sales"
              }
              aside={
                tuning ? (
                  <Pill tone="neutral" className="shrink-0">
                    <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-[var(--cb-ember)]" aria-hidden />
                    Recomputing…
                  </Pill>
                ) : asOf ? (
                  <span className="font-data text-xs text-muted-foreground">
                    as of {dateLong(asOf)}
                  </span>
                ) : null
              }
            />
            {onToggleComp ? (
              <span className="-mt-2 text-xs text-muted-foreground">
                {excludedCount > 0
                  ? `${excludedCount} excluded — value recomputed from the remaining set. `
                  : "Toggle any comp to exclude it, or add your own — the value recomputes live."}
              </span>
            ) : null}

            {/* add-a-comparable affordance — LIVE reports only. Anchored: the
                STANDARD-tier "Pin a closer comparable" chip jumps here and
                focuses the search. */}
            {canControl ? (
              <div
                id={ADD_COMP_SECTION_ID}
                className="flex scroll-mt-6 flex-col gap-3 rounded-xl border border-border/70 bg-secondary/30 p-3.5 sm:p-4"
              >
                <AddCompSearch onAdd={onAddComp!} busy={tuning} pinned={forcedSet} />
                {forcedComps.length ? (
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="cb-eyebrow mr-0.5 text-muted-foreground">Pinned</span>
                    {forcedComps.map(({ address, comp }) => (
                      <span
                        key={address}
                        className="inline-flex items-center gap-1.5 rounded-full border border-[var(--cb-ember)]/30 bg-[var(--cb-tint)] py-1 pl-3 pr-1.5 text-xs font-medium text-[var(--cb-ember-text)]"
                      >
                        <span className="max-w-[18rem] truncate" title={comp?.address ?? address}>
                          {(comp?.address ?? address).split(",")[0]}
                        </span>
                        <button
                          type="button"
                          onClick={() => onRemoveForced?.(address)}
                          disabled={tuning}
                          aria-label={`Remove ${address} from the comp set`}
                          className="relative inline-flex h-5 w-5 items-center justify-center rounded-full text-[var(--cb-ember-text)] transition-colors after:absolute after:-inset-2 after:content-[''] hover:bg-[var(--cb-ember)]/15 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-[var(--cb-ember)] disabled:cursor-not-allowed disabled:opacity-50"
                        >
                          <svg viewBox="0 0 16 16" className="h-3 w-3" fill="none" aria-hidden>
                            <path
                              d="M4 4l8 8M12 4l-8 8"
                              stroke="currentColor"
                              strokeWidth="1.7"
                              strokeLinecap="round"
                            />
                          </svg>
                        </button>
                      </span>
                    ))}
                  </div>
                ) : null}
              </div>
            ) : null}

            {/* Screen-reader narration for the recompute cycle: a comp toggle
                visually dims + re-numbers the panel, but without this a
                keyboard/AT user gets silence between click and settled value.
                A settled recompute also names the largest method mover
                ("Direct comparison moved up 2 percent.") — the accessible twin
                of the panel's aria-hidden row deltas. */}
            <p aria-live="polite" role="status" className="sr-only">
              {tuning
                ? "Recomputing the valuation…"
                : [
                    excludedCount > 0
                      ? `${excludedCount} comparable${excludedCount === 1 ? "" : "s"} excluded. Valuation updated.`
                      : moverRef.current
                        ? "Valuation updated."
                        : "",
                    moverRef.current ?? "",
                  ]
                    .filter(Boolean)
                    .join(" ")}
            </p>

            <CompsTable
              comps={displayComps}
              excluded={excluded}
              forced={forcedSet}
              onToggle={onToggleComp}
              busy={tuning}
            />
            <PpsfBars comps={comps} />
          </div>

          {/* live analytics — every mark derives from THIS lookup's comps +
              method values, recomputing as the user tunes the set. Heading and
              divider are gated on the SAME data floor LiveAnalytics renders on
              (comps = the tuned set, so the section disappears/reappears as
              users exclude comps); the component's own null-return stays as
              defense in depth. */}
          {hasAnalytics(comps, valuation ?? null) ? (
            <>
              {/* hairline divider — the evidence reads as one movement, not cards */}
              <div className="border-t border-border" aria-hidden />
              <div className="flex flex-col gap-5">
                <ZoneHeading
                  eyebrow="Live analytics"
                  title="This lookup, charted"
                  aside={tuning ? <span className="text-xs text-muted-foreground">recomputing…</span> : null}
                />
                <div
                  className={tuning ? "opacity-60 transition-opacity" : "transition-opacity"}
                  aria-busy={tuning}
                >
                  <LiveAnalytics comps={comps} valuation={valuation ?? null} />
                </div>
              </div>
            </>
          ) : null}

          {/* market context — redacted to null on a locked live report */}
          {marketContext ? (
            <>
              <div className="border-t border-border" aria-hidden />
              <MarketPanel market={marketContext} saleHistory={saleHistory} />
            </>
          ) : null}
        </section>
      )}

      {/* ══ ZONE 3 — OUTPUT ═══════════════════════════════════════════════════
          What the agent leaves with: paste-able talking points, the exec-summary
          override that rides the PDF, and the download actions. Lighter weight —
          no bordered box per item, just spaced blocks and a hairline. */}
      <section aria-label="Report output" className="flex flex-col gap-6">
        {/* paste-able executive summary — listing-consultation talking points.
            Gated: a payload with no facts builds an empty summary, and a
            Talking-points block over nothing (or a lone ".") helps no one. */}
        {summary ? (
          <div className="flex flex-col gap-2">
            <div className="flex items-start justify-between gap-3">
              <span className="cb-eyebrow text-muted-foreground">Talking points</span>
              <button
                type="button"
                aria-label="Copy the talking-points summary"
                onClick={() => {
                  void navigator.clipboard
                    .writeText(summary)
                    .then(() => toast.success("Summary copied"));
                }}
                className="rounded-full border border-border px-3 py-1 text-xs font-medium text-muted-foreground transition-colors hover:border-[var(--cb-ember)]/40 hover:text-foreground focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--cb-ember)]"
              >
                Copy
              </button>
            </div>
            <p className="text-sm leading-relaxed text-foreground">{summary}</p>
          </div>
        ) : null}

        {/* exec-summary override — LIVE reports only; rides the generated PDF */}
        {canEdit ? (
          <SummaryEditor value={reportConfig ?? EMPTY_CONFIG} onChange={onReportConfigChange!} />
        ) : null}

        <div className="border-t border-border" aria-hidden />

        <div id={REPORT_ACTIONS_SECTION_ID} className="scroll-mt-6">
          <ReportActions
            address={facts.address}
            parcelId={facts.parcel_id}
            isSample={isSample}
            excluded={excluded ? Array.from(excluded) : undefined}
            forced={forced ? Array.from(forced) : undefined}
            subjectOverrides={canEdit ? overrides : undefined}
            reportConfig={canEdit ? reportConfig : undefined}
            evidence={!locked}
          />
        </div>

        {isSample ? (
          <p className="flex items-center gap-2 text-xs text-muted-foreground">
            <Pill tone="neutral">Sample data</Pill>
            Representative sample figures modeled on the New River Valley — search a real address above for live records.
          </p>
        ) : null}
      </section>
    </div>
  );
}

const EMPTY_SET: Set<string> = new Set();
const EMPTY_CONFIG: ReportConfig = {};

/** One-line hook for the locked comps panel, built from the redacted teaser. */
function lockedCompsTeaser(profile: ProfileResult): string {
  const s = profile.compsSummary;
  if (!s || s.count <= 0) return "Every comparable sale behind this estimate.";
  const parts = [`${s.count} comparable sale${s.count === 1 ? "" : "s"} found`];
  if (s.nearest_mi != null) parts.push(`nearest ${s.nearest_mi.toFixed(1)} mi`);
  // Match clause only when the redaction-surviving aggregate exists (i.e. the
  // engine scored the set) — older engine responses keep the line unchanged.
  if (s.avg_similarity != null)
    return `${parts.join(" · ")} · average match ${s.avg_similarity} — unlock the comp set to see why.`;
  return parts.join(" · ");
}

/** One paste-able paragraph an agent can read aloud or drop into a text. */
function dossierSummary(profile: ProfileResult, nearestMi: number | null): string {
  const f = profile.facts;
  const v = profile.valuation;
  // Locked live reports carry no comp rows — the redacted compsSummary still
  // gives the honest count/farthest, so the talking points keep their evidence line.
  const n = (profile.comps ?? []).length || profile.compsSummary?.count || 0;
  const m = profile.marketContext;
  const parts: string[] = [];
  if (f?.address && v?.mid != null) parts.push(`${f.address} — estimated ${usd(v.mid)}`);
  if (v?.low != null && v?.high != null) parts.push(`range ${usd(v.low)} to ${usd(v.high)}`);
  if (n > 0) {
    // "within X mi" must bound ALL comps — use the farthest, not the nearest.
    const far =
      (profile.comps ?? []).reduce<number | null>((mx, c) => {
        const d = c.distance_mi;
        if (d == null || !Number.isFinite(d)) return mx;
        return mx == null || d > mx ? d : mx;
      }, null) ??
      profile.compsSummary?.farthest_mi ??
      null;
    parts.push(
      `${n} closed comparable${n === 1 ? "" : "s"}${
        // Round UP for whole miles — "within X mi" must still bound ALL comps.
        far != null ? ` within ${far < 1 ? far.toFixed(1) : String(Math.ceil(far))} mi` : ""
      }`,
    );
  }
  if (m?.months_of_inventory != null)
    parts.push(
      `${m.months_of_inventory < 3 ? "seller's" : m.months_of_inventory < 6 ? "balanced" : "buyer's"} market at ${m.months_of_inventory.toFixed(1)} months of inventory`,
    );
  // No facts → empty string (callers gate the Talking-points block on it),
  // never a bare ".".
  return parts.length ? parts.join(" · ") + "." : "";
}
