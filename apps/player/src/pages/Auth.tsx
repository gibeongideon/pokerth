import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { Avatar, Chip } from "../components/bits";
import { CardFan, LogoMark } from "../components/Brand";
import { Icon, type IconName } from "../components/Icon";
import { useToast } from "../components/Toast";
import { api, call, errorMessage, setToken, storeSession } from "../lib/api";
import { API_BASE, DEV_TOOLS, isNative } from "../lib/native";
import { useMe } from "../lib/hooks";
import { play } from "../lib/sound";

const REF_KEY = "fk.ref";
const RETURN_KEY = "fk.returnTo";
const DEMO_PLAYERS = ["alice", "bob", "carol", "dave", "erin", "frank", "grace"];

function remember(key: string, value: string | null) {
  try {
    if (value) sessionStorage.setItem(key, value);
  } catch {
    /* ignore */
  }
}
function recall(key: string): string | null {
  try {
    return sessionStorage.getItem(key);
  } catch {
    return null;
  }
}

export function afterSignIn(): string {
  const to = recall(RETURN_KEY) || "/";
  try {
    sessionStorage.removeItem(RETURN_KEY);
  } catch {
    /* ignore */
  }
  return to;
}

export function rememberReturn(path: string) {
  remember(RETURN_KEY, path);
}

/** Keep an invite/referral code for the sign-up that follows. */
export function rememberRef(code: string | null) {
  remember(REF_KEY, code);
}

/** Same-site path only (no //host, no scheme). */
export function safeNext(path: string | null): string | null {
  return path && path.startsWith("/") && !path.startsWith("//") && path.length <= 200 ? path : null;
}

/** After any sign-in: new players see the welcome step first, then `next`. */
function finishSignIn(res: unknown, next: string | null, navigate: (to: string, o?: { replace?: boolean }) => void) {
  const user = (res as { user?: { username: string | null; terms_accepted: boolean } }).user;
  if (!(user?.username && user.terms_accepted)) {
    if (next) rememberReturn(next);
    return navigate("/welcome", { replace: true });
  }
  if (next) afterSignIn(); // drop any older same-device fallback
  navigate(next ?? afterSignIn(), { replace: true });
}

/**
 * Email -> magic link. Used by the sign-in page and by invite pages, so a
 * newcomer can sign up right where the invite landed them. The link carries
 * the referral code and brings them back to `next` - even on another device.
 */
export function EmailSignIn({ refCode, next, cta = "Email me a sign-in link", compact }: {
  refCode?: string | null;
  next?: string | null;
  cta?: string;
  compact?: boolean;
}) {
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [code, setCode] = useState("");
  const toast = useToast();
  const navigate = useNavigate();
  const qc = useQueryClient();

  const signInWithCode = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      const res = await call(api.POST("/auth/magic-link/verify-code", { body: { email, code, client: isNative ? "app" : "web" } }));
      await storeSession(res as { access_token?: string; refresh_token?: string });
      await qc.invalidateQueries();
      play("ready");
      finishSignIn(res, safeNext(next ?? null), navigate);
    } catch (err) {
      toast(errorMessage(err), "error");
    } finally {
      setBusy(false);
    }
  };

  const send = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    const ref = refCode ?? recall(REF_KEY);
    const to = safeNext(next ?? recall(RETURN_KEY));
    if (next) rememberReturn(next); // same-device fallback
    try {
      await call(api.POST("/auth/magic-link", { body: { email, ref: ref || null, next: to } }));
      play("chip");
      setSent(true);
    } catch (err) {
      toast(errorMessage(err), "error");
    } finally {
      setBusy(false);
    }
  };

  if (sent) {
    return (
      <div className="animate-pop space-y-3 text-center">
        <span className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl bg-gold-400/15 text-gold-300">
          <Icon name="mail" size={28} />
        </span>
        <h2 className="title text-2xl">Check your email</h2>
        <p className="text-cream/70">
          We sent a sign-in link to <b className="text-cream">{email}</b>.{" "}
          {isNative ? "Type the 6-digit code from it below." : "Tap it on any device, or type the 6-digit code from it here."}
        </p>
        <form onSubmit={signInWithCode} className="space-y-2 text-left">
          <input
            className="input text-center font-display text-3xl tracking-[0.4em]"
            inputMode="numeric"
            autoComplete="one-time-code"
            placeholder="••••••"
            maxLength={7}
            value={code}
            onChange={(e) => setCode(e.target.value.replace(/[^0-9 ]/g, ""))}
            aria-label="6-digit code"
          />
          <button className="btn-gold w-full py-3 text-lg" disabled={busy || code.replace(/\D/g, "").length !== 6}>
            {busy ? "Checking…" : "Sign in with code"}
          </button>
        </form>
        <button className="btn-ghost" onClick={() => setSent(false)}>
          Use another email
        </button>
      </div>
    );
  }
  return (
    <form onSubmit={send} className="space-y-3">
      {!compact && (
        <label className="label" htmlFor="email">
          Email
        </label>
      )}
      <input
        id="email"
        className="input"
        type="email"
        autoComplete="email"
        required
        placeholder="you@example.com"
        aria-label="Email"
        value={email}
        onChange={(e) => setEmail(e.target.value)}
      />
      <button className="btn-gold w-full py-3 text-lg" disabled={busy}>
        <Icon name="mail" size={18} strokeWidth={2.4} /> {busy ? "Sending…" : cta}
      </button>
    </form>
  );
}

