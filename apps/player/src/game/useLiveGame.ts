import { GameClient, isMyTurn, type PlayerMove, type TableState } from "@poker/protocol";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, call, errorMessage } from "../lib/api";
import { play } from "../lib/sound";

interface SeatToken {
  token: string;
  ws_url: string;
  game_ref: string;
}

/**
 * Connects the signed-in player to their running game on the game server.
 * The platform issues a short-lived seat token; the game server checks it and
 * seats us. Returns live TableState plus `act()` for the betting controls.
 */
export function useLiveGame(tableId: string, enabled: boolean) {
  const [state, setState] = useState<TableState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const client = useRef<GameClient | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    if (!enabled) return;
    let closed = false;
    setError(null);
    (async () => {
      let seat: SeatToken;
      try {
        seat = await call<SeatToken>(api.GET("/tables/{table_id}/seat-token", { params: { path: { table_id: tableId } } }));
      } catch (e) {
        if (!closed) setError(errorMessage(e));
        return;
      }
      if (closed) return;
      let prev: TableState | null = null;
      const c = new GameClient({
        url: seat.ws_url,
        token: seat.token,
        onState: (s) => {
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
  }, [tableId, enabled, attempt]);

  const act = useCallback((move: PlayerMove) => {
    if (client.current?.act(move)) play(move.kind === "fold" || move.kind === "check" ? "click" : "chip");
  }, []);

  const retry = useCallback(() => {
    setState(null);
    setAttempt((n) => n + 1);
  }, []);

  return { state, error: error ?? (state?.phase === "error" ? state.error ?? "Disconnected" : null), act, retry };
}
