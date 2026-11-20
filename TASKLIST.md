# TASKLIST

Status legend: `[ ]` todo · `[~]` in progress · `[x]` done · `[!]` blocked

Full plan: [docs/platform/PRODUCTION_PLAN.md](docs/platform/PRODUCTION_PLAN.md) · Decisions: [DECISIONS.md](DECISIONS.md) · Session state: [HANDOFF.md](HANDOFF.md)

## Phase 0 — Foundations
- [x] Create `prod` branch from `stable` (local only, not pushed)
- [x] Create `dev` branch from `prod`; all work happens on `dev`
- [x] Production plan as Markdown (`docs/platform/PRODUCTION_PLAN.md`)
- [x] Tracking docs: TASKLIST, DECISIONS, HANDOFF, ARCHITECTURE, CLAUDE.md
- [x] `platform/` FastAPI skeleton: settings (pydantic-settings), `/healthz`, `/readyz`
- [x] SQLAlchemy 2 async + Alembic set up (no tables yet; first migration comes with Phase 1 models)
- [x] `platform/docker-compose.yml` (api, postgres, redis, mailpit) — verified `/readyz` ok
- [x] pytest + ruff + mypy configured and passing
- [ ] CI workflow for `platform/` (GitHub Actions)
- [x] Client design is mobile-portable: one player app + Capacitor (D-011)
- [x] Decide wallet currency (USD, KES reference — D-012), fee model (D-013), KYC (D-014)

## Phase 1 — Identity, config, ledger, deposits
- [ ] Users, profiles, unique username (table display name)
- [ ] Email magic-link login (single-use, 15 min TTL, hashed token, rate-limited)
- [ ] Google OIDC login (link to existing account by verified email)
- [ ] Sessions: httpOnly secure cookies (web) and bearer tokens (mobile apps), refresh rotation, revoke all sessions
- [ ] Real-money onboarding gate: terms/RG acceptance, then KYC Tier 1 on first deposit
- [ ] Config system: `config_settings` typed registry + DB overrides + Redis cache + audit log
- [ ] Feature flags: `real_money_enabled`, `p2p_transfers_enabled`, `auto_payout_enabled`, `tournaments_enabled`, `referrals_enabled`
- [ ] Double-entry ledger (accounts, journal, entries), integer minor units, idempotency keys
- [ ] Paystack async client (port of dafeapp `subscriptions/paystack.py`, with timeouts and error handling)
- [ ] Deposit: card (initialize → Popup/redirect → verify)
- [ ] Deposit: M-Pesa STK push (Charge API, `mobile_money`, provider `mpesa`) + pending poll
- [ ] Webhook endpoint: HMAC-SHA512, event store (idempotent), amount + currency check, retry-friendly status codes
- [ ] Fund-a-friend: pay on behalf of a user; wallet→wallet transfer (caps, flag)
- [ ] FX: USD/KES reference rate worker, configurable spread, quote-then-confirm for M-Pesa, rate stored per conversion
- [ ] Fee engine: entry fee per stake tier (flat/%/min/max), optional levers off by default, tax lines (excise, withholding)
- [ ] KYC tiers with Smile ID: Tier 1 ID-number check, Tier 2 selfie + liveness; tier gates on deposit/play/withdraw
- [ ] Stale PENDING expiry job; daily reconciliation job; daily FX exposure report

## Phase 2 — Game server managed mode + Sit & Go
- [ ] Proto: optional `platformToken` in `InitMessage` (backward compatible)
- [ ] Game server: Ed25519 JWT verification for seat tokens
- [ ] Game server: internal HTTP API (Boost.Beast, HMAC): create table, drain, health
- [ ] Game server: result/elimination callbacks to the platform (signed, retried)
- [ ] RNG: refuse to deal if OpenSSL `RAND_bytes` fails when real money is on (`src/engine/local_engine/tools.cpp`)
- [ ] Hand history persistence (for disputes and RNG certification)
- [ ] Table templates (stake, seats, min players, start mode, payout structure, rake, blinds)
- [ ] Sit & Go lifecycle: join→escrow, pull-out window, ready check, start, cancel/refund, settlement
- [ ] Quick Play matchmaking queue per stake tier
- [ ] Private tables + invite links/codes

## Phase 3 — Player app (web + mobile) and site
- [ ] pnpm workspace; `packages/api-client` (from OpenAPI), `packages/protocol` (ts-proto), `packages/ui` (tokens, components)
- [ ] `apps/player/` Vite + React + TS: auth, wallet, deposit, lobby, tables, profile — mobile-first
- [ ] PixiJS table screen, protobuf over WSS; portrait + landscape layouts, touch controls
- [ ] Capacitor Android build: deep links (invites, magic links), push notifications, secure storage, native Google sign-in
- [ ] Capacitor iOS build (after the licence is granted)
- [ ] `apps/site/` Next.js: landing, SEO, legal and responsible-gaming pages
- [ ] Original visual identity (no PokerTH branding); PWA

## Phase 4 — Withdrawals, KYC, admin
- [ ] Payout destinations (M-Pesa `mobile_money`/`MPESA`, bank) via Paystack transfer recipients
- [ ] Withdrawal rules: min/max, daily/monthly limits, fee, post-deposit cooldown, KYC tier
- [ ] Approval: auto below threshold, manual above; email OTP step-up
- [ ] Transfer webhooks: success / failed / reversed
- [ ] Admin back office (RBAC + 2FA): users, KYC, ledger, approvals, templates, settings, reports

## Phase 5 — Social & tournaments
- [ ] Scheduled tournaments (registration windows, late reg, guarantees, re-entry, payout tables)
- [ ] Friends list, invites, referrals (configurable bonus)
- [ ] Responsible gaming: deposit/loss/session limits, self-exclusion

## Phase 6 — Production
- [ ] Docker images for all services; Helm charts in `deploy/`; Argo CD apps
- [ ] Game-server StatefulSet with graceful drain; per-pod WSS routing
- [ ] Observability: Prometheus, Grafana, Loki, Sentry, OpenTelemetry; alerts
- [ ] Load tests; chaos drill (kill pods mid-game, check ledger)
- [ ] Security review; RNG certification; BCLB compliance pack
- [ ] Launch: switch on `real_money_enabled` in production
