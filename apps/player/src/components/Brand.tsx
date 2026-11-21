/** Logo mark, wordmark and the playing-card art used across the app. */
// Only the card helper: importing the package root would pull protobuf into the main bundle.
import { card as decodeCard } from "@poker/protocol/src/cards";
import { useId } from "react";

const SUIT_GLYPH = { d: "♦", h: "♥", s: "♠", c: "♣" } as const;

/** A crown on a red chip: the app mark (also the favicon / app icon). */
export function LogoMark({ size = 40 }: { size?: number }) {
  // Unique gradient ids: a duplicate id inside a hidden copy (e.g. the desktop
  // rail on phones) would otherwise leave this copy without its fills.
  const id = useId().replace(/:/g, "");
  return (
    <svg width={size} height={size} viewBox="0 0 64 64" aria-hidden>
      <defs>
        <radialGradient id={`${id}c`} cx="40%" cy="35%" r="70%">
          <stop offset="0" stopColor="#ff6b6f" />
          <stop offset="1" stopColor="#a8242a" />
        </radialGradient>
        <linearGradient id={`${id}g`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#fff3c4" />
          <stop offset=".5" stopColor="#f5c451" />
          <stop offset="1" stopColor="#c98d1c" />
        </linearGradient>
      </defs>
      <circle cx="32" cy="33" r="29" fill="#000" opacity=".35" />
      <circle cx="32" cy="31" r="29" fill={`url(#${id}c)`} />
      {Array.from({ length: 8 }, (_, i) => (
        <rect key={i} x="29" y="2" width="6" height="9" rx="1.5" fill="#fff" transform={`rotate(${i * 45} 32 31)`} />
      ))}
      <circle cx="32" cy="31" r="19" fill="#7d1d21" />
      <circle cx="32" cy="31" r="17.5" fill="none" stroke={`url(#${id}g)`} strokeWidth="1.5" strokeDasharray="2 2.6" />
      <path d="M21 37 19 24l7 6 6-10 6 10 7-6-2 13z" fill={`url(#${id}g)`} stroke="#7a5310" strokeWidth="1" strokeLinejoin="round" />
      <rect x="21" y="38" width="22" height="3.5" rx="1.2" fill={`url(#${id}g)`} />
    </svg>
  );
}

export function Wordmark({ className = "text-2xl" }: { className?: string }) {
  return <span className={`title gold-text whitespace-nowrap ${className}`}>Draely</span>;
}

export function Logo({ size = 40, text = "text-2xl" }: { size?: number; text?: string }) {
  return (
    <span className="flex items-center gap-2.5">
      <LogoMark size={size} />
      <Wordmark className={text} />
    </span>
  );
}

/** A playing card (PokerTH index 0..51), or a card back when index is undefined. */
export function PlayingCard({ index, width = 64, className = "", style }: { index?: number; width?: number; className?: string; style?: React.CSSProperties }) {
  const h = width * 1.4;
  const id = useId().replace(/:/g, "");
  if (index === undefined) {
    return (
      <svg width={width} height={h} viewBox="0 0 100 140" className={className} style={style} aria-hidden>
        <defs>
          <pattern id={`${id}b`} width="10" height="10" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
            <rect width="10" height="10" fill="#b3262c" />
            <rect width="5" height="10" fill="#c9363b" />
          </pattern>
        </defs>
        <rect x="1" y="1" width="98" height="138" rx="10" fill="#fff" />
        <rect x="6" y="6" width="88" height="128" rx="7" fill={`url(#${id}b)`} />
        <rect x="6" y="6" width="88" height="128" rx="7" fill="none" stroke="#f5c451" strokeWidth="2" />
        <circle cx="50" cy="70" r="16" fill="#7d1d21" stroke="#f5c451" strokeWidth="2" />
        <path d="M42 75 41 66l4 3 5-7 5 7 4-3-1 9z" fill="#f5c451" />
      </svg>
    );
  }
  const c = decodeCard(index);
  const color = c.red ? "#d62f36" : "#15171c";
  const glyph = SUIT_GLYPH[c.suit];
  return (
    <svg width={width} height={h} viewBox="0 0 100 140" className={className} style={style} role="img" aria-label={`${c.rank}${glyph}`}>
      <defs>
        <linearGradient id={`${id}f`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#ffffff" />
          <stop offset="1" stopColor="#efe9da" />
        </linearGradient>
      </defs>
      <rect x="1" y="1" width="98" height="138" rx="10" fill={`url(#${id}f)`} stroke="#d7d0bd" strokeWidth="1.5" />
      <text x="11" y="32" fill={color} fontFamily="Lilita One" fontSize="30">{c.rank}</text>
      <text x="12" y="56" fill={color} fontSize="24">{glyph}</text>
      <text x="50" y="102" fill={color} fontSize="58" textAnchor="middle">{glyph}</text>
    </svg>
  );
}

/** Decorative fan of cards (hero art): A♠ K♥ Q♣ by default. */
export function CardFan({ cards = [38, 24, 49], width = 92 }: { cards?: number[]; width?: number }) {
  const mid = (cards.length - 1) / 2;
  return (
    <div className="relative" style={{ width: width * 2.2, height: width * 1.65 }} aria-hidden>
      {cards.map((idx, i) => (
        <PlayingCard
          key={idx}
          index={idx}
          width={width}
          className="absolute bottom-0 left-1/2 drop-shadow-[0_12px_18px_rgba(0,0,0,.55)]"
          style={{ transform: `translateX(-50%) rotate(${(i - mid) * 14}deg) translateY(${Math.abs(i - mid) * 8}px)`, transformOrigin: "50% 120%" }}
        />
      ))}
    </div>
  );
}
