import { useEffect, useState, type ReactNode } from "react";
import { Link, NavLink, useLocation } from "react-router-dom";
import { usd } from "../lib/format";
import { useInvites, useMe, useWallet } from "../lib/hooks";
import { DEMO_PLAYER } from "../lib/native";
import { isMuted, play, setMuted } from "../lib/sound";
import { Avatar } from "./bits";
import { Logo, LogoMark } from "./Brand";
import { Icon, type IconName } from "./Icon";

const NAV: { to: string; label: string; icon: IconName }[] = [
  { to: "/", label: "Lobby", icon: "lobby" },
  { to: "/tables", label: "My tables", icon: "tables" },
  { to: "/wallet", label: "Wallet", icon: "wallet" },
  { to: "/friends", label: "Friends", icon: "friends" },
  { to: "/profile", label: "Profile", icon: "profile" },
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
  const name = me.data?.username ?? "player";
  const toggleSound = () => {
    setMuted(!muted);
    setMutedState(!muted);
  };

  return (
    <div className="mx-auto flex min-h-screen max-w-7xl flex-col md:flex-row">
      {/* Side rail on larger screens */}
      <aside className="sticky top-0 hidden h-screen w-64 shrink-0 flex-col p-4 md:flex">
        <Link to="/" className="mb-8 mt-2 px-2">
          <Logo size={42} />
        </Link>
        <nav className="flex flex-col gap-1">
          {NAV.map((n) => (
            <NavLink
              key={n.to}
              to={n.to}
              end={n.to === "/"}
              onClick={() => play("click")}
              className={({ isActive }) => `nav-item ${isActive ? "active" : ""}`}
            >
              <Icon name={n.icon} size={20} />
              {n.label}
              {n.to === "/friends" && pending > 0 && (
                <span className="ml-auto rounded-full bg-chip-red px-2 py-0.5 font-sans text-xs font-bold text-white">{pending}</span>
              )}
            </NavLink>
          ))}
        </nav>
        <div className="mt-auto space-y-3">
          <Link to="/organize" className="panel block overflow-hidden p-4 transition hover:-translate-y-0.5">
            <div className="eyebrow">Play with friends</div>
            <div className="title mt-1 text-lg leading-snug">Organize a private game</div>
            <div className="mt-2 inline-flex items-center gap-1 text-sm text-gold-300">
              Start <Icon name="chevron" size={16} />
            </div>
          </Link>
          <div className="panel-flat flex items-center gap-3 p-2.5">
            <Avatar name={name} size={38} />
            <div className="min-w-0 flex-1">
              <div className="truncate font-semibold">{name}</div>
              <div className="text-xs text-cream/45">{me.data?.kyc_tier ? "Verified" : "Basic account"}</div>
            </div>
            <button className="btn-icon h-9 w-9" onClick={toggleSound} aria-label={muted ? "Turn sound on" : "Turn sound off"}>
              <Icon name={muted ? "soundOff" : "soundOn"} size={18} />
            </button>
          </div>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header
          className="sticky top-0 z-30 flex items-center gap-2 border-b border-cream/[0.06] bg-[#030c08]/80 px-4 py-2.5 backdrop-blur-xl md:border-none md:bg-transparent md:px-6 md:pt-5 md:backdrop-blur-none"
          style={{ paddingTop: "max(0.625rem, env(safe-area-inset-top))" }}
        >
          <Link to="/" className="md:hidden" aria-label="Felt Kings home">
            <span className="flex items-center gap-2">
              <LogoMark size={32} />
              <span className="title gold-text whitespace-nowrap text-xl">Felt Kings</span>
            </span>
          </Link>
          <div className="flex-1" />
          {DEMO_PLAYER && <span className="badge bg-chip-red/80 text-white">Demo</span>}
          <button className="btn-icon h-9 w-9 md:hidden" onClick={toggleSound} aria-label={muted ? "Turn sound on" : "Turn sound off"}>
            <Icon name={muted ? "soundOff" : "soundOn"} size={18} />
          </button>
          <div className="flex items-center rounded-full border border-gold-400/30 bg-black/40 p-1 shadow-glow">
            <Link to="/wallet" className="flex items-center gap-2 pl-1 pr-3" aria-label="Wallet balance">
              <span className="flex h-7 w-7 items-center justify-center rounded-full bg-gradient-to-b from-gold-300 to-gold-600 text-felt-950">
                <Icon name="wallet" size={15} strokeWidth={2.4} />
              </span>
              <span className="font-display text-lg text-gold-300">{wallet.data ? usd(wallet.data.available_usd_cents) : "—"}</span>
            </Link>
            <Link
              to="/wallet"
              className="flex h-7 w-7 items-center justify-center rounded-full bg-gradient-to-b from-[#1c9a6d] to-felt-600 text-cream shadow-[inset_0_1px_0_rgba(255,255,255,.25)]"
              aria-label="Add money"
              onClick={() => play("click")}
            >
              <Icon name="plus" size={16} strokeWidth={2.6} />
            </Link>
          </div>
        </header>

        <main key={location.pathname} className="flex-1 animate-fadeUp px-4 pb-28 pt-4 md:px-6 md:pb-10">
          {children}
        </main>
      </div>

      {/* Bottom tab bar on phones */}
      <nav
        className="fixed inset-x-0 bottom-0 z-30 grid grid-cols-5 border-t border-cream/[0.07] bg-[#030c08]/90 px-1 backdrop-blur-xl md:hidden"
        style={{ paddingBottom: "env(safe-area-inset-bottom)" }}
      >
        {NAV.map((n) => (
          <NavLink
            key={n.to}
            to={n.to}
            end={n.to === "/"}
            onClick={() => play("click")}
            className={({ isActive }) =>
              `relative flex flex-col items-center gap-1 pb-2 pt-2.5 text-[11px] font-semibold transition ${isActive ? "text-gold-300" : "text-cream/50"}`
            }
          >
            {({ isActive }) => (
              <>
                {isActive && <span className="absolute top-0 h-[3px] w-8 rounded-b-full bg-gold-400 shadow-[0_0_10px_rgba(245,196,81,.9)]" />}
                <span className={`flex h-8 w-12 items-center justify-center rounded-full transition ${isActive ? "bg-gold-400/15" : ""}`}>
                  <Icon name={n.icon} size={21} />
                </span>
                {n.label}
                {n.to === "/friends" && pending > 0 && (
                  <span className="absolute right-[24%] top-2 h-2.5 w-2.5 rounded-full bg-chip-red ring-2 ring-[#030c08]" />
                )}
              </>
            )}
          </NavLink>
        ))}
      </nav>
      {me.data?.reality_check_minutes ? <RealityCheck minutes={me.data.reality_check_minutes} /> : null}
    </div>
  );
}
