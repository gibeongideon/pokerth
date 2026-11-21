/**
 * /i/<code> - a player's personal invite link (WhatsApp, SMS, anywhere).
 * Newcomers type their email right here and get a one-tap sign-in link; the
 * new account is credited to the inviter and the two become friends.
 * Someone already signed in can add the inviter as a friend instead.
 */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { Avatar, Chip, Spinner } from "../components/bits";
import { CardFan, Logo } from "../components/Brand";
import { Icon, type IconName } from "../components/Icon";
import { useToast } from "../components/Toast";
import { api, call, errorMessage } from "../lib/api";
import { useMe } from "../lib/hooks";
import { play } from "../lib/sound";
import { EmailSignIn, GoogleButton, rememberRef } from "./Auth";

interface Inviter {
  code: string;
  inviter: string;
  username: string | null;
}

const STEPS: { icon: IconName; text: string }[] = [
  { icon: "mail", text: "Enter your email — we send a one-tap sign-in link" },
  { icon: "profile", text: "Pick your table name (18+ only)" },
  { icon: "seat", text: "Top up with M-Pesa or card and take a seat" },
];

export function InviteLanding() {
  const { code = "" } = useParams();
  const me = useMe();
  const qc = useQueryClient();
  const toast = useToast();
  const navigate = useNavigate();
  const [added, setAdded] = useState(false);
  const inviter = useQuery({
    queryKey: ["personal-invite", code],
    queryFn: () => call<Inviter>(api.GET("/invites/personal/{code}", { params: { path: { code } } })),
    retry: false,
  });
  useEffect(() => rememberRef(code), [code]);
  // Already a player: opening the link makes you friends right away.
  const connected = useRef(false);
  useEffect(() => {
    if (!me.data || !inviter.data || connected.current) return;
    connected.current = true;
    call<{ connected: boolean }>(api.POST("/invites/personal/{code}/connect", { params: { path: { code } } }))
      .then(async (r) => {
        if (r.connected) {
          setAdded(true);
          play("chip");
          await qc.invalidateQueries({ queryKey: ["friends"] });
        }
      })
      .catch(() => undefined);
  }, [me.data, inviter.data, code, qc]);

  if (inviter.isLoading || me.isLoading) return <Spinner />;
  if (!inviter.data) {
    return (
      <div className="mx-auto flex min-h-screen max-w-sm flex-col items-center justify-center gap-4 px-6 text-center">
        <Logo size={44} />
        <div className="title text-2xl">This invite link isn't valid</div>
        <Link to="/login" className="btn-gold">
          Sign in or join anyway
        </Link>
      </div>
    );
  }
  const who = inviter.data.inviter;

  const addFriend = async () => {
    try {
      await call(api.POST("/friends/requests", { body: { handle: inviter.data!.username ?? "" } }));
      await qc.invalidateQueries({ queryKey: ["friends"] });
      play("chip");
      setAdded(true);
    } catch (e) {
      toast(errorMessage(e), "error");
    }
  };

  return (
    <div className="mx-auto grid min-h-screen max-w-5xl items-center gap-10 px-5 py-10 md:grid-cols-2 md:gap-14">
      <div>
        <Logo size={44} />
        <div className="mt-8 flex items-center gap-4">
          <Avatar name={who} size={64} ring="#f5c451" />
          <div>
            <div className="eyebrow">You're invited</div>
            <h1 className="title text-3xl leading-tight md:text-4xl">
              <span className="gold-text">{who}</span> wants you at the table
            </h1>
          </div>
        </div>
        <p className="mt-4 max-w-md text-cream/70">
          Draely is Sit &amp; Go poker with your crew. One price up front, the prize pool shown before you sit, winnings paid to
          your wallet.
        </p>
        <ol className="mt-6 space-y-3">
          {STEPS.map((s, i) => (
            <li key={s.text} className="flex items-center gap-3 text-sm text-cream/75">
              <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full border border-gold-400/30 bg-gold-400/10 font-display text-gold-300">
                {i + 1}
              </span>
              <Icon name={s.icon} size={16} className="shrink-0 text-cream/40" />
              {s.text}
            </li>
          ))}
        </ol>
      </div>

      <div className="relative w-full max-w-md justify-self-center md:justify-self-end">
        <div className="pointer-events-none absolute -right-8 -top-28 z-10 hidden rotate-12 md:block">
          <CardFan width={66} />
        </div>
        <span className="pointer-events-none absolute -bottom-6 -left-6 hidden animate-float md:block">
          <Chip color="#e0464b" size={60} />
        </span>
        <div className="panel relative space-y-4 p-6 md:p-8">
          {me.data ? (
            added ? (
              <div className="space-y-3 text-center">
                <span className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl bg-chip-green/15 text-chip-green">
                  <Icon name="check" size={28} />
                </span>
                <div className="title text-2xl">You and {who} are now friends</div>
                <p className="text-sm text-cream/60">Invite each other to tables in one tap.</p>
                <button className="btn-gold w-full" onClick={() => navigate("/")}>
                  Go to the lobby
                </button>
              </div>
            ) : (
              <>
                <div className="title text-2xl">You already have an account</div>
                <p className="text-sm text-cream/60">Add {who} as a friend so you can invite each other to tables in one tap.</p>
                <button className="btn-gold w-full py-3 text-lg" onClick={addFriend} disabled={!inviter.data.username}>
                  <Icon name="users" size={18} /> Add {who} as a friend
                </button>
                <Link to="/" className="btn-ghost w-full">
                  Go to the lobby
                </Link>
              </>
            )
          ) : (
            <>
              <div>
                <h2 className="title text-3xl">Join {who}</h2>
                <p className="mt-1 text-sm text-cream/55">Free to join. No password — just your email.</p>
              </div>
              <EmailSignIn refCode={code} next="/" cta="Join with my email" compact />
              <div className="flex items-center gap-3 text-xs text-cream/35">
                <span className="h-px flex-1 bg-cream/10" /> or <span className="h-px flex-1 bg-cream/10" />
              </div>
              <GoogleButton />
              <p className="flex items-center justify-center gap-1.5 text-center text-xs text-cream/45">
                <Icon name="shield" size={14} /> 18+ only · Already a player?{" "}
                <Link to="/login" className="text-gold-300 underline-offset-2 hover:underline">
                  Sign in
                </Link>
              </p>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
