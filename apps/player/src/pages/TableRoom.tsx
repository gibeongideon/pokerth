import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { Avatar, Ring, SeatDots, Spinner, StatusBadge } from "../components/bits";
import { useToast } from "../components/Toast";
import { TableCanvas, type CanvasSeat } from "../game/TableCanvas";
import { api, call, errorMessage } from "../lib/api";
import { usd, when } from "../lib/format";
import { useMe, useSecondsLeft } from "../lib/hooks";
import { play } from "../lib/sound";
import type { FriendItem, TableView } from "../lib/types";

function InvitePanel({ table, onClose }: { table: TableView; onClose: () => void }) {
  const toast = useToast();
  const friends = useQuery({
    queryKey: ["friends"],
    queryFn: () => call<{ friends: FriendItem[] }>(api.GET("/friends")),
  });
  const [picked, setPicked] = useState<string[]>([]);
  const [extra, setExtra] = useState("");
  const [message, setMessage] = useState("");
  const link = table.invite_code ? `${location.origin}/join/${table.invite_code}` : `${location.origin}/tables/${table.id}`;

  const send = async () => {
    const handles = [...picked, ...extra.split(/[\s,]+/).filter(Boolean)];
    if (!handles.length) return toast("Pick a friend or type a username/email.", "info");
    try {
      const r = await call<{ invited: string[]; skipped: { handle: string; reason: string }[] }>(
        api.POST("/tables/{table_id}/invites", {
          params: { path: { table_id: table.id } },
          body: { handles, message: message || null },
        }),
      );
      play("chip");
      toast(
        `Invited ${r.invited.length}${r.skipped.length ? ` · skipped ${r.skipped.map((s) => `${s.handle} (${s.reason.replace("_", " ")})`).join(", ")}` : ""}`,
        r.invited.length ? "ok" : "info",
      );
      onClose();
    } catch (e) {
      toast(errorMessage(e), "error");
    }
  };

  const share = async () => {
    const text = `Join my poker table (${table.price_label}) on Felt Kings`;
    try {
      if (navigator.share) await navigator.share({ title: "Felt Kings", text, url: link });
      else {
        await navigator.clipboard.writeText(link);
        toast("Link copied", "ok");
      }
    } catch {
      /* cancelled */
    }
  };

  return (
    <div className="fixed inset-0 z-40 flex items-end justify-center bg-black/60 p-0 sm:items-center sm:p-6" onClick={onClose}>
      <div className="panel animate-pop w-full max-w-md rounded-b-none p-5 sm:rounded-2xl" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between">
          <h3 className="title text-2xl">Invite friends</h3>
          <button className="text-2xl text-cream/50" onClick={onClose} aria-label="Close">
            ×
          </button>
        </div>
        {(friends.data?.friends.length ?? 0) > 0 && (
          <div className="mt-4 flex flex-wrap gap-2">
            {friends.data!.friends.map((f) => {
              const on = picked.includes(f.username ?? "");
              return (
                <button
                  key={f.user_id}
                  className={`flex items-center gap-2 rounded-full border px-2 py-1 pr-3 text-sm transition ${
                    on ? "border-gold-400 bg-gold-400/15 text-gold-300" : "border-cream/15 text-cream/80"
                  }`}
                  onClick={() =>
                    f.username && setPicked((p) => (on ? p.filter((x) => x !== f.username) : [...p, f.username!]))
                  }
                >
                  <Avatar name={f.name} size={24} /> {f.username}
                </button>
              );
            })}
          </div>
        )}
        <label className="label mt-4" htmlFor="handles">
          Usernames or emails
        </label>
        <input id="handles" className="input" placeholder="kevo, wanjiru@example.com" value={extra} onChange={(e) => setExtra(e.target.value)} />
        <label className="label mt-3" htmlFor="msg">
          Message (optional)
        </label>
        <input id="msg" className="input" placeholder="One seat left, come!" value={message} onChange={(e) => setMessage(e.target.value)} />
        <div className="mt-5 flex gap-2">
          <button className="btn-ghost flex-1" onClick={share}>
            🔗 Share link
          </button>
          <button className="btn-gold flex-1" onClick={send}>
            Send invites
          </button>
        </div>
      </div>
    </div>
  );
}

