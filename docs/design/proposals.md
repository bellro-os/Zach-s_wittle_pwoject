# Design proposals — awaiting Zach's sign-off

Brand-level or behavior-risky changes the design agent found but will NOT
auto-apply. Approve one by telling the agent (or Claude) to implement it;
strike it through or delete it to decline. The recurring design agent appends
here (dated) and never applies these on its own.

## 2026-07-15 — first full design pass (51 findings, 12 safe fixes shipped separately)

1. **Market-reports band is an invisible slab** after the cb-dark light flip (bg == page bg, no
   border) — pick one canonical slab surface (`border border-border bg-card`, matching
   coverage.tsx:105) for market-reports.tsx:44 and cta.tsx:15, and reconcile the doubled
   inner+outer vertical padding. `[brand]`
2. **Pricing Pro card lost its "featured tier" emphasis** — reads visually identical to Free.
   Re-establish hierarchy on the light system (ember border, --cb-tint header band, or a
   "Most popular" pill) and delete the stale "dark instrument slab" comment at
   pricing/page.tsx:16-18. `[brand]`
3. **Landing SSRs at opacity:0 until JS hydrates** (49 Reveal wrappers) — invert the Reveal
   default in motion.tsx so content degrades to visible HTML without JS (helps SEO + slow
   devices). `[risky: touches every section's reveal]`
4. **FREE users see six paid CTAs on one report screen** — collapse the three ZONE-2
   LockedPanels (report-view.tsx:454-465) into one locked band with a single unlock button.
   `[brand/monetization call]`
5. **Portfolio results row fires window.open on ANY click** inside the row, including text
   selection (results-table.tsx:190-199) — drop the row-level onClick or guard on
   window.getSelection(). `[risky: changes row interaction]`
6. **"Instant CMA" / "real estate agents" never appear in visible copy** (SEO metadata only) —
   put category+audience into the hero eyebrow/subhead (hero.tsx:24,34-37) and echo once on
   /pricing. `[brand voice call]`
7. **"See a sample report" silently hits the signup wall** and ?demo=1 is stripped by
   safeRedirect — add "free account, no card" microcopy under both CTAs and carry demo intent
   through /join and /signin. `[risky: auth redirect surface]`
8. **Zero social proof on the marketing surface** — collect real agent quotes or a
   machine-derived usage counter first, then add one modest proof band before FinalCTA and
   beside the Pro card. `[brand; requires real material — do not fabricate]`
9. **Accuracy section never states a measured figure** — publish a backtested "median error X%
   on N closed sales" line with a methodology footnote. `[brand/legal decision on which number]`
