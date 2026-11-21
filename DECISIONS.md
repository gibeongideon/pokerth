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

### D-019 · 2026-11-20 · Accepted — Sit & Go rules as built (Phase 2a)
- **Price = buy-in + entry fee (+ excise if set)**, shown once ("$100.00 + $0.50"). Buy-ins sit in a per-table escrow account; fees go to `house:fees` at join time; prizes are paid from escrow by place. Rounding leftovers go to 1st place. With fewer players than paid places, shares are scaled up.
- **Pull-out:** free and fully refunded (fee included) within `table.unregister_grace_seconds` (default 120 s) and only while the table is still open.
- **Ready check:** when a table fills, players have `table.ready_check_seconds` (default 60 s). No-shows are removed and refunded, or lose the fee if `table.no_show_policy=forfeit_fee`. The table re-opens for the rest; scheduled tables start with whoever is ready if that meets `min_players`, else cancel and refund.
- **Tables copy their stake level** when opened, so admin changes only affect new tables.
- **Free-play levels** (buy-in 0) work even with real money switched off.
- **Game server is a stand-in** (`LocalGateway`) until Phase 2b; results can be simulated on the local dev dashboard.

### D-020 · 2026-11-20 · Accepted — Gamey visual style; order of work
- The player app (Phase 3) gets a **gamey** look: felt table, chip stacks, glowing call-to-action buttons, motion and sound, not a plain dashboard style. Design tokens go in `packages/ui` so web and mobile match.
- Order agreed with the owner: finish the non-UI task list first (Phase 4 withdrawals/admin, Phase 5 social/tournaments back end), then Phase 3 UI, then Phase 2b (C++ game server) after the app exists.

### D-021 · 2026-11-20 · Accepted — Withdrawal rules as built (Phase 4)
- M-Pesa only for now; the payout number must equal the phone on the player's profile.
- The player confirms with a 6-digit code emailed to them (10 min, 5 tries). Money moves from the wallet to `payouts:pending` only on confirmation.
- Automatic approval up to `withdraw.auto_approve_max_usd_cents` ($200); above that, or within `withdraw.deposit_review_hours` (24 h) of a deposit, an admin reviews. KYC tier 2 above $500.
- Conversion uses the same rate (129) minus the optional spread, rounded down to whole shillings. Fees default to 0.
- Transfer sends are retried by the worker; before a retry the worker asks Paystack whether the transfer already exists (reference = withdrawal reference), so nobody is paid twice.

### D-022 · 2026-11-20 · Accepted — Friends and invites as built (Phase 5.1-5.5)
- Invites go by username or email, to friends or anyone (setting `invites.friends_only` restricts usernames to friends). Each handle is reported invited or skipped with a reason.
- Only someone seated at the table, or its organizer, can invite. Accepting an invite is a normal join: same buy-in, gates and limits. Accepting a private-table invite doesn't need the code.
- Organized games are private tables with a title and message; the organizer may or may not play, can start at a set time or when full, sees an RSVP list, and can cancel before start (full refunds, pending invites revoked).
- Unknown emails get a sign-up invite; the invite appears when they sign in with that email. Friend requests to unknown emails answer "sent" so emails can't be probed.
- Limits: 50 invites per player per day, 30 per table, 72 h expiry; invites also close when the table starts or is cancelled.

### D-023 · 2026-11-20 · Accepted — Responsible gaming and tournaments as built (Phase 5)
- **Limits** are player-set deposit and loss limits over rolling 24 h / 7 d / 30 d. Tighter applies at once; looser or removed applies after `rg.limit_increase_delay_hours` (24 h). Loss = buy-ins minus refunds and prizes in the window; joining checks that the full price could still fit.
- **Self-exclusion** (24h, 7d, 30d, 6m, permanent) can only be extended. It blocks deposits, transfers and paid play, refunds open seats at once, and still allows sign-in and withdrawals. Ready-check seats of an excluded player become no-shows.
- **Referral bonuses** and **guaranteed prize top-ups** are paid from `house:promotions`, so marketing spend is visible in one account.
- **Tournaments** for now are scheduled single tables (2-10 players) with a registration window and optional guarantee. Late registration, re-entry and multi-table events wait for the game server work.

