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

## Phase 2b — Game server managed mode (C++) (done 2026-11-20)
- [x] Server-only build: `POKERTH_SERVER_ONLY` CMake option + `docker/server/Dockerfile.build` (Ubuntu 25.10, Qt 6.9, Boost 1.88); builds on this machine with `-j2`
- [x] Proto: optional `platformToken` in `InitMessage` (backward compatible)
- [x] Game server: Ed25519 seat-token verification (OpenSSL) + claims (Boost.JSON); in platform mode the token is the only login
- [x] Game created by the server from the token's signed table settings on first arrival; players seated automatically; lobby create/join refused (D-025, replaces the internal HTTP API)
- [x] Auto-start when every seated player is in; start with those present after `POKERTH_PLATFORM_START_TIMEOUT_SEC`; no admin timeout for platform games
- [x] Result callback: finishing order POSTed to `/internal/games/{table_id}/result` (HMAC), retried with backoff; platform places no-shows last
- [x] RNG: refuses to deal if OpenSSL `RAND_bytes` fails in platform mode
- [x] `--foreground` option for containers; packet limit 384 → 1024 bytes so logins can carry a seat token
- [x] Bot: `--platform-tokens` (one bot per seat token)
- [x] End-to-end verified: 3 bots played a real game on the C++ server, result reported and paid out correctly (`platform/scripts/e2e_game_server.sh`)
- [ ] Runtime Docker image for the server (multi-stage, slim) for deployment
- [ ] Hand history persistence (for disputes and RNG certification)
- [x] WebSocket on automatically in platform mode; `POKERTH_WS_ORIGIN` restricts browser origins (http and https)
- [x] Reconnect/rejoin (done 2026-11-21, D-027): in platform mode the seat token itself unlocks the player's seat in their table's running game (no previous session id needed), so a page reload, a new device or a dropped network gets the seat back; dealt in again from the next hand. Client retries with backoff and at once on `online` / app resume. Verified in Chrome: reload mid-game and a cut connection (TCP relay) both returned alice to her seat and the game settled
- [ ] Rejoin is refused after the seat is released (offline longer than the server's grace period, ~5 min); consider a platform-mode setting for it

## Phase 3 — Player app (web + mobile) and site
- [x] Fixed: root `.gitignore` rule `lib/` (C++) hid `apps/player/src/lib/` — those files are now committed
- [x] npm workspace (pnpm is broken on this machine); `packages/api-client` typed from the OpenAPI schema (`npm run api:types`)
- [x] `apps/player/` Vite + React + TS + Tailwind, gamey look (D-020): sign-in (magic link), welcome (username + 18+/terms), lobby, quick play, private tables, table room, wallet (M-Pesa/card deposit, fund a friend, withdraw with code, history), friends + invites inbox, organize a game, invite-link page, profile (phone, referral link, limits, reality check, take a break) — mobile-first with bottom tabs, side rail on desktop
- [x] PixiJS table: seats around the felt (you at the bottom), ready glow, chip stacks, pot, medals + prizes, demo deal while running; fits portrait and landscape
- [x] Sounds (synthesized, mute toggle), reality-check reminder, toasts
- [x] Screenshots: `docs/platform/screenshots/phase3/` (desktop + phone)
- [x] Live hands over the game-server protocol: `packages/protocol` (generated from `pokerth.proto` with protoc-gen-es, `GameClient` over WebSocket with the seat token, pure `TableState` reducer + `legalActions`, 9 tests) (done 2026-11-21, D-026)
- [x] Table controls for live play: fold / check / call / bet-raise with slider and Min · ½ Pot · Pot · Max, all-in, turn countdown, hand log; PixiJS live view (real cards, board, bets, stacks, dealer button, turn ring); sounds
- [x] Verified end to end: alice played a full game in Chrome (desktop + phone size) against two C++ bots; the table settled (`docs/platform/screenshots/live/`). `WEB_CLIENTS=2 platform/scripts/e2e_game_server.sh` plays seats through the TS client headless
- [x] Error boundaries around the table view and betting controls (a render bug can't drop the game connection)
- [x] Table page lazy-loaded: main bundle 612 kB → 258 kB; table chunk 359 kB loads on demand
- [x] Visual redesign (2026-11-21): SVG icon set + crown-chip logo, glass panels, redesigned shell, lobby, sign-in, wallet, table canvas (lit felt, real card faces, striped chips), action bar timer (`docs/platform/screenshots/ui-v2/`)
- [ ] Google sign-in button (needs a Google OAuth client ID)
- [ ] PWA manifest + offline shell
- [x] Capacitor Android project (`apps/player/android`, Capacitor 7, appId `app.feltkings.player`): app-mode API base URL + public URL, bearer sessions with the refresh token on the device (single-flight refresh), sign-in with the 6-digit code from the email (D-029), deep links (App Links for `/i/`, `/join/`, `/auth/callback` + `feltkings://`), back button, status bar, splash, launcher icons generated from the logo (`scripts/gen_android_assets.py`), CORS for `https://localhost`, CI workflow `player-android.yml` (debug APK artifact) (2026-11-21)
- [ ] Build and run the APK locally — blocked: no JDK on this machine (`sudo apt install openjdk-21-jdk`, then `npm run android:debug` in apps/player); test on a real phone with `adb install`
- [ ] Secure token storage (Android Keystore / iOS Keychain) instead of Preferences
- [ ] Card deposits in the app: open Paystack in the in-app browser and return via deep link
- [ ] Push notifications (table filling, your turn, invites), native Google sign-in
- [ ] Release signing + AAB for Play; publish `/.well-known/assetlinks.json` (template `deploy/assetlinks.json.example`)
- [ ] Capacitor iOS build (after the licence is granted)
- [ ] `apps/site/` Next.js: landing, SEO, legal and responsible-gaming pages; admin back office UI
- [ ] Final name and visual identity ("Felt Kings" is a working title, O-5)

## Next up (owner requests, 2026-11-21)
- [ ] **Tokens:** 1 USD = 129 tokens (KES-pegged), so stakes can be smaller than $1. Plan written: `docs/platform/TOKENS_PLAN.md` - waiting for the owner's OK and answers to its 3 questions.
- [x] Hand rankings guide (`/hands`, public): linked from the table (?), lobby, profile and side menu
- [x] Easier navigation: "Back to game" banner anywhere in the app, live/waiting dot on My tables, errors with a one-tap fix (Add money, Refill, My tables, Finish setup)
- [ ] Phone check of the pinned betting bar and start-now prompt on a real device.

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
- [x] 5.1 Friends list: requests by username/email, accept/decline/remove
- [x] 5.2 Personal invites to a table (one or many friends), in-app inbox + email, accept = join, decline
- [x] 5.3 Organized games: organizer sets title/message/start time/plays-or-not, invites a group, RSVP list, organizer cancel with refunds
- [x] 5.4 Invite links: public preview by code, join after sign-in; email invites to people without an account
- [x] 5.5 Invite expiry + anti-spam limits (per day, per table) as settings
- [x] 5.6 Referrals: code + link per player, bonus after the new player's first paid game, both sides configurable, off by default, cap per referrer
- [x] 5.6b Quick invites (done 2026-11-21, D-028): personal link `/i/<code>` with a sign-up landing page (email → magic link); invite by email from the Friends page, tracked by email (whenever that address signs up, the inviter is credited and both become friends); table links `/join/<code>?ref=` sign newcomers up in place and bring them back to the table; magic links carry a same-site `next` (works on another device); `/?ref=` fixed; auto-friend setting `referral.auto_friend`. Verified in browsers (`docs/platform/screenshots/invites/`)
- [ ] SMS invites (Africa's Talking) for players without email at hand
- [x] 5.7a Scheduled tournaments: admin-scheduled tables with title, registration window, guaranteed prize pool (house tops up from promotions), payout tables per stake level
- [ ] 5.7b Late registration, re-entry, multi-table (>10 players) — need the game server (after Phase 2b)
- [x] 5.8 Responsible gaming: deposit and loss limits (day/week/month, tighten now, loosen after 24 h), self-exclusion (24h to permanent, auto-refund open seats), reality-check reminder setting

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
