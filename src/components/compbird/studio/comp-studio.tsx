"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import { Eyebrow, Pill } from "@/components/compbird/ui";
import { Reveal } from "@/components/compbird/motion";
import { fetchProfile, previewComps } from "@/lib/compbird/api";
import type { SubjectOverrides, ReportConfig } from "@/lib/cma/overrides";
import { pruneOverrides } from "@/lib/cma/overrides";
import { SAMPLE_PROFILE, SAMPLE_PRESETS } from "@/lib/compbird/sample";
import type {
  ProfileResult,
  ProfileComp,
  PropertyMatch,
  PreviewComp,
  PreviewResult,
  PreviewValuation,
  Valuation,
} from "@/lib/compbird/types";
import { SearchBar } from "./search-bar";
import { ReportView } from "./report-view";
import { ReportSkeleton } from "./report-skeleton";

/**
 * The comp studio. Paints SAMPLE_PROFILE instantly on mount (always impressive,
 * never a spinner on first load), then runs live against the engine on demand.
 * Live failures fall back to the canonical 509 Jefferson sample (never re-keyed
 * to the user's address — a real address must never sit atop fabricated comps).
 *
 * On a LIVE report the user can tune the comp set: excluding (or re-forcing) a
 * comparable calls the preview engine for the same subject and re-renders the
 * valuation panel, comps table and $/sqft bars from the recomputed result.
 * Debounced + aborted exactly like the search; a hard no-op on sample data.
 */

/** Debounce window for a tuning recompute — matches the search bar's cadence. */
const TUNE_DEBOUNCE_MS = 300;

/** The retryable warm-up state the engine reports while the worker spins up. */
const RETRYABLE_503 =
  "The records engine is warming up. Give it a moment and try again.";

/** Combine full + half baths into the single ProfileComp `baths` figure. */
function combineBaths(full: number | null, half: number | null): number | null {
  if (full == null && half == null) return null;
  return (full ?? 0) + (half ? half * 0.5 : 0);
}

/** Per-sqft from a preview comp (the wire shape carries no precomputed ppsf). */
function compPpsf(sold: number | null, sqft: number | null): number | null {
  if (sold == null || sqft == null || sqft <= 0) return null;
  return sold / sqft;
}

/**
 * Map a live PREVIEW comp onto the display ProfileComp shape. The preview wire
 * now carries each comp's own latitude/longitude, so we map those directly —
 * which keeps the pin for added/forced comps that aren't in the original set.
 * We still fall back to the original live comps by address for any comp the feed
 * left without coordinates, so the aerial map stays as populated as before.
 */
function previewCompToProfile(
  c: PreviewComp,
  coords: Map<string, { lat: number | null; lng: number | null }>,
): ProfileComp {
  const address = c.address ?? "—";
  const xy = coords.get(address);
  return {
    address,
    city: c.city,
    subdivision: c.subdivision,
    sold_price: c.sold_price,
    ppsf: compPpsf(c.sold_price, c.sqft),
    sqft: c.sqft,
    acres: c.acres,
    beds: c.bedrooms,
    baths: combineBaths(c.full_baths, c.half_baths),
    year_built: c.year_built,
    close_date: c.close_date,
    dom: c.dom,
    distance_mi: c.distance_mi,
    lat: c.latitude ?? xy?.lat ?? null,
    lng: c.longitude ?? xy?.lng ?? null,
    pending: c.pending,
    atypical: c.atypical_sale,
    source: c.source,
    cohort: c.cohort,
    atypical_reason: c.atypical_reason,
    appearance_tier: c.appearance_tier,
  };
}

/** Map the preview valuation onto the display Valuation shape. */
function previewValuationToProfile(v: PreviewValuation): Valuation {
  return {
    mid: v.mid,
    low: v.low,
    high: v.high,
    comp_ppsf: v.ppsf,
    implied_subject_ppsf: null,
    divergence_pct: v.divergence_pct,
    methods: v.methods.map((m) => ({
      name: m.name,
      value: m.value,
      rationale: m.rationale,
    })),
  };
}

