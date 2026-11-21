import { useEffect, useState } from "react";
import { bestHandRank } from "@poker/protocol";
import { useNavigate } from "react-router-dom";
import { PlayingCard } from "../components/Brand";
import { Icon } from "../components/Icon";

const RANKS = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A"];
const SUITS = ["d", "h", "s", "c"];

/** "As" -> PokerTH card index. */
export function idx(code: string): number {
  const suit = code.slice(-1);
  const rank = code.slice(0, -1);
  return SUITS.indexOf(suit) * 13 + RANKS.indexOf(rank);
}

export type Hand = { name: string; what: string; cards: string[]; used: number };

// `used` = how many of the five cards make the hand (the rest are kickers, shown dimmed).
export const HANDS: Hand[] = [
  { name: "Royal flush", what: "A, K, Q, J, 10, all the same suit.", cards: ["As", "Ks", "Qs", "Js", "10s"], used: 5 },
  { name: "Straight flush", what: "Five in a row, all the same suit.", cards: ["9h", "8h", "7h", "6h", "5h"], used: 5 },
  { name: "Four of a kind", what: "Four cards of the same rank.", cards: ["Qc", "Qd", "Qh", "Qs", "7d"], used: 4 },
  { name: "Full house", what: "Three of a kind plus a pair.", cards: ["Kh", "Kc", "Ks", "4d", "4h"], used: 5 },
  { name: "Flush", what: "Any five cards of the same suit.", cards: ["Ad", "Jd", "9d", "6d", "3d"], used: 5 },
  { name: "Straight", what: "Five in a row, mixed suits. A can be high or low (A-2-3-4-5).", cards: ["10c", "9d", "8s", "7h", "6c"], used: 5 },
  { name: "Three of a kind", what: "Three cards of the same rank.", cards: ["8s", "8h", "8d", "Kc", "2s"], used: 3 },
  { name: "Two pair", what: "Two different pairs.", cards: ["Jh", "Jc", "5s", "5d", "Ah"], used: 4 },
  { name: "One pair", what: "Two cards of the same rank.", cards: ["10h", "10s", "Ac", "7d", "4s"], used: 2 },
  { name: "High card", what: "Nothing above? The highest card plays.", cards: ["Ah", "Jd", "8c", "5s", "3h"], used: 1 },
];

/** Strength score shown to players: 10 = Royal flush (best) .. 1 = High card. */
export const strength = (i: number) => HANDS.length - i;

/** An on/off choice remembered on this device. */
export function useStoredFlag(key: string, initial: boolean): [boolean, (v: boolean) => void] {
  const [value, setValue] = useState(() => {
    try {
      const v = localStorage.getItem(key);
      return v === null ? initial : v === "1";
    } catch {
      return initial;
    }
  });
  // Other components using the same flag follow along.
  useEffect(() => {
    const on = (e: Event) => {
      const d = (e as CustomEvent<{ key: string; value: boolean }>).detail;
      if (d.key === key) setValue(d.value);
    };
    window.addEventListener("fk-flag", on);
    return () => window.removeEventListener("fk-flag", on);
  }, [key]);
  const set = (v: boolean) => {
    try {
      localStorage.setItem(key, v ? "1" : "0");
    } catch {
      /* private mode: just don't remember */
    }
    window.dispatchEvent(new CustomEvent("fk-flag", { detail: { key, value: v } }));
    setValue(v);
  };
  return [value, set];
}

/** The best hand in these cards, as an index into HANDS; null before the cards are dealt. */
export function myHandIndex(cards: number[] | null | undefined): number | null {
  return cards && cards.length >= 2 ? bestHandRank(cards) : null;
}

/** "Your hand: Two pair · 3/10" above the betting buttons - only if the player turns it on. */
export function MyHandHint({ cards }: { cards: number[] | null }) {
  const [show, setShow] = useStoredFlag("fk.showMyHand", false);
  const i = myHandIndex(cards);
  if (i === null) return null;
  if (!show) {
    return (
      <button className="mb-2 text-xs text-gold-300/80 hover:text-gold-300" onClick={() => setShow(true)}>
        Show my hand
      </button>
    );
  }
  return (
    <div className="mb-2 flex items-center gap-2 text-sm">
      <span className="text-cream/60">Your hand:</span>
      <b className="font-display text-base text-gold-300">{HANDS[i].name}</b>
      <span className="rounded-full bg-gold-400/15 px-2 py-0.5 font-display text-xs text-gold-300">{strength(i)}/10</span>
      <button className="ml-auto text-xs text-cream/45 hover:text-cream" onClick={() => setShow(false)}>
        Hide
      </button>
    </div>
  );
}

