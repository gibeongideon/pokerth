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

### D-010 · 2026-11-20 · Accepted — Kubernetes topology
Stateless Deployments (api, workers, web, webclient) with HPA/PDB; game server as a StatefulSet with graceful drain because games live in memory. Managed Postgres (HA + PITR) and Redis. Argo CD GitOps: `dev` → staging, `prod` → production.

---

## Open items (to decide)
- **O-1 Wallet currency.** Recommendation: KES wallet (Paystack Kenya settles KES, M-Pesa is KES), USD shown for reference. Alternative: USD wallet with a configurable FX rate + spread recorded per deposit.
- **O-2 Rake / entry-fee model** and default stake tiers (e.g. $1, $5, $20, $100).
- **O-3 KYC provider** (e.g. Smile ID) and thresholds that trigger it.
- **O-4 Licence of `platform/`.** The game server is AGPL-3.0 (modified source must be offered to network users). `platform/` only talks to it over HTTP; decide whether to keep `platform/` in this repo or a separate private repo.
- **O-5 Branding.** New name and original art; confirm licences of any assets reused from `data/gfx`.
