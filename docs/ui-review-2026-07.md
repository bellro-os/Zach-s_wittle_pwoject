# compbird — UI & Product Review (2026-07-02)

Synthesis of six specialist source-code reviews (landing narrative, studio workflow, visual craft, auth/billing/account, report output, platform gaps). Standalone app at `C:/Users/zach/Desktop/Compbird/`. Items already on `docs/feature-roadmap-2026-07.md` are omitted below unless a reviewer added implementation-grade specificity beyond the roadmap line.

## What is working

- **Every figure on the landing is a real engine run** — the $455k hero valuation, the five-method convergence graphic, and the live market cards all come from actual output, honoring the anti-slop charter ("real numbers or nothing") where most competitor sites fake it.
- **The accuracy section is the strongest single surface**: three independent valuation methods as bars converging on a shared scale with a dashed consensus guide plus a confidence dial — data IS the layout, no icon-card explainers.
- **The design system is genuinely systematic**: token re-declaration in `compbird.css` (`.compbird-root` / `.cb-dark`) makes shared components render on-brand with zero edits; asymmetric section rhythm (1-col → 2-col → 3-col → bento with a 2x2 lead tile → dark band), the hairline+ember tick motif, hand-drawn stroke-only marks, and dependency-free token-driven SVG charts all hold the "precision instrument" identity.
- **The studio tuning loop is fast and honest**: exclude/force comps with a 300ms-debounced live recompute, instant sample-first load (clearly badged, never masquerading as a searched address), and sticky inline error notices when live lookups fail.
- **Report honesty gates are real, not decorative**: the confidence pill downgrades on wide spreads / distant comps / single-method estimates; the record→adjusted override disclosure is non-suppressible; null KPIs render "—"; all five methods carry plain-English rationale ("Median time+size-adjusted $219/sf × 2,096 sqft").
- **Billing and metering plumbing is production-grade**: atomic reserve→render→record with refund-on-failure, a webhook that re-reads subscription state before granting tier, an explicit auditable entitlement matrix, and a quota banner shown before any render cost.
- **Auth is defensive and accessible**: safe redirect validation, constant-time password verification against a dummy hash, proper error association on forms, and role=combobox + aria-activedescendant keyboard navigation in search.
- **The narrative arc converts**: hero value prop → data-source trust strip → accuracy defense → three-move workflow, with the waitlist removed and the footer honestly hedging ("model-driven opinions — not appraisals").

## What is not working

