import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { Chip } from "../components/bits";
import { useToast } from "../components/Toast";
import { api, call, errorMessage, setToken } from "../lib/api";
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

function Logo() {
  return (
    <div className="flex flex-col items-center">
      <div className="relative mb-3 flex">
        <span className="-mr-4 animate-float" style={{ animationDelay: "0s" }}>
          <Chip color="#35b26b" size={56} />
        </span>
        <span className="z-10 -mt-3 animate-float" style={{ animationDelay: ".4s" }}>
          <Chip color="#e0464b" size={68} />
        </span>
        <span className="-ml-4 animate-float" style={{ animationDelay: ".8s" }}>
          <Chip color="#3d7be0" size={56} />
        </span>
      </div>
      <h1 className="title gold-text text-5xl">Felt Kings</h1>
      <p className="mt-2 text-center text-cream/70">Sit &amp; Go poker. Real stakes. Your crew.</p>
    </div>
  );
}

export function Login() {
  const [params] = useSearchParams();
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);
  const [busy, setBusy] = useState(false);
  const toast = useToast();
  const navigate = useNavigate();
  const qc = useQueryClient();

  useEffect(() => remember(REF_KEY, params.get("ref")), [params]);

  const send = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      await call(api.POST("/auth/magic-link", { body: { email, ref: recall(REF_KEY) } }));
      play("chip");
      setSent(true);
    } catch (err) {
      toast(errorMessage(err), "error");
    } finally {
      setBusy(false);
    }
  };

  const demo = async (name: string) => {
    const res = await fetch(`/api/dev/token/${name}`, { method: "POST" });
    if (!res.ok) return toast("Demo players need the local seed (python -m app.seed).", "error");
    setToken(((await res.json()) as { access_token: string }).access_token);
    await qc.invalidateQueries();
    play("ready");
    navigate(afterSignIn());
  };

  return (
    <div className="flex min-h-screen items-center justify-center px-4 py-10">
      <div className="w-full max-w-md">
        <Logo />
        <div className="panel mt-8 p-6">
          {sent ? (
            <div className="animate-pop text-center">
              <div className="text-5xl">📬</div>
              <h2 className="title mt-3 text-2xl">Check your email</h2>
              <p className="mt-2 text-cream/70">
                We sent a sign-in link to <b className="text-cream">{email}</b>. It works once and expires in 15 minutes.
              </p>
              <button className="btn-ghost mt-5" onClick={() => setSent(false)}>
                Use another email
              </button>
            </div>
          ) : (
            <form onSubmit={send} className="space-y-4">
              <h2 className="title text-2xl">Sign in or join</h2>
              <div>
                <label className="label" htmlFor="email">
                  Email
                </label>
                <input
                  id="email"
                  className="input"
                  type="email"
                  autoComplete="email"
                  required
                  placeholder="you@example.com"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                />
              </div>
              <button className="btn-gold w-full text-lg" disabled={busy}>
                {busy ? "Sending…" : "Email me a sign-in link"}
              </button>
              <button type="button" className="btn-ghost w-full" disabled title="Needs a Google client ID">
                Continue with Google
              </button>
              <p className="text-center text-xs text-cream/45">No password needed. 18+ only.</p>
            </form>
          )}
        </div>

        {import.meta.env.DEV && (
          <div className="panel mt-4 border-dashed p-4">
            <div className="label">Local demo · sign in as</div>
            <div className="flex flex-wrap gap-2">
              {DEMO_PLAYERS.map((p) => (
                <button key={p} className="btn-felt px-3 py-1.5 text-sm" onClick={() => demo(p)}>
                  {p}
                </button>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
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
    call(api.POST("/auth/magic-link/verify", { body: { token, client: "web" } }))
      .then(async () => {
        setToken(null);
        await qc.invalidateQueries();
        play("ready");
        navigate(afterSignIn(), { replace: true });
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