### D-024 · 2026-11-20 · Accepted — Player app as built (Phase 3 web)
- One codebase for web and phones (D-011): Vite + React 18 + TypeScript + Tailwind, react-router, TanStack Query; PixiJS 8 draws the table. npm workspaces (pnpm is broken on this machine).
- The app talks to the API under `/api` on its own origin (Vite proxy locally, Caddy in production), so httpOnly cookies work; the API's `PLATFORM_COOKIE_PATH_PREFIX=/api` scopes the refresh cookie. Native apps will use bearer tokens through the same client.
- Gamey look: felt greens, gold, chunky "candy" buttons, chip motifs, Lilita One display font (bundled, no CDN), synthesized sounds with a mute toggle, reduced-motion respected.
- Mail outages no longer break requests: invite emails are best-effort (the in-app invite is saved); sign-in links and withdrawal codes answer 503 `email_unavailable`.
- Local-dev-only helpers (`/dev-login/:name`, demo buttons) are compiled out of production builds.

### D-025 · 2026-11-20 · Accepted — Game server creates platform games from the seat token (supersedes the internal-API part of D-009)
The seat token already carries signed table settings (`cfg`: players, chips, small blind, blind minutes, title). The game server creates the game when the first seat-holder logs in, seats each player automatically, and starts when everyone is in (or after a start timeout with those present). So the platform never calls the game server; the only server-to-platform traffic is the signed result POST. Fewer moving parts: no inbound internal port on game servers, no placement API.
- Platform mode is set by environment (`POKERTH_PLATFORM_MODE=1`, public key, platform URL, shared secret); the public lobby's create/join is refused in that mode.
- Packet limit raised from 384 to 1024 bytes (a login with a token is ~560 bytes); older clients are unaffected.
- Result: finishing order (winner first). Players the server never saw are appended last by the platform (a no-show forfeits the seat).

### D-026 · 2026-11-21 · Accepted — Browser/phone client protocol layer
- `packages/protocol` holds everything game-protocol related for the player app (web and Capacitor share it): TypeScript generated from `pokerth.proto` with `@bufbuild/protobuf` + `protoc-gen-es` (committed under `src/gen`, CI checks it is current), a `GameClient` (WebSocket, one PokerTHMessage per binary frame, no length-prefix subprotocol), and a pure `reduce(state, message)` that turns server messages into `TableState`. UI code renders `TableState` only; the server stays the authority on every rule, `legalActions()` just limits what the buttons offer.
- The client identifies as client type 3 (web), build 0.1.0, logs in with `unauthenticatedLogin` + `platformToken`, acknowledges `StartEvent` and answers timeout warnings.
- Bet amounts on the wire are the chips added by this action (`myRelativeBet`); the UI works in "raise to" totals and converts.
- Platform mode turns the WebSocket listener (port 7233) on without a config file. `POKERTH_WS_ORIGIN=play.example.com` limits browser origins; the check now accepts `https://` as well as `http://`. TLS is terminated by the ingress/Caddy in front (WSS).

### D-027 · 2026-11-21 · Accepted — Rejoin by seat token
- In platform mode a valid seat token for a table whose game is running, from a player who still holds a seat there (seat not released, not kicked, chips left), is treated as that seat's previous session id. The game server's existing rejoin path does the rest: rejoin offer in `InitAck`, the client sends `RejoinExistingGame`, acknowledges the start event, and is dealt in from the next hand (`GameStartRejoin` + player-id change). The token is bound to the table and the player, so it can't be used to take someone else's seat.
- Opening the table in a second tab/device takes the seat over; the first one shows "Your seat was opened somewhere else" and does not auto-retry (no ping-pong). It can take the seat back with Reconnect.
- Client: network drops and session timeouts retry automatically (1, 2, 4, 8, 15, 30 s; reset when seated again), and immediately on `online` and when the tab/app becomes visible (Capacitor resume). A 4xx from the seat-token endpoint (game over, no seat) is not retried.

