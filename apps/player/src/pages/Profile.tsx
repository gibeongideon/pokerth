import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Avatar } from "../components/bits";
import { useToast } from "../components/Toast";
import { api, call, errorMessage, setToken } from "../lib/api";
import { usd, when } from "../lib/format";
import { useMe } from "../lib/hooks";
import { play } from "../lib/sound";

interface Limit {
  kind: "deposit" | "loss";
  period: "day" | "week" | "month";
  amount_cents: number | null;
  used_cents: number;
  pending_amount_cents: number | null;
  pending_effective_at: string | null;
}

function Limits() {
  const toast = useToast();
  const qc = useQueryClient();
  const data = useQuery({
    queryKey: ["limits"],
    queryFn: () => call<{ limits: Limit[] }>(api.GET("/me/limits")),
  });
  const save = async (l: Limit, value: string) => {
    const amount = value.trim() === "" ? null : Math.round(Number(value) * 100);
    try {
      await call(api.PUT("/me/limits", { body: { kind: l.kind, period: l.period, amount_cents: amount } }));
      await qc.invalidateQueries({ queryKey: ["limits"] });
      toast("Limit saved", "ok");
    } catch (e) {
      toast(errorMessage(e), "error");
    }
  };
  return (
    <div className="space-y-3">
      {(["deposit", "loss"] as const).map((kind) => (
        <div key={kind}>
          <div className="mb-1.5 font-semibold capitalize">{kind} limits</div>
          <div className="grid grid-cols-3 gap-2">
            {data.data?.limits
              .filter((l) => l.kind === kind)
              .map((l) => (
                <div key={l.period} className="rounded-xl bg-felt-950/60 p-2.5">
                  <div className="text-[11px] uppercase tracking-wider text-cream/50">per {l.period}</div>
                  <input
                    className="mt-1 w-full bg-transparent font-display text-lg outline-none placeholder:text-cream/30"
                    defaultValue={l.amount_cents != null ? l.amount_cents / 100 : ""}
                    placeholder="No limit"
                    inputMode="decimal"
                    aria-label={`${kind} limit per ${l.period} in dollars`}
                    onBlur={(e) => {
                      const was = l.amount_cents != null ? String(l.amount_cents / 100) : "";
                      if (e.target.value !== was) void save(l, e.target.value);
                    }}
                  />
                  <div className="text-[11px] text-cream/45">used {usd(l.used_cents)}</div>
                  {l.pending_effective_at && (
                    <div className="text-[11px] text-gold-300">
                      → {l.pending_amount_cents != null ? usd(l.pending_amount_cents) : "none"} from {when(l.pending_effective_at)}
                    </div>
                  )}
                </div>
              ))}
          </div>
        </div>
      ))}
      <p className="text-xs text-cream/45">Lowering a limit works right away. Raising or removing one takes 24 hours.</p>
    </div>
  );
}

