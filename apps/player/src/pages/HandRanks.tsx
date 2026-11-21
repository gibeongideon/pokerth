import { useNavigate } from "react-router-dom";
import { PlayingCard } from "../components/Brand";
import { Icon } from "../components/Icon";

const RANKS = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A"];
const SUITS = ["d", "h", "s", "c"];

/** "As" -> PokerTH card index. */
function idx(code: string): number {
  const suit = code.slice(-1);
  const rank = code.slice(0, -1);
  return SUITS.indexOf(suit) * 13 + RANKS.indexOf(rank);
}

type Hand = { name: string; what: string; cards: string[]; used: number };

// `used` = how many of the five cards make the hand (the rest are kickers, shown dimmed).
const HANDS: Hand[] = [
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
          <p className="text-sm text-cream/60">Strongest at the top. Your best five cards from your two plus the five on the table.</p>
        </div>
      </div>

      <ol className="space-y-2.5">
        {HANDS.map((h, i) => (
          <li key={h.name} className="panel flex flex-col gap-3 p-3.5 sm:flex-row sm:items-center">
            <div className="flex items-center gap-3 sm:w-52 sm:shrink-0">
              <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-gold-400/15 font-display text-gold-300">
                {i + 1}
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
