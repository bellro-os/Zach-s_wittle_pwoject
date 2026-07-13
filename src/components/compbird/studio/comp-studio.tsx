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
import { FirstRun } from "./first-run";
import { Recents, pushRecent } from "./recents";
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
 *
 * SUBJECT ISOLATION (the carry-over-leak fix): everything the user tunes is
 * scoped to ONE subject — what-if overrides, the exec-summary override, comp
 * pins/exclusions, and the untouched engine base the tuning merges onto. Every
 * path that changes the active subject (search select, preset chip, recents
 * chip + Cmd-K palette, ?address= deep link, the ?demo=1 branch, retry) funnels
 * through ONE shared reset, and every async result (profile fetch, preview
 * recompute, override edit) is stamped with a subject epoch and DISCARDED when
 * it arrives for a subject the user has already left. Previously the select()
 * success path applied a resolved profile unguarded, so a superseded lookup
 * that settled despite the abort could re-key the report to an old subject
 * underneath live override state — Edited badges from one house on another
 * house's report.
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
    // Comp-workshop similarity surface (CompSimilarity) — carried through
    // VERBATIM so a tuned recompute keeps its Match column. All optional:
    // an engine without CMA_COMP_SCORE_SURFACE=1 simply doesn't send them.
    similarity: c.similarity,
    subscores: c.subscores,
    reasons: c.reasons,
    atypical_flags: c.atypical_flags,
    hygiene_note: c.hygiene_note,
    impact_usd: c.impact_usd,
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
    // Blind-AI ensemble arm — carried through so a TUNED recompute keeps the
    // ensemble-agreement confidence gate (dropping these would silently fall
    // back to the distance/spread gate mid-session). Optional contract: an
    // engine without CMA_BLIND_ENSEMBLE=1 simply doesn't send them.
    ai_blind: v.ai_blind ?? null,
    ai_ensemble: v.ai_ensemble,
    // Engine-computed measured tier — authoritative for the badge; dropping it
    // here would silently demote the studio to the client-side fallback on
    // every tuned recompute.
    confidence_tier: v.confidence_tier ?? null,
  };
}

/**
 * Headless per-subject session — the WIRE-TRUTH for everything scoped to the
 * active subject, plus the monotonically-increasing epoch that stamps every
 * async operation touching it. The component mirrors this session into React
 * state for rendering, but every decision about what rides a preview/generate
 * wire — and whether an async result is still CURRENT — is made here, in one
 * framework-free place.
 *
 * Rules it enforces:
 *  - `beginSubjectChange()` bumps the epoch and drops ALL subject-scoped state
 *    (overrides, report config, the resolved subject + untouched engine base).
 *    Every subject-change path goes through it, so no path can forget a piece.
 *  - every mutator/acceptor takes the epoch its caller captured when the work
 *    started; a mismatch (the user has since switched subjects) is REFUSED, so
 *    a stale profile response, a stale preview, or a straggler override edit
 *    can never leak onto the next subject.
 *  - `base` is set exactly ONCE per subject (on profile success) and is never
 *    replaced by tuning recomputes — preserving the engineMid baseline ("first
 *    unmodified engine mid per subject") and the zero-round-trip reset.
 *
 * Exported (no React/browser dependencies) for the carry-over-leak regression
 * test: comp-studio.leak.test.ts drives the exact observed scenario.
 */
