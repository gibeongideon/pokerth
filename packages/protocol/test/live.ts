// Live check: plays a real platform-mode game server through GameClient, the
// same code the web and phone app use. Usage (after bundling with esbuild):
//   node live.mjs ws://127.0.0.1:7233 <seat-token> [<seat-token> ...]
import WebSocket from "ws";
import { GameClient, legalActions, me, pot, type TableState } from "../src/index";

const [url, ...tokens] = process.argv.slice(2);
if (!url || !tokens.length) {
  console.error("usage: live <ws-url> <token>...");
  process.exit(2);
}

let actions = 0;
let raises = 0;
const finished = new Set<number>();
const clients = tokens.map((token, i) => {
  let lastLog = 0;
  const client: GameClient = new GameClient({
    url,
    token,
    WebSocketImpl: WebSocket as unknown as typeof globalThis.WebSocket,
    onState: (s: TableState) => {
      if (i === 0) {
        for (const line of s.log.slice(lastLog >= s.log.length ? s.log.length : lastLog)) console.log(`  | ${line}`);
        lastLog = s.log.length;
      }
      const legal = legalActions(s);
      if (legal) {
        // Give the UI-equivalent a moment, then play a simple mixed strategy.
        setTimeout(() => {
          if (legalActions(client.current) === null) return;
          const r = Math.random();
          actions++;
          if (legal.raise && r < 0.2) {
            raises++;
            client.act({ kind: "raise", to: legal.raise.min + Math.floor(Math.random() * (legal.raise.min / 2)) });
          } else if (legal.check) client.act({ kind: "check" });
          else if (legal.call && (r > 0.15 || legal.call < s.smallBlind * 4)) client.act({ kind: "call" });
          else client.act({ kind: "fold" });
        }, 50);
      }
      if ((s.phase === "ended" || s.phase === "error") && !finished.has(i)) {
        finished.add(i);
        const mine = me(s);
        console.log(`client ${i + 1} (${mine?.name ?? "?"}): ${s.phase}${s.error ? " - " + s.error : ""}; hands ${s.handNum}; chips ${mine?.cash}; pot ${pot(s)}; winner id ${s.winnerId}`);
        if (finished.size === clients.length) {
          console.log(`actions sent ${actions}, raises ${raises}`);
          process.exit(clients.every((c) => c.current.phase === "ended") ? 0 : 1);
        }
      }
    },
  });
  client.connect();
  return client;
});

setTimeout(() => {
  console.error("timeout");
  for (const [i, c] of clients.entries()) console.error(`client ${i + 1}: phase ${c.current.phase}, hand ${c.current.handNum}`);
  process.exit(1);
}, 10 * 60_000);