/** Compact, collapsible hand rankings for the table screen. Remembers open/closed. */
export function HandRanksPanel({ cards, helperOff = false }: { cards?: number[] | null; helperOff?: boolean }) {
  const [open, setOpen] = useStoredFlag("fk.handsPanel", true);
  const [showMine] = useStoredFlag("fk.showMyHand", false);
  const mine = showMine ? myHandIndex(cards) : null;
  const toggle = () => setOpen(!open);
  return (
    <div className="panel p-3 text-sm">
      <button className="flex w-full items-center gap-2 text-left" onClick={toggle} aria-expanded={open}>
        <span className="flex h-6 w-6 items-center justify-center rounded-full bg-gold-400/15 font-display text-xs text-gold-300">?</span>
        <span className="label mb-0 flex-1">Hand rankings</span>
        <span className="text-xs text-gold-300">{open ? "Hide" : "Show"}</span>
        <Icon name="chevron" size={14} className={`text-gold-300 transition ${open ? "rotate-90" : ""}`} />
      </button>
      {open && (
        <ol className="mt-2 space-y-1">
          {HANDS.map((h, i) => (
            <li
              key={h.name}
              className={`-mx-1 flex items-center gap-2 rounded-lg px-1 ${i === mine ? "bg-gold-400/15 text-gold-300 ring-1 ring-gold-400/50" : ""}`}
              title={h.what}
            >
              <span className="w-5 shrink-0 text-right text-xs text-cream/40">{strength(i)}</span>
              <span className="min-w-0 flex-1 truncate">{h.name}</span>
              <span className="flex shrink-0 gap-0.5">
                {h.cards.map((c, j) => (
                  <PlayingCard key={c} index={idx(c)} width={20} className={j < h.used ? "" : "opacity-30"} />
                ))}
              </span>
            </li>
          ))}
          {helperOff && <li className="pt-1 text-xs text-cream/45">Hand helper is off at this table.</li>}
        </ol>
      )}
    </div>
  );
}

export function HandRanks() {
  const nav = useNavigate();
  return (
    <div className="mx-auto max-w-2xl space-y-4">
      <div className="flex items-center gap-3">
        <button className="btn-icon h-10 w-10" onClick={() => nav(-1)} aria-label="Back">
          <Icon name="back" size={20} />
        </button>
        <div>
          <h1 className="title text-3xl">Hand rankings</h1>
          <p className="text-sm text-cream/60">Strongest at the top (10) down to the weakest (1). Your best five cards from your two plus the five on the table.</p>
        </div>
      </div>

      <ol className="space-y-2.5">
        {HANDS.map((h, i) => (
          <li key={h.name} className="panel flex flex-col gap-3 p-3.5 sm:flex-row sm:items-center">
            <div className="flex items-center gap-3 sm:w-52 sm:shrink-0">
              <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-gold-400/15 font-display text-gold-300">
                {strength(i)}
              </span>
              <div className="min-w-0">
                <div className="font-display text-lg leading-tight">{h.name}</div>
                <div className="text-xs text-cream/60">{h.what}</div>
              </div>
            </div>
            <div className="flex gap-1.5 sm:ml-auto">
              {h.cards.map((c, j) => (
                <PlayingCard
                  key={c}
                  index={idx(c)}
                  width={46}
                  className={`drop-shadow-[0_4px_6px_rgba(0,0,0,.45)] transition ${j < h.used ? "" : "opacity-35"}`}
                />
              ))}
            </div>
          </li>
        ))}
      </ol>

      <div className="panel-flat space-y-2 p-4 text-sm text-cream/75">
        <div className="font-display text-base text-cream">Good to know</div>
        <p>• Same hand? The higher cards win: a pair of kings beats a pair of queens.</p>
        <p>• Still a tie? The next highest card (the "kicker") decides. Faded cards above are kickers.</p>
        <p>• Suits never rank: a spade flush and a heart flush of the same cards split the pot.</p>
      </div>
    </div>
  );
}
