# compbird — Launch Checklist (owner-tagged)

Status as of 2026-07-03. Engineering items are done or in this repo; the four
items marked **YOU** are the only blockers requiring your accounts.

## 1. Stripe (YOU — ~1 hour)
1. Stripe Dashboard → Products → **Add product** "compbird Pro" → **recurring
   price $20/month** (optionally a second annual price, e.g. $204/yr = 15% off).
2. Copy into the VPS `.env.production` (template in repo root):
   - `STRIPE_SECRET_KEY` (sk_live_… — use sk_test_… first for the smoke run)
   - `STRIPE_PRICE_ID` (the monthly price id)
   - `STRIPE_PRICE_ID_ANNUAL` (optional)
3. Developers → Webhooks → **Add endpoint** `https://<DOMAIN>/api/billing/webhook`
   with events: `checkout.session.completed`, `customer.subscription.created`,
   `customer.subscription.updated`, `customer.subscription.deleted`.
   Copy the signing secret → `STRIPE_WEBHOOK_SECRET`.
4. Test-mode first: run one full checkout with card 4242 4242 4242 4242 and
   confirm the plan chip flips to Pro and the welcome email fires (if RESEND set).

## 2. Domain + DNS (YOU — ~1 hour)
- Buy/point the domain (an A record → the VPS IP). Set `COMPBIRD_DOMAIN` for the
  Caddy vhost and `NEXT_PUBLIC_APP_URL=https://<DOMAIN>` in `.env.production`.
- Caddy auto-provisions TLS once DNS resolves.

## 3. Email (YOU: one key — code already wired)
- Create a Resend account → verify the sending domain → `RESEND_API_KEY` +
  `MAIL_FROM="compbird <no-reply@<DOMAIN>>"` in `.env.production`.
- Without the key everything still works; reset links log to the server console.

## 4. GitHub remote (YOU — ~10 min; gh CLI not installed on this machine)
```bash
# on github.com: create PRIVATE repo (e.g. <you>/compbird), no README
cd "C:/Users/zach/Desktop/Compbird"
git remote add origin git@github.com:<you>/compbird.git
git push -u origin main
```

## 5. Legal review packet (YOU + attorney)
Pages to review (drafts are flagged in-source as attorney-review drafts):
- `/terms` — liability cap, not-an-appraisal, subscription terms
- `/privacy` — data collected (account email, generated reports, public-records data)
- The recurring claim to bless: **"Estimates are model-driven opinions of value —
  not appraisals."** (hero, footer, studio, pricing, PDF)
- The accuracy claims on the landing (all from real engine runs; backing data in
  docs/regional-accuracy-2026-07.md and docs/blacksburg-head-to-head-2026-07.md)

## 6. Deploy (ME — runbook in DEPLOY.md once the deploy pack lands)
Build image → compose up alongside the existing engine service → Caddy include →
first-boot db push → smoke.

## 7. Production smoke (ME, after 1+2)
signup → free instant estimate → locked evidence → 403 → test-mode checkout →
Pro unlock → full comps + watermark-free PDF → billing portal → password reset
email.

## Cost/config notes
- Engine hygiene model for compbird: leave `CMA_HYGIENE_MODEL` at the engine
  default for launch; consider Haiku for cost once volume exists (bake-off data
  in the accuracy memos — Opus 2.17% vs Haiku 4.35% hygiene error).
- Marginal monthly cost ≈ VPS share + domain + Stripe fees → break-even ≈ 1–2
  Pro subscribers.
