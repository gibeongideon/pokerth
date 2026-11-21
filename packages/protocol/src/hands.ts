// Name the best poker hand you hold right now (your 2 cards + the board, 2..7 cards).
// Only the hand category; enough for a quick "what do I have" hint.

export const HAND_NAMES = [
  "Royal flush",
  "Straight flush",
  "Four of a kind",
  "Full house",
  "Flush",
  "Straight",
  "Three of a kind",
  "Two pair",
  "One pair",
  "High card",
] as const;

export type HandName = (typeof HAND_NAMES)[number];

/** Highest card of a 5-in-a-row among these ranks (0 = "2" .. 12 = "A"), or -1. A plays low too. */
function straightTop(ranks: Set<number>): number {
  // top = 3 is the wheel: 5-4-3-2-A (rank -1 stands for the ace).
  for (let top = 12; top >= 3; top--) {
    if ([0, 1, 2, 3, 4].every((k) => ranks.has(top - k === -1 ? 12 : top - k))) return top;
  }
  return -1;
}

/** Index into HAND_NAMES (0 = Royal flush .. 9 = High card) for the best hand in ``cards``. */
export function bestHandRank(cards: number[]): number {
  const counts = new Array<number>(13).fill(0);
  const bySuit: Set<number>[] = [new Set(), new Set(), new Set(), new Set()];
  for (const c of cards) {
    counts[c % 13]++;
    bySuit[Math.floor(c / 13)].add(c % 13);
  }
  for (const suited of bySuit) {
    if (suited.size >= 5) {
      const top = straightTop(suited);
      if (top === 12) return 0;
      if (top >= 0) return 1;
    }
  }
  const groups = counts.filter((n) => n > 0).sort((a, b) => b - a);
  if (groups[0] >= 4) return 2;
  if (groups[0] === 3 && (groups[1] ?? 0) >= 2) return 3;
  if (bySuit.some((s) => s.size >= 5)) return 4;
  if (straightTop(new Set(cards.map((c) => c % 13))) >= 0) return 5;
  if (groups[0] === 3) return 6;
  if (groups[0] === 2 && groups[1] === 2) return 7;
  if (groups[0] === 2) return 8;
  return 9;
}

export function bestHandName(cards: number[]): HandName {
  return HAND_NAMES[bestHandRank(cards)];
}
