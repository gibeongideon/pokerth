// Reducer + wire round-trip tests. Run: npm test -w packages/protocol
import assert from "node:assert/strict";
import { create, fromBinary, toBinary, type MessageInitShape } from "@bufbuild/protobuf";
import { bestHandName, card, cardLabel, initialTableState, legalActions, pot, reduce, WEB_BUILD_ID, type TableState } from "../src/index";
import { NetGameState, NetPlayerAction, PokerTHMessageSchema, PokerTHMessage_PokerTHMessageType as T } from "../src/gen/pokerth_pb";

type Init = MessageInitShape<typeof PokerTHMessageSchema>;
// Every message goes through the wire format, like in the app.
const wire = (m: Init) => fromBinary(PokerTHMessageSchema, toBinary(PokerTHMessageSchema, create(PokerTHMessageSchema, m)));
const apply = (s: TableState, ...ms: Init[]) => ms.reduce((acc, m) => reduce(acc, wire(m), 1000), s);

const gameInfo = {
  gameName: "High", netGameType: 1, maxNumPlayers: 3, raiseIntervalMode: 2, endRaiseMode: 1,
  proposedGuiSpeed: 4, delayBetweenHands: 5, playerActionTimeout: 20, firstSmallBlind: 10, startMoney: 1000,
};
const done = (playerId: number, action: NetPlayerAction, total: number, money: number, highest: number, minRaise: number, state = NetGameState.netStatePreflop): Init => ({
  messageType: T.Type_PlayersActionDoneMessage,
  playersActionDoneMessage: { gameId: 1, playerId, gameState: state, playerAction: action, totalPlayerBet: total, playerMoney: money, highestSet: highest, minimumRaise: minRaise },
});

let tests = 0;
function test(name: string, f: () => void) {
  f();
  tests++;
  console.log(`ok - ${name}`);
}

test("card encoding matches the server (index % 13 = rank, d/h/s/c)", () => {
  assert.equal(cardLabel(0), "2♦");
  assert.equal(cardLabel(12), "A♦");
  assert.equal(cardLabel(13), "2♥");
  assert.equal(cardLabel(51), "A♣");
  assert.equal(card(38).suit, "s");
  assert.throws(() => card(52));
});

test("web build id carries client type 3", () => {
  assert.equal(WEB_BUILD_ID >>> 24, 3);
});

let s = initialTableState();
test("login, seat and start", () => {
  s = apply(s,
    { messageType: T.Type_InitAckMessage, initAckMessage: { yourSessionId: new Uint8Array([1]), yourPlayerId: 7 } },
    { messageType: T.Type_JoinGameAckMessage, joinGameAckMessage: { gameId: 1, areYouGameAdmin: false, gameInfo } },
    { messageType: T.Type_GamePlayerJoinedMessage, gamePlayerJoinedMessage: { gameId: 1, playerId: 8, isGameAdmin: false } },
    { messageType: T.Type_GamePlayerJoinedMessage, gamePlayerJoinedMessage: { gameId: 1, playerId: 9, isGameAdmin: false } },
    { messageType: T.Type_PlayerInfoReplyMessage, playerInfoReplyMessage: { playerId: 8, playerInfoData: { playerName: "bob", isHuman: true, playerRights: 2 } } },
    { messageType: T.Type_GameStartInitialMessage, gameStartInitialMessage: { gameId: 1, startDealerPlayerId: 9, playerSeats: [9, 7, 8] } },
  );
  assert.equal(s.phase, "playing");
  assert.equal(s.myId, 7);
  assert.equal(s.title, "High");
  assert.deepEqual(s.seats.map((p) => p.playerId), [9, 7, 8]);
  assert.equal(s.seats[2].name, "bob");
  assert.ok(s.seats.every((p) => p.cash === 1000));
});

