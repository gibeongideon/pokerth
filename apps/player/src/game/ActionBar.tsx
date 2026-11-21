/**
 * Betting controls for live play. Big thumb-sized buttons so it works the same
 * in a phone browser and the Capacitor app: Fold · Check/Call · Raise (slider
 * with quick sizes) · All-in. Only legal moves are offered; the game server
 * still validates every action.
 */
import { legalActions, me, pot, type PlayerMove, type TableState } from "@poker/protocol";
import { useEffect, useState } from "react";
import { Icon } from "../components/Icon";

const chips = (n: number) => n.toLocaleString("en-US");

function useTurnSecondsLeft(s: TableState) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 250);
    return () => clearInterval(t);
  }, []);
  return Math.max(0, Math.ceil(s.actionTimeoutSec - (now - s.turnStartedAt) / 1000));
}

export function ActionBar({ state, act }: { state: TableState; act: (m: PlayerMove) => void }) {
  const legal = legalActions(state);
  const mine = me(state);
  const left = useTurnSecondsLeft(state);
  const [raiseTo, setRaiseTo] = useState(0);
  const [sizing, setSizing] = useState(false);

  // Reset the slider at the start of each decision.
  const turnKey = `${state.handNum}:${state.street}:${state.turnStartedAt}`;
  useEffect(() => {
    setRaiseTo(legal?.raise?.min ?? 0);
    setSizing(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [turnKey]);

  if (!mine) return null;

  if (!legal) {
    const turnName = state.seats.find((p) => p.playerId === state.turnPlayerId)?.name;
    return (
      <div className="flex min-h-[64px] items-center justify-center gap-3 text-cream/70">
        {state.handOver ? (
          <span className="font-display text-lg">Next hand coming up…</span>
        ) : mine.folded ? (
          <span>You folded · watching the hand</span>
        ) : mine.allIn ? (
          <span className="font-display text-lg text-gold-300">You're all-in — good luck</span>
        ) : turnName ? (
          <span>
            Waiting for <b className="text-cream">{turnName}</b>…
          </span>
        ) : (
          <span>Dealing…</span>
        )}
      </div>
    );
  }

  const r = legal.raise;
  const p = pot(state);
  const quick = r
    ? [
        { label: "Min", to: r.min },
        { label: "½ Pot", to: state.highestSet + Math.floor((p + legal.call) / 2) },
        { label: "Pot", to: state.highestSet + p + legal.call },
      ].filter((q, i, all) => q.to > r.min - 1 && q.to < r.max && all.findIndex((x) => x.to === q.to) === i)
    : [];
  const word = r?.kind === "bet" ? "Bet" : "Raise to";

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-3">
        <span className="flex items-center gap-2 font-display text-lg text-gold-300">
          <span className="h-2.5 w-2.5 animate-pulse rounded-full bg-gold-400 shadow-[0_0_10px_#f5c451]" /> Your turn
        </span>
        <div className="h-2 flex-1 overflow-hidden rounded-full bg-cream/10">
          <div
            className={`h-full rounded-full transition-[width] duration-300 ease-linear ${left <= 5 ? "bg-chip-red" : "bg-gradient-to-r from-gold-600 to-gold-300"}`}
            style={{ width: `${(left / Math.max(1, state.actionTimeoutSec)) * 100}%` }}
          />
        </div>
        <span className={`w-9 text-right font-display text-lg ${left <= 5 ? "text-[#ff8a8e]" : "text-cream/70"}`}>{left}s</span>
      </div>
      {sizing && r && (
        <div className="panel animate-pop space-y-3 p-3">
          <div className="flex items-center gap-3">
            <input
              type="range"
              className="h-3 flex-1 accent-[#f5c451]"
              min={r.min}
              max={r.max}
              step={Math.max(1, state.smallBlind)}
              value={raiseTo}
              onChange={(e) => setRaiseTo(Number(e.target.value))}
              aria-label="Raise amount"
            />
            <input
              type="number"
              className="input w-24 py-1.5 text-right"
              min={r.min}
              max={r.max}
              value={raiseTo}
              onChange={(e) => setRaiseTo(Number(e.target.value))}
              onBlur={() => setRaiseTo((v) => Math.min(r.max, Math.max(r.min, v || r.min)))}
            />
          </div>
          <div className="flex flex-wrap gap-2">
            {quick.map((q) => (
              <button key={q.label} className="btn-ghost flex-1 px-2 py-1.5 text-sm" onClick={() => setRaiseTo(Math.min(r.max, Math.max(r.min, q.to)))}>
                {q.label}
              </button>
            ))}
            <button className="btn-ghost flex-1 px-2 py-1.5 text-sm" onClick={() => setRaiseTo(r.max)}>
              Max
            </button>
          </div>
        </div>
      )}
      <div className="grid grid-cols-3 gap-2">
        <button className="btn-red py-4 text-lg" onClick={() => act({ kind: "fold" })}>
          <Icon name="close" size={18} strokeWidth={2.6} /> Fold
        </button>
        {legal.check ? (
          <button className="btn-felt py-4 text-lg" onClick={() => act({ kind: "check" })}>
            <Icon name="check" size={18} strokeWidth={2.6} /> Check
          </button>
        ) : (
          <button className="btn-felt py-4 text-lg" onClick={() => act({ kind: "call" })}>
            {legal.call >= mine.cash ? "All-in" : "Call"} {chips(legal.call)}
          </button>
        )}
        {r ? (
          sizing ? (
            <button className="btn-gold py-4 text-lg" onClick={() => act(raiseTo >= r.max ? { kind: "allin" } : { kind: "raise", to: raiseTo })}>
              {raiseTo >= r.max ? "All-in" : word} {chips(Math.min(r.max, Math.max(r.min, raiseTo)))}
            </button>
          ) : (
            <button className="btn-gold py-4 text-lg" onClick={() => setSizing(true)}>
              {r.kind === "bet" ? "Bet" : "Raise"} ▸
            </button>
          )
        ) : legal.call < mine.cash ? (
          <button className="btn-gold py-4 text-lg" onClick={() => act({ kind: "allin" })}>
            All-in {chips(legal.allIn)}
          </button>
        ) : (
          <span />
        )}
      </div>
    </div>
  );
}