export function createSubjectSession() {
  let epoch = 0;
  let subject: { address?: string; parcelId?: string } | null = null;
  let base: ProfileResult | null = null;
  let overrides: SubjectOverrides = {};
  let reportConfig: ReportConfig = {};

  return {
    /** Current epoch — capture before async work, hand it back on arrival. */
    epoch: (): number => epoch,
    /** True when a captured epoch has been superseded by a subject change. */
    isStale: (e: number): boolean => e !== epoch,

    /**
     * EVERY subject change starts here: bump the epoch (instantly staling all
     * in-flight work) and drop the full subject-scoped state. Returns the new
     * epoch that stamps the incoming subject's async work.
     */
    beginSubjectChange(): number {
      epoch += 1;
      subject = null;
      base = null;
      overrides = {};
      reportConfig = {};
      return epoch;
    },

    /**
     * Arm the session with a RESOLVED live profile. Refused (returns false)
     * when the response is stale, so the stale-fetch race can never key the
     * tuning surface — or the map/valuation base — to a subject the user left.
     */
    armSubject(
      e: number,
      s: { address?: string; parcelId?: string },
      b: ProfileResult,
    ): boolean {
      if (e !== epoch) return false;
      subject = s;
      base = b;
      return true;
    },

    /** Drop the armed subject (live-lookup failure → sample fallback). */
    disarm(e: number): boolean {
      if (e !== epoch) return false;
      subject = null;
      base = null;
      return true;
    },

    /** Record a what-if edit; refused when stamped by a superseded epoch. */
    setOverrides(e: number, next: SubjectOverrides): boolean {
      if (e !== epoch) return false;
      overrides = next;
      return true;
    },
    /** Record a report-config edit; refused when stale, like setOverrides. */
    setReportConfig(e: number, next: ReportConfig): boolean {
      if (e !== epoch) return false;
      reportConfig = next;
      return true;
    },

    /** The resolved live subject (null on sample / while a lookup is in flight). */
    subject: () => subject,
    /** The untouched engine base for the armed subject — set once per subject. */
    base: () => base,
    /** Wire-truth what-if overrides for the armed subject. */
    overrides: () => overrides,
    /** Wire-truth report config for the armed subject. */
    reportConfig: () => reportConfig,
  };
}
export type SubjectSession = ReturnType<typeof createSubjectSession>;

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
  // (sqft/condition) and the report composition (exec-summary override). These
  // MIRROR the session (below) for rendering; the session copy is what rides
  // the wire, so a mirror can never drift ahead of the guarded truth.
  const [overrides, setOverrides] = useState<SubjectOverrides>({});
  const [reportConfig, setReportConfig] = useState<ReportConfig>({});
  const [tuning, setTuning] = useState(false);

  // The per-subject session: wire-truth overrides/config, the resolved subject
  // + untouched engine base, and the epoch that stales superseded async work.
  // useState's lazy initializer gives one stable instance per mounted studio.
  const [session] = useState(createSubjectSession);

  const abortRef = useRef<AbortController | null>(null);
  const previewAbortRef = useRef<AbortController | null>(null);
  const previewTimerRef = useRef<number | null>(null);

  /** Last attempted selection — powers the failure banner's real Retry. */
  const lastAttemptRef = useRef<Pick<PropertyMatch, "address" | "parcel_id"> | null>(null);

  const cancelPreview = useCallback(() => {
    previewAbortRef.current?.abort();
    previewAbortRef.current = null;
    if (previewTimerRef.current != null) {
      window.clearTimeout(previewTimerRef.current);
      previewTimerRef.current = null;
    }
  }, []);

  /**
   * THE one shared subject-change reset. Every path that changes the active
   * subject funnels through here, so no path can forget a piece of
   * subject-scoped state (the observed leak: Edited badges + adjusted bd/ba
   * from a previous subject rendered on the next subject's report). Bumps the
   * session epoch — instantly staling any in-flight profile fetch or preview
   * recompute — kills the in-flight work, and mirrors the wiped session into
   * render state. Returns the new epoch for the incoming subject's async work.
   */
  const beginSubjectChange = useCallback((): number => {
    const epoch = session.beginSubjectChange();
    abortRef.current?.abort();
    cancelPreview();
    setExcluded([]);
    setForced([]);
    setOverrides({});
    setReportConfig({});
    setTuning(false);
    return epoch;
  }, [session, cancelPreview]);

  // Accepts the full search-result PropertyMatch as well as the minimal
  // {address, parcel_id} seed the deep-link branch builds — only these two
  // fields are read, so no cast is needed at the call site.
  const select = useCallback(
    async (match: Pick<PropertyMatch, "address" | "parcel_id">) => {
      // Shared reset (see beginSubjectChange): a new subject invalidates any
      // in-progress tuning AND drops what-if overrides + narrative edits —
      // they were keyed to the previous subject's record facts.
      const epoch = beginSubjectChange();

      const ctrl = new AbortController();
      abortRef.current = ctrl;
      lastAttemptRef.current = { address: match.address, parcel_id: match.parcel_id };

      setLoading(true);
      setLiveError(null);
      try {
        const input = match.parcel_id
          ? { parcelId: match.parcel_id, address: match.address }
          : { address: match.address };
        const result = await fetchProfile(input, ctrl.signal);

        // Stale-response guard — the leak's root: the abort SHOULD reject a
        // superseded fetch, but a response that has already settled when the
        // user switches subjects resolves anyway. It must be discarded here,
        // never applied over the newer subject (where it would sit beneath —
        // or bring along — another subject's override state).
        if (ctrl.signal.aborted || session.isStale(epoch)) return;

        if (result?.ok && result.facts) {
          // Arm tuning against this resolved subject (epoch-checked in the
          // session too, so a stale arm is structurally impossible).
          session.armSubject(
            epoch,
            {
              address: result.facts.address,
              parcelId: result.facts.parcel_id || undefined,
            },
            result,
          );
          setProfile(result);
          setIsSample(false);
          // Session recents: record the RESOLVED subject (canonical address +
          // parcel), so a chip / Cmd-K re-select hits the same record.
          pushRecent({
            address: result.facts.address,
            parcel_id: result.facts.parcel_id,
          });
        } else {
          throw new Error(result?.error || "no profile");
        }
      } catch (err) {
        if (ctrl.signal.aborted || session.isStale(epoch)) return; // superseded by a newer selection
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
        // No live subject — tuning/override callbacks stay hard no-ops.
        session.disarm(epoch);
      } finally {
        // A superseded selection owns `loading` itself — only the CURRENT
        // lookup may clear it.
        if (!ctrl.signal.aborted && !session.isStale(epoch)) setLoading(false);
      }
    },
    [session, beginSubjectChange],
  );

  // Deep links. ?demo=1 keeps the sample (already the default mount state).
  // ?address= / ?parcelId= resolve a specific subject live via the same
  // select/fetch path a search result uses, with the existing sample fallback.
  // Read client-side to avoid coupling the page to search params.
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.get("demo") === "1") {
      // Same shared reset as every other subject-change path — the sample must
      // start clean even if this branch ever re-runs with state on the board.
      beginSubjectChange();
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
  }, [select, beginSubjectChange]);

  /**
   * Run a tuning recompute for the current excluded/forced sets, merging the
   * preview result onto the live base. Debounced + aborted like the search,
   * and epoch-stamped: a recompute scheduled (or resolving) for a subject the
   * user has since left is dropped, never merged onto the new subject.
   */
  const runPreview = useCallback(
    (nextExcluded: string[], nextForced: string[]) => {
      const subject = session.subject();
      const base = session.base();
      if (!subject || !base) return; // sample / no live subject ⇒ no-op

      cancelPreview();

      // Stamp this recompute to the subject it was requested for. cancelPreview
      // (run by every subject change) clears the timer and aborts the fetch;
      // the epoch is the backstop for a response that settles anyway.
      const epoch = session.epoch();

      // The agent's what-if subject edits travel with every recompute (pruned so
      // an empty editor is a no-op on the wire). The exec-summary override is
      // narrative-only and does NOT move the valuation, so it never rides the
      // preview — it travels with generateReport instead.
      const subjectOverrides = pruneOverrides(session.overrides());

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
        if (session.isStale(epoch)) return; // subject changed while debouncing
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
          if (ctrl.signal.aborted || session.isStale(epoch)) return;
          if (result?.ok && result.comps && result.valuation) {
            // Original comp coordinates keyed by address — derived from the
            // untouched base so comps the recompute kept (or re-added) keep
            // their map pins even when the feed omits coordinates.
            const coords = new Map<string, { lat: number | null; lng: number | null }>();
            for (const c of base.comps ?? []) coords.set(c.address, { lat: c.lat, lng: c.lng });
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
          if (ctrl.signal.aborted || session.isStale(epoch)) return;
          const msg = err instanceof Error ? err.message : "";
          const retryable = msg.includes("warming up") || msg.includes("503");
          toast.error(
            retryable ? RETRYABLE_503 : "Couldn't recompute — keeping the prior comp set.",
          );
        } finally {
          // A stale recompute must not touch state — the subject change that
          // staled it already reset `tuning`.
          if (!ctrl.signal.aborted && !session.isStale(epoch)) setTuning(false);
        }
      }, TUNE_DEBOUNCE_MS);
    },
    [session, cancelPreview],
  );

  // Toggle one comp in/out of the valuation and recompute. No-op on sample.
  const toggleComp = useCallback(
    (key: string, exclude: boolean) => {
      if (isSample || !session.subject()) return;
      setExcluded((prev) => {
        const next = exclude ? Array.from(new Set([...prev, key])) : prev.filter((k) => k !== key);
        // `forced` is reserved for re-adding comps the engine dropped; toggling
        // a visible row only ever moves it in/out of `excluded`.
        runPreview(next, forced);
        return next;
      });
    },
    [isSample, forced, runPreview, session],
  );

  // Pin a searched address IN as a comp (the engine's `forced` list) and
  // recompute. No-op on sample. A re-add also clears any stale exclusion of the
  // same address so a pinned comp can't sit excluded.
  const addForced = useCallback(
    (address: string) => {
      const key = address.trim();
      if (isSample || !session.subject() || !key) return;
      const nextExcluded = excluded.filter((k) => k !== key);
      setExcluded(nextExcluded);
      setForced((prev) => {
        if (prev.includes(key)) return prev; // already pinned — no churn
        const next = [...prev, key];
        runPreview(nextExcluded, next);
        return next;
      });
    },
    [isSample, excluded, runPreview, session],
  );

  // Drop a previously-pinned address back out of the set and recompute.
  const removeForced = useCallback(
    (address: string) => {
      if (isSample || !session.subject()) return;
      setForced((prev) => {
        if (!prev.includes(address)) return prev;
        const next = prev.filter((k) => k !== address);
        runPreview(excluded, next);
        return next;
      });
    },
    [isSample, excluded, runPreview, session],
  );

  // Subject what-if overrides (sqft/condition) changed — re-estimate live, the
  // same debounced/aborted path a comp toggle takes. Guarded BEFORE any state
  // is written: while a subject switch is in flight the session is disarmed,
  // so a straggler edit surviving from the previous subject's editor can no
  // longer poison the state the next subject inherits. No-op on sample data.
  const onOverridesChange = useCallback(
    (next: SubjectOverrides) => {
      if (isSample || !session.subject()) return;
      session.setOverrides(session.epoch(), next);
      setOverrides(next);
      runPreview(excluded, forced);
    },
    [isSample, excluded, forced, runPreview, session],
  );

  // Executive-summary override changed. This is purely narrative (it doesn't
  // move the valuation), so we update the session + state but DON'T trigger a
  // recompute — it rides along on the next preview/generate. Same disarmed-
  // session guard as onOverridesChange: stragglers are dropped, not recorded.
  const onReportConfigChange = useCallback(
    (next: ReportConfig) => {
      if (!session.subject()) return;
      session.setReportConfig(session.epoch(), next);
      setReportConfig(next);
    },
    [session],
  );

  // "Reset to engine picks": clear every pin/exclusion and restore the engine's
  // own comp set. runPreview([], []) short-circuits to the stored base when no
  // subject overrides are active, so the common case is a zero-round-trip snap
  // back; with overrides present it recomputes them against the untouched set.
  const resetTuning = useCallback(() => {
    if (isSample || !session.subject()) return;
    setExcluded([]);
    setForced([]);
    runPreview([], []);
  }, [isSample, runPreview, session]);

  // Tear down any pending preview on unmount.
  useEffect(() => cancelPreview, [cancelPreview]);

  const subjectAddress = profile.facts?.address ?? "";
  // Evidence-locked live profile (server-redacted for a FREE viewer): the comp
  // set is empty, so every tuning affordance is moot — withhold the callbacks
  // exactly like the sample does, so the excluded/tuning UI can't be reached.
  const locked = Boolean(profile.locked);
  const inert = isSample || locked;
  // Memoized: ReportView's children (CompsTable, the map) are React.memo'd, so
  // these must keep their identity across re-renders where nothing was toggled —
  // a fresh Set every render would defeat every memo below it.
  const excludedSet = useMemo(
    () => (inert ? undefined : new Set(excluded)),
    [inert, excluded],
  );
  const forcedSet = useMemo(
    () => (inert ? undefined : new Set(forced)),
    [inert, forced],
  );

  return (
    <div className="flex flex-col gap-10">
      {/* first-run onboarding — an overlay; the studio paints beneath it */}
      <FirstRun />

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

        <div>
          <SearchBar presets={SAMPLE_PRESETS} onSelect={select} busy={loading} />
          {/* session recents: chip row under the "Try" presets + the Cmd/Ctrl-K
              switcher — both re-run select() on a stored subject */}
          <Recents onPick={select} busy={loading} />
        </div>
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
            The report below is a sample — not the address you searched.
          </span>
          <button
            type="button"
            onClick={() => {
              const last = lastAttemptRef.current;
              if (last) void select(last);
            }}
            className="rounded-full border border-border px-3 py-1 text-xs font-medium text-foreground transition-colors hover:border-[var(--cb-ember)]/40 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--cb-ember)]"
          >
            Retry search
          </button>
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
              onToggleComp={inert ? undefined : toggleComp}
              onAddComp={inert ? undefined : addForced}
              onRemoveForced={inert ? undefined : removeForced}
              overrides={overrides}
              reportConfig={reportConfig}
              onOverridesChange={inert ? undefined : onOverridesChange}
              onReportConfigChange={inert ? undefined : onReportConfigChange}
              engineMid={inert ? undefined : session.base()?.valuation?.mid ?? null}
              onResetTuning={inert ? undefined : resetTuning}
              tuning={tuning}
            />
          </Reveal>
        )}
      </div>
    </div>
  );
}

export default CompStudio;
