# Plan: PokerTH → real-money web poker platform (Paystack card + M-Pesa), production on Kubernetes

## Context
`bgames/pokerth` is a fork (origin `github.com/gibeongideon/pokerth`, branch `stable`, clean) of PokerTH 2.1.11:
a mature C++23/Qt6 Texas Hold'em client + server (AGPL-3.0). It is **free-play only**:
- no wallet, payments or real money
- no in-app registration (accounts lived in the pokerth.net website DB; that schema is not in the repo)
- no matchmaking or tournament engine
- clients are native QML only

The goal is a web-first, real-money poker product:
- easy sign-up and funding: card + M-Pesa through Paystack, plus topping up someone else's wallet
- staked games: e.g. a $100 Sit & Go that starts when full or at a set time, with configurable pull-out windows and timeouts
- tournaments and friend invites
- withdrawals and payouts to winners
- everything highly configurable (limits, timeouts, rake, flags)
- hosted on HA Kubernetes

The BCLB licence is in progress, so real money ships behind a feature flag.

Decisions already made with the user:
- **Backend:** FastAPI
- **Web:** React + TypeScript (Next.js portal, Vite + PixiJS game client)
- **Login:** email magic link + Google
- **Payments:** Paystack, reusing Dafeapp patterns

## Target architecture
```
                 ┌──────────── Ingress (TLS, cert-manager) ─────────────┐
 Browser ──► web (Next.js portal: auth, wallet, lobby, tournaments, admin)
         ──► /play (Vite+PixiJS table client) ──WSS protobuf──► game-server pods (C++ PokerTH)
         ──► platform-api (FastAPI) ◄── Paystack webhooks
                     │  Postgres (ledger, users, tables, tournaments, config)
                     │  Redis (queues, matchmaking, rate limits, pub/sub)
                     └─ workers (Celery + beat): payouts, timeouts, scheduled starts, reconciliation
 platform-api ◄─HMAC internal HTTP─► game-server  (create table / results / eliminations)
```
**Platform API (new, `platform/`)** is the source of truth for money, identity and scheduling.
- FastAPI, SQLAlchemy 2 + Alembic, Pydantic v2, Celery/Redis.

**Game server (existing C++)** only runs hands. It runs in a new "managed" mode:
- **Join tokens:** players join with a short-lived Ed25519-signed JWT that the platform issues per seat. Add an optional `platformToken` field to `InitMessage` in `pokerth.proto`, which stays backward compatible. Verify with OpenSSL, which is already a dependency.
- **Internal HTTP:** tables are created over HMAC-signed internal HTTP using Boost.Beast (Boost is already a dependency). Results and eliminations are posted back the same way.
- **No MySQL:** MySQL and the `dbofficial` code path are not needed. Build on the dedicated-server path (`src/net/serverlobbythread.cpp`, `servergame.cpp`, `servergamestate.cpp`, `serveracceptwebhelper.cpp`) instead.
- **Real-money hardening:** use a CSPRNG for shuffling (audit `src/engine/local_engine` deck code). Store full hand histories for disputes and BCLB RNG certification.

**Web:**
- `web/`: Next.js App Router, Tailwind + shadcn/ui, mobile-first, PWA.
- `webclient/`: Vite + React + PixiJS poker table. It speaks the existing protobuf protocol over WebSocket port 7233, using TS types generated from `pokerth.proto` with `ts-proto`.
- New original art. Don't reuse the PokerTH branding, and check the licences of anything taken from `data/gfx`.

## Key product flows

**Registration and login**
- Email magic link, or Google OIDC.
- Sessions are httpOnly cookies with refresh rotation.
- Required before real money: age 18+ confirmation, phone number capture for M-Pesa, and acceptance of terms and responsible-gaming rules.
- Withdrawals need an email OTP step-up. Optional TOTP.

**Funding**
- **Card:** Paystack Popup or redirect, then verify.
- **M-Pesa:** Paystack Charge API `mobile_money {provider:"mpesa", phone}` sends an STK push. The UI polls a pending state until the `charge.success` webhook arrives.
- **Fund a friend:** either pay on behalf of a username or email (the deposit is credited to them), or do a wallet-to-wallet transfer. Both have configurable caps and an AML flag.

