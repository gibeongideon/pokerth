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
- [x] CI workflow for `platform/` (`.github/workflows/platform-ci.yml`: ruff, mypy, migrations, pytest with Postgres + Redis, Docker build)
- [x] Client design is mobile-portable: one player app + Capacitor (D-011)
- [x] Decide wallet currency (USD, KES reference — D-012), fee model (D-013), KYC (D-014)

## Phase 1 — Identity, config, ledger, deposits
- [x] Users, profiles, unique username (table display name) — `/me`, `PATCH /me`
- [x] Email magic-link login (single-use, 15 min TTL, hashed token, rate-limited silently, no account enumeration)
- [x] Google sign-in (ID token checked against Google keys; links to existing account by verified email)
- [x] Sessions: httpOnly cookies (web) and bearer tokens (apps), refresh rotation with reuse detection, logout / logout-all
- [x] Real-money onboarding gate: terms + 18+ (`/me/accept-terms`), KYC tier gate on deposit and transfers
- [x] Config system: typed registry + DB overrides + audit log + 5 s per-process cache; admin API `/admin/settings`
- [x] Feature flags now: `real_money_enabled`, `p2p_transfers_enabled`, `deposit_on_behalf_enabled` (others are added with their features)
- [x] Double-entry ledger (accounts, journal, entries), integer cents, idempotency keys, row locks; concurrency test
- [x] Paystack async client (timeouts, non-JSON handling, disabled when no secret)
- [x] Deposit: card (initialize → redirect/Popup → webhook or poll)
- [x] Deposit: M-Pesa STK push (Charge API, `mobile_money`/`mpesa`) + pending poll that verifies with Paystack
- [x] Webhook: HMAC-SHA512, optional IP allowlist, event store (idempotent), amount + currency check, 500 on failure so Paystack retries
- [x] Fund-a-friend: deposit for another player (by username/email); wallet→wallet transfer (flag, per-tx and daily caps, idempotent)
- [x] FX: `fx.usd_kes_rate` (default 129), `fx.spread_pct` (default 0), quote endpoint, rate stored per deposit
- [x] Jobs (Celery worker + beat): stale pending expiry every 5 min; daily reconciliation against Paystack
- [ ] Smile ID integration for KYC tiers (for now admins set tiers via `PUT /admin/users/{id}/kyc-tier`)
- [ ] Daily FX exposure report (needs withdrawals, Phase 4)
- Moved to Phase 2 (needs buy-ins): fee engine — entry fee per stake level, optional levers, tax lines

