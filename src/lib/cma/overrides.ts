/**
 * Shared contract for agent CMA control — subject-fact overrides + report
 * composition — threaded app → routes → worker → engine. Everything is additive:
 * when nothing is supplied the engine behaves byte-identically to today.
 *
 * Surface note: the editable builder is the (authenticated) compbird studio; the
 * engine application of these overrides is surface-agnostic (build_cma /
 * build_preview / build_profile all apply them at the same pre-comps point).
 *
 * Integrity note: the statutory "not an appraisal" disclaimer is ENGINE-LOCKED —
 * it is NOT part of ReportConfig and cannot be replaced or suppressed by an
 * agent. Likewise the record→adjusted disclosure is rendered server-side whenever
 * an override is applied and is not a toggleable section. See the engine
 * (_build_html) for where these are enforced.
 */

export type CmaCondition =
  | "needs_work"
  | "fair"
  | "average"
  | "good"
  | "renovated"
  | "new_build";

/** Subject-fact overrides applied onto the resolved subject before comps/AVM/valuation. */
export interface SubjectOverrides {
  sqft?: number; // finished living area (value-moving)
  bedrooms?: number;
  full_baths?: number; // integer
  half_baths?: number; // integer (0.5-bath fix: kept separate from full)
  acres?: number;
  year_built?: number;
  property_type?: string; // free-text class label
  condition?: CmaCondition; // maps to engine `appearance` token (value-moving)
}

/**
 * Report composition + narrative overrides. NOTE: there is deliberately NO
 * `disclaimerText` field — the legal disclaimer is engine-locked and may never be
 * replaced by an agent. `sections`/`strategyText` are defined for MVP-2 (the
 * template registry); the tight v1 UI only sends `execText`.
 */
export const CMA_SECTIONS = [
  "hero",
  "exec",
  "kpis",
  "comps",
  "dom_band",
  "methods",
  "strategy",
] as const;
export type CmaSection = (typeof CMA_SECTIONS)[number];

/** Named report templates — MUST mirror the engine `_TEMPLATES` keys in build_cma.py. */
export const CMA_TEMPLATES = ["executive_1pager", "full_packet", "buyer_brief"] as const;
export type CmaTemplate = (typeof CMA_TEMPLATES)[number];
export const CMA_TEMPLATE_LABELS: Record<CmaTemplate, string> = {
  executive_1pager: "Executive one-pager",
  full_packet: "Full packet (multi-page)",
  buyer_brief: "Buyer brief",
};

export interface ReportConfig {
  /** Named layout template (ordered sections + pagination). Omitted ⇒ default one-pager. */
  template?: CmaTemplate;
  /** Sections to render. Omitted ⇒ all (today's behavior). (MVP-2 UI.) */
  sections?: CmaSection[];
  /** Replace the auto exec-summary paragraph. Plain text; engine HTML-escapes it. */
  execText?: string;
  /** Replace the auto strategy bullets (one per line). Engine HTML-escapes each. (MVP-2 UI.) */
  strategyText?: string;
}

/** Condition → engine LFD_Appearance token (see _APPEARANCE_TIER in build_cma.py). */
export const CONDITION_TO_APPEARANCE: Record<CmaCondition, string> = {
  needs_work: "NEEDS REPAIR",
  fair: "FAIR",
  average: "AVERAGE",
  good: "GOOD",
  renovated: "REMODELED",
  new_build: "NEW CONSTRUCTION",
};

export const CONDITION_LABELS: Record<CmaCondition, string> = {
  needs_work: "Needs work",
  fair: "Fair",
  average: "Average",
  good: "Good",
  renovated: "Renovated",
  new_build: "New build",
};

/** Server-side numeric bounds. Out-of-range values are clamped (never silently trusted). */
export const OVERRIDE_BOUNDS: Record<
  "sqft" | "bedrooms" | "full_baths" | "half_baths" | "acres" | "year_built",
  { min: number; max: number; integer: boolean }
> = {
  sqft: { min: 100, max: 25000, integer: true },
  bedrooms: { min: 0, max: 20, integer: true },
  full_baths: { min: 0, max: 20, integer: true },
  half_baths: { min: 0, max: 20, integer: true },
  acres: { min: 0, max: 2000, integer: false },
  year_built: { min: 1800, max: new Date().getFullYear() + 1, integer: true },
};

/** Narrative length caps (bound the render + the XSS surface). */
export const NARRATIVE_CAPS = { execText: 1200, strategyText: 1500 } as const;

/** Strip empty/zero fields so an untouched editor sends `undefined` (no-op). */
export function pruneOverrides(o: SubjectOverrides): SubjectOverrides | undefined {
  const out: SubjectOverrides = {};
  for (const [k, v] of Object.entries(o)) {
    if (v === undefined || v === null || v === "") continue;
    if (typeof v === "number" && !Number.isFinite(v)) continue;
    (out as Record<string, unknown>)[k] = v;
  }
  return Object.keys(out).length ? out : undefined;
}

/**
 * Clamp numeric overrides to OVERRIDE_BOUNDS and drop anything out of range that
 * can't be clamped. Runs server-side before the overrides reach the engine, so a
 * crafted payload can never push an unbounded value into the valuation.
 */
export function sanitizeSubjectOverrides(o?: SubjectOverrides): SubjectOverrides | undefined {
  const p = o && pruneOverrides(o);
  if (!p) return undefined;
  const out: SubjectOverrides = {};
  for (const [k, v] of Object.entries(p)) {
    const bound = (OVERRIDE_BOUNDS as Record<string, { min: number; max: number; integer: boolean }>)[k];
    if (bound) {
      let n = Number(v);
      if (!Number.isFinite(n)) continue;
      n = Math.min(bound.max, Math.max(bound.min, n));
      (out as Record<string, unknown>)[k] = bound.integer ? Math.round(n) : n;
    } else if (k === "condition") {
      if (v && Object.prototype.hasOwnProperty.call(CONDITION_TO_APPEARANCE, v as string)) {
        out.condition = v as CmaCondition;
      }
    } else if (k === "property_type") {
      out.property_type = String(v).slice(0, 60);
    }
  }
  return Object.keys(out).length ? out : undefined;
}

/** App (camel, condition enum) → engine (snake, appearance token) override dict. */
export function toEngineOverrides(o?: SubjectOverrides): Record<string, unknown> | undefined {
  const p = sanitizeSubjectOverrides(o);
  if (!p) return undefined;
  const { condition, ...rest } = p;
  const out: Record<string, unknown> = { ...rest };
  if (condition) out.appearance = CONDITION_TO_APPEARANCE[condition];
  return out;
}

/** Validate + cap a ReportConfig server-side (sections allowlisted, narrative capped). */
export function sanitizeReportConfig(c?: ReportConfig): ReportConfig | undefined {
  if (!c) return undefined;
  const out: ReportConfig = {};
  if (c.template && (CMA_TEMPLATES as readonly string[]).includes(c.template)) {
    out.template = c.template;
  }
  if (Array.isArray(c.sections)) {
    const allowed = c.sections.filter((s): s is CmaSection => (CMA_SECTIONS as readonly string[]).includes(s));
    if (allowed.length) out.sections = allowed;
  }
  if (typeof c.execText === "string" && c.execText.trim()) {
    out.execText = c.execText.slice(0, NARRATIVE_CAPS.execText);
  }
  if (typeof c.strategyText === "string" && c.strategyText.trim()) {
    out.strategyText = c.strategyText.slice(0, NARRATIVE_CAPS.strategyText);
  }
  return Object.keys(out).length ? out : undefined;
}
