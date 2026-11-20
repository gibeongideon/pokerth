import type { ReactNode } from "react";
import { colorFor, initials } from "../lib/format";

export function Avatar({ name, size = 36, ring }: { name: string; size?: number; ring?: string }) {
  return (
    <span
      className="inline-flex shrink-0 items-center justify-center rounded-full font-display text-white"
      style={{
        width: size,
        height: size,
        fontSize: size * 0.38,
        background: `radial-gradient(circle at 35% 30%, ${colorFor(name)}ee, ${colorFor(name)} 60%, #0008 140%)`,
        boxShadow: `0 0 0 2px ${ring ?? "rgba(0,0,0,.35)"}, 0 3px 8px rgba(0,0,0,.4)`,
      }}
      aria-hidden
    >
      {initials(name)}
    </span>
  );
}

/** A poker-chip shaped badge in a given colour. */
export function Chip({ color, size = 44, children }: { color: string; size?: number; children?: ReactNode }) {
  return (
    <span
      className="relative inline-flex shrink-0 items-center justify-center rounded-full font-display text-white"
      style={{
        width: size,
        height: size,
        background: `repeating-conic-gradient(${color} 0 30deg, #fff 30deg 45deg)`,
        boxShadow: "0 3px 0 rgba(0,0,0,.45), 0 6px 14px rgba(0,0,0,.35)",
      }}
      aria-hidden
    >
      <span
        className="absolute inset-[18%] flex items-center justify-center rounded-full text-[11px]"
        style={{ background: color, boxShadow: "inset 0 0 0 2px rgba(255,255,255,.55)" }}
      >
        {children}
      </span>
    </span>
  );
}

const STATUS_STYLE: Record<string, string> = {
  open: "bg-chip-green/20 text-chip-green",
  ready_check: "bg-gold-400/20 text-gold-300 animate-pulse",
  running: "bg-chip-blue/25 text-[#8db6ff]",
  finished: "bg-cream/10 text-cream/70",
  cancelled: "bg-chip-red/20 text-[#ff9a9d]",
};
const STATUS_TEXT: Record<string, string> = {
  open: "Taking seats",
  ready_check: "Ready check",
  running: "In play",
  finished: "Finished",
  cancelled: "Cancelled",
};

export function StatusBadge({ status }: { status: string }) {
  return <span className={`badge ${STATUS_STYLE[status] ?? ""}`}>{STATUS_TEXT[status] ?? status}</span>;
}

export function SeatDots({ filled, total }: { filled: number; total: number }) {
  return (
    <span className="inline-flex gap-1" aria-label={`${filled} of ${total} seats taken`}>
      {Array.from({ length: total }, (_, i) => (
        <span
          key={i}
          className={`h-2.5 w-2.5 rounded-full ${i < filled ? "bg-gold-400 shadow-[0_0_6px_rgba(245,196,81,.7)]" : "bg-cream/15"}`}
        />
      ))}
    </span>
  );
}

export function Ring({ seconds, total, size = 64 }: { seconds: number; total: number; size?: number }) {
  const r = size / 2 - 5;
  const c = 2 * Math.PI * r;
  const frac = total > 0 ? Math.max(0, Math.min(1, seconds / total)) : 0;
  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} aria-label={`${seconds} seconds left`}>
      <circle cx={size / 2} cy={size / 2} r={r} stroke="rgba(255,255,255,.12)" strokeWidth="6" fill="none" />
      <circle
        cx={size / 2}
        cy={size / 2}
        r={r}
        stroke={frac < 0.25 ? "#e0464b" : "#f5c451"}
        strokeWidth="6"
        fill="none"
        strokeLinecap="round"
        strokeDasharray={c}
        strokeDashoffset={c * (1 - frac)}
        transform={`rotate(-90 ${size / 2} ${size / 2})`}
        style={{ transition: "stroke-dashoffset 1s linear" }}
      />
      <text x="50%" y="54%" textAnchor="middle" dominantBaseline="middle" fill="#f6f1e3" fontFamily="Lilita One" fontSize={size * 0.32}>
        {seconds}
      </text>
    </svg>
  );
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="rounded-2xl border border-dashed border-cream/15 px-5 py-8 text-center">
      <div className="title text-lg">{title}</div>
      {children && <div className="mt-1 text-sm text-cream/60">{children}</div>}
    </div>
  );
}

export function Spinner() {
  return (
    <div className="flex justify-center py-10" aria-label="Loading">
      <span className="h-9 w-9 animate-spin rounded-full border-4 border-gold-400/20 border-t-gold-400" />
    </div>
  );
}