### D-028 · 2026-11-21 · Accepted — Invites that sign people up
- Every player has one invite code (the referral code). `/i/<code>` is a public landing page ("alice wants you at the table") with an email box: it sends a magic link carrying the code and a return path. No account is created until the link is used.
- Invites by email are stored per (inviter, email) in `player_invites`, so they follow the address: when it signs up - through any link or none - the first inviter gets the referral, every inviter of that address becomes a friend (`referral.auto_friend`, on by default), and the inviter's list shows "Joined". Emails that already have an account get a friend request instead. Re-sending to the same address is limited to once a day; total sends count against `invites.per_day`.
- Table links carry `?ref=<inviter code>` (and fall back to the organizer's code), so a newcomer who signs up from a shared table link is credited too and is returned to the table after the welcome step.
- Magic links carry `next` (a same-site path; `//host` and schemes are refused server- and client-side), so the flow works when the email is opened on another device.

### D-029 · 2026-11-21 · Accepted — Phone app: same web app in Capacitor, code sign-in
- The Android app is the player app built in "app" mode (`npm run build:app`, `VITE_API_BASE_URL`, `VITE_PUBLIC_URL`) inside Capacitor 7. One codebase; `src/lib/native.ts` holds the differences.
- Sessions in the app use bearer tokens (`client: "app"`): access token in memory, refresh token on the device; refreshes are single-flight because refresh tokens rotate and a duplicate would trigger reuse detection.
- Sign-in in the app: the sign-in email now also carries a 6-digit code (keyed hash, expires with the link, 5 wrong tries burn it). Typing it works without deep links, on any device. Links still open the app when App Links are verified (`assetlinks.json` on the site's domain).
- Shared links always use the public site URL, never the app's own origin.
- appId `app.feltkings.player` follows the working brand; it cannot change after the first Play upload (decide O-5 first).

### D-030 · 2026-11-21 · Accepted — Name "Draely" (UI only)
The product shows the name **Draely** (from Braela + Darius) everywhere users see it: app, emails, page titles, Android label. Code identifiers stay (`feltkings` image/compose names, `app.feltkings.player` app id, storage keys). Closes the naming part of O-5.

### D-031 · 2026-11-21 · Accepted — Staging deploy: one server, Docker Compose, GitHub Actions
- `dev` → staging at https://draely.dafeapp.com (209.38.120.140); `prod` → a separate production server later. One workflow (`deploy.yml`), GitHub Environments per target.
- Stack: Caddy (TLS, web app, `/api` → API, `/ws` → game server, `/mail` → Mailpit on staging), API, Celery worker + beat, game server, Postgres, Redis. Images in GHCR, tagged with the commit.
- Secrets are generated on the server (`deploy/bootstrap-server.sh`) and never stored in git or GitHub; GitHub only holds the SSH deploy key.
- Kubernetes (PRODUCTION_PLAN) stays the long-term target; this is the D-018 VPS step.

### D-032 · 2026-11-21 · Accepted — Free play: tables for anyone, practice vs computer, demo money
- Players create **free** tables, public (listed under Open tables) or invite only, as many as they like. Paid stakes run one system table at a time via Quick play (`tables.user_created_paid` off); the public list shows only tables still taking players.
- **Practice vs computer**: a free table that starts at once; the game server fills the other seats with its computer players (seat-token `cfg.bots`).
- **Demo money** (dollars, never real money): $100 to start, a free seat costs $5, winners share the demo pot; beating the computer pays the computer players' entries. When it runs out, refill to $100 once per 24h. All amounts are settings (`play.*`). Separate ledger accounts (`user:*:play`, `table:*:play`, `house:play_bank`); no deposit, withdrawal, transfer or real-money report touches them.

---

## Open items (to decide)
- **O-8 VPS provider and region** — parked by the owner (2026-11-20); decide before Phase 6. Latency to Kenyan players matters.
- **O-4 Licence of `platform/`.** The game server is AGPL-3.0 (modified source must be offered to network users). `platform/` only talks to it over HTTP; decide whether to keep `platform/` in this repo or a separate private repo.
- **O-5 Branding.** New name and original art; confirm licences of any assets reused from `data/gfx`.
