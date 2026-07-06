"use client";

import { toast } from "sonner";
import { Pill } from "@/components/compbird/ui";
import { LeafletMap, type GeoMapPoint } from "@/components/geo/leaflet-map";
import { AerialMap } from "@/components/compbird/graphics";
import { StreetView } from "@/components/geo/street-view";
import { dateLong, usd } from "@/lib/compbird/format";
import type { ProfileResult, ProfileComp } from "@/lib/compbird/types";
import { SubjectHeader } from "./subject-header";
import { ValuationPanel } from "./valuation-panel";
import { CompsTable, compKey } from "./comps-table";
import { AddCompSearch } from "./add-comp-search";
import { PpsfBars } from "./ppsf-bars";
import { LiveAnalytics } from "./live-analytics";
import { MarketPanel } from "./market-panel";
import { LockedPanel } from "./locked-panel";
import { ReportActions } from "./report-actions";
import { SubjectFactsEditor } from "./subject-facts-editor";
import { SummaryEditor } from "./summary-editor";
import type { SubjectOverrides, ReportConfig } from "@/lib/cma/overrides";

/**
 * Composes a full dossier from a ProfileResult. A client component now — it
 * mounts the real Leaflet map + Street View tile and, on LIVE reports, the
 * "add a comparable" search so the comp set is fully user-controllable. The
 * studio swaps this in once a profile resolves.
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

function PanelCard({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={`rounded-2xl border border-border bg-card/70 p-5 sm:p-7 ${className ?? ""}`}>
      {children}
    </div>
  );
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
  /** Agent what-if subject overrides (sqft/condition) — live reports only. */
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
  const comps = profile.comps ?? [];
  const saleHistory = profile.saleHistory ?? [];
  // Evidence-locked: the server redacted comps/market/methods for a non-Pro
  // viewer (src/lib/compbird/redact.ts). The SAMPLE dossier is never locked —
  // it is the demo, and its richness IS the pitch.
  const locked = Boolean(profile.locked) && !isSample;
  // Closest comp distance — caps the valuation confidence when comps aren't local.
  const nearestMi = comps.reduce<number | null>((min, c) => {
    const d = c.distance_mi;
    if (d == null || !Number.isFinite(d)) return min;
    return min == null || d < min ? d : min;
  }, null);
  if (!facts) {
    return (
      <p className="rounded-2xl border border-border bg-card/60 p-8 text-sm text-muted-foreground">
        This property has no record we can profile yet.
      </p>
    );
  }

  const points = mapPoints(profile);
  const asOf = meta?.as_of ?? meta?.generated ?? null;

  const excludedCount = excluded?.size ?? 0;
  const forcedSet = forced ?? EMPTY_SET;

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
  const forcedComps: { address: string; comp: ProfileComp | null }[] = canControl
    ? Array.from(forcedSet).map((address) => ({
        address,
        comp: comps.find((c) => compKey(c) === address) ?? null,
      }))
    : [];

  return (
    <div className="flex flex-col gap-6">
      {/*
        Valuation + comps live inside one wrapper so a fallback report gets an
        unmistakable inline SAMPLE treatment — a tinted ring + corner banner over
        the figures that are modeled, not measured.
      */}
      <div
        className={
          isSample
            ? "relative rounded-3xl ring-1 ring-inset ring-[var(--cb-ember)]/25"
            : "relative"
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

        <div className="flex flex-col gap-6 p-px sm:p-1">
          {/* identity + value, side by side on wide screens */}
          <div className="grid gap-6 lg:grid-cols-[1.05fr_0.95fr]">
            <PanelCard className="flex flex-col gap-7">
              <SubjectHeader facts={facts} estimateMid={valuation?.mid ?? null} />

              {/* street view — auto-loads from the proxy when coords are present */}
              <div className="flex flex-col gap-2">
                <span className="cb-eyebrow text-muted-foreground">Street view</span>
                <StreetView lat={facts.lat} lng={facts.lng} address={facts.address} />
              </div>

              {valuation ? (
                <div
                  className={
                    tuning ? "opacity-60 transition-opacity" : "transition-opacity"
                  }
                  aria-busy={tuning}
                >
                  <ValuationPanel
                    valuation={valuation}
                    nearestMi={locked ? profile.compsSummary?.nearest_mi ?? null : nearestMi}
                    supplementalShare={
                      comps.length
                        ? comps.filter((c) => c.source === "supplemental").length / comps.length
                        : 0
                    }
                    locked={locked}
                  />
                </div>
              ) : null}
              {profile.overrideDiff ? (
                <OverrideDisclosure diff={profile.overrideDiff} value={profile.overrideValue} />
              ) : null}
            </PanelCard>

            {/* Map of the subject + comps. Sample reports draw the pure-SVG
                aerial (fabricated comps must not sit on a real OSM basemap, and
                it skips the Leaflet runtime + tile fetches on first paint); live
                reports get the real OSM map. */}
            <div className="relative flex flex-col">
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
                <AerialMap points={points} height={420} className="h-full min-h-[20rem]" />
              ) : (
                <LeafletMap
                  points={points}
                  height={420}
                  className="h-full min-h-[20rem]"
                />
              )}
            </div>
          </div>

          {/* comps evidence — Pro-only. On a locked live report the server has
              already stripped the comp rows; one LockedPanel stands in for the
              table, $/sqft bars, editors, and the add-a-comp search. */}
          {locked ? (
            <LockedPanel title="Comparable sales" teaser={lockedCompsTeaser(profile)} />
          ) : (
          <PanelCard className="flex flex-col gap-6">
            <div className="flex flex-wrap items-end justify-between gap-3">
              <div className="flex flex-col gap-1">
                <span className="cb-eyebrow text-muted-foreground">Comparable sales</span>
                <h3 className="font-display text-xl font-semibold text-foreground">
                  The {comps.length} comps the value rests on
                </h3>
                {onToggleComp ? (
                  <span className="text-xs text-muted-foreground">
                    {excludedCount > 0
                      ? `${excludedCount} excluded — value recomputed from the remaining set. `
                      : "Toggle any comp to exclude it, or add your own — the value recomputes live."}
                  </span>
                ) : null}
              </div>
              {tuning ? (
                <Pill tone="neutral" className="shrink-0">
                  <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-[var(--cb-ember)]" aria-hidden />
                  Recomputing…
                </Pill>
              ) : asOf ? (
                <span className="font-data text-xs text-muted-foreground">
                  as of {dateLong(asOf)}
                </span>
              ) : null}
            </div>

            {/* agent-control editors — LIVE reports only. The what-if subject
                edits re-estimate live; the summary override rides the PDF. */}
            {canEdit ? (
              <div className="flex flex-col gap-3">
                <SubjectFactsEditor
                  facts={facts}
                  value={overrides ?? EMPTY_OVERRIDES}
                  onChange={onOverridesChange!}
                />
                <SummaryEditor
                  value={reportConfig ?? EMPTY_CONFIG}
                  onChange={onReportConfigChange!}
                />
              </div>
            ) : null}

            {/* add-a-comparable affordance — LIVE reports only */}
            {canControl ? (
              <div className="flex flex-col gap-3 rounded-xl border border-border/70 bg-secondary/30 p-3.5 sm:p-4">
                <AddCompSearch
                  onAdd={onAddComp!}
                  busy={tuning}
                  pinned={forcedSet}
                />
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
                          className="inline-flex h-5 w-5 items-center justify-center rounded-full text-[var(--cb-ember-text)] transition-colors hover:bg-[var(--cb-ember)]/15 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-[var(--cb-ember)] disabled:cursor-not-allowed disabled:opacity-50"
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
                keyboard/AT user gets silence between click and settled value. */}
            <p aria-live="polite" role="status" className="sr-only">
              {tuning
                ? "Recomputing the valuation…"
                : excludedCount > 0
                  ? `${excludedCount} comparable${excludedCount === 1 ? "" : "s"} excluded. Valuation updated.`
                  : ""}
            </p>

            <CompsTable
              comps={comps}
              excluded={excluded}
              forced={forcedSet}
              onToggle={onToggleComp}
              busy={tuning}
            />
            <PpsfBars comps={comps} />
          </PanelCard>
          )}
        </div>
      </div>

      {/* live analytics — every mark derives from THIS lookup's comps + method
          values, recomputing as the user tunes the set. Pro-only. */}
      {locked ? (
        <LockedPanel
          title="Live analytics"
          teaser="Sale-price timeline, $/sqft by distance, and the method-convergence read for this exact lookup."
        />
      ) : (
        <PanelCard className="flex flex-col gap-4">
          <div className="flex flex-wrap items-end justify-between gap-3">
            <div className="flex flex-col gap-1">
              <span className="cb-eyebrow text-muted-foreground">Live analytics</span>
              <h3 className="font-display text-xl font-semibold text-foreground">
                This lookup, charted
              </h3>
            </div>
            {tuning ? (
              <span className="text-xs text-muted-foreground">recomputing…</span>
            ) : null}
          </div>
          <div className={tuning ? "opacity-60 transition-opacity" : "transition-opacity"}>
            <LiveAnalytics comps={comps} valuation={valuation ?? null} />
          </div>
        </PanelCard>
      )}

      {/* market context — Pro-only; redacted to null on a locked live report */}
      {locked ? (
        <LockedPanel
          title="Neighborhood market"
          teaser="The local market read — median $/sqft, price trend, days on market, inventory."
        />
      ) : marketContext ? (
        <PanelCard>
          <MarketPanel market={marketContext} saleHistory={saleHistory} />
        </PanelCard>
      ) : null}

      {/* paste-able executive summary — listing-consultation talking points */}
      <PanelCard className="flex flex-col gap-2">
        <div className="flex items-start justify-between gap-3">
          <span className="cb-eyebrow text-muted-foreground">Talking points</span>
          <button
            type="button"
            onClick={() => {
              void navigator.clipboard
                .writeText(dossierSummary(profile, nearestMi))
                .then(() => toast.success("Summary copied"));
            }}
            className="rounded-full border border-border px-3 py-1 text-xs font-medium text-muted-foreground transition-colors hover:border-[var(--cb-ember)]/40 hover:text-foreground focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--cb-ember)]"
          >
            Copy
          </button>
        </div>
        <p className="text-sm leading-relaxed text-foreground">
          {dossierSummary(profile, nearestMi)}
        </p>
      </PanelCard>

      {/* actions */}
      <PanelCard className="flex flex-col gap-1">
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
      </PanelCard>

      {isSample ? (
        <p className="flex items-center gap-2 text-xs text-muted-foreground">
          <Pill tone="neutral">Sample data</Pill>
          Representative sample figures modeled on the New River Valley — search a real address above for live records.
        </p>
      ) : null}
    </div>
  );
}

const EMPTY_SET: Set<string> = new Set();
const EMPTY_OVERRIDES: SubjectOverrides = {};
const EMPTY_CONFIG: ReportConfig = {};

/** One-line hook for the locked comps panel, built from the redacted teaser. */
function lockedCompsTeaser(profile: ProfileResult): string {
  const s = profile.compsSummary;
  if (!s || s.count <= 0) return "Every comparable sale behind this estimate.";
  const n = `${s.count} comparable sale${s.count === 1 ? "" : "s"} found`;
  return s.nearest_mi != null ? `${n} · nearest ${s.nearest_mi.toFixed(1)} mi` : n;
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
        far != null ? ` within ${far < 1 ? far.toFixed(1) : far.toFixed(1)} mi` : ""
      }`,
    );
  }
  if (m?.months_of_inventory != null)
    parts.push(
      `${m.months_of_inventory < 3 ? "seller's" : m.months_of_inventory < 6 ? "balanced" : "buyer's"} market at ${m.months_of_inventory.toFixed(1)} months of inventory`,
    );
  return parts.join(" · ") + ".";
}
