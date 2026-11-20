# DECISIONS

Architecture decision log. Append new entries at the bottom; never rewrite an accepted one — supersede it.
Format: **ID · date · status** — decision, then why and consequences.

---

### D-001 · 2026-11-20 · Accepted — Branching model
`stable` (upstream-tracking) → `prod` → `dev`. All work lands on `dev` (directly or via feature branches), then `dev` → `prod` for releases. `prod` is what Kubernetes production deploys. Branches are local until the owner asks to push.

### D-002 · 2026-11-20 · Accepted — Keep the C++ PokerTH server for gameplay
The engine, protocol, rejoin and WebSocket support are mature. Rewriting the game is out of scope. The server runs in a new "managed" mode; money, identity and scheduling move out of it.

### D-003 · 2026-11-20 · Accepted — New platform service in FastAPI
FastAPI + SQLAlchemy 2 (async) + Alembic + Pydantic v2 + Postgres + Redis + Celery (workers + beat). Lives in `platform/` in this repo. It is the source of truth for users, wallet, payments, tables, tournaments and config.

### D-004 · 2026-11-20 · Accepted — Web front ends in React + TypeScript
- `web/`: Next.js (App Router) portal — auth, wallet, lobby, tournaments, admin. Tailwind + shadcn/ui.
- `webclient/`: Vite + React + PixiJS poker table, speaking the existing protobuf protocol over WSS (types generated with `ts-proto` from `pokerth.proto`).
The native QML client stays buildable but is not the product's primary client.

### D-005 · 2026-11-20 · Accepted — Login: email magic link + Google
Passwordless. Magic-link tokens are single-use, short-lived and stored hashed. Withdrawals require an extra email OTP step-up; TOTP is optional.

### D-006 · 2026-11-20 · Accepted — Paystack for card, M-Pesa and payouts
Reuse the dafeapp patterns (`dafeapp/subscriptions/paystack.py`) but fix the known gaps: verify amount and currency on settle, store webhook events for idempotency, HTTP timeouts, non-200 on handler failure, integer money, stale-pending expiry, reconciliation. M-Pesa uses the Charge API (`mobile_money`, provider `mpesa`); payouts use the Transfers API.

### D-007 · 2026-11-20 · Accepted — Real money behind a feature flag
The BCLB licence and Paystack gaming approval are in progress. `real_money_enabled` defaults to **off**; everything else ships and can run in free-play mode.

### D-008 · 2026-11-20 · Accepted — Double-entry ledger, integer minor units
Balances are derived from ledger entries, never stored as a float. Every money movement is one balanced journal transaction with an idempotency key.

### D-009 · 2026-11-20 · Accepted — Platform ↔ game server integration
Players join with a short-lived Ed25519-signed seat token (new optional `platformToken` field in `InitMessage`). The platform creates tables over an HMAC-signed internal HTTP API on the game server; the game server posts results back the same way. The game server does not use MySQL in managed mode.

### D-010 · 2026-11-20 · Deferred by D-015 — Kubernetes topology
Stateless Deployments (api, workers, web, webclient) with HPA/PDB; game server as a StatefulSet with graceful drain because games live in memory. Managed Postgres (HA + PITR) and Redis. Argo CD GitOps: `dev` → staging, `prod` → production.

### D-011 · 2026-11-20 · Accepted — One mobile-portable player app (supersedes the client split in D-004)
The owner wants a design that ports easily to mobile apps. So instead of a Next.js portal plus a separate table client:
- `apps/player/` is the single player app: Vite + React + TypeScript + PixiJS, mobile-first, shipped as web/PWA and wrapped with **Capacitor** for Android and iOS from the same code.
- `apps/site/` (Next.js) keeps only the public landing page, SEO, legal pages and the admin back office.
- Shared code in `packages/` (`api-client`, `protocol`, `ui`), pnpm workspace.

Why Capacitor rather than React Native: the PixiJS table and all screens run unchanged in the native WebView, so there is one UI to build and test. React Native would need a second table renderer. Capacitor still gives push notifications, deep links, secure storage and native Google sign-in.

Consequences: the platform API must support bearer tokens (for apps) as well as cookies (for web); magic links and invite links must be universal/app links; Android ships first, iOS after the licence is granted (store rules for real-money gaming).

