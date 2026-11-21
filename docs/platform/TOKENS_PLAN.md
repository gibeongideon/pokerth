# Plan: tokens (1 USD = 129 tokens)

**Status:** not doing (2026-11-21). The owner chose to keep standard cents; small games use cent stake levels instead (D-033). Kept for reference.

## What the owner wants
Money inside Draely shown and played as **tokens**: 1 USD = 129 tokens. Stakes can then be much smaller
than $1 (e.g. a 20-token table ≈ $0.16), which suits M-Pesa players.

## The problem with "just displaying" tokens
Today every amount is stored as **US cents** (whole numbers). One token is 1/129 USD = **0.775 cents**, smaller
than a cent. A 20-token stake would be 15.5 cents: it can't be stored exactly. Showing tokens on top of cents
would round, and rounded money in a real-money ledger leaks or creates cents over time. So tokens must
become the **unit the ledger counts in**.

## Recommendation
1. **The ledger counts tokens** (whole tokens) instead of cents. Every balance, entry, stake, fee, prize and limit
   is an integer number of tokens. The double-entry rules, idempotency and locks stay exactly as they are.
2. **Conversion happens only at the edges**, at the configured rate (`fx.tokens_per_usd = 129`):
   - Deposit: M-Pesa KES → tokens (1 KES ≈ 1 token at today's rate; card USD → USD × 129).
   - Withdrawal: tokens → KES for M-Pesa.
   Rounding at the edges is always in the house's disfavour by at most 1 token (as today with cents).
3. **Display:** "1,290 tokens" with the USD/KES value next to it where useful ("≈ $10.00").
   Play money also in tokens (start 12,900 tokens = $100).
4. **Stakes in tokens:** stake levels and fees are set in tokens; the smallest sensible stake ~10 tokens.
   One-price display (fee included) stays.
5. **Migration (staging only has test data):** multiply every stored amount by 1.29 and round per account,
   then re-check the ledger integrity job (every transaction sums to zero, balances match entries). Before real
   players exist this is a one-time, safe conversion.

## What changes
- Platform: ledger units, payments/payouts conversion, stake levels/fees, limits (deposit/withdraw/RG/P2P),
  settings with `_usd_cents` names → `_tokens`, admin reports, play money.
- App: every money display (`usd()` → `tokens()`), wallet quick amounts, stake cards, receipts.
- Tests: amounts throughout.
- Estimated effort: 1–2 focused sessions; real-money flows retested end to end (deposit, play, settle, withdraw).

## Questions for the owner
1. Is the token rate fixed at 129 forever, or does it follow the KES rate setting? (Recommendation: a setting,
   changed rarely, and existing balances are never revalued.)
2. Should players still see dollars anywhere (e.g. "≈ $10") or only tokens and KES?
3. Name on screen: "tokens", or a brand name (e.g. "Draely chips")?
