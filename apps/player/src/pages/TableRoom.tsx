import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { Avatar, Ring, SeatDots, Spinner, StatusBadge } from "../components/bits";
import { ErrorBoundary } from "../components/ErrorBoundary";
import { Icon } from "../components/Icon";
import { useErrorToast, useToast } from "../components/Toast";
import { ActionBar } from "../game/ActionBar";
import { TableCanvas, type CanvasSeat, type LiveTable } from "../game/TableCanvas";
import { useLiveGame } from "../game/useLiveGame";
import { pot as potOf, type TableState } from "@poker/protocol";
import { api, call } from "../lib/api";
import { PUBLIC_URL } from "../lib/native";
import { usd, when } from "../lib/format";
import { useMe, useSecondsLeft } from "../lib/hooks";
import { play } from "../lib/sound";
import type { FriendItem, TableView } from "../lib/types";

function InvitePanel({ table, onClose }: { table: TableView; onClose: () => void }) {
  const toast = useToast();
  const showError = useErrorToast();
  const friends = useQuery({
    queryKey: ["friends"],
    queryFn: () => call<{ friends: FriendItem[] }>(api.GET("/friends")),
  });
  const [picked, setPicked] = useState<string[]>([]);
  const [extra, setExtra] = useState("");
  const [message, setMessage] = useState("");
  const referral = useQuery({ queryKey: ["referral"], queryFn: () => call<{ code: string }>(api.GET("/me/referral")) });
  // Newcomers who sign up from this link are credited to you (and become your friend).
  const ref = referral.data?.code ? `?ref=${referral.data.code}` : "";
  const link = table.invite_code ? `${PUBLIC_URL}/join/${table.invite_code}${ref}` : `${PUBLIC_URL}/tables/${table.id}`;

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
      showError(e);
    }
  };

  const share = async () => {
    const text = `Join my poker table (${table.price_label}) on Draely`;
    try {
      if (navigator.share) await navigator.share({ title: "Draely", text, url: link });
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
          <div className="mt-4 flex items-center justify-between text-xs">
            <span className="label mb-0">Pick friends ({picked.length} selected)</span>
            <button
              type="button"
              className="text-gold-300 hover:underline"
              onClick={() => {
                const all = friends.data!.friends.map((f) => f.username).filter((u): u is string => !!u);
                setPicked((p) => (p.length === all.length ? [] : all));
              }}
            >
              {picked.length === friends.data!.friends.length ? "Clear" : "Select all"}
            </button>
          </div>
        )}
        {(friends.data?.friends.length ?? 0) > 0 && (
          <div className="mt-2 flex flex-wrap gap-2">
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
            <Icon name="link" size={18} /> Share link
          </button>
          <button className="btn-gold flex-1" onClick={send}>
            Send invites{picked.length ? ` (${picked.length})` : ""}
          </button>
        </div>
      </div>
    </div>
  );
}

/** Canvas view of the live game state (seat order, me at the bottom). */
function toLiveTable(s: TableState): LiveTable {
  return {
    handKey: s.handNum,
    board: s.board,
    pot: potOf(s),
    turnStartedAt: s.turnStartedAt,
    turnSeconds: s.actionTimeoutSec,
    seats: s.seats.map((p) => ({
      id: p.playerId,
      name: p.name,
      me: p.playerId === s.myId,
      cash: p.cash,
      bet: p.bet,
      folded: p.folded,
      out: p.out,
      allIn: p.allIn,
      dealer: p.playerId === s.dealerId,
      turn: !s.handOver && p.playerId === s.turnPlayerId,
      inHand: s.handNum > 0 && !p.out,
      cards: p.cards,
      action: p.lastAction,
      won: p.won,
    })),
  };
}

function HandLog({ lines }: { lines: string[] }) {
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    // Scroll only the log box, never the page.
    if (box.current) box.current.scrollTop = box.current.scrollHeight;
  }, [lines.length]);
  return (
    <div ref={box} className="panel max-h-40 overflow-y-auto p-3 text-sm">
      <div className="label">Hand history</div>
      {lines.map((l, i) => (
        <div key={i} className={l.startsWith("Hand #") ? "mt-1 font-display text-gold-300" : "text-cream/75"}>
          {l}
        </div>
      ))}
    </div>
  );
}

