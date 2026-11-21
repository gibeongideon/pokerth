import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Chip, Spinner, StatusBadge } from "../components/bits";
import { CardFan } from "../components/Brand";
import { Icon } from "../components/Icon";
import { useErrorToast } from "../components/Toast";
import { api, call } from "../lib/api";
import { TIER_COLORS, kes, usd, usdShort, when } from "../lib/format";
import { useInvites, useMe, useTiers } from "../lib/hooks";
import { play } from "../lib/sound";
import type { LobbyTable, TableView, Tier } from "../lib/types";

const topPrize = (t: Tier) => Math.floor((t.max_prize_pool_cents * (t.payout_bps[0] ?? 0)) / 10_000);
const chipLabel = (t: Tier) => (t.buy_in_cents ? usdShort(t.buy_in_cents) : "FREE");

function greeting() {
  const h = new Date().getHours();
  return h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening";
}

function FillBar({ filled, total, color }: { filled: number; total: number; color: string }) {
  return (
    <div className="h-1.5 w-full overflow-hidden rounded-full bg-cream/10">
      <div className="h-full rounded-full transition-all" style={{ width: `${(filled / Math.max(1, total)) * 100}%`, background: color, boxShadow: `0 0 10px ${color}` }} />
    </div>
  );
}

function TierCard({ tier, color, filling, onPlay, onPrivate, busy }: {
  tier: Tier;
  color: string;
  filling?: LobbyTable;
  onPlay: () => void;
  onPrivate: () => void;
  busy: boolean;
}) {
  const top = topPrize(tier);
  const split = tier.payout_bps.map((b) => `${b / 100}%`).join(" / ");
  return (
    <>
      {/* Phone: compact row */}
      <div className="panel flex items-center gap-3 p-3 sm:hidden">
        <Chip color={color} size={46}>
          {chipLabel(tier)}
        </Chip>
        <div className="min-w-0 flex-1">
          <div className="text-[11px] font-bold uppercase tracking-widest text-cream/50">{tier.name}</div>
          <div className="title truncate text-lg leading-tight">{tier.price_label}</div>
          <div className="mt-0.5 flex items-center gap-2 text-xs text-cream/55">
            {top > 0 ? (
              <span className="inline-flex items-center gap-1 text-gold-300">
                <Icon name="trophy" size={12} /> {usd(top)}
              </span>
            ) : (
              <span>Play money</span>
            )}
            <span>· {tier.seats} seats</span>
            {filling && <span className="text-chip-green">· {filling.players} waiting</span>}
          </div>
        </div>
        {tier.buy_in_cents === 0 && (
          <button className="btn-icon h-11 w-11" onClick={onPrivate} disabled={busy} aria-label={`Private ${tier.name} table`}>
            <Icon name="lock" size={18} />
          </button>
        )}
        <button className="btn-gold h-11 px-4" onClick={onPlay} disabled={busy}>
          Play
        </button>
      </div>

      {/* Tablet/desktop: card */}
      <div className="panel group relative hidden overflow-hidden p-5 transition duration-200 hover:-translate-y-1 hover:shadow-glow sm:block">
        <div className="pointer-events-none absolute -right-16 -top-16 h-44 w-44 rounded-full opacity-30 blur-3xl transition group-hover:opacity-50" style={{ background: color }} />
        <div className="relative flex items-start gap-4">
          <span className="transition duration-300 group-hover:rotate-[20deg]">
            <Chip color={color} size={60}>
              {chipLabel(tier)}
            </Chip>
          </span>
          <div className="min-w-0 flex-1">
            <div className="text-[11px] font-bold uppercase tracking-[0.2em] text-cream/50">{tier.name}</div>
            <div className="title text-[28px] leading-tight">{tier.price_label}</div>
            {tier.total_cents > 0 && <div className="text-sm text-cream/45">≈ {kes(tier.total_kes_reference)}</div>}
          </div>
        </div>

        <div className="relative mt-4 grid grid-cols-2 gap-2">
          <div className="stat">
            <b className={top > 0 ? "text-gold-300" : ""}>{top > 0 ? usd(top) : "Play money"}</b>
            <span>Winner takes</span>
          </div>
          <div className="stat">
            <b>{tier.seats}</b>
            <span title={split ? `Prize split ${split}` : undefined}>Seats</span>
          </div>
        </div>

        <div className="relative mt-4 min-h-[34px]">
          {filling ? (
            <>
              <div className="mb-1.5 flex justify-between text-xs">
                <span className="font-semibold text-chip-green">● Filling now</span>
                <span className="text-cream/55">
                  {filling.players}/{filling.seats_total} seated
                </span>
              </div>
              <FillBar filled={filling.players} total={filling.seats_total} color={color} />
            </>
          ) : (
            <div className="text-xs text-cream/45">Start a new table — it deals the moment it's full.</div>
          )}
        </div>

        <div className="relative mt-4 flex gap-2">
          <button className="btn-gold flex-1 text-lg" onClick={onPlay} disabled={busy}>
            <Icon name="bolt" size={18} strokeWidth={2.4} /> Quick play
          </button>
          {tier.buy_in_cents === 0 && (
            <button className="btn-icon h-auto w-12" onClick={onPrivate} disabled={busy} title="Private table for friends" aria-label={`Private ${tier.name} table`}>
              <Icon name="lock" size={18} />
            </button>
          )}
        </div>
      </div>
    </>
  );
}

