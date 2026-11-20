import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Chip, Empty, SeatDots, Spinner, StatusBadge } from "../components/bits";
import { useToast } from "../components/Toast";
import { api, call, errorMessage } from "../lib/api";
import { TIER_COLORS, kes, usd, when } from "../lib/format";
import { useInvites, useTiers } from "../lib/hooks";
import { play } from "../lib/sound";
import type { LobbyTable, TableView, Tier } from "../lib/types";

function TierCard({ tier, color, onPlay, onPrivate, busy }: {
  tier: Tier;
  color: string;
  onPlay: () => void;
  onPrivate: () => void;
  busy: boolean;
}) {
  const top = Math.floor((tier.max_prize_pool_cents * (tier.payout_bps[0] ?? 0)) / 10_000);
  return (
    <div className="panel group relative overflow-hidden p-4 transition hover:-translate-y-1 hover:shadow-glow">
      <div
        className="pointer-events-none absolute -right-10 -top-10 h-36 w-36 rounded-full opacity-25 blur-2xl transition group-hover:opacity-40"
        style={{ background: color }}
      />
      <div className="flex items-center gap-3">
        <Chip color={color} size={52}>
          {tier.buy_in_cents ? `$${Math.round(tier.buy_in_cents / 100)}` : "FREE"}
        </Chip>
        <div className="min-w-0">
          <div className="text-xs font-bold uppercase tracking-widest text-cream/55">{tier.name}</div>
          <div className="title text-2xl leading-tight">{tier.price_label}</div>
        </div>
      </div>
      <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-sm text-cream/70">
        {tier.total_cents > 0 && <span>≈ {kes(tier.total_kes_reference)}</span>}
        <span>{tier.seats} seats</span>
        {top > 0 && (
          <span>
            Top prize <b className="text-gold-300">{usd(top)}</b>
          </span>
        )}
      </div>
      <div className="mt-4 flex gap-2">
        <button className="btn-gold flex-1" onClick={onPlay} disabled={busy}>
          Quick play
        </button>
        <button className="btn-ghost px-3" onClick={onPrivate} disabled={busy} title="Private table for friends">
          🔒
        </button>
      </div>
    </div>
  );
}

export function Lobby() {
  const tiers = useTiers();
  const tables = useQuery({
    queryKey: ["lobby-tables"],
    queryFn: () => call<LobbyTable[]>(api.GET("/lobby/tables")),
    refetchInterval: 5000,
  });
  const invites = useInvites();
  const navigate = useNavigate();
  const toast = useToast();
  const qc = useQueryClient();
  const [busy, setBusy] = useState(false);

  const go = async (request: Promise<TableView>) => {
    setBusy(true);
    try {
      const table = await request;
      play("chip");
      await qc.invalidateQueries({ queryKey: ["wallet"] });
      navigate(`/tables/${table.id}`);
    } catch (e) {
      toast(errorMessage(e), "error");
    } finally {
      setBusy(false);
    }
  };

  const filling = (tables.data ?? []).filter((t) => t.status === "open" && t.players > 0);

  return (
    <div className="space-y-8">
      <section className="relative overflow-hidden rounded-3xl border border-gold-400/20 bg-gradient-to-br from-felt-700 via-felt-800 to-felt-950 p-6 shadow-panel md:p-8">
        <div className="absolute -right-6 -top-8 hidden rotate-12 opacity-80 sm:block">
          <Chip color="#e0464b" size={120} />
        </div>
        <div className="absolute bottom-[-30px] right-24 hidden -rotate-6 opacity-60 sm:block">
          <Chip color="#3d7be0" size={90} />
        </div>
        <h1 className="title gold-text text-4xl md:text-5xl">Pick your stakes</h1>
        <p className="mt-2 max-w-md text-cream/75">
          One price, shown up front. Nothing taken during play. The table starts the moment it's full.
        </p>
        <div className="mt-5 flex flex-wrap gap-3">
          <Link to="/organize" className="btn-felt">
            🎉 Organize a game
          </Link>
          {(invites.data?.length ?? 0) > 0 && (
            <Link to="/friends" className="btn-ghost animate-pulseGlow">
              📨 {invites.data!.length} invite{invites.data!.length > 1 ? "s" : ""} waiting
            </Link>
          )}
        </div>
      </section>

      <section>
        {tiers.isLoading ? (
          <Spinner />
        ) : (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {tiers.data?.map((t, i) => (
              <TierCard
                key={t.id}
                tier={t}
                color={TIER_COLORS[i % TIER_COLORS.length]}
                busy={busy}
                onPlay={() => go(call<TableView>(api.POST("/lobby/quick-play", { body: { tier_id: t.id } })))}
                onPrivate={() => go(call<TableView>(api.POST("/tables/private", { body: { tier_id: t.id } })))}
              />
            ))}
          </div>
        )}
      </section>

      <section>
        <h2 className="title mb-3 text-2xl">Tables filling now</h2>
        {filling.length === 0 ? (
          <Empty title="No tables filling yet">Hit Quick play and be the first to sit down.</Empty>
        ) : (
          <div className="space-y-2">
            {filling.map((t) => (
              <Link
                key={t.id}
                to={`/tables/${t.id}`}
                className="panel flex items-center gap-4 px-4 py-3 transition hover:border-gold-400/40"
              >
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="font-display text-lg">{t.name}</span>
                    <StatusBadge status={t.status} />
                  </div>
                  <div className="text-sm text-cream/60">
                    {t.price_label}
                    {t.scheduled_start_at && ` · starts ${when(t.scheduled_start_at)}`}
                  </div>
                </div>
                <SeatDots filled={t.players} total={t.seats_total} />
                <span className="btn-felt hidden px-3 py-1.5 text-sm sm:inline-flex">View</span>
              </Link>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