export function CompStudio() {
  const [profile, setProfile] = useState<ProfileResult>(SAMPLE_PROFILE);
  const [isSample, setIsSample] = useState(true);
  const [loading, setLoading] = useState(false);
  // A live lookup failed and we fell back to the sample — surfaced as a
  // PERSISTENT inline notice (the toast alone evaporates, and a sample report
  // must never quietly pass for the searched address).
  const [liveError, setLiveError] = useState<string | null>(null);

  // Tuning state — only meaningful on a LIVE report.
  const [excluded, setExcluded] = useState<string[]>([]);
  const [forced, setForced] = useState<string[]>([]);
  // Agent-control state, SIBLING to excluded/forced: subject what-if overrides
  // (sqft/condition) and the report composition (exec-summary override).
  const [overrides, setOverrides] = useState<SubjectOverrides>({});
  const [reportConfig, setReportConfig] = useState<ReportConfig>({});
  const [tuning, setTuning] = useState(false);

  // Refs mirror the override/config state so runPreview (and its callers
  // toggleComp/addForced/removeForced) always read the latest values without a
  // stale closure or an extra argument on every call site.
  const overridesRef = useRef<SubjectOverrides>({});
  const reportConfigRef = useRef<ReportConfig>({});

  const abortRef = useRef<AbortController | null>(null);
  const previewAbortRef = useRef<AbortController | null>(null);
  const previewTimerRef = useRef<number | null>(null);

  /**
   * The LIVE base for tuning: the subject we resolved and its original comp
   * coordinates. Preview always recomputes the same subject; we merge the
   * returned comps + valuation onto this base so identity/map/market persist.
   */
  const subjectRef = useRef<{ address?: string; parcelId?: string } | null>(null);
  const baseRef = useRef<ProfileResult | null>(null);
  const coordsRef = useRef<Map<string, { lat: number | null; lng: number | null }>>(
    new Map(),
  );

  const cancelPreview = useCallback(() => {
    previewAbortRef.current?.abort();
    previewAbortRef.current = null;
    if (previewTimerRef.current != null) {
      window.clearTimeout(previewTimerRef.current);
      previewTimerRef.current = null;
    }
  }, []);

  // Accepts the full search-result PropertyMatch as well as the minimal
  // {address, parcel_id} seed the deep-link branch builds — only these two
  // fields are read, so no cast is needed at the call site.
  const select = useCallback(
    async (match: Pick<PropertyMatch, "address" | "parcel_id">) => {
      abortRef.current?.abort();
      cancelPreview();
      // A new subject invalidates any in-progress tuning.
      setExcluded([]);
      setForced([]);
      // A new subject also drops any what-if overrides + narrative edits — they
      // were keyed to the previous subject's record facts.
      setOverrides({});
      setReportConfig({});
      overridesRef.current = {};
      reportConfigRef.current = {};
      setTuning(false);

      const ctrl = new AbortController();
      abortRef.current = ctrl;

      setLoading(true);
      setLiveError(null);
      try {
        const input = match.parcel_id
          ? { parcelId: match.parcel_id, address: match.address }
          : { address: match.address };
        const result = await fetchProfile(input, ctrl.signal);

        if (result?.ok && result.facts) {
          setProfile(result);
          setIsSample(false);
          // Arm tuning against this resolved subject.
          subjectRef.current = {
            address: result.facts.address,
            parcelId: result.facts.parcel_id || undefined,
          };
          baseRef.current = result;
          const coords = new Map<string, { lat: number | null; lng: number | null }>();
          for (const c of result.comps ?? []) coords.set(c.address, { lat: c.lat, lng: c.lng });
          coordsRef.current = coords;
        } else {
          throw new Error(result?.error || "no profile");
        }
      } catch (err) {
        if (ctrl.signal.aborted) return; // superseded by a newer selection
        // Surface the engine's specific retryable warm-up message verbatim so a
        // user knows to retry; otherwise the generic outage line.
        const msg = err instanceof Error ? err.message : "";
        const retryable = msg.includes("warming up") || msg.includes("503");
        const notice = retryable
          ? RETRYABLE_503
          : "Couldn't reach live records — showing a sample report.";
        toast.error(notice);
        setLiveError(notice);
        // Keep the canonical 509 Jefferson demo — never re-key the sample to the
        // searched address, so a real address never sits atop fabricated comps.
        setProfile(SAMPLE_PROFILE);
        setIsSample(true);
        subjectRef.current = null;
        baseRef.current = null;
        coordsRef.current = new Map();
      } finally {
        if (!ctrl.signal.aborted) setLoading(false);
      }
    },
    [cancelPreview],
  );

  // Deep links. ?demo=1 keeps the sample (already the default mount state).
  // ?address= / ?parcelId= resolve a specific subject live via the same
  // select/fetch path a search result uses, with the existing sample fallback.
  // Read client-side to avoid coupling the page to search params.
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.get("demo") === "1") {
      setProfile(SAMPLE_PROFILE);
      setIsSample(true);
      return;
    }
    const address = params.get("address")?.trim() ?? "";
    const parcelId = params.get("parcelId")?.trim() ?? "";
    if (address || parcelId) {
      // Minimal, correctly-typed seed — only the fields select() reads. No cast.
      void select({ address, parcel_id: parcelId });
    }
  }, [select]);

  /**
   * Run a tuning recompute for the current excluded/forced sets, merging the
   * preview result onto the live base. Debounced + aborted like the search.
   */
  const runPreview = useCallback(
    (nextExcluded: string[], nextForced: string[]) => {
      const subject = subjectRef.current;
      const base = baseRef.current;
      if (!subject || !base) return; // sample / no live subject ⇒ no-op

      cancelPreview();

      // The agent's what-if subject edits travel with every recompute (pruned so
      // an empty editor is a no-op on the wire). The exec-summary override is
      // narrative-only and does NOT move the valuation, so it never rides the
      // preview — it travels with generateReport instead.
      const subjectOverrides = pruneOverrides(overridesRef.current);

      // Nothing tuned at all (no comp edits AND no subject overrides) ⇒ restore
      // the original live report with no round-trip. Subject overrides re-drive
      // the valuation, so their presence alone must still trigger a recompute.
      if (
        nextExcluded.length === 0 &&
        nextForced.length === 0 &&
        !subjectOverrides
      ) {
        setProfile(base);
        setTuning(false);
        return;
      }

      setTuning(true);
      previewTimerRef.current = window.setTimeout(async () => {
        const ctrl = new AbortController();
        previewAbortRef.current = ctrl;
        try {
          const result: PreviewResult = await previewComps(
            {
              address: subject.address,
              parcelId: subject.parcelId,
              excluded: nextExcluded,
              forced: nextForced,
              subjectOverrides,
            },
            ctrl.signal,
          );
          if (ctrl.signal.aborted) return;
          if (result?.ok && result.comps && result.valuation) {
            const coords = coordsRef.current;
            const mergedComps = result.comps.map((c) => previewCompToProfile(c, coords));
            const mergedValuation = previewValuationToProfile(result.valuation);
            setProfile({
              ...base,
              comps: mergedComps,
              valuation: mergedValuation,
              // Carry the engine's authoritative record→adjusted diff so the
              // on-screen report renders the SAME non-suppressible disclosure as
              // the PDF (null when no subject override was applied).
              overrideDiff: result.subject?._override_diff ?? null,
              overrideValue: result.subject?._overridden
                ? {
                    record: result.subject._record_mid ?? null,
                    adjusted: result.subject._adjusted_mid ?? null,
                  }
                : null,
            });
            // Add-a-comp truth: drop any pinned address the engine couldn't use
            // as a comp here (too far / wrong class / outside lookback) so the
            // "Pinned" chip never lies. Match on a normalized address — the
            // engine echoes a canonical form that may add the city/zip — using a
            // prefix test in either direction to avoid false drops.
            if (nextForced.length > 0) {
              const norm = (s: string) =>
                s.toUpperCase().replace(/,/g, "").replace(/\s+/g, " ").trim();
              const usedNorm = result.comps.map((c) => norm(c.address ?? ""));
              const dropped = nextForced.filter((a) => {
                const an = norm(a);
                return (
                  an.length > 4 &&
                  !usedNorm.some(
                    (u) => u.length > 4 && (u.startsWith(an) || an.startsWith(u)),
                  )
                );
              });
              if (dropped.length > 0) {
                const ds = new Set(dropped.map(norm));
                setForced((prev) => prev.filter((a) => !ds.has(norm(a))));
                toast.message(
                  dropped.length === 1
                    ? "That sale couldn't be used as a comp here — removed."
                    : `${dropped.length} pinned sales couldn't be used here — removed.`,
                );
              }
            }
          } else {
            throw new Error(result?.error || "preview failed");
          }
        } catch (err) {
          if (ctrl.signal.aborted) return;
          const msg = err instanceof Error ? err.message : "";
          const retryable = msg.includes("warming up") || msg.includes("503");
          toast.error(
            retryable ? RETRYABLE_503 : "Couldn't recompute — keeping the prior comp set.",
          );
        } finally {
          if (!ctrl.signal.aborted) setTuning(false);
        }
      }, TUNE_DEBOUNCE_MS);
    },
    [cancelPreview],
  );

  // Toggle one comp in/out of the valuation and recompute. No-op on sample.
  const toggleComp = useCallback(
    (key: string, exclude: boolean) => {
      if (isSample || !subjectRef.current) return;
      setExcluded((prev) => {
        const next = exclude ? Array.from(new Set([...prev, key])) : prev.filter((k) => k !== key);
        // `forced` is reserved for re-adding comps the engine dropped; toggling
        // a visible row only ever moves it in/out of `excluded`.
        runPreview(next, forced);
        return next;
      });
    },
    [isSample, forced, runPreview],
  );

  // Pin a searched address IN as a comp (the engine's `forced` list) and
  // recompute. No-op on sample. A re-add also clears any stale exclusion of the
  // same address so a pinned comp can't sit excluded.
  const addForced = useCallback(
    (address: string) => {
      const key = address.trim();
      if (isSample || !subjectRef.current || !key) return;
      const nextExcluded = excluded.filter((k) => k !== key);
      setExcluded(nextExcluded);
      setForced((prev) => {
        if (prev.includes(key)) return prev; // already pinned — no churn
        const next = [...prev, key];
        runPreview(nextExcluded, next);
        return next;
      });
    },
    [isSample, excluded, runPreview],
  );

  // Drop a previously-pinned address back out of the set and recompute.
  const removeForced = useCallback(
    (address: string) => {
      if (isSample || !subjectRef.current) return;
      setForced((prev) => {
        if (!prev.includes(address)) return prev;
        const next = prev.filter((k) => k !== address);
        runPreview(excluded, next);
        return next;
      });
    },
    [isSample, excluded, runPreview],
  );

  // Subject what-if overrides (sqft/condition) changed — re-estimate live, the
  // same debounced/aborted path a comp toggle takes. No-op on sample data.
  const onOverridesChange = useCallback(
    (next: SubjectOverrides) => {
      setOverrides(next);
      overridesRef.current = next;
      if (isSample || !subjectRef.current) return;
      runPreview(excluded, forced);
    },
    [isSample, excluded, forced, runPreview],
  );

  // Executive-summary override changed. This is purely narrative (it doesn't
  // move the valuation), so we update state/ref but DON'T trigger a recompute —
  // it rides along on the next preview/generate. No-op styling on sample.
  const onReportConfigChange = useCallback((next: ReportConfig) => {
    setReportConfig(next);
    reportConfigRef.current = next;
  }, []);

  // Tear down any pending preview on unmount.
  useEffect(() => cancelPreview, [cancelPreview]);

  const subjectAddress = profile.facts?.address ?? "";
  // Memoized: ReportView's children (CompsTable, the map) are React.memo'd, so
  // these must keep their identity across re-renders where nothing was toggled —
  // a fresh Set every render would defeat every memo below it.
  const excludedSet = useMemo(
    () => (isSample ? undefined : new Set(excluded)),
    [isSample, excluded],
  );
  const forcedSet = useMemo(
    () => (isSample ? undefined : new Set(forced)),
    [isSample, forced],
  );

  return (
    <div className="flex flex-col gap-10">
      {/* search console */}
      <div className="flex flex-col gap-6">
        <div className="flex flex-col gap-3">
          <Eyebrow>The comp studio</Eyebrow>
          <div className="flex flex-wrap items-end justify-between gap-4">
            <h1 className="font-display max-w-2xl text-3xl font-bold leading-[1.05] tracking-tight text-foreground text-balance sm:text-4xl">
              Price any home with appraisal-grade comparables.
            </h1>
            <span
              className="inline-flex items-center gap-2"
              role="status"
              aria-live="polite"
            >
              <Pill tone={isSample ? "neutral" : "ember"}>
                <span
                  className={`h-1.5 w-1.5 rounded-full ${
                    isSample ? "bg-muted-foreground" : "bg-[var(--cb-ember)]"
                  }`}
                  aria-hidden
                />
                {isSample ? "Sample" : "Live"}
              </Pill>
            </span>
          </div>
        </div>

        <SearchBar presets={SAMPLE_PRESETS} onSelect={select} busy={loading} />
      </div>

      {/* live-lookup failure notice — persists until the next search, so the
          sample below can never quietly pass for the searched address */}
      {liveError && !loading ? (
        <div
          role="alert"
          className="flex flex-wrap items-baseline gap-x-2 gap-y-1 rounded-xl border border-[var(--negative)]/30 bg-[var(--negative)]/5 px-4 py-3 text-sm"
        >
          <span className="font-medium text-foreground">{liveError}</span>
          <span className="text-muted-foreground">
            The report below is a sample — not the address you searched. Try again in
            a moment.
          </span>
        </div>
      ) : null}

      {/* report area */}
      <div aria-busy={loading}>
        {loading ? (
          <ReportSkeleton />
        ) : (
          <Reveal key={subjectAddress + String(isSample)} y={16}>
            <ReportView
              profile={profile}
              isSample={isSample}
              excluded={excludedSet}
              forced={forcedSet}
              onToggleComp={isSample ? undefined : toggleComp}
              onAddComp={isSample ? undefined : addForced}
              onRemoveForced={isSample ? undefined : removeForced}
              overrides={overrides}
              reportConfig={reportConfig}
              onOverridesChange={isSample ? undefined : onOverridesChange}
              onReportConfigChange={isSample ? undefined : onReportConfigChange}
              tuning={tuning}
            />
          </Reveal>
        )}
      </div>
    </div>
  );
}

export default CompStudio;
