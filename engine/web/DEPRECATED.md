# DEPRECATED — legacy personal CRM (not part of the Ratified product)

This `web/` directory is a **legacy, personal-use CRM** built on top of the MLS
Bot Python engine. It is **not** part of the Ratified product and is **not**
shipped, linked, or surfaced anywhere in the Document Compliance AI host app.

## Status

- **Retired from the product surface** as of 2026-06-13.
- The supported CMA experience now lives inside the Ratified host app at
  `Document Compliance AI Laptop/src/app/(app)/cma/*`, which reaches this repo's
  Python engine + data over the `MLS_BOT_ROOT` cross-repo bridge.
- This folder is **kept, not deleted** — it remains usable for personal,
  off-product workflows and as a reference for the original UI.

## Do not

- Do not add new features here intending them for the product.
- Do not link to this `web/` app from the Ratified host (sidebar, breadcrumbs,
  API routes, env). The host's CMA module replaces it.

## Why it's still here

The code is intentionally preserved for personal use and historical reference.
If you're looking for the product CMA module, see the host app's `/cma` route
and `src/lib/cma/*` bridge instead.
