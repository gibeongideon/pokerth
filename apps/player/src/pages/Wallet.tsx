import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Chip, Empty, Spinner } from "../components/bits";
import { useToast } from "../components/Toast";
import { api, call, errorMessage } from "../lib/api";
import { kes, kesFromSubunits, usd, when } from "../lib/format";
import { useMe, useWallet } from "../lib/hooks";
import { play } from "../lib/sound";
import type { Deposit, HistoryItem, Withdrawal } from "../lib/types";

const PRESETS = [500, 1_000, 2_000, 5_000, 10_000];
const KIND: Record<string, { icon: string; label: string }> = {
  deposit: { icon: "⬇️", label: "Deposit" },
  buy_in: { icon: "🎟️", label: "Table entry" },
  prize: { icon: "🏆", label: "Prize" },
  refund: { icon: "↩️", label: "Refund" },
  withdrawal: { icon: "⬆️", label: "Withdrawal" },
  p2p_transfer: { icon: "🤝", label: "Transfer" },
  bonus: { icon: "🎁", label: "Bonus" },
  adjustment: { icon: "✨", label: "Adjustment" },
};

function usePollDeposit(reference: string | null, onDone: (d: Deposit) => void) {
  useEffect(() => {
    if (!reference) return;
    let stop = false;
    const tick = async () => {
      try {
        const d = await call<Deposit>(api.GET("/wallet/deposits/{reference}", { params: { path: { reference } } }));
        if (d.status !== "pending") {
          onDone(d);
          return;
        }
      } catch {
        /* keep polling */
      }
      if (!stop) setTimeout(tick, 3000);
    };
    const id = setTimeout(tick, 3000);
    return () => {
      stop = true;
      clearTimeout(id);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reference]);
}

function DepositForm() {
  const me = useMe();
  const toast = useToast();
  const qc = useQueryClient();
  const [channel, setChannel] = useState<"mpesa" | "card">("mpesa");
  const [cents, setCents] = useState(2_000);
  const [phone, setPhone] = useState("");
  const [forFriend, setForFriend] = useState(false);
  const [recipient, setRecipient] = useState("");
  const [waiting, setWaiting] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => setPhone(me.data?.phone ?? ""), [me.data?.phone]);

  const quote = useQuery({
    queryKey: ["quote", channel, cents],
    queryFn: () =>
      call<{ charge_currency: string; charge_amount: number }>(
        api.GET("/wallet/deposits/quote", { params: { query: { channel, amount_usd_cents: cents } } }),
      ),
    enabled: cents > 0,
    retry: false,
  });

  usePollDeposit(waiting, async (d) => {
    setWaiting(null);
    if (d.status === "success") {
      play("win");
      toast(`${usd(d.credit_usd_cents)} added`, "ok");
    } else toast(`Payment ${d.status}. Nothing was charged.`, "error");
    await qc.invalidateQueries({ queryKey: ["wallet"] });
  });

  const pay = async () => {
    setBusy(true);
    try {
      const r = await call<{ deposit: Deposit; next: { type: string; authorization_url?: string; display_text?: string } }>(
        api.POST("/wallet/deposits", {
          body: { channel, amount_usd_cents: cents, phone: channel === "mpesa" ? phone : null, recipient: forFriend ? recipient : null },
        }),
      );
      if (r.next.type === "redirect" && r.next.authorization_url) {
        window.location.href = r.next.authorization_url;
        return;
      }
      play("chip");
      setWaiting(r.deposit.reference);
    } catch (e) {
      toast(errorMessage(e), "error");
    } finally {
      setBusy(false);
    }
  };

  if (waiting) {
    return (
      <div className="flex flex-col items-center gap-4 py-8 text-center">
        <div className="relative">
          <span className="absolute inset-0 animate-ping rounded-full bg-chip-green/30" />
          <span className="relative block text-6xl">📱</span>
        </div>
        <div className="title text-2xl">Check your phone</div>
        <p className="max-w-xs text-cream/70">Enter your M-Pesa PIN on the prompt we just sent to {phone}.</p>
        <span className="h-7 w-7 animate-spin rounded-full border-4 border-gold-400/20 border-t-gold-400" />
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 gap-2 rounded-2xl bg-felt-950/60 p-1.5">
        {(["mpesa", "card"] as const).map((c) => (
          <button
            key={c}
            className={`rounded-xl py-2.5 font-display text-lg tracking-wide transition ${
              channel === c ? "bg-gold-400 text-felt-950 shadow" : "text-cream/70"
            }`}
            onClick={() => setChannel(c)}
          >
            {c === "mpesa" ? "M-Pesa" : "Card"}
          </button>
        ))}
      </div>
      <div>
        <div className="label">Amount</div>
        <div className="flex flex-wrap gap-2">
          {PRESETS.map((p) => (
            <button
              key={p}
              onClick={() => setCents(p)}
              className={`rounded-full border-2 px-4 py-1.5 font-display text-lg transition ${
                cents === p ? "border-gold-400 bg-gold-400/15 text-gold-300" : "border-cream/15 text-cream/80"
              }`}
            >
              {usd(p).replace(".00", "")}
            </button>
          ))}
          <input
            className="input w-28"
            type="number"
            min={1}
            aria-label="Custom amount in dollars"
            placeholder="Other $"
            onChange={(e) => setCents(Math.round(Number(e.target.value) * 100))}
          />
        </div>
      </div>
      {channel === "mpesa" && (
        <div>
          <label className="label" htmlFor="phone">
            M-Pesa number
          </label>
          <input id="phone" className="input" inputMode="tel" placeholder="0712 345 678" value={phone} onChange={(e) => setPhone(e.target.value)} />
        </div>
      )}
      <label className="flex items-center gap-3 text-sm">
        <input type="checkbox" className="h-5 w-5 accent-gold-400" checked={forFriend} onChange={(e) => setForFriend(e.target.checked)} />
        Fund a friend's wallet instead
      </label>
      {forFriend && <input className="input" placeholder="Their username or email" value={recipient} onChange={(e) => setRecipient(e.target.value)} />}
      <div className="flex items-center justify-between rounded-xl bg-felt-950/60 px-4 py-3">
        <span className="text-cream/70">You pay</span>
        <span className="font-display text-xl text-gold-300">
          {quote.data
            ? quote.data.charge_currency === "KES"
              ? kesFromSubunits(quote.data.charge_amount)
              : usd(quote.data.charge_amount)
            : quote.error
              ? "—"
              : "…"}
        </span>
      </div>
      {quote.error && <p className="text-sm text-[#ff9a9d]">{errorMessage(quote.error)}</p>}
      <button className="btn-gold w-full py-3 text-xl" disabled={busy || !quote.data} onClick={pay}>
        Add {usd(cents)}
      </button>
    </div>
  );
}

function WithdrawForm() {
  const me = useMe();
  const toast = useToast();
  const qc = useQueryClient();
  const [cents, setCents] = useState(1_000);
  const [pending, setPending] = useState<Withdrawal | null>(null);
  const [code, setCode] = useState("");
  const dests = useQuery({
    queryKey: ["destinations"],
    queryFn: () => call<{ id: string; phone: string }[]>(api.GET("/wallet/payout-destinations")),
  });
  const quote = useQuery({
    queryKey: ["wquote", cents],
    queryFn: () =>
      call<{ fee_usd_cents: number; payout_amount: number }>(
        api.GET("/wallet/withdrawals/quote", { params: { query: { amount_usd_cents: cents } } }),
      ),
    enabled: cents > 0,
    retry: false,
  });

  const start = async () => {
    try {
      let dest = dests.data?.[0];
      if (!dest) {
        if (!me.data?.phone) return toast("Add your M-Pesa number in Profile first.", "info");
        dest = await call<{ id: string; phone: string }>(api.POST("/wallet/payout-destinations", { body: { phone: me.data.phone } }));
        await qc.invalidateQueries({ queryKey: ["destinations"] });
      }
      const w = await call<Withdrawal>(api.POST("/wallet/withdrawals", { body: { destination_id: dest.id, amount_usd_cents: cents } }));
      setPending(w.status === "awaiting_confirmation" ? w : null);
      if (w.status !== "awaiting_confirmation") toast(`Withdrawal ${w.status.replace("_", " ")}`, "ok");
    } catch (e) {
      toast(errorMessage(e), "error");
    }
  };

  const confirm = async () => {
    if (!pending) return;
    try {
      const w = await call<Withdrawal>(
        api.POST("/wallet/withdrawals/{reference}/confirm", { params: { path: { reference: pending.reference } }, body: { code } }),
      );
      play("chip");
      setPending(null);
      setCode("");
      toast(w.status === "pending_review" ? "Sent for a quick review. We'll email you." : "On its way to your M-Pesa", "ok");
      await qc.invalidateQueries({ queryKey: ["wallet"] });
    } catch (e) {
      toast(errorMessage(e), "error");
    }
  };

  if (pending) {
    return (
      <div className="space-y-4 text-center">
        <div className="title text-2xl">Enter the 6-digit code</div>
        <p className="text-cream/70">We emailed it to {me.data?.email}.</p>
        <input
          className="input mx-auto max-w-[220px] text-center font-display text-3xl tracking-[0.5em]"
          inputMode="numeric"
          maxLength={6}
          value={code}
          onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
          aria-label="Six digit code"
        />
        <button className="btn-gold w-full" disabled={code.length !== 6} onClick={confirm}>
          Confirm withdrawal
        </button>
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <div>
        <label className="label" htmlFor="wamount">
          Amount ($)
        </label>
        <input
          id="wamount"
          className="input font-display text-2xl"
          type="number"
          min={1}
          value={cents / 100}
          onChange={(e) => setCents(Math.round(Number(e.target.value) * 100))}
        />
      </div>
      <div className="rounded-xl bg-felt-950/60 px-4 py-3 text-sm">
        <div className="flex justify-between">
          <span className="text-cream/70">To M-Pesa</span>
          <span>{dests.data?.[0]?.phone ?? me.data?.phone ?? "add your number in Profile"}</span>
        </div>
        <div className="mt-1 flex justify-between">
          <span className="text-cream/70">You receive</span>
          <span className="font-display text-xl text-gold-300">{quote.data ? kesFromSubunits(quote.data.payout_amount) : "—"}</span>
        </div>
        {quote.data && quote.data.fee_usd_cents > 0 && (
          <div className="mt-1 flex justify-between text-cream/60">
            <span>Fee</span>
            <span>{usd(quote.data.fee_usd_cents)}</span>
          </div>
        )}
      </div>
      {quote.error && <p className="text-sm text-[#ff9a9d]">{errorMessage(quote.error)}</p>}
      <button className="btn-gold w-full py-3 text-xl" disabled={!quote.data} onClick={start}>
        Withdraw {usd(cents)}
      </button>
    </div>
  );
}

function History() {
  const history = useQuery({ queryKey: ["history"], queryFn: () => call<HistoryItem[]>(api.GET("/wallet/history")) });
  if (history.isLoading) return <Spinner />;
  if (!history.data?.length) return <Empty title="No activity yet">Your deposits, games and prizes show up here.</Empty>;
  return (
    <ul className="divide-y divide-cream/5">
      {history.data.map((h) => {
        const k = KIND[h.kind] ?? { icon: "•", label: h.kind };
        return (
          <li key={`${h.transaction_id}-${h.amount_usd_cents}`} className="flex items-center gap-3 py-3">
            <span className="text-xl">{k.icon}</span>
            <div className="min-w-0 flex-1">
              <div className="font-semibold">{k.label}</div>
              <div className="truncate text-xs text-cream/50">
                {h.memo ? `${h.memo} · ` : ""}
                {when(h.at)}
              </div>
            </div>
            <span className={`font-display text-lg ${h.amount_usd_cents > 0 ? "text-chip-green" : "text-cream/80"}`}>
              {h.amount_usd_cents > 0 ? "+" : ""}
              {usd(h.amount_usd_cents)}
            </span>
          </li>
        );
      })}
    </ul>
  );
}

export function WalletPage() {
  const wallet = useWallet();
  const [tab, setTab] = useState<"deposit" | "withdraw" | "history">("deposit");
  return (
    <div className="mx-auto max-w-xl space-y-5">
      <div className="panel relative overflow-hidden p-6 text-center">
        <div className="absolute -left-6 -top-6 opacity-30">
          <Chip color="#e2a72e" size={110} />
        </div>
        <div className="text-xs uppercase tracking-[0.3em] text-cream/55">Balance</div>
        <div className="title gold-text mt-1 text-6xl">{wallet.data ? usd(wallet.data.available_usd_cents) : "—"}</div>
        {wallet.data && <div className="mt-1 text-cream/60">≈ {kes(wallet.data.kes_reference)}</div>}
        {wallet.data && !wallet.data.real_money_enabled && (
          <div className="badge mt-3 bg-gold-400/15 text-gold-300">Real-money play opens soon</div>
        )}
      </div>
      <div className="grid grid-cols-3 gap-2">
        {(["deposit", "withdraw", "history"] as const).map((t) => (
          <button
            key={t}
            className={`rounded-xl py-2.5 font-display text-lg capitalize tracking-wide transition ${
              tab === t ? "bg-felt-600 text-cream shadow-glow" : "bg-felt-900/70 text-cream/60"
            }`}
            onClick={() => setTab(t)}
          >
            {t}
          </button>
        ))}
      </div>
      <div className="panel p-5">
        {tab === "deposit" && <DepositForm />}
        {tab === "withdraw" && <WithdrawForm />}
        {tab === "history" && <History />}
      </div>
    </div>
  );
}

/** Paystack sends card payers back here with ?reference=. */
export function DepositReturn() {
  const [params] = useSearchParams();
  const reference = params.get("reference") ?? params.get("trxref");
  const [result, setResult] = useState<Deposit | null>(null);
  const qc = useQueryClient();
  usePollDeposit(reference, (d) => {
    setResult(d);
    if (d.status === "success") play("win");
    void qc.invalidateQueries({ queryKey: ["wallet"] });
  });
  return (
    <div className="mx-auto max-w-sm py-10 text-center">
      {!result ? (
        <>
          <span className="mx-auto block h-10 w-10 animate-spin rounded-full border-4 border-gold-400/20 border-t-gold-400" />
          <div className="title mt-4 text-2xl">Confirming your payment…</div>
        </>
      ) : result.status === "success" ? (
        <div className="animate-pop">
          <div className="text-6xl">🎉</div>
          <div className="title gold-text mt-3 text-4xl">+{usd(result.credit_usd_cents)}</div>
          <p className="mt-2 text-cream/70">Added to your wallet.</p>
        </div>
      ) : (
        <div>
          <div className="title text-2xl">Payment {result.status}</div>
          <p className="mt-2 text-cream/70">Nothing was added. You can try again.</p>
        </div>
      )}
    </div>
  );
}
