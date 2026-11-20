// WebSocket connection to a platform-mode game server. One binary frame =
// one PokerTHMessage (no length-prefix subprotocol is offered).

import { create, fromBinary, toBinary, type MessageInitShape } from "@bufbuild/protobuf";
import {
  InitMessage_ClientPlatform,
  InitMessage_LoginType,
  NetPlayerAction,
  PokerTHMessageSchema,
  PokerTHMessage_PokerTHMessageType as T,
  type PokerTHMessage,
} from "./gen/pokerth_pb";
import { initialTableState, legalActions, me, reduce, type TableState } from "./table";

export const NET_VERSION = { majorVersion: 5, minorVersion: 1 };
const CLIENT_TYPE_WEB = 0x03;
/** buildId = (clientType << 24) | (major << 16) | (minor << 8) | revision */
export const WEB_BUILD_ID = ((CLIENT_TYPE_WEB << 24) | (0 << 16) | (1 << 8) | 0) >>> 0;

export type PlayerMove =
  | { kind: "fold" }
  | { kind: "check" }
  | { kind: "call" }
  | { kind: "raise"; to: number } // total chips for this street (bet or raise)
  | { kind: "allin" };

export interface ClientOptions {
  url: string; // ws://host:7233 or wss://...
  token: string; // platform seat token
  platform?: InitMessage_ClientPlatform;
  onState: (s: TableState) => void;
  onMessage?: (m: PokerTHMessage) => void; // debugging / sounds
  WebSocketImpl?: typeof WebSocket;
}

export class GameClient {
  private ws?: WebSocket;
  private state: TableState = initialTableState();
  private closedByUser = false;
  private namesAsked = new Set<number>();

  constructor(private opts: ClientOptions) {}

  get current() {
    return this.state;
  }

  connect() {
    const WS = this.opts.WebSocketImpl ?? WebSocket;
    const ws = new WS(this.opts.url);
    ws.binaryType = "arraybuffer";
    ws.onmessage = (ev) => this.receive(new Uint8Array(ev.data as ArrayBuffer));
    ws.onclose = () => {
      if (!this.closedByUser && this.state.phase !== "ended" && this.state.phase !== "error") {
        this.set({ ...this.state, phase: "error", error: "Connection to the table was lost." });
      }
    };
    ws.onerror = () => {
      /* onclose follows and reports */
    };
    this.ws = ws;
  }

  close() {
    this.closedByUser = true;
    this.ws?.close();
  }

  act(move: PlayerMove) {
    const s = this.state;
    const legal = legalActions(s);
    const p = me(s);
    if (!legal || !p) return false;
    let action: NetPlayerAction;
    let bet = 0;
    switch (move.kind) {
      case "fold":
        action = NetPlayerAction.netActionFold;
        break;
      case "check":
        if (!legal.check) return false;
        action = NetPlayerAction.netActionCheck;
        break;
      case "call":
        if (!legal.call) return false;
        bet = legal.call;
        action = bet === p.cash ? NetPlayerAction.netActionAllIn : NetPlayerAction.netActionCall;
        break;
      case "raise": {
        if (!legal.raise) return false;
        const to = Math.round(Math.min(Math.max(move.to, legal.raise.min), legal.raise.max));
        bet = to - p.bet;
        action = to === legal.allIn ? NetPlayerAction.netActionAllIn : legal.raise.kind === "bet" ? NetPlayerAction.netActionBet : NetPlayerAction.netActionRaise;
        break;
      }
      case "allin":
        bet = p.cash;
        action = NetPlayerAction.netActionAllIn;
        break;
    }
    this.send({
      messageType: T.Type_MyActionRequestMessage,
      myActionRequestMessage: {
        gameId: s.gameId,
        handNum: s.handNum,
        gameState: this.netState(),
        myAction: action,
        myRelativeBet: bet,
      },
    });
    // Optimistically end my turn; the server's PlayersActionDone confirms it.
    this.set({ ...s, turnPlayerId: 0 });
    return true;
  }

  private lastTurnState = 0;

  private netState() {
    return this.lastTurnState;
  }

  private send(m: MessageInitShape<typeof PokerTHMessageSchema>) {
    if (!this.ws || this.ws.readyState !== 1) return;
    this.ws.send(toBinary(PokerTHMessageSchema, create(PokerTHMessageSchema, m)));
  }

  private set(s: TableState) {
    this.state = s;
    this.opts.onState(s);
  }

  private askNames(ids: number[]) {
    const fresh = ids.filter((id) => !this.namesAsked.has(id));
    if (!fresh.length) return;
    fresh.forEach((id) => this.namesAsked.add(id));
    this.send({ messageType: T.Type_PlayerInfoRequestMessage, playerInfoRequestMessage: { playerId: fresh } });
  }

  private receive(bytes: Uint8Array) {
    let m: PokerTHMessage;
    try {
      m = fromBinary(PokerTHMessageSchema, bytes);
    } catch {
      return; // ignore what we cannot parse; the server is the authority
    }
    this.opts.onMessage?.(m);

    switch (m.messageType) {
      case T.Type_AnnounceMessage:
        this.send({
          messageType: T.Type_InitMessage,
          initMessage: {
            requestedVersion: NET_VERSION,
            buildId: WEB_BUILD_ID,
            login: InitMessage_LoginType.unauthenticatedLogin,
            nickName: "web",
            clientPlatform: this.opts.platform ?? InitMessage_ClientPlatform.platformUnknown,
            platformToken: this.opts.token,
          },
        });
        break;
      case T.Type_StartEventMessage:
        // The server waits for every client to acknowledge the start.
        this.send({ messageType: T.Type_StartEventAckMessage, startEventAckMessage: { gameId: m.startEventMessage!.gameId } });
        break;
      case T.Type_TimeoutWarningMessage:
        this.send({ messageType: T.Type_ResetTimeoutMessage, resetTimeoutMessage: {} });
        break;
      case T.Type_PlayersTurnMessage:
        this.lastTurnState = m.playersTurnMessage!.gameState;
        break;
    }

    const next = reduce(this.state, m);
    if (next !== this.state) this.set(next);

    if (m.messageType === T.Type_GamePlayerJoinedMessage || m.messageType === T.Type_GameStartInitialMessage || m.messageType === T.Type_JoinGameAckMessage) {
      this.askNames(this.state.seats.map((p) => p.playerId));
    }
  }
}