export function Lobby() {
  const tiers = useTiers();
  const me = useMe();
  const tables = useQuery({
    queryKey: ["lobby-tables"],
    queryFn: () => call<LobbyTable[]>(api.GET("/lobby/tables")),
    refetchInterval: 5000,
  });
  const invites = useInvites();
  const navigate = useNavigate();
  const showError = useErrorToast();
  const qc = useQueryClient();
  const [busy, setBusy] = useState(false);

  const go = async (request: Promise<TableView>) => {
    setBusy(true);
    try {
      const table = await request;
      play("chip");
      await Promise.all([qc.invalidateQueries({ queryKey: ["wallet"] }), qc.invalidateQueries({ queryKey: ["demo-money"] })]);
      navigate(`/tables/${table.id}`);
    } catch (e) {
      showError(e);
    } finally {
      setBusy(false);
    }
  };
  const quickPlay = (t: Tier) => go(call<TableView>(api.POST("/lobby/quick-play", { body: { tier_id: t.id } })));
  const [practiceSeats, setPracticeSeats] = useState(6);
  // You plus (seats - 1) computer players.
  const practice = () => go(call<TableView>(api.POST("/lobby/practice", { body: { bots: practiceSeats - 1 } })));

  const all = tables.data ?? [];
  // Open tables: anything public still taking players that has someone in it,
  // or that a player created (it has a title) - including empty ones.
  const filling = all.filter((t) => t.status === "open" && (t.players > 0 || !!t.title));
  const seated = all.reduce((n, t) => n + (t.status === "running" || t.status === "open" || t.status === "ready_check" ? t.players : 0), 0);
  const tierList = tiers.data ?? [];
  const colorOf = (label: string) => TIER_COLORS[Math.max(0, tierList.findIndex((t) => t.price_label === label)) % TIER_COLORS.length];
  const biggest = tierList.reduce((m, t) => Math.max(m, topPrize(t)), 0);
  // Suggest the busiest stake, else the cheapest paid one, else the first.
  const suggested =
    tierList.find((t) => filling.some((f) => f.price_label === t.price_label)) ?? tierList.find((t) => t.buy_in_cents > 0) ?? tierList[0];
  const pendingInvites = invites.data?.length ?? 0;

  return (
    <div className="space-y-8">
      <section className="relative overflow-hidden rounded-3xl border border-gold-400/20 bg-[radial-gradient(120%_120%_at_0%_0%,#17805a_0%,#0c3a2a_45%,#05170f_100%)] p-6 shadow-panel md:p-9">
        <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(60%_80%_at_85%_40%,rgba(245,196,81,.16),transparent_60%)]" />
        <div className="pointer-events-none absolute -right-2 top-1/2 hidden -translate-y-1/2 md:block lg:right-10">
          <div className="relative">
            <CardFan width={104} />
            <span className="absolute -bottom-2 -left-10 rotate-[-12deg] animate-float">
              <Chip color="#e0464b" size={64} />
            </span>
            <span className="absolute -right-4 bottom-6 rotate-[18deg] animate-float" style={{ animationDelay: ".6s" }}>
              <Chip color="#1c1c22" size={52} />
            </span>
          </div>
        </div>
        <div className="relative max-w-lg">
          <div className="eyebrow">
            {greeting()}, {me.data?.username ?? "king"}
          </div>
          <h1 className="title gold-text mt-1 text-4xl leading-[1.05] md:text-6xl">Take a seat.</h1>
          <p className="mt-3 max-w-md text-cream/75 md:text-lg">
            Sit &amp; Go tables that deal the moment they're full. One price up front — nothing taken during play.
          </p>
          <div className="mt-6 flex flex-wrap gap-3">
            {suggested && (
              <button className="btn-gold w-full px-6 py-3 text-lg sm:w-auto" disabled={busy} onClick={() => quickPlay(suggested)}>
                <Icon name="bolt" size={20} strokeWidth={2.4} /> Quick play · {suggested.buy_in_cents ? usd(suggested.buy_in_cents) : "Free"}
              </button>
            )}
            <div className="flex w-full gap-2 sm:w-auto">
              <button className="btn-felt flex-1 px-5 py-3" disabled={busy} onClick={practice}>
                <Icon name="spark" size={18} /> Practice vs computer
              </button>
              <select
                className="input w-auto shrink-0 py-2 font-display"
                value={practiceSeats}
                onChange={(e) => setPracticeSeats(Number(e.target.value))}
                aria-label="Seats at the practice table"
                title="Seats (you + computer players)"
              >
                {[2, 3, 4, 5, 6].map((n) => (
                  <option key={n} value={n}>
                    {n} seats
                  </option>
                ))}
              </select>
            </div>
            <Link to="/organize" className="btn-ghost w-full px-5 py-3 sm:w-auto">
              <Icon name="users" size={18} /> Create a table
            </Link>
          </div>
          {pendingInvites > 0 && (
            <Link to="/friends" className="mt-4 inline-flex items-center gap-2 rounded-full border border-gold-400/40 bg-black/30 py-1.5 pl-2 pr-3 text-sm text-gold-300 animate-pulseGlow">
              <span className="flex h-6 w-6 items-center justify-center rounded-full bg-gold-400 text-felt-950">
                <Icon name="mail" size={14} strokeWidth={2.4} />
              </span>
              {pendingInvites} game invite{pendingInvites > 1 ? "s" : ""} waiting for you
              <Icon name="chevron" size={14} />
            </Link>
          )}
        </div>
        <Link to="/hands" className="relative mt-4 inline-flex items-center gap-1.5 text-sm text-gold-300 hover:underline">
          <span className="flex h-5 w-5 items-center justify-center rounded-full bg-gold-400/20 font-display text-xs">?</span>
          New to poker? See which hands win
        </Link>
        <div className="relative mt-7 grid max-w-lg grid-cols-3 gap-2">
          <div className="stat bg-black/30">
            <b>{seated}</b>
            <span>At tables</span>
          </div>
          <div className="stat bg-black/30">
            <b>{filling.length}</b>
            <span>Filling now</span>
          </div>
          <div className="stat bg-black/30">
            <b className="text-gold-300">{biggest ? usd(biggest) : "—"}</b>
            <span>Top prize</span>
          </div>
        </div>
      </section>

      <section>
        <div className="mb-4 flex items-end justify-between gap-3">
          <div>
            <h2 className="title text-2xl md:text-3xl">Choose your stakes</h2>
            <p className="text-sm text-cream/55">The price includes a small entry fee. The prize pool is shown before you sit.</p>
          </div>
        </div>
        {tiers.isLoading ? (
          <Spinner />
        ) : (
          <div className="grid gap-3 sm:grid-cols-2 sm:gap-4 xl:grid-cols-3">
            {tierList.map((t, i) => (
              <TierCard
                key={t.id}
                tier={t}
                color={TIER_COLORS[i % TIER_COLORS.length]}
                filling={filling.find((f) => f.price_label === t.price_label)}
                busy={busy}
                onPlay={() => quickPlay(t)}
                onPrivate={() => go(call<TableView>(api.POST("/tables/private", { body: { tier_id: t.id } })))}
              />
            ))}
          </div>
        )}
      </section>

      <section>
        <div className="mb-3 flex items-center gap-3">
          <h2 className="title text-2xl">Open tables</h2>
          <Link to="/organize" className="ml-auto text-sm text-gold-300 hover:underline">
            + Create a table
          </Link>
          {filling.length > 0 && <span className="h-2 w-2 animate-pulse rounded-full bg-chip-green shadow-[0_0_8px_#35b26b]" />}
        </div>
        {filling.length === 0 ? (
          <div className="panel-flat flex flex-col items-center gap-2 px-5 py-8 text-center">
            <Icon name="seat" size={28} className="text-cream/30" />
            <div className="title text-lg">No open tables right now</div>
            <div className="text-sm text-cream/55">Hit Quick play, create a public table, or practice against the computer.</div>
          </div>
        ) : (
          <div className="grid gap-2 lg:grid-cols-2">
            {filling.map((t) => {
              const color = colorOf(t.price_label);
              const left = t.seats_total - t.players;
              return (
                <Link key={t.id} to={`/tables/${t.id}`} className="panel flex items-center gap-3 px-4 py-3 transition hover:-translate-y-0.5 hover:shadow-glow">
                  <Chip color={color} size={38} />
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="truncate font-display text-lg">{t.title ?? t.name}</span>
                      <StatusBadge status={t.status} />
                    </div>
                    <div className="mb-1.5 text-xs text-cream/55">
                      {t.organizer ? `by ${t.organizer} · ` : ""}
                      {t.price_label} · {left} seat{left === 1 ? "" : "s"} left
                      {t.scheduled_start_at && ` · starts ${when(t.scheduled_start_at)}`}
                    </div>
                    <FillBar filled={t.players} total={t.seats_total} color={color} />
                  </div>
                  <span className="btn-felt shrink-0 px-4 py-2 text-sm">Join</span>
                </Link>
              );
            })}
          </div>
        )}
      </section>
    </div>
  );
}
