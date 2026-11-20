import { GameClient, isMyTurn, type PlayerMove, type TableState } from "@poker/protocol";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, call, errorMessage } from "../lib/api";
import { play } from "../lib/sound";

interface SeatToken {
  token: string;
  ws_url: string;
  game_ref: string;
}

const RETRY_DELAYS = [1000, 2000, 4000, 8000, 15000, 30000];

/**
 * Connects the signed-in player to their running game on the game server.
 * The platform issues a short-lived seat token; the game server checks it and
 * seats us - or, after a reload or a dropped connection, gives our seat back
 * (dealt in again from the next hand). Lost connections are retried with
 * backoff, and at once when the network or the tab/app comes back.
 */
export function useLiveGame(tableId: string, enabled: boolean) {
  const [state, setState] = useState<TableState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reconnecting, setReconnecting] = useState(false);
  const client = useRef<GameClient | null>(null);
  const [attempt, setAttempt] = useState(0);
  const failures = useRef(0);
  const retryTimer = useRef<number | undefined>(undefined);

  const scheduleRetry = useCallback((immediate = false) => {
    window.clearTimeout(retryTimer.current);
    if (failures.current >= RETRY_DELAYS.length) {
      setReconnecting(false);
      return;
    }
    setReconnecting(true);
    const delay = immediate ? 0 : RETRY_DELAYS[failures.current];
    failures.current += 1;
    retryTimer.current = window.setTimeout(() => setAttempt((n) => n + 1), delay);
  }, []);

  useEffect(() => {
    if (!enabled) return;
    let closed = false;
    setError(null);
    (async () => {
      let seat: SeatToken;
      try {
        seat = await call<SeatToken>(api.GET("/tables/{table_id}/seat-token", { params: { path: { table_id: tableId } } }));
      } catch (e) {
        if (closed) return;
        setError(errorMessage(e));
        // Network/server trouble is worth retrying; a 4xx (game over, no seat) is not.
        const status = e && typeof e === "object" && "status" in e ? (e as { status: number }).status : 0;
        if (status === 0 || status >= 500) scheduleRetry();
        return;
      }
      if (closed) return;
      let prev: TableState | null = null;
      const c = new GameClient({
        url: seat.ws_url,
        token: seat.token,
        onState: (s) => {
          if (s.phase === "playing" || s.phase === "ended" || (s.phase === "waiting" && s.gameId)) {
            failures.current = 0; // connected and seated again
            setReconnecting(false);
          }
          if (s.phase === "error" && s.retryable && !closed) scheduleRetry();
          // Sounds: my turn, cards hitting the board, chips going in, a win.
          if (prev) {
            if (isMyTurn(s) && !isMyTurn(prev)) play("ready");
            else if (s.board.length > prev.board.length || s.handNum > prev.handNum) play("click");
            else if (s.log.length !== prev.log.length && /call|bet|raise|all-in/.test(s.log[s.log.length - 1] ?? "")) play("chip");
            const mine = s.seats.find((p) => p.playerId === s.myId);
            const minePrev = prev.seats.find((p) => p.playerId === s.myId);
            if ((mine?.won ?? 0) > 0 && !(minePrev?.won ?? 0)) play("win");
          }
          prev = s;
          setState(s);
        },
      });
      client.current = c;
      c.connect();
    })();
    return () => {
      closed = true;
      client.current?.close();
      client.current = null;
    };
  }, [tableId, enabled, attempt, scheduleRetry]);

  // Back online / back in the foreground (phone app resumed): reconnect now.
  useEffect(() => {
    if (!enabled) return;
    const wake = () => {
      const s = client.current?.current;
      if (document.visibilityState === "visible" && s?.phase === "error" && s.retryable) {
        failures.current = 0;
        scheduleRetry(true);
      }
    };
    window.addEventListener("online", wake);
    document.addEventListener("visibilitychange", wake);
    return () => {
      window.removeEventListener("online", wake);
      document.removeEventListener("visibilitychange", wake);
      window.clearTimeout(retryTimer.current);
    };
  }, [enabled, scheduleRetry]);

  const act = useCallback((move: PlayerMove) => {
    if (client.current?.act(move)) play(move.kind === "fold" || move.kind === "check" ? "click" : "chip");
  }, []);

  /** Manual "Reconnect" button: also used to take the seat back from another tab. */
  const retry = useCallback(() => {
    failures.current = 0;
    scheduleRetry(true);
  }, [scheduleRetry]);

  return {
    state,
    reconnecting,
    error: reconnecting ? null : error ?? (state?.phase === "error" ? state.error ?? "Disconnected" : null),
    act,
    retry,
  };
}
