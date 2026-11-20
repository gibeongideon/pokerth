export function usd(cents: number): string {
  const sign = cents < 0 ? "-" : "";
  const abs = Math.abs(cents);
  return `${sign}$${Math.floor(abs / 100).toLocaleString()}.${String(abs % 100).padStart(2, "0")}`;
}

export function kes(whole: number): string {
  return `KES ${whole.toLocaleString()}`;
}

export function kesFromSubunits(subunits: number): string {
  return kes(Math.round(subunits / 100));
}

export function when(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    weekday: "short",
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

const PALETTE = ["#e0464b", "#3d7be0", "#35b26b", "#8f5ce0", "#e2a72e", "#1fb5b5", "#e06fb0"];

export function colorFor(name: string): string {
  let h = 0;
  for (const ch of name) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return PALETTE[h % PALETTE.length];
}

export function initials(name: string): string {
  return name.slice(0, 2).toUpperCase();
}

/** Chip colour per stake level, cheapest first. */
export const TIER_COLORS = ["#35b26b", "#e0464b", "#3d7be0", "#8f5ce0", "#1c1c22", "#e2a72e"];