### D-012 · 2026-11-20 · Accepted — Wallet in USD, KES shown for reference (resolves O-1)
Balances, buy-ins and prizes are USD cents. KES equivalents are shown under every amount. M-Pesa deposits/withdrawals convert at a quoted rate (reference rate ± configurable spread), shown before confirming and stored per conversion. Cards charge USD (Paystack USD on the Kenya merchant account must be confirmed). Consequence: FX exposure — the house keeps a KES float and a daily liabilities-vs-holdings report.

### D-013 · 2026-11-20 · Accepted — House earnings: entry fee shown once, no rake during play (resolves O-2)
Price shown as "$100 + $0.50" on join and receipt; prize pool = buy-ins, fee → `house:fees`. Default ≈ 0.5 %, configurable per stake tier (flat or %, min/max). Optional levers (FX spread, withdrawal fee, prize-pool cut) exist but are off by default and shown where they apply. Owner asked for fees that are not intrusive or noticeable while playing; fees are still always disclosed because BCLB licensing and consumer-protection law require it. Excise duty and winnings withholding tax are configurable tax lines; rates to be confirmed with a tax adviser.

### D-014 · 2026-11-20 · Accepted — Identity: tiered KYC with Smile ID (resolves O-3)
Tier 0 email/Google (free play) → Tier 1 name, DOB, phone, national ID number checked against the register, no photo (deposits and play up to a limit) → Tier 2 selfie + liveness (withdrawals above threshold, higher limits). Asked only when the user first needs the tier. Web + Android/iOS SDKs fit D-011. Thresholds are config settings. One person per account (unique national ID).

### D-015 · 2026-11-20 · Accepted — Local until MVP, then one VPS via GitHub Actions; Kubernetes later
Develop and test locally with Docker Compose until the MVP works end to end (sign-in, deposit, Sit & Go, payout). Then deploy to a single VPS: GitHub Actions builds images to GHCR on push to `prod` and deploys over SSH with `docker compose`, with Caddy for HTTPS. `dev` runs CI only. Kubernetes (D-010) moves to after launch. Why: far less to run and pay for while the product is unproven, and a 12-factor setup keeps the later move to Kubernetes a deployment change, not a code change.

### D-016 · 2026-11-20 · Accepted — Stake levels are configuration, not code (resolves O-6)
Stake levels are rows in a `stake_tiers` table managed from the admin back office: buy-in (USD cents), entry fee (flat or %, min/max), seats, min players, start mode, payout structure, blind structure, enabled flag, display order. Admins can add, change or retire levels without a deploy; a change never affects tables already open. Seed data for local dev only: $1, $5, $20, $100, editable.

### D-017 · 2026-11-20 · Accepted — USD/KES rate: fixed, configurable, default 129 (resolves O-7)
The KES rate is a config setting `fx.usd_kes_rate`, default **129** KES per USD, changed by an admin (audit-logged), no live feed for now. Used for KES reference amounts and M-Pesa conversions; the rate in force is stored on every conversion. Spread `fx.spread_pct` defaults to 0 (D-013 keeps it off). A live rate source can be added later behind the same setting.

### D-018 · 2026-11-20 · Accepted — Phase 1 implementation choices
- **Running balance column.** `ledger_accounts.balance` is updated only by `ledger.post`, under a row lock, in the same DB transaction as the entries, so overdraft checks are one row read. A DB check constraint forbids negative balances on user accounts; tests check balance = sum of entries.
- **Sessions.** Access token = HS256 JWT, 15 min. Refresh token = random opaque string stored as SHA-256, 30 days, rotated on every use; replaying a rotated token revokes the whole family. Web gets httpOnly SameSite=Lax cookies (refresh cookie scoped to `/auth`); apps get tokens in the body (`client: "app"`).
- **Business settings** live in the code-declared registry (`app/services/config_registry.py`) with DB overrides and an audit table, cached 5 s per process. No Redis cache needed yet.
- **Deposits** are credited only by `settle_deposit` (status success + exact amount + exact currency). Mismatches become `mismatch` and are never credited. A late success still credits an `expired` deposit, because the money was received.
- **Webhooks** are stored before processing (unique per event + id) and answer 500 on failure so Paystack retries.
- **KYC** tiers are set by admins until Smile ID is integrated.

---

## Open items (to decide)
- **O-8 VPS provider and region** — parked by the owner (2026-11-20); decide before Phase 6. Latency to Kenyan players matters.
- **O-4 Licence of `platform/`.** The game server is AGPL-3.0 (modified source must be offered to network users). `platform/` only talks to it over HTTP; decide whether to keep `platform/` in this repo or a separate private repo.
- **O-5 Branding.** New name and original art; confirm licences of any assets reused from `data/gfx`.
