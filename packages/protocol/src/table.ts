// Pure table state for one platform game, built from server messages.
// UI code (web and the Capacitor phone app) renders TableState and never
// touches protobuf directly; the server stays the authority on every rule.

import {
  ErrorMessage_ErrorReason,
  NetGameState,
  NetPlayerAction,
  NetPlayerState,
  PokerTHMessage_PokerTHMessageType as T,
  type PokerTHMessage,
} from "./gen/pokerth_pb";

export type Phase = "connecting" | "waiting" | "playing" | "ended" | "error";
export type Street = "preflop" | "flop" | "turn" | "river";

export interface Seat {
  playerId: number;
  name: string;
  cash: number; // chips behind
  bet: number; // chips put in during the current street
  folded: boolean;
  allIn: boolean;
  out: boolean; // busted or left
  lastAction?: string;
  cards?: [number, number]; // own cards, or revealed at showdown
  won?: number; // chips won in the last hand
}

export interface TableState {
  phase: Phase;
  error?: string;
  gameId: number;
  myId: number;
  title: string;
  seats: Seat[]; // seat order once the game has started, join order before
  dealerId: number;
  handNum: number;
  smallBlind: number;
  street: Street;
  board: number[];
  collected: number; // chips from finished streets
  highestSet: number;
  minimumRaise: number;
  turnPlayerId: number;
  turnStartedAt: number; // ms epoch (client clock)
  actionTimeoutSec: number;
  startMoney: number;
  maxPlayers: number;
  handOver: boolean;
  winnerId: number;
  log: string[];
}

export const initialTableState = (): TableState => ({
  phase: "connecting",
  gameId: 0,
  myId: 0,
  title: "",
  seats: [],
  dealerId: 0,
  handNum: 0,
  smallBlind: 0,
  street: "preflop",
  board: [],
  collected: 0,
  highestSet: 0,
  minimumRaise: 0,
  turnPlayerId: 0,
  turnStartedAt: 0,
  actionTimeoutSec: 20,
  startMoney: 0,
  maxPlayers: 0,
  handOver: false,
  winnerId: 0,
  log: [],
});

export const pot = (s: TableState) => s.collected + s.seats.reduce((n, p) => n + p.bet, 0);
export const me = (s: TableState) => s.seats.find((p) => p.playerId === s.myId);
export const isMyTurn = (s: TableState) => s.phase === "playing" && !s.handOver && s.turnPlayerId === s.myId && s.myId !== 0;

const STREET: Record<number, Street> = {
  [NetGameState.netStatePreflop]: "preflop",
  [NetGameState.netStatePreflopSmallBlind]: "preflop",
  [NetGameState.netStatePreflopBigBlind]: "preflop",
  [NetGameState.netStateFlop]: "flop",
  [NetGameState.netStateTurn]: "turn",
  [NetGameState.netStateRiver]: "river",
};

const ACTION_WORD: Record<number, string> = {
  [NetPlayerAction.netActionFold]: "fold",
  [NetPlayerAction.netActionCheck]: "check",
  [NetPlayerAction.netActionCall]: "call",
  [NetPlayerAction.netActionBet]: "bet",
  [NetPlayerAction.netActionRaise]: "raise",
  [NetPlayerAction.netActionAllIn]: "all-in",
};

const ERROR_TEXT: Partial<Record<ErrorMessage_ErrorReason, string>> = {
  [ErrorMessage_ErrorReason.initAuthFailure]: "Your seat pass was not accepted. Reopen the table to get a fresh one.",
  [ErrorMessage_ErrorReason.initVersionNotSupported]: "This app version is not supported by the game server.",
  [ErrorMessage_ErrorReason.initServerFull]: "The game server is full. Try again in a moment.",
  [ErrorMessage_ErrorReason.initServerMaintenance]: "The game server is under maintenance.",
  [ErrorMessage_ErrorReason.sessionTimeout]: "You were disconnected for inactivity.",
  [ErrorMessage_ErrorReason.kickedFromServer]: "You were removed from the server.",
  [ErrorMessage_ErrorReason.invalidPacket]: "The game server rejected a message.",
};

function seatFor(s: TableState, playerId: number): Seat {
  return { playerId, name: s.seats.find((p) => p.playerId === playerId)?.name ?? `Player ${playerId}`, cash: s.startMoney, bet: 0, folded: false, allIn: false, out: false };
}

function updateSeat(s: TableState, playerId: number, f: (p: Seat) => Seat): Seat[] {
  return s.seats.map((p) => (p.playerId === playerId ? f(p) : p));
}

function nameOf(s: TableState, playerId: number) {
  return playerId === s.myId ? "You" : s.seats.find((p) => p.playerId === playerId)?.name ?? `Player ${playerId}`;
}

function addLog(s: TableState, line: string): string[] {
  return [...s.log, line].slice(-40);
}

