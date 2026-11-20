# HANDOFF

Read this first when resuming. Update it at the end of every session.

## Current state (2026-11-20)
- Branches: `stable` → `prod` → `dev`. **`dev` is checked out.** Nothing pushed to `origin`.
- Phase 0 done. **Phase 1 done** except Smile ID (admins set KYC tiers by hand for now) and the FX exposure report (needs withdrawals).
- Platform API now has: magic-link + Google sign-in, sessions (cookies for web, bearer for apps), profile + terms, admin settings with audit, double-entry ledger, Paystack card + M-Pesa deposits, webhook, fund-a-friend, wallet-to-wallet transfers, expiry + reconciliation jobs.
- Decisions this session: D-011 to D-018 (mobile-portable app, USD wallet, entry-fee model, KYC tiers, local-then-VPS, configurable stake levels, KES rate 129, Phase 1 choices).
- Next: Phase 2 — fee engine + stake levels + Sit & Go lifecycle in the platform, then game-server managed mode (seat tokens, internal API, result callbacks).
- To confirm with Paystack: USD card acceptance on the Kenya merchant account, gaming approval, Transfers enabled.

## API map (platform)
- Auth: `POST /auth/magic-link`, `/auth/magic-link/verify`, `/auth/google`, `/auth/refresh`, `/auth/logout`, `/auth/logout-all`
- Me: `GET/PATCH /me`, `POST /me/accept-terms`
- Wallet: `GET /wallet`, `/wallet/history`, `/wallet/deposits/quote`, `POST /wallet/deposits`, `GET /wallet/deposits/{ref}`, `POST /wallet/transfers`
- Webhook: `POST /webhooks/paystack`
- Admin: `GET /admin/settings`, `PUT /admin/settings/{key}`, `PUT /admin/users/{id}/kyc-tier`
- Interactive docs: http://localhost:8000/docs

## Trying payments locally
1. Put Paystack **test** keys in `platform/.env` (`PLATFORM_PAYSTACK_SECRET_KEY`, `PLATFORM_PAYSTACK_PUBLIC_KEY`).
2. Make yourself admin: `docker compose exec postgres psql -U platform -c "update users set is_admin=true, kyc_tier=1 where email='you@example.com'"`.
3. Turn on real money: `PUT /admin/settings/real_money_enabled {"value": true}`.
4. Expose the webhook: `cloudflared tunnel --url http://localhost:8000` and set the Paystack test webhook URL to `<tunnel>/webhooks/paystack`.

## How to run
- `cd platform && docker compose up --build` → `curl localhost:8000/readyz`.
- Host ports are moved off the defaults because this machine already runs Postgres/Redis/Mailpit (and another project uses 55432):
  Postgres 55433, Redis 56379, Mailpit UI 58025, SMTP 51025, API 8000. Override with `PG_PORT`, `REDIS_PORT`, etc.
- Tests: `cd platform && . .venv/bin/activate && PLATFORM_TEST_SERVICES=1 pytest` (needs the compose Postgres + Redis; uses a separate `platform_test` DB). Without services, DB tests are skipped.
- Lint/types: `ruff check . && ruff format --check . && mypy app`.
- Worker/beat run in compose; trigger a job by hand: `docker compose exec worker celery -A app.worker call app.worker.expire_stale_deposits`.

## Where things are
- Plan: `docs/platform/PRODUCTION_PLAN.md`
- Architecture: `docs/platform/ARCHITECTURE.md`
- Tasks: `TASKLIST.md`
- Decisions and open questions: `DECISIONS.md`
- Paystack reference implementation: `/home/rock/Desktop/2026_Projects/my/dafeapp/subscriptions/paystack.py` and `views.py` (Django). Known gaps are listed in D-006.

## Open questions waiting on the owner
See DECISIONS.md → Open items (wallet currency, rake model, KYC provider, `platform/` licence, branding).

## Gotchas
- This repo is a fork of PokerTH (AGPL-3.0). Changes to the game server must be published to network users.
- Keep `pokerth.proto` changes backward compatible (optional fields only).
- Real money stays off (`real_money_enabled=false`) until the BCLB licence and Paystack approval are confirmed.
- The repo is large (~750 MB, mostly `.git`). Don't add build output; `.gitignore` covers `build*/`.
