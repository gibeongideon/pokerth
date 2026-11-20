# HANDOFF

Read this first when resuming. Update it at the end of every session.

## Current state (2026-11-20)
- Branches: `stable` → `prod` → `dev`, all at commit `52c05c31`. **`dev` is checked out.** Nothing pushed to `origin`.
- Phase 0 done. Done: branches, production plan, tracking docs, `platform/` skeleton.
- Client design changed to one mobile-portable player app + Capacitor (D-011).
- Owner decided (2026-11-20): USD wallet with KES reference (D-012), entry fee shown once like "$100 + $0.50" (D-013), tiered KYC with Smile ID (D-014).
- Deployment path (D-015): local Docker Compose until MVP, then one VPS deployed by GitHub Actions on push to `prod`; Kubernetes after launch.
- Phase 0 complete (CI added: `.github/workflows/platform-ci.yml`; runs on push/PR to `dev`/`prod` touching `platform/`; not yet run on GitHub because nothing is pushed). Stake levels are admin-configurable (D-016); USD/KES fixed at 129, configurable (D-017). VPS provider parked (O-8).
- To confirm with Paystack: USD card acceptance on the Kenya merchant account, gaming approval, Transfers enabled.
- Next: Phase 1 — users + magic-link/Google auth, config registry, ledger, Paystack deposits.

## How to run
- `cd platform && docker compose up --build` → `curl localhost:8000/readyz`.
- Host ports are moved off the defaults because this machine already runs Postgres/Redis/Mailpit (and another project uses 55432):
  Postgres 55433, Redis 56379, Mailpit UI 58025, SMTP 51025, API 8000. Override with `PG_PORT`, `REDIS_PORT`, etc.
- Tests without Docker: `cd platform && . .venv/bin/activate && pytest && ruff check . && mypy app`.

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