**Ledger**
- Double-entry, integer minor units, Postgres row locks, idempotency keys.
- Accounts: `user:available`, `user:escrow`, `house:rake`, `paystack:clearing`, `payouts:pending`.
- The balance is always derived from ledger entries and never stored as a free float.

**Sit & Go pools (core scenario)**
1. Tables are created from table templates: stake tier (e.g. $100), seats (2–10), min players, start mode (`when_full` or `scheduled_at`), payout structure, rake %, blind structure.
2. **Join:** buy-in plus fee moves to escrow.
3. **Pull-out window:** free unregister within `unregister_grace_seconds`; after that, locked until start or cancel.
4. **Full table:** a ready check with `ready_check_timeout`. No-shows are replaced from the waitlist, or forfeit or are refunded, depending on config.
5. **Scheduled start below `min_players`:** auto-cancel and refund everyone.
6. **Game end:** the result callback pays the prizes to winners' wallets and the rake to the house, as one atomic ledger transaction.
7. **Disconnects:** PokerTH's existing session-ID rejoin, plus configurable autofold or sit-out timeouts.

**Quick Play:** a matchmaking queue per stake tier that seats you at the next filling table.

**Private tables and friend invites:** invite link or code (shareable on WhatsApp), a friends list, and invite-only stakes.

**Tournaments**
- Scheduled, with registration open/close, late registration, guaranteed prize pool, re-entry config and payout tables.
- MTT table balancing across game-server instances is a later phase.

**Referrals:** an invite code with a configurable bonus, which can be switched off.

**Withdrawals**
1. Choose a destination: M-Pesa (Paystack transfer recipient `type: mobile_money`, `bank_code: MPESA`) or a bank account.
2. Amount checks: limits per transaction, per day and per month; minimum amount; fee; cooldown after a deposit; KYC tier threshold.
3. Approval: automatic under a threshold, manual admin approval above it.
4. Send via the Paystack Transfer API.
5. Webhooks `transfer.success`, `transfer.failed` and `transfer.reversed` move the money from `payouts:pending` to final, or refund it.
6. Winners can opt into auto-withdraw.

**Configurability**
- `config_settings` table with a typed schema, admin UI, audit log and a Redis cache.
- Feature flags: `real_money_enabled`, `p2p_transfers_enabled`, `auto_payout_enabled`, `tournaments_enabled`, and others.
- Responsible gaming: deposit, loss and session limits and self-exclusion.
- Secrets live only in environment variables or Kubernetes secrets.

**Admin back office**
- Users, KYC, ledger viewer, withdrawal approvals, table and tournament templates, settings, reconciliation reports.
- Role-based, with 2FA.

**Paystack fixes over the Dafeapp code** (`dafeapp/subscriptions/paystack.py`, `views.py`). Port it to an async `httpx` client, then:
- verify amount **and** currency on every settlement
- store webhook events (unique event key) for idempotency
- return non-200 on handler failure so Paystack retries
- set HTTP timeouts
- reject an empty secret, and allowlist Paystack IPs
- use Decimal / integer money throughout
- run a stale-PENDING expiry job
- run a daily reconciliation against `GET /transaction` and `/transfer`

## Repository and workflow
- **Monorepo inside `bgames/pokerth`:** existing C++ code plus new `platform/`, `web/`, `webclient/` and `deploy/` (Helm charts and Argo CD apps).
- **AGPL note:** modified game-server source must be made available to network users. `platform/` talks to it only over HTTP, so record the licensing choice for it in DECISIONS.md.
- **Branches:** `prod` from `stable`, then `dev` from `prod`. All work happens on `dev` (feature branches → `dev` → `prod`).
  - Only local branches at first. Push to `origin` only when you ask.
- **CI/CD:**
  - GitHub Actions builds and tests images for game-server, platform-api, worker, web and webclient.
  - Argo CD deploys the `dev` branch to the dev/staging namespace and `prod` to production.
- **Tracking docs at the repo root** (kept up to date every session):
  - `TASKLIST.md`: phased checklist with status
  - `DECISIONS.md`: ADR-style log, starting with the decisions above
  - `HANDOFF.md`: current state, next steps, how to run, gotchas
  - `docs/platform/PRODUCTION_PLAN.md`: this plan in full
  - `docs/platform/ARCHITECTURE.md`
  - `CLAUDE.md`: points to all of the above