test("hand start deals my cards and blinds are posted", () => {
  s = apply(s,
    { messageType: T.Type_HandStartMessage, handStartMessage: { gameId: 1, smallBlind: 10, plainCards: { plainCard1: 12, plainCard2: 25 }, seatStates: [0, 0, 0], dealerPlayerId: 9 } },
    done(7, NetPlayerAction.netActionNone, 10, 990, 10, 0, NetGameState.netStatePreflopSmallBlind),
    done(8, NetPlayerAction.netActionNone, 20, 980, 20, 20, NetGameState.netStatePreflopBigBlind),
    { messageType: T.Type_PlayersTurnMessage, playersTurnMessage: { gameId: 1, playerId: 9, gameState: NetGameState.netStatePreflop } },
  );
  assert.equal(s.handNum, 1);
  assert.deepEqual(s.seats[1].cards, [12, 25]);
  assert.equal(s.seats[0].cards, undefined);
  assert.equal(s.seats[1].lastAction, "SB");
  assert.equal(pot(s), 30);
  assert.equal(legalActions(s), null, "not my turn");
});

test("my turn: legal actions and raise bounds", () => {
  s = apply(s,
    done(9, NetPlayerAction.netActionRaise, 60, 940, 60, 40),
    { messageType: T.Type_PlayersTurnMessage, playersTurnMessage: { gameId: 1, playerId: 7, gameState: NetGameState.netStatePreflop } },
  );
  const l = legalActions(s)!;
  assert.ok(l);
  assert.equal(l.check, false);
  assert.equal(l.call, 50); // 60 - my 10
  assert.deepEqual(l.raise, { min: 100, max: 1000, kind: "raise" }); // 60 + min raise 40; all-in total 10 + 990
  assert.equal(pot(s), 90);
});

test("flop collects the street into the pot", () => {
  s = apply(s,
    done(7, NetPlayerAction.netActionCall, 60, 940, 60, 40),
    done(8, NetPlayerAction.netActionFold, 20, 980, 60, 40),
    { messageType: T.Type_DealFlopCardsMessage, dealFlopCardsMessage: { gameId: 1, flopCard1: 0, flopCard2: 1, flopCard3: 2 } },
    { messageType: T.Type_PlayersTurnMessage, playersTurnMessage: { gameId: 1, playerId: 7, gameState: NetGameState.netStateFlop } },
  );
  assert.equal(s.street, "flop");
  assert.deepEqual(s.board, [0, 1, 2]);
  assert.equal(pot(s), 140);
  assert.ok(s.seats.every((p) => p.bet === 0));
  assert.equal(s.seats[2].folded, true);
  const l = legalActions(s)!;
  assert.equal(l.check, true);
  assert.deepEqual(l.raise, { min: 20, max: 940, kind: "bet" });
});

test("hand result updates stacks and shows cards", () => {
  s = apply(s, {
    messageType: T.Type_EndOfHandShowCardsMessage,
    endOfHandShowCardsMessage: { gameId: 1, playerResults: [
      { playerId: 7, resultCard1: 12, resultCard2: 25, bestHandPosition: [], moneyWon: 140, playerMoney: 1080 },
      { playerId: 9, resultCard1: 3, resultCard2: 4, bestHandPosition: [], moneyWon: 0, playerMoney: 940 },
    ] },
  });
  assert.equal(s.handOver, true);
  assert.equal(s.seats[1].cash, 1080);
  assert.equal(s.seats[1].won, 140);
  assert.deepEqual(s.seats[0].cards, [3, 4]);
  assert.match(s.log.at(-1)!, /You won 140/);
});

test("busted player is out next hand; game end", () => {
  s = apply(s,
    { messageType: T.Type_HandStartMessage, handStartMessage: { gameId: 1, smallBlind: 10, seatStates: [0, 0, 2] } },
  );
  assert.equal(s.seats[2].out, true);
  assert.equal(s.seats[2].folded, true);
  s = apply(s, { messageType: T.Type_EndOfGameMessage, endOfGameMessage: { gameId: 1, winnerPlayerId: 7 } });
  assert.equal(s.phase, "ended");
  assert.equal(s.winnerId, 7);
});

test("server errors become readable text", () => {
  const e = apply(initialTableState(), { messageType: T.Type_ErrorMessage, errorMessage: { errorReason: 3 } });
  assert.equal(e.phase, "error");
  assert.match(e.error!, /seat pass/);
});