const PERKS: { icon: IconName; title: string; text: string }[] = [
  { icon: "phone", title: "M-Pesa or card in seconds", text: "Top up with an STK push or any card. Fund a friend too." },
  { icon: "trophy", title: "Prize shown before you sit", text: "One price up front. Nothing taken while you play." },
  { icon: "bolt", title: "Cash out to M-Pesa", text: "Winnings land in your wallet the moment the game ends." },
];

function Hero() {
  return (
    <div className="relative">
      <div className="flex items-center gap-3">
        <LogoMark size={56} />
        <span className="title gold-text text-4xl md:text-5xl">Felt Kings</span>
      </div>
      <h1 className="title mt-6 text-4xl leading-[1.05] md:text-6xl">
        Sit &amp; Go poker.
        <br />
        <span className="gold-text">Real stakes. Your crew.</span>
      </h1>
      <ul className="mt-8 hidden space-y-4 md:block">
        {PERKS.map((p) => (
          <li key={p.title} className="flex items-start gap-3">
            <span className="mt-0.5 flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border border-gold-400/30 bg-gold-400/10 text-gold-300">
              <Icon name={p.icon} size={20} />
            </span>
            <span>
              <b className="block font-display text-lg tracking-wide">{p.title}</b>
              <span className="text-sm text-cream/60">{p.text}</span>
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function Login() {
  const [params] = useSearchParams();
  const toast = useToast();
  const navigate = useNavigate();
  const qc = useQueryClient();

  useEffect(() => remember(REF_KEY, params.get("ref")), [params]);

  const demo = async (name: string) => {
    const res = await fetch(`${API_BASE}/dev/token/${name}`, { method: "POST" });
    if (!res.ok) return toast("Demo players need the local seed (python -m app.seed).", "error");
    setToken(((await res.json()) as { access_token: string }).access_token);
    await qc.invalidateQueries();
    play("ready");
    navigate(afterSignIn());
  };

  return (
    <div className="mx-auto grid min-h-screen max-w-6xl items-center gap-10 px-5 py-10 md:grid-cols-[1.1fr_1fr] md:gap-16 md:px-10">
      <div className="relative">
        <Hero />
        <div className="pointer-events-none absolute -right-4 -top-6 opacity-90 md:hidden">
          <CardFan width={52} />
        </div>
      </div>
      <div className="relative w-full max-w-md justify-self-center md:justify-self-end">
        <div className="pointer-events-none absolute -right-10 -top-32 z-10 hidden rotate-12 md:block">
          <CardFan width={70} />
        </div>
        <span className="pointer-events-none absolute -bottom-6 -right-6 hidden animate-float md:block">
          <Chip color="#3d7be0" size={64} />
        </span>
        <div className="panel relative space-y-4 p-6 md:p-8">
          <div>
            <h2 className="title text-3xl">Sign in or join</h2>
            <p className="mt-1 text-sm text-cream/55">We'll email you a one-tap link. No password to remember.</p>
          </div>
          <EmailSignIn />
          <div className="flex items-center gap-3 text-xs text-cream/35">
            <span className="h-px flex-1 bg-cream/10" /> or <span className="h-px flex-1 bg-cream/10" />
          </div>
          <GoogleButton />
          <p className="flex items-center justify-center gap-1.5 text-center text-xs text-cream/45">
            <Icon name="shield" size={14} /> 18+ only · Play responsibly
          </p>
        </div>

        {DEV_TOOLS && (
          <div className="panel-flat relative mt-4 border-dashed p-4">
            <div className="label">Local demo · sign in as</div>
            <div className="flex flex-wrap gap-2">
              {DEMO_PLAYERS.map((p) => (
                <button key={p} className="flex items-center gap-2 rounded-full border border-cream/10 bg-black/20 py-1 pl-1 pr-3 text-sm font-semibold transition hover:border-gold-400/50" onClick={() => demo(p)}>
                  <Avatar name={p} size={24} /> {p}
                </button>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

export function GoogleButton() {
  return (
    <button type="button" className="btn w-full border border-cream/15 bg-white/[0.04] text-cream/60" disabled title="Needs a Google client ID">
      <svg width="18" height="18" viewBox="0 0 48 48" aria-hidden>
        <path fill="#FFC107" d="M43.6 20.5H42V20H24v8h11.3C33.7 32.7 29.2 36 24 36c-6.6 0-12-5.4-12-12s5.4-12 12-12c3 0 5.8 1.1 7.9 3l5.7-5.7C34 6.1 29.3 4 24 4 12.9 4 4 12.9 4 24s8.9 20 20 20 20-8.9 20-20c0-1.3-.1-2.4-.4-3.5z" />
        <path fill="#FF3D00" d="m6.3 14.7 6.6 4.8C14.7 15.1 19 12 24 12c3 0 5.8 1.1 7.9 3l5.7-5.7C34 6.1 29.3 4 24 4 16.3 4 9.7 8.3 6.3 14.7z" />
        <path fill="#4CAF50" d="M24 44c5.2 0 9.9-2 13.4-5.2l-6.2-5.2C29.2 35.1 26.7 36 24 36c-5.2 0-9.6-3.3-11.3-8l-6.5 5C9.5 39.6 16.2 44 24 44z" />
        <path fill="#1976D2" d="M43.6 20.5H42V20H24v8h11.3c-.8 2.2-2.2 4.2-4.1 5.6l6.2 5.2C37 39.2 44 34 44 24c0-1.3-.1-2.4-.4-3.5z" />
      </svg>
      Continue with Google
    </button>
  );
}

export function AuthCallback() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const once = useRef(false);

  useEffect(() => {
    if (once.current) return;
    once.current = true;
    const token = params.get("token");
    if (!token) return setError("This link is missing its token.");
    call(api.POST("/auth/magic-link/verify", { body: { token, client: isNative ? "app" : "web" } }))
      .then(async (res) => {
        setToken(null);
        await storeSession(res as { access_token?: string; refresh_token?: string }); // app only
        await qc.invalidateQueries();
        play("ready");
        // `next` came in the link itself, so it works on another device too.
        finishSignIn(res, safeNext(params.get("next")), navigate);
      })
      .catch((e) => setError(errorMessage(e)));
  }, [params, navigate, qc]);

  return (
    <div className="flex min-h-screen items-center justify-center p-6 text-center">
      {error ? (
        <div className="panel max-w-sm p-6">
          <div className="title text-2xl">Link didn't work</div>
          <p className="mt-2 text-cream/70">{error}</p>
          <button className="btn-gold mt-5" onClick={() => navigate("/login")}>
            Get a new link
          </button>
        </div>
      ) : (
        <div className="title animate-pulse text-2xl">Dealing you in…</div>
      )}
    </div>
  );
}

export function Welcome() {
  const me = useMe();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const toast = useToast();
  const [username, setUsername] = useState("");
  const [adult, setAdult] = useState(false);
  const [terms, setTerms] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (me.data?.username) setUsername(me.data.username);
  }, [me.data?.username]);

  const save = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      if (username !== me.data?.username) {
        await call(api.PATCH("/me", { body: { username } }));
      }
      if (!me.data?.terms_accepted) {
        await call(api.POST("/me/accept-terms", { body: { confirm_over_18: adult, accept_terms: terms } }));
      }
      await qc.invalidateQueries({ queryKey: ["me"] });
      play("win");
      navigate(afterSignIn(), { replace: true });
    } catch (err) {
      toast(errorMessage(err), "error");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center px-4 py-10">
      <form onSubmit={save} className="panel w-full max-w-md space-y-5 p-6">
        <div>
          <h1 className="title gold-text text-4xl">Welcome, king</h1>
          <p className="mt-1 text-cream/70">Pick the name other players see at the table.</p>
        </div>
        <div>
          <label className="label" htmlFor="username">
            Table name
          </label>
          <input
            id="username"
            className="input font-display text-lg tracking-wide"
            value={username}
            onChange={(e) => setUsername(e.target.value.toLowerCase())}
            pattern="[a-z0-9_]{3,20}"
            title="3-20 letters, numbers or _"
            required
            placeholder="ace_of_nairobi"
          />
          <p className="mt-1 text-xs text-cream/45">3–20 letters, numbers or _</p>
        </div>
        {!me.data?.terms_accepted && (
          <div className="space-y-3 rounded-xl bg-felt-950/60 p-4">
            <label className="flex items-start gap-3 text-sm">
              <input type="checkbox" className="mt-0.5 h-5 w-5 accent-gold-400" checked={adult} onChange={(e) => setAdult(e.target.checked)} />
              I am 18 or older.
            </label>
            <label className="flex items-start gap-3 text-sm">
              <input type="checkbox" className="mt-0.5 h-5 w-5 accent-gold-400" checked={terms} onChange={(e) => setTerms(e.target.checked)} />
              I accept the terms and the responsible gaming rules.
            </label>
          </div>
        )}
        <button className="btn-gold w-full text-lg" disabled={busy || (!me.data?.terms_accepted && !(adult && terms))}>
          Let's play
        </button>
      </form>
    </div>
  );
}