export function Profile() {
  const me = useMe();
  const toast = useToast();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [phone, setPhone] = useState("");
  const referral = useQuery({
    queryKey: ["referral"],
    queryFn: () => call<{ link: string; enabled: boolean; bonus_usd_cents: number; signed_up: number; earned_usd_cents: number }>(api.GET("/me/referral")),
  });
  useEffect(() => setPhone(me.data?.phone ?? ""), [me.data?.phone]);
  if (!me.data) return null;
  const m = me.data;

  const savePhone = async () => {
    try {
      await call(api.PATCH("/me", { body: { phone } }));
      await qc.invalidateQueries({ queryKey: ["me"] });
      toast("Number saved", "ok");
    } catch (e) {
      toast(errorMessage(e), "error");
    }
  };
  const breakFor = async (period: "24h" | "7d" | "30d" | "6m" | "permanent") => {
    if (!confirm("Take a break from real-money play? This can't be undone early. You can still withdraw.")) return;
    try {
      await call(api.POST("/me/self-exclude", { body: { period, confirm: true } }));
      await qc.invalidateQueries();
      toast("Break started. Take care.", "ok");
    } catch (e) {
      toast(errorMessage(e), "error");
    }
  };
  const signOut = async () => {
    await fetch("/api/auth/logout", { method: "POST", credentials: "include" }).catch(() => undefined);
    setToken(null);
    qc.clear();
    navigate("/login");
  };

  return (
    <div className="mx-auto max-w-2xl space-y-5">
      <div className="panel flex items-center gap-4 p-5">
        <Avatar name={m.username ?? m.email} size={64} ring="#f5c451" />
        <div className="min-w-0">
          <div className="title text-3xl">{m.username}</div>
          <div className="truncate text-sm text-cream/60">{m.email}</div>
          <div className="mt-1 flex gap-2">
            <span className="badge bg-felt-600/60 text-cream/80">Verified level {m.kyc_tier}</span>
            {m.is_admin && <span className="badge bg-gold-400/20 text-gold-300">Admin</span>}
          </div>
        </div>
      </div>

      <div className="panel space-y-3 p-5">
        <div className="title text-xl">M-Pesa number</div>
        <div className="flex gap-2">
          <input className="input" inputMode="tel" placeholder="0712 345 678" value={phone} onChange={(e) => setPhone(e.target.value)} />
          <button className="btn-felt shrink-0" onClick={savePhone}>
            Save
          </button>
        </div>
        <p className="text-xs text-cream/45">Withdrawals only go to this number.</p>
      </div>

      {referral.data && (
        <div className="panel space-y-3 p-5">
          <div className="title text-xl">Bring your crew 🎁</div>
          <p className="text-sm text-cream/70">
            {referral.data.enabled
              ? `Earn ${usd(referral.data.bonus_usd_cents)} when a friend you invite plays their first paid game.`
              : "Share your link so friends can find you."}
          </p>
          <div className="flex gap-2">
            <input className="input text-sm" readOnly value={referral.data.link} aria-label="Your referral link" />
            <button
              className="btn-gold shrink-0"
              onClick={async () => {
                try {
                  await navigator.clipboard.writeText(referral.data!.link);
                  play("chip");
                  toast("Link copied", "ok");
                } catch {
                  toast("Couldn't copy, select the link instead", "info");
                }
              }}
            >
              Copy
            </button>
          </div>
          <div className="text-xs text-cream/50">
            {referral.data.signed_up} joined · {usd(referral.data.earned_usd_cents)} earned
          </div>
        </div>
      )}

      <div className="panel space-y-4 p-5">
        <div className="title text-xl">Play safe</div>
        <Limits />
        <div>
          <label className="label" htmlFor="rc">
            Remind me how long I've played
          </label>
          <select
            id="rc"
            className="input"
            value={m.reality_check_minutes ?? ""}
            onChange={async (e) => {
              await call(api.PUT("/me/reality-check", { body: { minutes: e.target.value ? Number(e.target.value) : null } }));
              await qc.invalidateQueries({ queryKey: ["me"] });
            }}
          >
            <option value="">Off</option>
            {[30, 60, 120].map((n) => (
              <option key={n} value={n}>
                Every {n} minutes
              </option>
            ))}
          </select>
        </div>
        <div className="rounded-xl border border-chip-red/30 p-4">
          <div className="font-semibold">Take a break</div>
          {m.excluded_until ? (
            <p className="mt-1 text-sm text-cream/70">You're on a break until {when(m.excluded_until)}.</p>
          ) : (
            <>
              <p className="mt-1 text-sm text-cream/60">Pauses deposits and paid tables. It can't be ended early.</p>
              <div className="mt-3 flex flex-wrap gap-2">
                {(["24h", "7d", "30d", "6m", "permanent"] as const).map((p) => (
                  <button key={p} className="btn-ghost border-chip-red/40 px-3 py-1.5 text-sm text-[#ff9a9d]" onClick={() => breakFor(p)}>
                    {p === "permanent" ? "For good" : p}
                  </button>
                ))}
              </div>
            </>
          )}
        </div>
      </div>

      <button className="btn-ghost w-full" onClick={signOut}>
        Sign out
      </button>
    </div>
  );
}