test("rejoin a running game: offer, table rebuilt, dealt in next hand", () => {
  let r = apply(initialTableState(),
    { messageType: T.Type_InitAckMessage, initAckMessage: { yourSessionId: new Uint8Array([2]), yourPlayerId: 12, rejoinGameId: 1 } },
    { messageType: T.Type_JoinGameAckMessage, joinGameAckMessage: { gameId: 1, areYouGameAdmin: false, gameInfo } },
    { messageType: T.Type_PlayerInfoReplyMessage, playerInfoReplyMessage: { playerId: 12, playerInfoData: { playerName: "alice", isHuman: true, playerRights: 2 } } },
  );
  assert.equal(r.rejoining, true);
  assert.equal(r.phase, "waiting");
  r = apply(r, {
    messageType: T.Type_GameStartRejoinMessage,
    gameStartRejoinMessage: { gameId: 1, startDealerPlayerId: 9, handNum: 6, rejoinPlayerData: [
      { playerId: 9, playerMoney: 700 }, { playerId: 12, playerMoney: 1250 }, { playerId: 8, playerMoney: 0 },
    ] },
  });
  assert.equal(r.phase, "playing");
  assert.deepEqual(r.seats.map((p) => [p.playerId, p.cash]), [[9, 700], [12, 1250], [8, 0]]);
  assert.equal(r.seats[1].name, "alice");
  assert.equal(r.seats[2].out, true);
  assert.equal(r.handNum, 6);
  r = apply(r, { messageType: T.Type_HandStartMessage, handStartMessage: { gameId: 1, smallBlind: 40, plainCards: { plainCard1: 1, plainCard2: 2 }, seatStates: [0, 0, 2] } });
  assert.equal(r.handNum, 7, "hand number continues from the server's");
  assert.equal(r.rejoining, false);
  assert.deepEqual(r.seats[1].cards, [1, 2]);
});

test("others' id changes keep their name", () => {
  const r = apply(s, { messageType: T.Type_PlayerIdChangedMessage, playerIdChangedMessage: { oldPlayerId: 8, newPlayerId: 20 } });
  assert.equal(r.seats.find((p) => p.playerId === 20)?.name, "bob");
});

test("seat opened elsewhere is not retried automatically; network loss is", () => {
  const e = apply(initialTableState(), { messageType: T.Type_ErrorMessage, errorMessage: { errorReason: 4 } });
  assert.equal(e.retryable, false);
  assert.match(e.error!, /somewhere else/);
  const k = apply(initialTableState(), { messageType: T.Type_RemovedFromGameMessage, removedFromGameMessage: { gameId: 1, removedFromGameReason: 3 } });
  assert.equal(k.retryable, false);
  assert.match(k.error!, /knocked out/);
});

test("best hand names", () => {
  // "As" -> index: suits d,h,s,c; ranks 2..A
  const R = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A"];
  const h = (...cs: string[]) => bestHandName(cs.map((c) => "dhsc".indexOf(c.slice(-1)) * 13 + R.indexOf(c.slice(0, -1))));
  assert.equal(h("Ah", "Kd"), "High card");
  assert.equal(h("Ah", "Ad"), "One pair");
  assert.equal(h("Ah", "Kd", "Ac", "Kc", "2s"), "Two pair");
  assert.equal(h("7h", "7d", "7c", "Kc", "2s"), "Three of a kind");
  assert.equal(h("Ah", "2d", "3c", "4c", "5s"), "Straight"); // wheel
  assert.equal(h("10h", "Jd", "Qc", "Kc", "As", "2d", "2h"), "Straight");
  assert.equal(h("2h", "9h", "Jh", "4h", "Kh", "Kd", "Ks"), "Flush"); // flush beats trips
  assert.equal(h("Kh", "Kd", "Ks", "4d", "4h", "4s"), "Full house"); // two trips
  assert.equal(h("Qh", "Qd", "Qs", "Qc", "4h"), "Four of a kind");
  assert.equal(h("5h", "6h", "7h", "8h", "9h", "Kd"), "Straight flush");
  assert.equal(h("Ac", "2c", "3c", "4c", "5c"), "Straight flush"); // steel wheel
  assert.equal(h("10s", "Js", "Qs", "Ks", "As", "9s"), "Royal flush");
  // Flush and a straight in different cards is just a flush, not a straight flush.
  assert.equal(h("2h", "5h", "9h", "Jh", "Kh", "10d", "Qc"), "Flush");
});

console.log(`${tests} tests passed`);
