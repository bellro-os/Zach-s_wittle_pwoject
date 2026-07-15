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
