import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { Avatar, Chip, Empty, SeatDots, Spinner } from "../components/bits";
import { useToast } from "../components/Toast";
import { api, call, errorMessage } from "../lib/api";
import { TIER_COLORS, usd, when } from "../lib/format";
import { useInvites, useMe, useTiers } from "../lib/hooks";
import { play } from "../lib/sound";
import type { FriendItem, Invite, TablePreview, TableView } from "../lib/types";
import { Icon } from "../components/Icon";
import { EmailSignIn, rememberReturn } from "./Auth";

function InviteCard({ invite }: { invite: Invite }) {
  const toast = useToast();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const t = invite.table;
  const [busy, setBusy] = useState(false);
  const respond = async (accept: boolean) => {
    if (busy) return;
    setBusy(true);
    const path = { params: { path: { invite_id: invite.invite_id } } };
    try {
      if (accept) {
        const table = await call<TableView>(api.POST("/invites/{invite_id}/accept", path));
        play("chip");
        navigate(`/tables/${table.id}`);
      } else {
        await call(api.POST("/invites/{invite_id}/decline", path));
      }
      await Promise.all([qc.invalidateQueries({ queryKey: ["invites"] }), qc.invalidateQueries({ queryKey: ["wallet"] })]);
    } catch (e) {
      toast(errorMessage(e), "error");
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="panel animate-pop overflow-hidden">
      <div className="flex items-center gap-3 bg-gradient-to-r from-gold-400/15 to-transparent px-4 py-3">
        <Avatar name={invite.from} size={34} />
        <div className="text-sm">
          <b>{invite.from}</b> invited you
        </div>
      </div>
      <div className="space-y-2 p-4">
        <div className="title text-2xl">{t.title}</div>
        <div className="flex flex-wrap items-center gap-3 text-sm text-cream/70">
          <span className="font-display text-base text-gold-300">{t.price_label}</span>
          <SeatDots filled={t.players} total={t.seats_total} />
          {t.scheduled_start_at && <span>Starts {when(t.scheduled_start_at)}</span>}
        </div>
        {invite.message && <p className="rounded-lg bg-felt-950/60 px-3 py-2 text-sm italic">“{invite.message}”</p>}
        <div className="flex gap-2 pt-1">
          <button className="btn-ghost flex-1" onClick={() => respond(false)}>
            Not this time
          </button>
          <button className="btn-gold flex-1" onClick={() => respond(true)}>
            I'm in
          </button>
        </div>
      </div>
    </div>
  );
}

interface SentInvite {
  email: string;
  status: "pending" | "joined";
  joined_as: string | null;
  sent_at: string;
}

/** Grow the crew: a personal link to share anywhere, or invites by email. */
export function InviteToApp() {
  const toast = useToast();
  const qc = useQueryClient();
  const [emails, setEmails] = useState("");
  const [busy, setBusy] = useState(false);
  const referral = useQuery({
    queryKey: ["referral"],
    queryFn: () => call<{ code: string; link: string; enabled: boolean; bonus_usd_cents: number; signed_up: number }>(api.GET("/me/referral")),
  });
  const sent = useQuery({ queryKey: ["sent-invites"], queryFn: () => call<SentInvite[]>(api.GET("/me/invites")) });
  const link = referral.data?.link ?? "";
  const text = `Join me on Draely — Sit & Go poker with friends. Sign up with one tap: ${link}`;

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(link);
      play("chip");
      toast("Invite link copied", "ok");
    } catch {
      toast(link, "info");
    }
  };
  const share = async () => {
    try {
      if (navigator.share) await navigator.share({ title: "Draely", text, url: link });
      else await copy();
    } catch {
      /* cancelled */
    }
  };
  const sendEmails = async (e: React.FormEvent) => {
    e.preventDefault();
    const list = emails.split(/[\s,;]+/).filter((x) => x.includes("@"));
    if (!list.length) return toast("Type one or more email addresses.", "info");
    setBusy(true);
    try {
      const r = await call<{ invited: string[]; friend_requests: string[]; skipped: { handle: string; reason: string }[] }>(
        api.POST("/me/invites", { body: { emails: list } }),
      );
      play("chip");
      const parts = [
        r.invited.length && `Invited ${r.invited.length}`,
        r.friend_requests.length && `${r.friend_requests.length} already play — friend request sent`,
        r.skipped.length && `skipped ${r.skipped.map((x) => `${x.handle} (${x.reason.replace("_", " ")})`).join(", ")}`,
      ].filter(Boolean);
      toast(parts.join(" · "), r.invited.length || r.friend_requests.length ? "ok" : "info");
      setEmails("");
      await Promise.all([qc.invalidateQueries({ queryKey: ["sent-invites"] }), qc.invalidateQueries({ queryKey: ["friends"] })]);
    } catch (err) {
      toast(errorMessage(err), "error");
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="panel relative overflow-hidden p-5">
      <div className="pointer-events-none absolute -right-16 -top-16 h-48 w-48 rounded-full bg-gold-400/15 blur-3xl" />
      <div className="relative flex items-start gap-3">
        <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-gold-400/15 text-gold-300">
          <Icon name="gift" size={22} />
        </span>
        <div className="min-w-0">
          <h2 className="title text-2xl">Invite friends to Draely</h2>
          <p className="text-sm text-cream/60">
            Anyone who joins with your link or email becomes your friend automatically
            {referral.data?.enabled && referral.data.bonus_usd_cents > 0 ? ` — and you earn ${usd(referral.data.bonus_usd_cents)} when they play their first paid game` : ""}.
          </p>
        </div>
      </div>

      <div className="relative mt-4 flex gap-2">
        <input className="input font-mono text-sm" readOnly value={link} aria-label="Your invite link" onFocus={(e) => e.currentTarget.select()} />
        <button className="btn-gold shrink-0 px-4" onClick={copy} disabled={!link}>
          <Icon name="link" size={18} /> Copy
        </button>
      </div>
      <div className="relative mt-2 grid grid-cols-2 gap-2">
        <a
          className="btn shrink-0 bg-[#25d366] text-[#06210f] shadow-[0_4px_0_#128c48]"
          href={`https://wa.me/?text=${encodeURIComponent(text)}`}
          target="_blank"
          rel="noreferrer"
        >
          WhatsApp
        </a>
        <button className="btn-ghost" onClick={share} disabled={!link}>
          <Icon name="spark" size={18} /> Share…
        </button>
      </div>

      <form onSubmit={sendEmails} className="relative mt-4 flex gap-2">
        <input
          className="input"
          type="text"
          inputMode="email"
          placeholder="Or invite by email: wanjiru@example.com, kevo@…"
          value={emails}
          onChange={(e) => setEmails(e.target.value)}
          aria-label="Emails to invite"
        />
        <button className="btn-felt shrink-0 px-4" disabled={busy}>
          <Icon name="mail" size={18} /> Send
        </button>
      </form>

      {(sent.data?.length ?? 0) > 0 && (
        <div className="relative mt-4">
          <div className="label">Invited ({sent.data!.filter((x) => x.status === "joined").length} joined)</div>
          <ul className="max-h-48 space-y-1.5 overflow-y-auto text-sm">
            {sent.data!.map((x) => (
              <li key={x.email} className="flex items-center gap-2">
                <Avatar name={x.joined_as ?? x.email} size={24} />
                <span className="min-w-0 flex-1 truncate">{x.joined_as ? `${x.joined_as} · ${x.email}` : x.email}</span>
                {x.status === "joined" ? (
                  <span className="badge bg-chip-green/20 text-chip-green">Joined</span>
                ) : (
                  <span className="badge bg-gold-400/15 text-gold-300">Invited</span>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}

export function Friends() {
  const toast = useToast();
  const qc = useQueryClient();
  const invites = useInvites();
  const friends = useQuery({
    queryKey: ["friends"],
    queryFn: () => call<{ friends: FriendItem[]; incoming: FriendItem[]; outgoing: FriendItem[] }>(api.GET("/friends")),
    refetchInterval: 15_000,
  });
  const [handle, setHandle] = useState("");

  const refresh = () => qc.invalidateQueries({ queryKey: ["friends"] });
  const add = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      const r = await call<{ status: string }>(api.POST("/friends/requests", { body: { handle } }));
      play("chip");
      toast(r.status === "accepted" ? "You're now friends!" : "Friend request sent", "ok");
      setHandle("");
      await refresh();
    } catch (err) {
      toast(errorMessage(err), "error");
    }
  };
  const respond = async (id: string, accept: boolean) => {
    const path = { params: { path: { request_id: id } } };
    await call(accept ? api.POST("/friends/requests/{request_id}/accept", path) : api.POST("/friends/requests/{request_id}/decline", path));
    await refresh();
  };

  return (
    <div className="space-y-6">
      <h1 className="title text-3xl">Friends</h1>
      {(invites.data?.length ?? 0) > 0 && (
        <section>
          <h2 className="label">Game invites</h2>
          <div className="grid gap-4 md:grid-cols-2">
            {invites.data!.map((i) => (
              <InviteCard key={i.invite_id} invite={i} />
            ))}
          </div>
        </section>
      )}

      <InviteToApp />

      <form onSubmit={add} className="panel flex gap-2 p-3">
        <input className="input" placeholder="Add a friend by username or email" value={handle} onChange={(e) => setHandle(e.target.value)} required />
        <button className="btn-gold shrink-0">Add</button>
      </form>

      {friends.isLoading ? (
        <Spinner />
      ) : (
        <>
          {(friends.data?.incoming.length ?? 0) > 0 && (
            <section>
              <h2 className="label">Requests</h2>
              <div className="space-y-2">
                {friends.data!.incoming.map((f) => (
                  <div key={f.request_id} className="panel flex items-center gap-3 p-3">
                    <Avatar name={f.name} />
                    <span className="flex-1 font-semibold">{f.username}</span>
                    <button className="btn-ghost px-3 py-1.5 text-sm" onClick={() => respond(f.request_id!, false)}>
                      Decline
                    </button>
                    <button className="btn-gold px-3 py-1.5 text-sm" onClick={() => respond(f.request_id!, true)}>
                      Accept
                    </button>
                  </div>
                ))}
              </div>
            </section>
          )}
          <section>
            <h2 className="label">Your crew ({friends.data?.friends.length ?? 0})</h2>
            {!friends.data?.friends.length ? (
              <Empty title="No friends yet">Add people you play with, then invite them to tables in one tap.</Empty>
            ) : (
              <div className="grid gap-2 sm:grid-cols-2">
                {friends.data.friends.map((f) => (
                  <div key={f.user_id} className="panel flex items-center gap-3 p-3">
                    <Avatar name={f.name} />
                    <span className="flex-1 font-semibold">{f.username}</span>
                    <button
                      className="text-sm text-cream/40 hover:text-[#ff9a9d]"
                      onClick={async () => {
                        await call(api.DELETE("/friends/{friend_id}", { params: { path: { friend_id: f.user_id } } }));
                        await refresh();
                      }}
                    >
                      Remove
                    </button>
                  </div>
                ))}
              </div>
            )}
            {(friends.data?.outgoing.length ?? 0) > 0 && (
              <p className="mt-3 text-sm text-cream/50">Waiting on: {friends.data!.outgoing.map((f) => f.username).join(", ")}</p>
            )}
          </section>
        </>
      )}
    </div>
  );
}

export function Organize() {
  const allTiers = useTiers();
  // For now players create free tables only; paid stakes run via Quick play.
  const tiers = { ...allTiers, data: allTiers.data?.filter((t) => t.buy_in_cents === 0) };
  const toast = useToast();
  const navigate = useNavigate();
  const friends = useQuery({ queryKey: ["friends"], queryFn: () => call<{ friends: FriendItem[] }>(api.GET("/friends")) });
  const [tierId, setTierId] = useState<number | null>(null);
  const [title, setTitle] = useState("Friday night poker");
  const [message, setMessage] = useState("");
  const [timed, setTimed] = useState(false);
  const [start, setStart] = useState("");
  const [plays, setPlays] = useState(true);
  const [isPublic, setIsPublic] = useState(false);
  const [seats, setSeats] = useState(6);
  const [picked, setPicked] = useState<string[]>([]);
  const [extra, setExtra] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    const tier = tierId ?? tiers.data?.[0]?.id;
    if (!tier) return;
    setBusy(true);
    try {
      const r = await call<{ table: TableView; invited: string[] }>(
        api.POST("/games/organize", {
          body: {
            tier_id: tier,
            title,
            message: message || null,
            scheduled_start_at: timed && start ? new Date(start).toISOString() : null,
            organizer_plays: plays,
            public: isPublic,
            seats,
            invite: [...picked, ...extra.split(/[\s,]+/).filter(Boolean)],
          },
        }),
      );
      play("win");
      toast(`Game created · ${r.invited.length} invited`, "ok");
      navigate(`/tables/${r.table.id}`);
    } catch (err) {
      toast(errorMessage(err), "error");
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} className="mx-auto max-w-2xl space-y-5">
      <div>
        <h1 className="title gold-text text-4xl">Organize a game</h1>
        <p className="text-cream/70">Your table: you choose the stakes, the time and who can join.</p>
      </div>
      <div className="panel space-y-5 p-5">
        <div>
          <label className="label" htmlFor="gtitle">
            Name
          </label>
          <input id="gtitle" className="input font-display text-xl" value={title} onChange={(e) => setTitle(e.target.value)} required maxLength={80} />
        </div>
        <div>
          <div className="label">Stakes</div>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
            {tiers.data?.map((t, i) => {
              const on = (tierId ?? tiers.data?.[0]?.id) === t.id;
              return (
                <button
                  type="button"
                  key={t.id}
                  onClick={() => setTierId(t.id)}
                  className={`flex items-center gap-2 rounded-xl border-2 p-2.5 text-left transition ${
                    on ? "border-gold-400 bg-gold-400/10" : "border-cream/10"
                  }`}
                >
                  <Chip color={TIER_COLORS[i % TIER_COLORS.length]} size={30} />
                  <span className="font-display leading-tight">{t.price_label}</span>
                </button>
              );
            })}
          </div>
        </div>
        <div>
          <div className="label">Seats</div>
          <div className="segmented" role="tablist">
            {[2, 3, 4, 5, 6].map((n) => (
              <button type="button" key={n} role="tab" aria-selected={seats === n} onClick={() => setSeats(n)}>
                {n}
              </button>
            ))}
          </div>
          <p className="mt-1.5 text-xs text-cream/50">The game starts as soon as {seats} players have joined.</p>
        </div>
        <div>
          <div className="label">Who can join</div>
          <div className="segmented" role="tablist">
            <button type="button" role="tab" aria-selected={!isPublic} onClick={() => setIsPublic(false)}>
              <Icon name="lock" size={16} /> Invite only
            </button>
            <button type="button" role="tab" aria-selected={isPublic} onClick={() => setIsPublic(true)}>
              <Icon name="users" size={16} /> Anyone (public)
            </button>
          </div>
          <p className="mt-1.5 text-xs text-cream/50">
            {isPublic
              ? "Listed in the lobby under Open tables - anyone can take a seat. You can still invite friends."
              : "Hidden from the lobby. Only people with your invite link or code can join."}
          </p>
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="flex items-center gap-3 rounded-xl bg-felt-950/60 p-3 text-sm">
            <input type="radio" className="h-5 w-5 accent-gold-400" checked={!timed} onChange={() => setTimed(false)} />
            Start when the table is full
          </label>
          <label className="flex items-center gap-3 rounded-xl bg-felt-950/60 p-3 text-sm">
            <input type="radio" className="h-5 w-5 accent-gold-400" checked={timed} onChange={() => setTimed(true)} />
            Start at a set time
          </label>
        </div>
        {timed && <input className="input" type="datetime-local" required value={start} onChange={(e) => setStart(e.target.value)} />}
        <label className="flex items-center gap-3 text-sm">
          <input type="checkbox" className="h-5 w-5 accent-gold-400" checked={plays} onChange={(e) => setPlays(e.target.checked)} />
          I'm playing too (takes a seat now)
        </label>
        <div>
          <div className="label">Invite</div>
          <div className="flex flex-wrap gap-2">
            {friends.data?.friends.map((f) => {
              const on = picked.includes(f.username ?? "");
              return (
                <button
                  type="button"
                  key={f.user_id}
                  className={`flex items-center gap-2 rounded-full border px-2 py-1 pr-3 text-sm ${
                    on ? "border-gold-400 bg-gold-400/15 text-gold-300" : "border-cream/15"
                  }`}
                  onClick={() => f.username && setPicked((p) => (on ? p.filter((x) => x !== f.username) : [...p, f.username!]))}
                >
                  <Avatar name={f.name} size={22} />
                  {f.username}
                </button>
              );
            })}
          </div>
          <input className="input mt-2" placeholder="More usernames or emails, comma separated" value={extra} onChange={(e) => setExtra(e.target.value)} />
        </div>
        <div>
          <label className="label" htmlFor="gmsg">
            Message
          </label>
          <input id="gmsg" className="input" placeholder="Bring snacks 🍿" value={message} onChange={(e) => setMessage(e.target.value)} maxLength={500} />
        </div>
      </div>
      <button className="btn-gold w-full py-3.5 text-xl" disabled={busy}>
        Create game &amp; send invites
      </button>
    </form>
  );
}

export function JoinByCode() {
  const { code = "" } = useParams();
  const [params] = useSearchParams();
  const me = useMe();
  const toast = useToast();
  const navigate = useNavigate();
  const [signingUp, setSigningUp] = useState(false);
  const preview = useQuery({
    queryKey: ["preview", code],
    queryFn: () => call<TablePreview>(api.GET("/invites/code/{code}", { params: { path: { code } } })),
    retry: false,
  });
  const joining = useRef(false);
  const join = async () => {
    if (joining.current) return;
    if (!me.data) return setSigningUp(true);
    if (!me.data.username || !me.data.terms_accepted) {
      rememberReturn(`/join/${code}`);
      return navigate("/welcome");
    }
    joining.current = true;
    try {
      await call(api.POST("/tables/{table_id}/join", { params: { path: { table_id: preview.data!.table_id } }, body: { invite_code: code } }));
      // Joined through someone's link: you become friends with them.
      const ref = params.get("ref");
      if (ref) {
        await call(api.POST("/invites/personal/{code}/connect", { params: { path: { code: ref } } })).catch(() => undefined);
      }
      play("chip");
      navigate(`/tables/${preview.data!.table_id}`);
    } catch (e) {
      toast(errorMessage(e), "error");
    } finally {
      joining.current = false;
    }
  };
  if (preview.isLoading) return <Spinner />;
  if (!preview.data)
    return (
      <div className="mx-auto max-w-sm py-16 text-center">
        <div className="title text-2xl">This invite link isn't valid</div>
        <Link to="/" className="btn-gold mt-5">
          Go to the lobby
        </Link>
      </div>
    );
  const t = preview.data;
  return (
    <div className="mx-auto flex min-h-[70vh] max-w-md items-center">
      <div className="panel w-full animate-pop overflow-hidden text-center">
        <div className="bg-gradient-to-b from-felt-600 to-felt-800 px-6 py-8">
          <div className="text-sm uppercase tracking-[0.3em] text-cream/60">You're invited</div>
          <div className="title gold-text mt-2 text-4xl">{t.title}</div>
          {t.organizer && <div className="mt-1 text-cream/70">by {t.organizer}</div>}
        </div>
        <div className="space-y-4 p-6">
          <div className="font-display text-2xl text-gold-300">{t.price_label}</div>
          <div className="flex justify-center">
            <SeatDots filled={t.players} total={t.seats_total} />
          </div>
          {t.scheduled_start_at && <div className="text-cream/70">Starts {when(t.scheduled_start_at)}</div>}
          {t.message && <p className="italic text-cream/80">“{t.message}”</p>}
          {signingUp && !me.data ? (
            <div className="space-y-2 text-left">
              <p className="text-center text-sm text-cream/65">
                New here? Enter your email — the link signs you up and brings you straight back to this table.
              </p>
              <EmailSignIn refCode={params.get("ref") ?? t.organizer_ref} next={`/join/${code}`} cta="Email me my seat link" compact />
            </div>
          ) : (
            <button className="btn-gold w-full py-3 text-xl" disabled={t.status !== "open"} onClick={join}>
              {t.status !== "open" ? "This game has started" : me.data ? "Take my seat" : (
                <>
                  <Icon name="seat" size={20} /> Join this game
                </>
              )}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