function Rsvp({ tableId }: { tableId: string }) {
  const rsvp = useQuery({
    queryKey: ["rsvp", tableId],
    queryFn: () =>
      call<{ invitee: string; status: string }[]>(api.GET("/tables/{table_id}/invites", { params: { path: { table_id: tableId } } })),
    refetchInterval: 8000,
  });
  if (!rsvp.data?.length) return null;
  const icon: Record<string, string> = { accepted: "✅", declined: "✖️", pending: "⏳", expired: "⌛", revoked: "🚫" };
  return (
    <div className="panel p-4">
      <div className="label">Who's coming</div>
      <ul className="space-y-1.5 text-sm">
        {rsvp.data.map((r) => (
          <li key={r.invitee} className="flex items-center gap-2">
            <span>{icon[r.status] ?? "•"}</span>
            <span className="flex-1 truncate">{r.invitee}</span>
            <span className="text-cream/50">{r.status}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function TableRoom() {
  const { id = "" } = useParams();
  const me = useMe();
  const toast = useToast();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [inviting, setInviting] = useState(false);
  const table = useQuery({
    queryKey: ["table", id],
    queryFn: () => call<TableView>(api.GET("/tables/{table_id}", { params: { path: { table_id: id } } })),
    refetchInterval: (q) => (q.state.data?.status === "finished" || q.state.data?.status === "cancelled" ? false : 2000),
  });
  const t = table.data;
  const readyLeft = useSecondsLeft(t?.status === "ready_check" ? t.ready_deadline : null);
  const pullOutDeadline = useMemo(
    () => (t?.me?.can_pull_out ? new Date(Date.now() + t.me.pull_out_seconds_left * 1000).toISOString() : null),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [t?.me?.can_pull_out, t?.status],
  );
  const pullOutLeft = useSecondsLeft(pullOutDeadline);

  // Sounds on state changes.
  const lastStatus = useRef<string | undefined>(undefined);
  useEffect(() => {
    if (!t) return;
    if (lastStatus.current && lastStatus.current !== t.status) {
      if (t.status === "ready_check") play("ready");
      if (t.status === "finished" && (t.me?.prize_cents ?? 0) > 0) play("win");
    }
    lastStatus.current = t.status;
  }, [t]);

  const act = async (fn: () => Promise<unknown>, sound: "chip" | "ready" = "chip") => {
    try {
      await fn();
      play(sound);
      await Promise.all([qc.invalidateQueries({ queryKey: ["table", id] }), qc.invalidateQueries({ queryKey: ["wallet"] })]);
    } catch (e) {
      toast(errorMessage(e), "error");
    }
  };

  const seats: CanvasSeat[] = useMemo(
    () =>
      (t?.seats ?? []).map((s) => ({
        name: s.username,
        me: s.username === me.data?.username,
        ready: t?.status === "ready_check" && s.ready,
        place: s.finish_position,
        prize: s.prize_cents ? `+${usd(s.prize_cents)}` : null,
      })),
    [t?.seats, t?.status, me.data?.username],
  );

  if (table.isLoading) return <Spinner />;
  if (!t) return <div className="text-center text-cream/70">Table not found.</div>;

  const path = { params: { path: { table_id: t.id } } };
  const phase = t.status === "open" ? "waiting" : t.status === "ready_check" ? "ready" : t.status;
  const seated = !!t.me;
  const readyCount = t.seats.filter((s) => s.ready).length;
  const podium = [...t.seats].filter((s) => s.finish_position).sort((a, b) => a.finish_position! - b.finish_position!);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <button className="btn-ghost px-3 py-1.5 text-sm" onClick={() => navigate(-1)}>
          ←
        </button>
        <div className="min-w-0 flex-1">
          <h1 className="title truncate text-3xl">{t.title ?? `${t.name} table`}</h1>
          <div className="flex flex-wrap items-center gap-2 text-sm text-cream/70">
            <StatusBadge status={t.status} />
            <span>{t.price_label}</span>
            {t.is_private && <span className="badge bg-cream/10 text-cream/70">🔒 Private</span>}
            {t.scheduled_start_at && <span>Starts {when(t.scheduled_start_at)}</span>}
          </div>
        </div>
        <div className="text-right">
          <div className="text-xs uppercase tracking-widest text-cream/50">Prize pool</div>
          <div className="title gold-text text-3xl">{usd(t.prize_pool_cents)}</div>
        </div>
      </div>

      {t.message && <div className="panel px-4 py-3 text-cream/80">💬 {t.message}</div>}

      <div className="panel relative aspect-[4/5] overflow-hidden sm:aspect-[16/10]">
        <TableCanvas seatsTotal={t.seats_total} seats={seats} phase={phase} potLabel={usd(t.prize_pool_cents)} />
        {t.status === "ready_check" && t.me && (
          <div className="absolute inset-0 flex items-center justify-center bg-black/35 backdrop-blur-[2px]">
            <div className="panel animate-pop flex flex-col items-center gap-3 p-6 text-center">
              <Ring seconds={readyLeft ?? 0} total={Math.max(60, readyLeft ?? 0)} size={84} />
              <div className="title text-2xl">Table's full!</div>
              <div className="text-sm text-cream/70">
                {readyCount}/{t.players} ready
              </div>
              {t.me.ready ? (
                <div className="font-display text-lg text-gold-300">You're in. Waiting for the others…</div>
              ) : (
                <button
                  className="btn-gold animate-pulseGlow px-10 py-4 text-2xl"
                  onClick={() => act(() => call(api.POST("/tables/{table_id}/ready", path)), "ready")}
                >
                  I'M READY
                </button>
              )}
            </div>
          </div>
        )}
      </div>

      <div className="grid gap-4 md:grid-cols-[1fr_280px]">
        <div className="panel p-4">
          {t.status === "open" && !seated && (
            <div className="flex flex-wrap items-center gap-4">
              <div className="flex-1">
                <div className="title text-xl">
                  {t.players}/{t.seats_total} seated
                </div>
                <SeatDots filled={t.players} total={t.seats_total} />
              </div>
              <button
                className="btn-gold px-6 py-3 text-lg"
                onClick={() =>
                  act(() => call(api.POST("/tables/{table_id}/join", { ...path, body: { invite_code: t.invite_code } })))
                }
              >
                Take a seat · {t.price_label}
              </button>
            </div>
          )}

          {t.status === "open" && seated && (
            <div className="flex flex-wrap items-center gap-4">
              <div className="flex-1">
                <div className="title text-xl">
                  Waiting for players · {t.players}/{t.seats_total}
                </div>
                <div className="mt-1">
                  <SeatDots filled={t.players} total={t.seats_total} />
                </div>
                <p className="mt-2 text-sm text-cream/60">
                  {t.start_mode === "scheduled"
                    ? `Starts at ${t.scheduled_start_at ? when(t.scheduled_start_at) : "the set time"} with at least ${t.min_players} players.`
                    : "Starts as soon as every seat is taken."}
                </p>
              </div>
              <div className="flex flex-wrap gap-2">
                <button className="btn-felt" onClick={() => setInviting(true)}>
                  👥 Invite friends
                </button>
                {t.me?.can_pull_out && (pullOutLeft ?? 0) > 0 && (
                  <button className="btn-ghost" onClick={() => act(() => call(api.POST("/tables/{table_id}/leave", path)))}>
                    Pull out · {Math.floor((pullOutLeft ?? 0) / 60)}:{String((pullOutLeft ?? 0) % 60).padStart(2, "0")}
                  </button>
                )}
              </div>
            </div>
          )}

          {t.status === "ready_check" && !t.me && <div className="title text-xl">Ready check in progress…</div>}
          {t.status === "ready_check" && t.me && (
            <div>
              <div className="title text-xl">{t.me.ready ? "You're ready ✔" : "Confirm you're in"}</div>
              <p className="mt-1 text-sm text-cream/60">
                The game starts when everyone is ready. Anyone who doesn't confirm in time loses their seat and gets
                refunded.
              </p>
            </div>
          )}

          {t.status === "running" && (
            <div className="flex flex-wrap items-center gap-3">
              <div className="title flex-1 text-xl">Game on! 🃏</div>
              <span className="text-sm text-cream/60">Blinds rise every few minutes. Good luck.</span>
              <span className="badge w-full justify-center bg-black/30 py-1 text-cream/60">
                Demo hand · live play arrives with the game server
              </span>
            </div>
          )}

          {t.status === "finished" && (
            <div>
              <div className="title mb-3 text-2xl">Results</div>
              <div className="space-y-2">
                {podium.map((s) => (
                  <div
                    key={s.username}
                    className={`flex items-center gap-3 rounded-xl px-3 py-2 ${s.prize_cents ? "bg-gold-400/10" : "bg-cream/5"}`}
                  >
                    <span className="w-8 text-center font-display text-xl">
                      {s.finish_position === 1 ? "🥇" : s.finish_position === 2 ? "🥈" : s.finish_position === 3 ? "🥉" : `#${s.finish_position}`}
                    </span>
                    <Avatar name={s.username} size={30} />
                    <span className="flex-1 font-semibold">{s.username}</span>
                    {s.prize_cents ? <span className="font-display text-lg text-gold-300">+{usd(s.prize_cents)}</span> : null}
                  </div>
                ))}
              </div>
              <Link to="/" className="btn-gold mt-4">
                Play again
              </Link>
            </div>
          )}

          {t.status === "cancelled" && (
            <div>
              <div className="title text-xl">This table was cancelled</div>
              <p className="mt-1 text-sm text-cream/60">Everyone who paid got a full refund.</p>
              <Link to="/" className="btn-gold mt-4">
                Back to the lobby
              </Link>
            </div>
          )}
        </div>

        <div className="space-y-4">
          <div className="panel p-4 text-sm">
            <div className="label">Payouts</div>
            {t.payout_bps.map((b, i) => (
              <div key={i} className="flex justify-between py-0.5">
                <span>{i + 1}{["st", "nd", "rd"][i] ?? "th"} place</span>
                <span className="font-display text-gold-300">
                  {b / 100}% · {usd(Math.floor((t.prize_pool_cents * b) / 10_000))}
                </span>
              </div>
            ))}
            {t.is_private && t.invite_code && (
              <div className="mt-3 rounded-xl bg-felt-950/60 p-3">
                <div className="label">Invite code</div>
                <div className="font-display text-2xl tracking-[0.3em] text-gold-300">{t.invite_code}</div>
              </div>
            )}
          </div>
          {t.is_organizer && (
            <>
              <Rsvp tableId={t.id} />
              {(t.status === "open" || t.status === "ready_check") && (
                <button
                  className="btn-red w-full"
                  onClick={() =>
                    confirm("Cancel this game? Everyone gets a full refund.") &&
                    act(() => call(api.POST("/tables/{table_id}/cancel", path)))
                  }
                >
                  Cancel game
                </button>
              )}
            </>
          )}
        </div>
      </div>
      {inviting && <InvitePanel table={t} onClose={() => setInviting(false)} />}
    </div>
  );
}

export function MyTables() {
  const tables = useQuery({
    queryKey: ["my-tables"],
    queryFn: () => call<TableView[]>(api.GET("/tables/mine")),
    refetchInterval: 4000,
  });
  if (tables.isLoading) return <Spinner />;
  return (
    <div className="space-y-4">
      <h1 className="title text-3xl">My tables</h1>
      {!tables.data?.length ? (
        <div className="panel p-6 text-center">
          <div className="title text-xl">You're not at any table</div>
          <Link to="/" className="btn-gold mt-4">
            Find a game
          </Link>
        </div>
      ) : (
        tables.data.map((t) => (
          <Link key={t.id} to={`/tables/${t.id}`} className="panel flex items-center gap-4 p-4 hover:border-gold-400/40">
            <div className="flex-1">
              <div className="flex items-center gap-2">
                <span className="font-display text-xl">{t.title ?? t.name}</span>
                <StatusBadge status={t.status} />
              </div>
              <div className="text-sm text-cream/60">{t.price_label}</div>
            </div>
            <SeatDots filled={t.players} total={t.seats_total} />
          </Link>
        ))
      )}
    </div>
  );
}