- **Money is invisible until after signup.** No `/pricing` page exists (`src/app/` confirmed), the landing never mentions FREE (2 downloads/mo) or Pro ($20/mo), and the quota constraint first appears inside the studio — a bait-and-switch feeling at exactly the moment budget questions arise.
- **Provenance — the roadmap's own #1 "RPR-beating differentiator" — is entirely absent.** No MLS-vs-supplemental labeling anywhere; `ProfileComp` has no `source` field; the confidence pill is blind to pool composition even though `docs/regional-accuracy-2026-07.md` proves it drives accuracy (supplemental +8% bias rural, MLS wins dense).
- **The account lifecycle is a skeleton**: no password reset ("email us" is the recovery path), no `/account` settings surface, no first-run onboarding explaining the 2/mo contract, and `?subscribed=1` after Stripe checkout is never read — a $20 purchase resolves with zero acknowledgment.
- **The studio has no memory.** No recents, history, or session persistence — an agent running five CMAs a day re-types every address; hard-coded sample chips are the only quick-access affordance. (The roadmap's "my reports shelf" is the full fix; nothing session-level exists in the interim.)
- **The engine's intelligence is hidden from users.** `atypical_reason`, `cohort` (e.g., `bedrooms_mismatch`), and `appearance_tier` are already on the wire in `PreviewComp` but never displayed — agents see a bare "Atypical" badge with no explanation of why a comp was down-weighted.
- **Platform table stakes are missing for a paid product**: no `error.tsx`/`not-found.tsx` (a studio crash white-screens), no `robots.txt`/sitemap, and no `/terms`, `/privacy`, or `/about` — the legal/trust surface a credit-card-taking product needs.
- **Market metrics ship ungated.** The market panel renders trend/MOI/DOM for any county with no sample-size gating or thin-data hedge — violating the roadmap's own §1 spec (monthly → quarterly → "insufficient data") in rural counties where the data is thin.
- **Small craft debts are accumulating against the token charter**: hardcoded `#475569` in `MiniBars.tsx`, five undocumented glow/card opacity values, navbar border jank on scroll, copy-paste marquee masks, and the Market Reports heading silently swapping between live and sample copy mid-scroll.

## 30 suggestions

Ranked by impact-per-effort. `[impact/effort/kind]`.

1. **Pre-signup pricing disclosure** — add a "Start free · 2 reports/mo" pill to the nav CTA, a "Free account · no credit card" caveat under the hero button (`hero.tsx` ~line 40), and a one-line quota note on `/join` and `/signin`, so the metering contract is visible before signup, not after [high/S/ux]
2. **Hedge the coverage claim** — under "Built on Virginia. Expanding out." (`coverage.tsx` ~line 60) add: "Statewide parcel + assessor data; live MLS in 9 jurisdictions today" per `regional-accuracy-2026-07.md`, so copy never outruns the data [high/S/content]
3. **App-level error boundary + 404** — add `src/app/error.tsx` (branded container, /comps redirect, support email) and `not-found.tsx`; today a client crash in the studio white-screens production [high/S/tool]
4. **robots.txt + sitemap.ts** — allow `/`, disallow `/comps` and `/api/*`; expose landing/join/signin; prerequisite for share-link OG cards when roadmap #3 lands [high/S/tool]
5. **Executive summary snippet in the dossier** — a paste-able 2–3 sentence `<DossierSummary />` in `report-view.tsx` ("Estimated $455k, range $X–$Y, 6 comps within 1.1 mi, market: balanced") for listing-consultation talking points [high/S/feature]
6. **Keyboard exclude-toggle on comp rows** — bind Space/X to toggle the focused row's exclusion in `comps-table.tsx` plus a row context menu, replacing the mouse-to-Use-column dance [high/S/ux]
7. **Public /pricing page** — `src/app/pricing/page.tsx` with the FREE/Pro feature matrix (2/mo watermarked vs unlimited + whitelabel + statewide), linked from nav and footer; Stripe is already live [high/M/feature]
8. **Terms + privacy pages** — `/terms` and `/privacy` (plus footer links); a product taking payment and storing agent data has no legal surface at all [high/M/content]
9. **Comp source wiring (provenance groundwork)** — add `source: 'mls' | 'supplemental'` to `ProfileComp`/`PreviewComp` in `src/lib/compbird/types.ts`, emit from the engine, render a neutral "Public Records" pill per row; feeds the roadmap provenance panel with a gating label when >30% supplemental or nearest >5 mi [high/M/feature]
10. **Surface comp rationale (cohort + atypical_reason + appearance_tier)** — tooltip/info-icon on the Atypical badge explaining why the engine down-weighted the comp; the data is already on the wire and currently wasted; a fuller drill-down panel can follow [high/M/ui]
11. **First-run onboarding modal** — on signup redirect to /comps, a 1–2 screen modal: "Welcome to compbird Free" + 2/mo watermark callout + plan comparison with upgrade CTA; makes the metering contract explicit without slowing the studio [high/M/ux]
12. **Session recents + Cmd+K quick switcher** — track the last ~10 searched properties in a collapsible panel and a Ctrl/Cmd+K modal with recents as quick-picks; the session-scoped stopgap until the roadmap's reports shelf ships [high/M/ux]
13. **"Coming next" coverage signal** — replace the static jurisdiction marquee (`coverage.tsx` ~line 142) with LIVE NOW (real counts from `/api/compbird/markets`) vs COMING NEXT tabs, converting coverage gaps into a roadmap signal instead of doubt [high/M/feature]
14. **/account settings page** — auth-walled `src/app/account/page.tsx`: name edit, change-password modal (reuse `auth-server.ts` scrypt), plan + next billing date, Manage billing button, and a billing-history table via a new `GET /api/billing/invoices` [high/M/feature]
15. **Pooled accuracy proof point on landing** — small stat block under the convergence card citing the real validation numbers (15.7% median |APE| MLS pool / 17.4% supplemental, 179 test subjects from `regional-accuracy-2026-07.md`) — honest aggregate proof, not a one-sample dial [medium/S/content]
16. **Assessed-vs-estimate delta pill** — in `subject-header.tsx`, when `assessed_value` differs from `valuation.mid`, show "Assessed $367,700 · Estimate $455,000 (+24%)" with tone; genuine listing intel currently left on the table [medium/S/feature]
17. **Recompute-now button + debounce label** — during tuning, show "Recomputing…" with a force-fire button next to the spinner so power users aren't left guessing whether the UI hung [medium/S/ux]
18. **Make the error-notice retry actually retry** — the persistent 503 notice's action should re-fire the search (not just toast), plus a `?retry=1` param for bookmarked failures [medium/S/ux]
19. **Stabilize Market Reports live/sample copy** — keep the section heading fixed and move state into a persistent [LIVE]/[SAMPLE] badge on the card header, ending the silent mid-scroll copy swap [medium/S/ux]
20. **Layered-surface token system** — name the opacity scale in `compbird.css` (`--cb-glow-strong/medium/soft`, card opaque/frosted/ghost), extract a shared `.cb-mask-fade` marquee utility and a `.cb-contour-accent` class with a "lead tiles only" rule, and replace `#475569` in `MiniBars.tsx` line 56 with a token [medium/S/ui]
21. **Sample-size gating on market metrics** — extend `MarketContext` with `sample_size`/`data_quality`; `market-panel.tsx` renders monthly medians at n≥50, quarterly at 15–49, "Insufficient data" below, plus a provenance footnote ("N closed sales, MLS + public records, as of [date]"); implements the roadmap's own §1 spec [medium/M/feature]
22. **Pool-aware confidence pill** — extend `confidence()` in `valuation-panel.tsx` with comp source counts and nearest-comp source; >50% supplemental + nearest >2 mi shifts the label ("Supplemental pool, moderate confidence") [medium/M/feature]
23. **Unified comp controls** — move AddCompSearch into a sticky table footer ('+' affordance), render pinned comps as inline removable chips, and toast the concrete rejection reason ("Too far — 4.2 mi") when the engine drops a pinned comp [medium/M/ui]
24. **Account menu dropdown** — convert StudioAccountMenu's inline buttons into an initial-avatar popover: Profile (→ /account), Plan & billing, Sign out; frees header space and matches SaaS convention [medium/M/ui]
25. **Post-subscribe confirmation** — consume `?subscribed=1` (currently never read) into a success view: plan name, unlocks, next billing date, back-to-studio; a $20 purchase should not resolve silently [medium/M/feature]
26. **Connect valuation bars to the confidence dial** — a subtle hairline/dashed connector across the ~16px gap in `accuracy.tsx` (~lines 193–197) so method convergence and the confidence readout read as one argument [medium/M/ui]
27. **cb-grid rule for data-dense panels** — codify "data-heavy panels (provenance, comps table, market metrics) may carry the faint parcel grid; forms and cards do not," ready for the provenance panel and market view [medium/M/ui]
28. **Self-serve password reset** — /forgot-password form → rate-limited `POST /api/auth/forgot` sending a 15-min single-use signed token → /reset-password page → `POST /api/auth/reset` with audit logging; "email us" is not a recovery path for a paid product [high/L/feature]
29. **Fix navbar border jank** — `nav.tsx` ~line 52: always render `border-[var(--cb-line)]` and transition opacity 0→100 on scroll instead of swapping from `border-transparent` [low/S/ui]
30. **Preserve method-rationale formatting** — replace `stripTags(m.rationale)` in `valuation-panel.tsx` ~line 141 with a sanitized allowlist (`<b>`, `<i>`, `<span>`) so engine emphasis survives [low/S/ui]

---

*Omitted as already roadmap-owned (no new specificity beyond what's merged above): market report tool M0–M3, my-reports shelf, shareable links, coverage explorer, compare view, what-if slider, engine blend rule.*
