import { useEffect, useState, type ReactNode } from "react";
import { Link, NavLink, useLocation } from "react-router-dom";
import { usd } from "../lib/format";
import { useInvites, useMe, useWallet } from "../lib/hooks";
import { isMuted, play, setMuted } from "../lib/sound";
import { Chip } from "./bits";

const NAV = [
  { to: "/", label: "Lobby", icon: "♠" },
  { to: "/tables", label: "My tables", icon: "♣" },
  { to: "/wallet", label: "Wallet", icon: "◆" },
  { to: "/friends", label: "Friends", icon: "♥" },
  { to: "/profile", label: "Profile", icon: "★" },
];

function RealityCheck({ minutes }: { minutes: number }) {
  const [shown, setShown] = useState(false);
  const [played, setPlayed] = useState(0);
  useEffect(() => {
    const id = setInterval(() => {
      setPlayed((p) => p + minutes);
      setShown(true);
    }, minutes * 60_000);
    return () => clearInterval(id);
  }, [minutes]);
  if (!shown) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-6">
      <div className="panel animate-pop max-w-sm p-6 text-center">
        <div className="title text-2xl">Time check</div>
        <p className="mt-2 text-cream/80">You've been playing for {played} minutes. Take a breather?</p>
        <div className="mt-5 flex justify-center gap-3">
          <Link to="/profile" className="btn-ghost" onClick={() => setShown(false)}>
            My limits
          </Link>
          <button className="btn-gold" onClick={() => setShown(false)}>
            Keep playing
          </button>
        </div>
      </div>
    </div>
  );
}

export function Shell({ children }: { children: ReactNode }) {
  const me = useMe();
  const wallet = useWallet(!!me.data);
  const invites = useInvites(!!me.data);
  const [muted, setMutedState] = useState(isMuted);
  const location = useLocation();
  const pending = invites.data?.length ?? 0;

  return (
    <div className="mx-auto flex min-h-screen max-w-6xl flex-col md:flex-row">
      {/* Side rail on larger screens */}
      <aside className="sticky top-0 hidden h-screen w-56 shrink-0 flex-col gap-1 p-4 md:flex">
        <Link to="/" className="mb-6 flex items-center gap-2">
          <Chip color="#e0464b" size={38} />
          <span className="title gold-text text-2xl">Felt Kings</span>
        </Link>
        {NAV.map((n) => (
          <NavLink
            key={n.to}
            to={n.to}
            end={n.to === "/"}
            onClick={() => play("click")}
            className={({ isActive }) =>
              `flex items-center gap-3 rounded-xl px-3 py-2.5 font-display text-lg tracking-wide transition ${
                isActive ? "bg-gold-400/15 text-gold-300 shadow-glow" : "text-cream/70 hover:bg-cream/5 hover:text-cream"
              }`
            }
          >
            <span className="w-5 text-center">{n.icon}</span>
            {n.label}
            {n.to === "/friends" && pending > 0 && (
              <span className="ml-auto rounded-full bg-chip-red px-2 text-xs text-white">{pending}</span>
            )}
          </NavLink>
        ))}
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header
          className="sticky top-0 z-30 flex items-center gap-3 border-b border-gold-400/10 bg-felt-950/85 px-4 py-3 backdrop-blur md:border-none md:bg-transparent"
          style={{ paddingTop: "max(0.75rem, env(safe-area-inset-top))" }}
        >
          <Link to="/" className="flex items-center gap-2 md:hidden">
            <Chip color="#e0464b" size={30} />
            <span className="title gold-text text-xl">Felt Kings</span>
          </Link>
          <div className="flex-1" />
          <button
            className="rounded-full p-2 text-cream/60 hover:text-cream"
            onClick={() => {
              setMuted(!muted);
              setMutedState(!muted);
            }}
            aria-label={muted ? "Turn sound on" : "Turn sound off"}
          >
            {muted ? "🔇" : "🔊"}
          </button>
          <Link
            to="/wallet"
            className="flex items-center gap-2 rounded-full border border-gold-400/30 bg-felt-900/90 py-1 pl-1 pr-4 shadow-glow"
          >
            <Chip color="#e2a72e" size={28} />
            <span className="font-display text-lg text-gold-300">
              {wallet.data ? usd(wallet.data.available_usd_cents) : "—"}
            </span>
          </Link>
        </header>

        <main key={location.pathname} className="flex-1 px-4 pb-28 pt-4 md:pb-10">
          {children}
        </main>
      </div>

      {/* Bottom tab bar on phones */}
      <nav
        className="fixed inset-x-0 bottom-0 z-30 grid grid-cols-5 border-t border-gold-400/15 bg-felt-950/95 backdrop-blur md:hidden"
        style={{ paddingBottom: "env(safe-area-inset-bottom)" }}
      >
        {NAV.map((n) => (
          <NavLink
            key={n.to}
            to={n.to}
            end={n.to === "/"}
            onClick={() => play("click")}
            className={({ isActive }) =>
              `relative flex flex-col items-center gap-0.5 py-2.5 text-[11px] font-semibold ${
                isActive ? "text-gold-300" : "text-cream/55"
              }`
            }
          >
            <span className="text-lg leading-none">{n.icon}</span>
            {n.label}
            {n.to === "/friends" && pending > 0 && (
              <span className="absolute right-[22%] top-1.5 h-2.5 w-2.5 rounded-full bg-chip-red" />
            )}
          </NavLink>
        ))}
      </nav>
      {me.data?.reality_check_minutes ? <RealityCheck minutes={me.data.reality_check_minutes} /> : null}
    </div>
  );
}