function endStreet(s: TableState, street: Street, cards: number[]): TableState {
  return {
    ...s,
    street,
    board: [...s.board, ...cards],
    collected: pot(s),
    highestSet: 0,
    minimumRaise: 0,
    turnPlayerId: 0,
    seats: s.seats.map((p) => ({ ...p, bet: 0, lastAction: p.folded || p.allIn ? p.lastAction : undefined })),
  };
}

/** Apply one server message. `now` is only used for the turn timer. */
export function reduce(s: TableState, m: PokerTHMessage, now = Date.now()): TableState {
  switch (m.messageType) {
    case T.Type_InitAckMessage:
      return { ...s, myId: m.initAckMessage!.yourPlayerId, phase: "waiting" };

    case T.Type_JoinGameAckMessage: {
      const a = m.joinGameAckMessage!;
      const info = a.gameInfo!;
      return {
        ...s,
        phase: "waiting",
        gameId: a.gameId,
        title: info.gameName,
        startMoney: info.startMoney,
        maxPlayers: info.maxNumPlayers,
        actionTimeoutSec: info.playerActionTimeout || 20,
        smallBlind: info.firstSmallBlind,
        seats: s.seats.some((p) => p.playerId === s.myId) || !s.myId ? s.seats : [...s.seats, seatFor({ ...s, startMoney: info.startMoney }, s.myId)],
      };
    }

    case T.Type_GamePlayerJoinedMessage: {
      const id = m.gamePlayerJoinedMessage!.playerId;
      if (s.seats.some((p) => p.playerId === id)) return s;
      return { ...s, seats: [...s.seats, seatFor(s, id)] };
    }

    case T.Type_PlayerInfoReplyMessage: {
      const r = m.playerInfoReplyMessage!;
      const name = r.playerInfoData?.playerName;
      return name ? { ...s, seats: updateSeat(s, r.playerId, (p) => ({ ...p, name })) } : s;
    }

    case T.Type_GamePlayerLeftMessage: {
      const id = m.gamePlayerLeftMessage!.playerId;
      if (s.phase === "waiting") return { ...s, seats: s.seats.filter((p) => p.playerId !== id) };
      return { ...s, seats: updateSeat(s, id, (p) => ({ ...p, out: true, lastAction: "left" })), log: addLog(s, `${nameOf(s, id)} left the table`) };
    }

    case T.Type_GameStartInitialMessage: {
      const g = m.gameStartInitialMessage!;
      const seats = g.playerSeats.map((id) => s.seats.find((p) => p.playerId === id) ?? seatFor(s, id));
      return { ...s, phase: "playing", seats, dealerId: g.startDealerPlayerId, log: addLog(s, "Game started — good luck!") };
    }

    case T.Type_HandStartMessage: {
      const h = m.handStartMessage!;
      const cards = h.plainCards ? ([h.plainCards.plainCard1, h.plainCards.plainCard2] as [number, number]) : undefined;
      const seats = s.seats.map((p, i) => {
        const out = p.out || h.seatStates[i] === NetPlayerState.netPlayerStateNoMoney || p.cash <= 0;
        return { ...p, bet: 0, folded: out, allIn: false, out, lastAction: undefined, won: undefined, cards: p.playerId === s.myId && !out ? cards : undefined };
      });
      return {
        ...s,
        phase: "playing",
        seats,
        handNum: s.handNum + 1,
        smallBlind: h.smallBlind,
        dealerId: h.dealerPlayerId ?? s.dealerId,
        street: "preflop",
        board: [],
        collected: 0,
        highestSet: 0,
        minimumRaise: 0,
        turnPlayerId: 0,
        handOver: false,
        log: addLog(s, `Hand #${s.handNum + 1} · blinds ${h.smallBlind}/${h.smallBlind * 2}`),
      };
    }

    case T.Type_PlayersTurnMessage: {
      const t = m.playersTurnMessage!;
      return { ...s, turnPlayerId: t.playerId, turnStartedAt: now, street: STREET[t.gameState] ?? s.street };
    }

    case T.Type_PlayersActionDoneMessage: {
      const a = m.playersActionDoneMessage!;
      const word = ACTION_WORD[a.playerAction];
      const seats = updateSeat(s, a.playerId, (p) => ({
        ...p,
        bet: a.totalPlayerBet,
        cash: a.playerMoney,
        folded: p.folded || a.playerAction === NetPlayerAction.netActionFold,
        allIn: p.allIn || a.playerAction === NetPlayerAction.netActionAllIn || (a.playerMoney === 0 && a.totalPlayerBet > 0),
        lastAction: word ?? (a.gameState === NetGameState.netStatePreflopSmallBlind ? "SB" : a.gameState === NetGameState.netStatePreflopBigBlind ? "BB" : p.lastAction),
      }));
      const amount = a.playerAction === NetPlayerAction.netActionCall || a.playerAction === NetPlayerAction.netActionBet || a.playerAction === NetPlayerAction.netActionRaise || a.playerAction === NetPlayerAction.netActionAllIn ? ` ${a.totalPlayerBet}` : "";
      const line = word ? `${nameOf(s, a.playerId)} ${word}${amount}` : undefined;
      return {
        ...s,
        seats,
        highestSet: a.highestSet,
        minimumRaise: a.minimumRaise,
        turnPlayerId: s.turnPlayerId === a.playerId ? 0 : s.turnPlayerId,
        log: line ? addLog(s, line) : s.log,
      };
    }

    case T.Type_DealFlopCardsMessage: {
      const f = m.dealFlopCardsMessage!;
      return endStreet(s, "flop", [f.flopCard1, f.flopCard2, f.flopCard3]);
    }
    case T.Type_DealTurnCardMessage:
      return endStreet(s, "turn", [m.dealTurnCardMessage!.turnCard]);
    case T.Type_DealRiverCardMessage:
      return endStreet(s, "river", [m.dealRiverCardMessage!.riverCard]);

    case T.Type_AllInShowCardsMessage: {
      let seats = s.seats;
      for (const p of m.allInShowCardsMessage!.playersAllIn) {
        seats = seats.map((x) => (x.playerId === p.playerId ? { ...x, cards: [p.allInCard1, p.allInCard2] as [number, number] } : x));
      }
      return { ...s, seats };
    }

    case T.Type_EndOfHandShowCardsMessage: {
      let next: TableState = { ...s, collected: pot(s), handOver: true, turnPlayerId: 0 };
      const winners: string[] = [];
      for (const r of m.endOfHandShowCardsMessage!.playerResults) {
        next = {
          ...next,
          seats: updateSeat(next, r.playerId, (p) => ({ ...p, bet: 0, cash: r.playerMoney, won: r.moneyWon || undefined, cards: [r.resultCard1, r.resultCard2] })),
        };
        if (r.moneyWon > 0) winners.push(`${nameOf(s, r.playerId)} won ${r.moneyWon}`);
      }
      return { ...next, log: addLog(next, winners.join(", ") || "Hand over") };
    }

    case T.Type_EndOfHandHideCardsMessage: {
      const e = m.endOfHandHideCardsMessage!;
      const next: TableState = { ...s, collected: pot(s), handOver: true, turnPlayerId: 0 };
      return {
        ...next,
        seats: next.seats.map((p) => ({ ...p, bet: 0, ...(p.playerId === e.playerId ? { cash: e.playerMoney, won: e.moneyWon } : {}) })),
        log: addLog(next, `${nameOf(s, e.playerId)} won ${e.moneyWon}`),
      };
    }

    case T.Type_AfterHandShowCardsMessage: {
      const r = m.afterHandShowCardsMessage!.playerResult!;
      return { ...s, seats: updateSeat(s, r.playerId, (p) => ({ ...p, cards: [r.resultCard1, r.resultCard2] })) };
    }

    case T.Type_EndOfGameMessage: {
      const id = m.endOfGameMessage!.winnerPlayerId;
      return { ...s, phase: "ended", winnerId: id, turnPlayerId: 0, log: addLog(s, `${nameOf(s, id)} won the game!`) };
    }

    case T.Type_PlayerIdChangedMessage: {
      const { oldPlayerId, newPlayerId } = m.playerIdChangedMessage!;
      return {
        ...s,
        myId: s.myId === oldPlayerId ? newPlayerId : s.myId,
        seats: updateSeat(s, oldPlayerId, (p) => ({ ...p, playerId: newPlayerId })),
      };
    }

    case T.Type_RemovedFromGameMessage:
      return s.phase === "ended" ? s : { ...s, phase: "error", error: "You were removed from the game." };

    case T.Type_ErrorMessage: {
      const reason = m.errorMessage!.errorReason;
      return { ...s, phase: "error", error: ERROR_TEXT[reason] ?? `Game server error (${ErrorMessage_ErrorReason[reason] ?? reason}).` };
    }

    default:
      return s;
  }
}

export interface LegalActions {
  fold: boolean;
  check: boolean;
  call: number; // chips to call (0 = not possible); equals cash when calling all-in
  /** bet/raise to a total for this street; null when only all-in is left */
  raise: { min: number; max: number; kind: "bet" | "raise" } | null;
  allIn: number; // total for this street when going all-in
}

/** What I may do right now; null when it is not my turn. */
export function legalActions(s: TableState): LegalActions | null {
  const p = me(s);
  if (!p || !isMyTurn(s) || p.folded || p.allIn || p.out) return null;
  const bb = s.smallBlind * 2;
  const toCall = Math.max(0, s.highestSet - p.bet);
  const most = p.bet + p.cash; // all-in total
  const minTo = s.highestSet === 0 ? bb : s.highestSet + Math.max(s.minimumRaise, bb);
  return {
    fold: true,
    check: toCall === 0,
    call: toCall > 0 ? Math.min(toCall, p.cash) : 0,
    raise: most > minTo ? { min: minTo, max: most, kind: s.highestSet === 0 ? "bet" : "raise" } : null,
    allIn: most,
  };
}