/** Start early with the players seated: everyone must agree. */
function StartNow({ table, onVote }: { table: TableView; onVote: (agree: boolean) => void }) {
  const [dismissed, setDismissed] = useState(false);
  const agreed = table.seats.filter((s) => s.start_vote).length;
  const total = table.seats.filter((s) => s.status === "registered").length;
  const mine = !!table.me?.start_vote;
  const othersWant = agreed > 0 && !mine;
  return (
    <div className={`w-full rounded-xl p-3 ${othersWant && !dismissed ? "animate-pop border border-gold-400/50 bg-gold-400/10" : "bg-black/20"}`}>
      <div className="flex flex-wrap items-center gap-3">
        <div className="min-w-0 flex-1 text-sm">
          {agreed === 0 ? (
            <span className="text-cream/70">Don't want to wait? Start now with the {total} players here (everyone must agree).</span>
          ) : (
            <span>
              <b className="text-gold-300">{agreed} of {total}</b> want to start now:{" "}
              {table.seats.filter((s) => s.start_vote).map((s) => s.username).join(", ")}
            </span>
          )}
        </div>
        {mine ? (
          <button className="btn-ghost px-3 py-1.5 text-sm" onClick={() => onVote(false)}>
            Keep waiting
          </button>
        ) : (
          <>
            {othersWant && !dismissed && (
              <button className="btn-ghost px-3 py-1.5 text-sm" onClick={() => setDismissed(true)}>
                Keep waiting
              </button>
            )}
            <button className="btn-gold px-4 py-1.5 text-sm" onClick={() => onVote(true)}>
              Start now
            </button>
          </>
        )}
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
  const tone: Record<string, string> = { accepted: "text-chip-green", declined: "text-[#ff9a9d]", pending: "text-gold-300", expired: "text-cream/40", revoked: "text-cream/40" };
  return (
    <div className="panel p-4">
      <div className="label">Who's coming</div>
      <ul className="space-y-1.5 text-sm">
        {rsvp.data.map((r) => (
          <li key={r.invitee} className="flex items-center gap-2">
            <Avatar name={r.invitee} size={24} />
            <span className="flex-1 truncate">{r.invitee}</span>
            <span className={`text-xs font-bold uppercase tracking-wider ${tone[r.status] ?? "text-cream/50"}`}>{r.status}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function TableRoom() {
  const { id = "" } = useParams();
  const me = useMe();
  const showError = useErrorToast();
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
  const playing = t?.status === "running" && t.me?.status === "playing";
  const live = useLiveGame(id, playing);
  // While reconnecting or waiting to be dealt back in, keep showing the last table we had.
  const lastLive = useRef<LiveTable | null>(null);
  const liveTable = useMemo(() => {
    if (!playing) return (lastLive.current = null);
    const s = live.state;
    const fresh = s && (s.phase === "playing" || s.phase === "ended") && s.seats.length && !s.rejoining ? toLiveTable(s) : null;
    if (fresh) lastLive.current = fresh;
    return fresh ?? lastLive.current;
  }, [playing, live.state]);

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

  // One request at a time: a double tap must not buy in / leave twice.
  const acting = useRef(false);
  const act = async (fn: () => Promise<unknown>, sound: "chip" | "ready" = "chip") => {
    if (acting.current) return;
    acting.current = true;
    try {
      await fn();
      play(sound);
      await Promise.all([
        qc.invalidateQueries({ queryKey: ["table", id] }),
        qc.invalidateQueries({ queryKey: ["wallet"] }),
        qc.invalidateQueries({ queryKey: ["demo-money"] }),
      ]);
    } catch (e) {
      showError(e);
    } finally {
      acting.current = false;
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
      <div className="flex items-center gap-3">
        <button className="btn-icon shrink-0" onClick={() => navigate(-1)} aria-label="Back">
          <Icon name="back" size={20} />
        </button>
        <div className="min-w-0 flex-1">
          <h1 className="title truncate text-2xl md:text-3xl">{t.title ?? `${t.name} table`}</h1>
          <div className="flex flex-wrap items-center gap-2 text-sm text-cream/65">
            <StatusBadge status={t.status} />
            <span>{t.price_label}</span>
            {t.is_private && (
              <span className="badge bg-cream/10 text-cream/70">
                <Icon name="lock" size={11} strokeWidth={2.6} /> Private
              </span>
            )}
            {t.scheduled_start_at && (
              <span className="inline-flex items-center gap-1">
                <Icon name="clock" size={14} /> {when(t.scheduled_start_at)}
              </span>
            )}
          </div>
        </div>
        <Link to="/hands" className="btn-icon shrink-0" aria-label="Hand rankings" title="Hand rankings">
          <span className="font-display text-lg leading-none">?</span>
        </Link>
        <div className="shrink-0 rounded-2xl border border-gold-400/30 bg-black/30 px-3 py-1.5 text-right shadow-glow md:px-4 md:py-2">
          <div className="text-[10px] font-bold uppercase tracking-[0.2em] text-cream/50">Prize pool</div>
          <div className="title gold-text text-2xl leading-tight md:text-3xl">{usd(t.prize_pool_cents)}</div>
        </div>
      </div>

      {t.message && (
        <div className="panel-flat flex items-start gap-3 px-4 py-3 text-cream/80">
          <Icon name="mail" size={18} className="mt-0.5 shrink-0 text-gold-300" />
          <span>{t.message}</span>
        </div>
      )}

      <div className="panel relative aspect-[4/5] overflow-hidden sm:aspect-[16/10]">
        <ErrorBoundary label="table view">
          <TableCanvas
            seatsTotal={t.seats_total}
            seats={seats}
            // A seated player waiting for the live table sees seats, not the demo deal.
            phase={playing && !liveTable ? "waiting" : phase}
            potLabel={usd(t.prize_pool_cents)}
            live={liveTable}
          />
        </ErrorBoundary>
        {playing && (live.reconnecting || live.state?.rejoining) && (
          <div className="pointer-events-none absolute inset-x-0 top-12 flex justify-center">
            <div className="animate-pop rounded-full bg-black/70 px-4 py-2 font-display text-gold-300">
              {live.reconnecting ? "Reconnecting…" : "Back at your seat · dealt in next hand"}
            </div>
          </div>
        )}
        {liveTable && live.state && (
          <div className="pointer-events-none absolute left-3 top-3 rounded-lg bg-black/45 px-2.5 py-1 text-xs text-cream/80">
            Hand #{live.state.handNum} · Blinds {live.state.smallBlind}/{live.state.smallBlind * 2}
          </div>
        )}
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
                  <Icon name="users" size={18} /> Invite friends
                </button>
                {t.me?.can_pull_out && (t.me.alone || (pullOutLeft ?? 0) > 0) && (
                  <button
                    className="btn-ghost"
                    onClick={() =>
                      act(async () => {
                        await call(api.POST("/tables/{table_id}/leave", path));
                        navigate("/");
                      })
                    }
                  >
                    <Icon name="logout" size={16} /> Leave table
                    {!t.me.alone && ` · ${Math.floor((pullOutLeft ?? 0) / 60)}:${String((pullOutLeft ?? 0) % 60).padStart(2, "0")}`}
                  </button>
                )}
              </div>
              {t.start_mode === "when_full" && t.players >= 2 && (
                <StartNow table={t} onVote={(agree) => act(() => call(api.POST("/tables/{table_id}/start-now", { ...path, body: { agree } })), "ready")} />
              )}
              {t.me && !t.me.alone && !(t.me.can_pull_out && (pullOutLeft ?? 0) > 0) && (
                <p className="w-full text-xs text-cream/50">
                  The 10-minute leave window has passed. The game starts when the table is full; if it
                  doesn't fill in time it's cancelled and everyone gets a full refund.
                </p>
              )}
            </div>
          )}

          {t.status === "ready_check" && !t.me && <div className="title text-xl">Ready check in progress…</div>}
          {t.status === "ready_check" && t.me && (
            <div>
              <div className="title text-xl">{t.me.ready ? "You're ready" : "Confirm you're in"}</div>
              <p className="mt-1 text-sm text-cream/60">
                The game starts when everyone is ready. Anyone who doesn't confirm in time loses their seat and gets
                refunded.
              </p>
            </div>
          )}

          {t.status === "running" && playing && t.start_mode === "practice" && (
            <div className="mb-3 flex justify-end">
              <button
                className="btn-ghost px-3 py-1.5 text-sm"
                onClick={() =>
                  confirm("Leave this practice game? You lose your play money entry.") &&
                  act(async () => {
                    await call(api.POST("/tables/{table_id}/quit-practice", path));
                    navigate("/");
                  })
                }
              >
                <Icon name="logout" size={16} /> Leave game
              </button>
            </div>
          )}
          {t.status === "running" && playing && (
            <>
              {live.reconnecting ? (
                <div className="flex items-center gap-3 text-cream/70">
                  <Spinner /> Connection dropped — getting your seat back…
                </div>
              ) : live.error ? (
                <div className="flex flex-wrap items-center gap-3">
                  <div className="flex flex-1 items-center gap-2 text-cream/80">
                    <Icon name="info" size={18} className="shrink-0 text-gold-300" /> {live.error}
                  </div>
                  <button className="btn-gold" onClick={live.retry}>
                    Reconnect
                  </button>
                </div>
              ) : !live.state || live.state.phase === "connecting" ? (
                <div className="flex items-center gap-3 text-cream/70">
                  <Spinner /> Connecting to your table…
                </div>
              ) : live.state.rejoining ? (
                <div>
                  <div className="title text-xl">Welcome back</div>
                  <p className="mt-1 text-sm text-cream/60">Your seat and chips are safe. You're dealt in at the next hand.</p>
                </div>
              ) : live.state.phase === "waiting" ? (
                <div>
                  <div className="title text-xl">Taking your seat…</div>
                  <p className="mt-1 text-sm text-cream/60">
                    {live.state.seats.length}/{t.players} players connected. The first hand is dealt when everyone is here.
                  </p>
                </div>
              ) : live.state.phase === "ended" ? (
                <div>
                  <div className="title text-2xl">
                    {live.state.winnerId === live.state.myId ? "You won the game!" : "Game over"}
                  </div>
                  <p className="mt-1 text-sm text-cream/60">Settling prizes… your wallet updates in a moment.</p>
                </div>
              ) : (
                <ErrorBoundary label="betting controls">
                  {/* Phones: pinned to the bottom of the screen so it's always in reach. */}
                  <div
                    className="fixed inset-x-0 bottom-0 z-30 border-t border-cream/10 bg-[#030c08]/95 px-4 pt-3 backdrop-blur-xl md:static md:border-0 md:bg-transparent md:p-0 md:backdrop-blur-none"
                    style={{ paddingBottom: "max(0.75rem, env(safe-area-inset-bottom))" }}
                  >
                    <ActionBar state={live.state} act={live.act} />
                  </div>
                </ErrorBoundary>
              )}
            </>
          )}
          {t.status === "running" && !playing && (
            <div className="flex flex-wrap items-center gap-3">
              <div className="title flex-1 text-xl">Game on! 🃏</div>
              <span className="text-sm text-cream/60">Blinds rise every few minutes.</span>
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
                    <span
                      className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full font-display text-sm text-felt-950"
                      style={{ background: ["#f5c451", "#d6dbe0", "#d08a4e"][s.finish_position! - 1] ?? "rgba(246,241,227,.15)", boxShadow: "inset 0 -2px 0 rgba(0,0,0,.25)" }}
                    >
                      {s.finish_position}
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
          {playing && live.state && live.state.log.length > 0 && <HandLog lines={live.state.log} />}
          <div className="panel p-4 text-sm">
            <div className="label">Payouts</div>
            {t.price_detail && t.price_detail !== t.price_label && (
              <div className="mb-2 text-xs text-cream/45">Entry {t.price_label}: {t.price_detail}</div>
            )}
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
