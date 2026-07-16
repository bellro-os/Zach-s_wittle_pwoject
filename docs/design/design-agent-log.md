# Design agent log

Continuity journal for the recurring design agent ("compbird-design-agent",
daily). Each run READS this first — do not re-litigate past decisions or thrash
previously-touched areas. Append a dated entry per run (changes + deferrals);
log "no-op" days honestly.

## 2026-07-15 — first full pass (5-reviewer audit; 51 findings → 12 safe fixes shipped)

Applied (23 files, +186/−122; typecheck + build green; deployed):

1. **Studio header mobile overflow** — account-menu.tsx: plan pill hidden on mobile
   (moved into dropdown), Upgrade label shortened on mobile w/ aria-label, 40px avatar
   touch target.
2. **Coverage section** — removed width="wide" (heading back on the 6xl rail); stat grid
   collapses to 1-col under 420px; stat type steps 3xl→4xl→5xl so "Statewide"/"Hourly"
   never clip.
3. **Keyboard-focus outlines restored** (Tailwind v4 trap: always-on `outline-none` +
   `focus-visible:outline-2` = no outline ever paints) — comps/page.tsx,
   portfolio/page.tsx wordmarks, portfolio input-panel textarea. HOUSE RULE: never pair
   always-on outline-none with focus-visible:outline-* utilities.
4. **AA contrast sweep** — no alpha suffixes on text-muted-foreground for informational
   text (#5b6577 is already the 5.53:1 floor; /80≈3.6:1 fails AA). Fixed hero pricing
   disclosure + legal line, join "(optional)", search-bar/recents Esc hints,
   pricing-strategy, report-skeleton. House-rule comment added in compbird.css above
   --muted-foreground.
5. **Nav breakpoint md→lg** — 768–1023px no longer wraps/overflows; hamburger serves
   tablets.
6. **Portfolio funnel bug** — /portfolio added to BOTH safeRedirect allowlists
   (join/signin); previously silently redirected to /comps.
7. **Studio input focus states** visible (same outline-none trap) + search placeholder
   shortened so it doesn't clip on phones.
8. **Comps table mobile** — Exclude toggle reachable, sub-40px touch targets fixed,
   scroll-fade hint wrapper.
9. **Live analytics** — legible chart labels on phones; section heading never renders
   over an empty chart area.
10. **Report view polish** — "0 comps" heading case, dossierSummary dead ternary + bare
    ".", pin-chip hit areas.
11. **Pricing page** — rail alignment, Portfolio batch valuation added to Pro features,
    Pro CTA copy de-apologized ("Start free — upgrade anytime"; Stripe + cancel-anytime
    trust line).
12. **ReportSkeleton rebuilt on SubjectPreview geometry** — report no longer jumps when
    the subject resolves.

Deferred to docs/design/proposals.md (9 brand/risky items — see that file): invisible
market-reports slab, Pro-card emphasis, Reveal SSR opacity:0 inversion, FREE locked-panel
collapse, portfolio row window.open, "instant CMA" in visible copy, sample-report demo
intent, social proof band, published accuracy figure.

Context for future runs: marketing bundle is framer-motion-FREE (motion.tsx =
IntersectionObserver + CSS — keep it that way); opengraph-image.tsx/icon.tsx must never
declare runtime="edge" (502s on Railway).

## 2026-07-15 — UI/UX audit quick-wins batch (9 items, all live-verified 11/11)

From the 6-lens audit (docs/design/uiux-audit-2026-07-15.md). Applied + deployed:
1. ONE shared safeAuthRedirect (src/lib/auth-redirect.ts) — replaced 3 divergent
   copies; /portfolio funnel NOW actually fixed (actions/auth.ts was the missed
   third copy); error/throttle bounces preserve redirect intent.
2. Report URLs: select() writes ?parcelId=&address= via history.replaceState;
   recents/Cmd-K rows are real anchors.
3. Portfolio discoverability: /comps header link, avatar menu order, footer link,
   avatar initial from account name.
4. Download PDF pill in report zone 1 (scroll-to ReportActions, id=cb-report-actions).
5. Hero eyebrow: "Instant CMAs for real estate agents" (delivers part of queued #6).
6. Coverage honesty: no-results + /join + first-run say VA & D.C.; placeLabel never
   fabricates "X County".
7. PpsfBars rebuilt (min−5% baseline, median rule, ember tints, tooltips).
8. FinalCTA sample link = bordered pill + "Free account · no card required."
9. First-run dismiss focuses search (SEARCH_INPUT_ID = cb-search-input).

NEXT UP (from the audit roadmap — do these before inventing new work): the
medium items in uiux-audit-2026-07-15.md (queued #7 demo intent BOTH layers,
address-first hero, #4+#2 conversion pass, #1 dark-band rhythm system, report
hierarchy pass, tuning persistence, waitlist capture).

## 2026-07-16 — Medium roadmap batch (7 items, 4 parallel implementers, 16/17 live checks)

All 7 mediums from uiux-audit-2026-07-15.md shipped + live-verified (FREE-phase
11/12 + Pro-phase 5/5; the one miss is by-design: section numerals only exist on
the unlocked layout). Highlights: intent plumbing (demo/address/parcelId/intent
survive the auth wall; shared withAuthRedirectParam), address-first hero,
$0/$20 pricing beat, true deep-ink .cb-dark rhythm (ONE dark band per page),
Pro-card featured emphasis, sticky report toolbar + numbered sections + SUBJECT
row + comps CSV, ONE locked evidence band (ProPitchBanner removed), tuning
persistence (cb-tuning:<parcel_id>, LRU 50) + tuned recents badges, ?intent=pro
finish-upgrading banner, waitlist endpoint (/data/waitlist.jsonl) + no-results
capture UI, portfolio same-tab links + back chip. Queued proposals #1 #2 #4 #5
#7 are now SHIPPED (marked in proposals.md); remaining open: #3 (Reveal SSR),
#6 (/pricing copy echo), #8 (social proof — needs real material), #9 (accuracy
figure — user/legal decision). NEXT: the audit's four BIG BETS (saved reports,
/markets route, interactive pricing rail, client share path).

## 2026-07-16 — appearance/layout audit landed (docs/design/layout-audit-2026-07-16.md)

3-lens audit on fresh screenshots. NEXT UP for daily runs (in order): (1) bug-class
fixes — comps-table cb-grid stray lines, blurry search icon, typeahead listbox
anchoring (2 lenses), SectionShell scroll-mt for anchored ids; (2) high-value
layout — unify landing left rails, comps table-fixed column discipline, ZONE-1
map-as-footer-row, mobile order fixes (Pro card first on /pricing, valuation first
in report), hero input text-base vs iOS zoom, waitlist/toolbar touch targets;
(3) polish list in the audit doc. The dark-band-placement question (FinalCTA as
the ink moment) is a BRAND call — add to proposals.md, do not auto-apply.
