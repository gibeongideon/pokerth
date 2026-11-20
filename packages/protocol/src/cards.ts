// PokerTH card index 0..51: rank = index % 13 (0 = "2" ... 12 = "A"),
// suit = floor(index / 13) in the order diamonds, hearts, spades, clubs.

export type Suit = "d" | "h" | "s" | "c";

export interface Card {
  index: number;
  rank: string; // "2".."10", "J", "Q", "K", "A"
  suit: Suit;
  red: boolean;
}

const RANKS = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A"];
const SUITS: Suit[] = ["d", "h", "s", "c"];

export const SUIT_GLYPH: Record<Suit, string> = { d: "♦", h: "♥", s: "♠", c: "♣" };

export function card(index: number): Card {
  if (!Number.isInteger(index) || index < 0 || index > 51) throw new RangeError(`bad card ${index}`);
  const suit = SUITS[Math.floor(index / 13)];
  return { index, rank: RANKS[index % 13], suit, red: suit === "d" || suit === "h" };
}

export function cardLabel(index: number): string {
  const c = card(index);
  return c.rank + SUIT_GLYPH[c.suit];
}