## Kubernetes / HA
- **platform-api, web, webclient:** stateless Deployments with an HPA, PDBs, and pods spread across zones.
- **Workers:** Celery workers, plus a single beat (or `celery-redbeat` for HA).
- **game-server:** a StatefulSet, because games live in memory. The platform assigns each table to a pod.
  - Clients connect through a per-pod host or path route (`wss://play.x/gs-N`).
  - Deploys drain gracefully: no new tables, wait for running games to finish, `terminationGracePeriodSeconds` sized to match.
  - Evaluate Agones later.
- **Data:** managed Postgres with HA and point-in-time recovery (or CloudNativePG), and managed or Sentinel Redis.
- **Ingress and secrets:** ingress-nginx with WebSocket timeouts, cert-manager, External Secrets.
- **Observability:** Prometheus/Grafana, Loki, Sentry and OpenTelemetry. Alerts on webhook failures, ledger imbalance, payout backlog and game-server crashes.

## First actions after approval (in order)
1. In `bgames/pokerth`, run `git checkout -b prod stable`, then `git checkout -b dev prod`.
2. On `dev`, write this plan **verbatim as a real Markdown file**: `pokerth/docs/platform/PRODUCTION_PLAN.md`.
3. Create `pokerth/TASKLIST.md`, `pokerth/DECISIONS.md`, `pokerth/HANDOFF.md`, `pokerth/docs/platform/ARCHITECTURE.md` and `pokerth/CLAUDE.md`.
4. Commit them on `dev` ("docs: production plan and tracking docs").
5. Continue with the Phase 0 scaffold.

## Phases
| Phase | Work |
|---|---|
| 0 (this session) | Create branches. Add tracking docs and the full production plan. Scaffold `platform/` (FastAPI skeleton, config, Alembic, docker-compose with Postgres and Redis) on `dev`. |
| 1 | Auth (magic link + Google), users and profiles, config/flags system, ledger, Paystack deposits (card + M-Pesa STK), webhooks, fund-a-friend. |
| 2 | Game-server managed mode: proto token field, internal API, result callbacks, CSPRNG, hand history. Table templates, Sit & Go lifecycle (escrow, pull-out window, ready check, start/cancel/refund, settlement). |
| 3 | Web portal (Next.js): auth, wallet, lobby, Quick Play, private tables and invites. Web table client (Vite + PixiJS). |
| 4 | Withdrawals and payouts, limits, KYC tiers, admin back office, reconciliation. |
| 5 | Scheduled tournaments, friends, referrals, responsible-gaming tools. |
| 6 | Docker images, Helm, Argo CD, observability, load tests, security review, RNG certification and BCLB compliance pack, then production launch with `real_money_enabled` switched on. |

## Open questions (to be resolved in DECISIONS.md, not blocking Phase 0)
- **Wallet currency:** Paystack Kenya settles in KES and M-Pesa is KES, so I recommend a KES wallet with USD shown for reference. The alternative is a USD wallet with a configurable FX rate and spread captured on each deposit.
- **Rake / fee model** and default stake tiers.
- **KYC provider** (e.g. Smile ID) and the thresholds that trigger it.

## Verification
- **Phase 0:**
  - `git branch` shows `prod` and `dev`, and `dev` is checked out.
  - The docs exist.
  - `docker compose up` in `platform/` starts the API, and `GET /healthz` returns 200.
  - `pytest` passes.
- **Ledger:** property tests check that the sum of all entries per transaction is 0, and that concurrent buy-ins never overdraw.
- **Payments:**
  - Run the full flows end to end against Paystack test keys: card, M-Pesa test numbers, transfers.
  - Replay webhooks to prove idempotency.
  - Send tampered signatures and confirm they are rejected.
  - Send amount-mismatch transactions and confirm they are rejected.
- **Game integration:**
  - Extend the existing Java protocol tests (`tests/src/de/pokerth/test/`) to cover token join and result callbacks.
  - Run an end-to-end Sit & Go with bots (`pokerth_bot`) and check the ledger after settlement.
- **Kubernetes:** a staging drill that kills pods during a game, checks that money stays consistent, and confirms the game-server drains during a rolling deploy.