## Phase 2a — Sit & Go in the platform (done 2026-11-20)
- [x] Fee engine: entry fee per stake level (flat/% with min/max), excise added to price, withholding on prizes — all configurable, default 0 tax
- [x] `stake_tiers` + admin API (validated: seats 2-10, payouts sum 100 % and don't increase); dev seed Free/$1/$5/$20/$100
- [x] Tables copy the stake level when opened, so admin edits never change an open table
- [x] Sit & Go lifecycle: join → escrow + fee, pull-out window (full refund), ready check, start, cancel/refund, payout by place
- [x] Ready-check timeout: no-shows removed and refunded (or fee kept, configurable); scheduled tables start or cancel
- [x] Quick Play (fullest table first), private tables with invite codes, one open table kept per stake level
- [x] Seat tokens (Ed25519 JWT) + public key endpoint; HMAC-signed result endpoint for the game server (idempotent)
- [x] Worker timer every 5 s; local dev dashboard + seed + simulate-result (screenshots in `docs/platform/screenshots/`)

## Phase 2b — Game server managed mode (C++)
- [!] Local build blocked: no CMake/Boost/Qt6 on this machine and ~1.5 GB free RAM. Options: install build deps, or build in Docker (`docker/linux/Dockerfile*`) on a machine with more memory / in CI.
- [ ] Proto: optional `platformToken` in `InitMessage` (backward compatible)
- [ ] Game server: Ed25519 seat-token verification (public key from `GET /internal/seat-token-key`)
- [ ] Game server: internal HTTP API (Boost.Beast, HMAC): create game from table config, drain, health
- [ ] Game server: result callback to `POST /internal/games/{table_id}/result` (signed, retried)
- [ ] Platform: real `GameGateway` replacing `LocalGateway` (`platform/app/services/game_gateway.py`)
- [ ] RNG: refuse to deal if OpenSSL `RAND_bytes` fails when real money is on (`src/engine/local_engine/tools.cpp`)
- [ ] Hand history persistence (for disputes and RNG certification)

## Phase 3 — Player app (web + mobile) and site
- [ ] pnpm workspace; `packages/api-client` (from OpenAPI), `packages/protocol` (ts-proto), `packages/ui` (tokens, components)
- [ ] `apps/player/` Vite + React + TS: auth, wallet, deposit, lobby, tables, profile — mobile-first
- [ ] PixiJS table screen, protobuf over WSS; portrait + landscape layouts, touch controls
- [ ] Capacitor Android build: deep links (invites, magic links), push notifications, secure storage, native Google sign-in
- [ ] Capacitor iOS build (after the licence is granted)
- [ ] `apps/site/` Next.js: landing, SEO, legal and responsible-gaming pages
- [ ] Original visual identity (no PokerTH branding); PWA

## Phase 4 — Withdrawals, KYC, admin (API done 2026-11-20)
- [x] Payout destinations: M-Pesa via Paystack transfer recipients; number must match the profile phone
- [x] Withdrawal rules: min/max, daily/monthly limits, fee (flat/%/free-above, default off), KYC tier (tier 2 above $500)
- [x] Approval: automatic below $200, admin review above or after a recent deposit; emailed 6-digit code to confirm
- [x] Money held in `payouts:pending`; refunded in full on reject/cancel/failed/reversed
- [x] Transfer webhooks (success/failed/reversed) + worker: expire codes, retry sends, verify stuck transfers
- [x] Admin API: withdrawal review queue, user search/detail/suspend, liabilities + FX exposure report
- [ ] Bank payouts (only M-Pesa now)
- [ ] Admin back office UI, admin roles + 2FA (with Phase 3 UI work)
- [ ] Smile ID integration (tiers still set by admins)
- [ ] Confirm with Paystack in test mode: M-Pesa recipient number format, transfer OTP disabled

## Phase 5 — Social & tournaments
- [ ] Scheduled tournaments (registration windows, late reg, guarantees, re-entry, payout tables)
- [ ] Friends list, invites, referrals (configurable bonus)
- [ ] Responsible gaming: deposit/loss/session limits, self-exclusion

## MVP checkpoint (all local)
- [ ] Sign in → deposit (card + M-Pesa, test keys, via tunnel) → join Sit & Go → play in browser → prize in wallet

## Phase 6 — VPS deploy and launch (D-015)
- [ ] `deploy/vps/docker-compose.prod.yml` + Caddyfile (HTTPS, WebSocket)
- [ ] Production Dockerfiles for platform, worker, game server; player app static build
- [ ] GitHub Actions: CI on push/PR; on `prod` build → GHCR → SSH deploy → migrate → health check → rollback
- [ ] VPS hardening: deploy user, SSH keys only, UFW, fail2ban, unattended upgrades
- [ ] Backups (pg_dump + WAL to off-site storage), tested restore
- [ ] Monitoring: uptime on `/readyz`, Sentry, off-box logs
- [ ] Game-server drain before deploy
- [ ] Load tests; security review; RNG certification; BCLB compliance pack
- [ ] Launch: switch on `real_money_enabled` in production

## Phase 7 — Kubernetes (after launch, when traffic needs it)
- [ ] Helm charts in `deploy/`; Argo CD apps
- [ ] Game-server StatefulSet with graceful drain; per-pod WSS routing
- [ ] HA Postgres/Redis; Prometheus, Grafana, Loki, OpenTelemetry
- [ ] Chaos drill (kill pods mid-game, check ledger)
