# HANDOFF

Read this first when resuming. Update it at the end of every session.

## Current state (2026-11-20)
- Branches: `stable` → `prod` → `dev`. **`dev` is checked out.** Nothing pushed to `origin`.
- Phase 0 and Phase 1 done (Smile ID still manual). **Phase 2a done**: stake levels, fees, full Sit & Go lifecycle with a stand-in game server. **Phase 4 API done**: M-Pesa withdrawals with emailed code, review queue, admin users/reports.
- Agreed order (D-020): non-UI tasks first (Phase 5 done except 5.7b late reg / re-entry / multi-table, which need the game server). **Phase 3 web player app built** (`apps/player`, screenshots in `docs/platform/screenshots/phase3/`). **Phase 2b done**: the C++ server runs in platform mode and an end-to-end bot game settled correctly. Next: live play in the web app (protobuf over WebSocket + table controls), then Capacitor Android., then Phase 3 gamey UI, then Phase 2b C++.
- Screenshots of the dev dashboard: `docs/platform/screenshots/phase2-desktop.png`, `phase2-mobile.png`.
- Phase 2b (C++ game server) waits until after the app; locally blocked (no CMake/Boost/Qt6, ~1.5 GB free RAM).
- The owner prefers screenshots at the end of each phase over a server left running (machine is short on memory).
- To confirm with Paystack: USD card acceptance on the Kenya merchant account, gaming approval, Transfers enabled.

## API map (platform)
- Auth: `POST /auth/magic-link`, `/auth/magic-link/verify`, `/auth/google`, `/auth/refresh`, `/auth/logout`, `/auth/logout-all`
- Me: `GET/PATCH /me`, `POST /me/accept-terms`, `GET /me/referral`, `GET/PUT /me/limits`, `POST /me/self-exclude`, `PUT /me/reality-check`; sign-up takes optional `ref` (magic link and Google)
- Wallet: `GET /wallet`, `/wallet/history`, `/wallet/deposits/quote`, `POST /wallet/deposits`, `GET /wallet/deposits/{ref}`, `POST /wallet/transfers`
- Withdrawals: `GET/POST /wallet/payout-destinations`, `GET /wallet/withdrawals/quote`, `GET/POST /wallet/withdrawals`, `POST /wallet/withdrawals/{ref}/confirm|cancel`
- Friends & invites: `GET /friends`, `POST /friends/requests`, `POST /friends/requests/{id}/accept|decline`, `DELETE /friends/{user_id}`, `POST/GET /tables/{id}/invites`, `GET /invites`, `POST /invites/{id}/accept|decline`, `GET /invites/code/{code}` (public preview), `POST /games/organize`, `POST /tables/{id}/cancel` (organizer)
- Webhook: `POST /webhooks/paystack` (charge.success, transfer.success/failed/reversed)
- Lobby/tables: `GET /lobby/tiers`, `GET /lobby/tables`, `POST /lobby/quick-play`, `POST /tables/private`, `GET /tables/mine`, `GET /tables/{id}`, `POST /tables/{id}/join|leave|ready`, `GET /tables/{id}/seat-token`
- Internal (game server): `GET /internal/seat-token-key`, `POST /internal/games/{table_id}/result` (HMAC `X-Signature`)
- Admin: `GET /admin/settings`, `PUT /admin/settings/{key}`, `PUT /admin/users/{id}/kyc-tier`, `GET/POST /admin/stake-tiers`, `PUT /admin/stake-tiers/{id}`, `POST /admin/tables` (scheduled), `POST /admin/tables/{id}/cancel`, `GET /admin/withdrawals`, `POST /admin/withdrawals/{ref}/approve|reject`, `GET /admin/users`, `GET /admin/users/{id}`, `PUT /admin/users/{id}/status`, `GET /admin/reports/liabilities`
- Dev (PLATFORM_ENV=local only): `GET /dev/dashboard`, `/dev/state`, `POST /dev/token/{username}`, `/dev/tick`, `/dev/tables/{id}/simulate-result`
- Interactive docs: http://localhost:8000/docs

## Build and test the game server (C++)
- Builder image: `docker build -t poker-server-build -f docker/server/Dockerfile.build docker/server`
- Compile (incremental, ~3 min after header changes): `docker run --rm -v "$PWD":/src -v poker-server-build-cache:/build poker-server-build`
- End-to-end with bots: start Postgres/Redis + seeded API on :8000, then `platform/scripts/e2e_game_server.sh` (takes ~3-5 min)
- Run the server: `pokerth_dedicated_server --foreground` with `POKERTH_PLATFORM_MODE=1`, `POKERTH_SEAT_TOKEN_PUBLIC_KEY` (from `GET /internal/seat-token-key`), `POKERTH_PLATFORM_URL`, `POKERTH_PLATFORM_SECRET`. Logs: `~/.pokerth/log-files/server_messages.log`.

## Run the web player app locally
1. `cd platform && docker compose up -d postgres redis mailpit && . .venv/bin/activate && alembic upgrade head && python -m app.seed`
2. `PLATFORM_COOKIE_PATH_PREFIX=/api uvicorn app.main:app --port 8000`
3. In another terminal at the repo root: `npm install` (once) then `npm run dev` → http://localhost:5173
4. Sign in with the "Local demo" buttons, or open `/dev-login/alice?next=/` (dev builds only).
5. After API changes: re-export `packages/api-client/openapi.json` (see HANDOFF history) and `npm run api:types`.

## See it locally (light: API only, no Docker build)
1. `cd platform && docker compose up -d postgres redis`
2. `. .venv/bin/activate && alembic upgrade head && python -m app.seed` (demo players alice…grace with $500 each)
3. `uvicorn app.main:app --port 8000` → open http://localhost:8000/dev/dashboard
4. Stop: Ctrl-C, then `docker compose stop`

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
