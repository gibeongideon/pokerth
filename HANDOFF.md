# HANDOFF

Read this first when resuming. Update it at the end of every session.

## Current state (2026-11-20)
- Branches: `stable` → `prod` → `dev`, all at commit `52c05c31`. **`dev` is checked out.** Nothing pushed to `origin`.
- Phase 0 in progress. Done: branches, production plan, tracking docs.
- Next: scaffold `platform/` (FastAPI skeleton, Alembic, docker-compose with Postgres + Redis, pytest).

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
