# CLAUDE.md

This fork turns PokerTH into a web-first, real-money poker platform (Paystack card + M-Pesa, Kubernetes).

## Start every session by reading
1. `HANDOFF.md` — current state and next step
2. `TASKLIST.md` — phased checklist
3. `DECISIONS.md` — accepted decisions and open items
4. `docs/platform/PRODUCTION_PLAN.md` and `docs/platform/ARCHITECTURE.md`

## End every session by
- Ticking items in `TASKLIST.md`
- Adding any new decision to `DECISIONS.md`
- Rewriting the "Current state" section of `HANDOFF.md`

## Rules
- Work on `dev` (or feature branches off `dev`). Never commit directly to `prod` or `stable`. Don't push unless asked.
- Money: integer minor units, double-entry ledger, idempotency keys. No floats.
- `pokerth.proto`: optional fields only, stay backward compatible.
- Secrets only via environment variables; never commit `.env` files.
- Real money stays behind the `real_money_enabled` flag.
