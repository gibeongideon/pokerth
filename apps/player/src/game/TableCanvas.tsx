/**
 * The poker table, drawn with PixiJS (WebGL, falls back to canvas).
 *
 * Two modes share one renderer (web and the Capacitor apps):
 *  - lobby mode: seats, ready glows, finishing places and prizes from the
 *    platform; a demo deal plays while a game runs without a live view;
 *  - live mode (`live` prop): real hands from the game server — hole cards,
 *    board, bets, stacks, dealer button, whose turn it is and the turn timer.
 */
import { card as decodeCard } from "@poker/protocol";
import { Application, Container, Graphics, Text, type TextStyleOptions } from "pixi.js";
import { useEffect, useRef } from "react";
import { colorFor } from "../lib/format";

export interface CanvasSeat {
  name: string;
  me?: boolean;
  ready?: boolean;
  place?: number | null;
  prize?: string | null;
}

export interface LiveSeat {
  id: number;
  name: string;
  me: boolean;
  cash: number;
  bet: number;
  folded: boolean;
  out: boolean;
  allIn: boolean;
  dealer: boolean;
  turn: boolean;
  inHand: boolean; // has cards this hand
  cards?: [number, number]; // known cards (mine, or shown)
  action?: string;
  won?: number;
}

export interface LiveTable {
  handKey: number; // changes every hand (deal animation)
  seats: LiveSeat[]; // seat order
  board: number[];
  pot: number;
  turnStartedAt: number;
  turnSeconds: number;
}

export interface TableCanvasProps {
  seatsTotal: number;
  seats: CanvasSeat[];
  phase: "waiting" | "ready" | "running" | "finished" | "cancelled";
  potLabel: string;
  live?: LiveTable | null;
}

const C = {
  rail: 0x3a2313,
  railHi: 0x5a3820,
  gold: 0xf5c451,
  goldDark: 0xb9821a,
  felt: 0x116149,
  feltHi: 0x178a62,
  feltDark: 0x0b3d2d,
  cream: 0xf6f1e3,
  ink: 0x04120c,
  red: 0xc9363b,
  green: 0x3ddc84,
};

const DISPLAY: TextStyleOptions = { fontFamily: "Lilita One", fill: C.cream };
const SUITS = ["♠", "♥", "♦", "♣"];
const RANKS = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A"];
const SUIT_GLYPH = { d: "♦", h: "♥", s: "♠", c: "♣" } as const;

interface Tween {
  obj: Container;
  from: { x: number; y: number; r: number; s: number };
  to: { x: number; y: number; r: number; s: number };
  t: number;
  dur: number;
  delay: number;
}

const chips = (n: number) => n.toLocaleString("en-US");

/** A playing card. `index` = PokerTH card 0..51; undefined = random face (demo). */
function cardSprite(w: number, faceUp: boolean, index?: number): Container {
  const h = w * 1.4;
  const rad = w * 0.11;
  const c = new Container();
  // Soft drop shadow under every card.
  c.addChild(new Graphics().roundRect(-w / 2 + 1.5, -h / 2 + 3, w, h, rad).fill({ color: 0x000000, alpha: 0.35 }));
  if (!faceUp) {
    const g = new Graphics().roundRect(-w / 2, -h / 2, w, h, rad).fill(0xffffff);
    const m = Math.max(2.5, w * 0.07);
    g.roundRect(-w / 2 + m, -h / 2 + m, w - 2 * m, h - 2 * m, rad * 0.7).fill(0xb3262c);
    // Diamond pattern, kept inside the border.
    const step = Math.max(6, w / 5);
    const iw = w / 2 - m - step / 2;
    const ih = h / 2 - m - step / 2;
    for (let y = -ih; y <= ih + 0.1; y += step / 2) {
      const odd = Math.round((y + ih) / (step / 2)) % 2 === 1;
      for (let x = -iw + (odd ? step / 2 : 0); x <= iw + 0.1; x += step) {
        g.poly([x, y - step / 2.4, x + step / 2.4, y, x, y + step / 2.4, x - step / 2.4, y]).fill({ color: 0xe0464b, alpha: 0.55 });
      }
    }
    g.roundRect(-w / 2 + m, -h / 2 + m, w - 2 * m, h - 2 * m, rad * 0.7).stroke({ width: 1.5, color: C.gold });
    g.circle(0, 0, w * 0.17).fill(0x7d1d21).stroke({ width: 1.5, color: C.gold });
    c.addChild(g);
    return c;
  }
  let rank: string;
  let suit: string;
  let red: boolean;
  if (index === undefined) {
    suit = SUITS[Math.floor(Math.random() * 4)];
    rank = RANKS[Math.floor(Math.random() * 13)];
    red = suit === "♥" || suit === "♦";
  } else {
    const k = decodeCard(index);
    rank = k.rank;
    suit = SUIT_GLYPH[k.suit];
    red = k.red;
  }
  const ink = red ? 0xd62f36 : 0x15171c;
  c.addChild(
    new Graphics()
      .roundRect(-w / 2, -h / 2, w, h, rad)
      .fill(0xfbf8f0)
      .stroke({ width: 1, color: 0xcfc6ae }),
  );
  const r = new Text({ text: rank, style: { ...DISPLAY, fontSize: w * 0.36, fill: ink } });
  r.position.set(-w / 2 + w * 0.09, -h / 2 + w * 0.04);
  const sm = new Text({ text: suit, style: { fontFamily: "system-ui", fontSize: w * 0.26, fill: ink } });
  sm.position.set(-w / 2 + w * 0.1, -h / 2 + w * 0.4);
  const big = new Text({ text: suit, style: { fontFamily: "system-ui", fontSize: w * 0.62, fill: ink } });
  big.anchor.set(0.5);
  big.position.set(w * 0.1, h * 0.12);
  c.addChild(r, sm, big);
  return c;
}

function chipStack(n: number, colors: number[]): Graphics {
  const g = new Graphics();
  g.ellipse(0, 3, 13, 5.5).fill({ color: 0x000000, alpha: 0.35 });
  for (let i = 0; i < n; i++) {
    const col = colors[i % colors.length];
    const y = -i * 3.2;
    g.rect(-11, y - 1, 22, 3).fill(col);
    g.ellipse(0, y + 2, 11, 4.6).fill(col);
    // White edge stripes.
    for (const x of [-7, 0, 7]) g.rect(x - 1.2, y - 0.5, 2.4, 2.8).fill({ color: 0xffffff, alpha: 0.85 });
    g.ellipse(0, y - 1, 11, 4.6).fill(col).stroke({ width: 1, color: 0x000000, alpha: 0.3 });
    g.ellipse(0, y - 1, 6.5, 2.6).stroke({ width: 1, color: 0xffffff, alpha: 0.55 });
  }
  return g;
}

/** Chips in front of a seat: a small stack sized to the amount plus the number. */
function betChips(amount: number, fontSize: number): Container {
  const c = new Container();
  const n = Math.max(1, Math.min(6, Math.ceil(Math.log10(amount + 1) * 1.6)));
  const st = chipStack(n, [0xe0464b, 0x3d7be0, 0x35b26b, 0xe2a72e]);
  st.position.set(0, 4);
  const t = new Text({ text: chips(amount), style: { ...DISPLAY, fontSize, fill: C.cream, stroke: { color: C.ink, width: 3 } } });
  t.anchor.set(0, 0.5);
  t.position.set(14, 0);
  c.addChild(st, t);
  return c;
}

export function TableCanvas(props: TableCanvasProps) {
  const host = useRef<HTMLDivElement>(null);
  const appRef = useRef<Application | null>(null);
  const propsRef = useRef(props);
  const redrawRef = useRef<() => void>(() => {});
  propsRef.current = props;

  useEffect(() => {
    let cancelled = false;
    const app = new Application();
    const tweens: Tween[] = [];
    let dealTimer = 0;
    let dealt: Container | null = null;
    // Live-mode animation memory.
    let lastHandKey = -1;
    let lastBoardLen = 0;
    let timer: { g: Graphics; x: number; y: number; r: number } | null = null;

    (async () => {
      await document.fonts.load('20px "Lilita One"').catch(() => undefined);
      await app.init({
        resizeTo: host.current!,
        backgroundAlpha: 0,
        antialias: true,
        autoDensity: true,
        resolution: Math.min(window.devicePixelRatio || 1, 2),
      });
      if (cancelled) {
        app.destroy(true);
        return;
      }
      appRef.current = app;
      host.current!.appendChild(app.canvas);

      const tableLayer = new Container();
      const seatLayer = new Container();
      const dealLayer = new Container();
      app.stage.addChild(tableLayer, dealLayer, seatLayer);

      // Size the table from the room the seats need, so every seat, name
      // plate and medal stays inside the canvas on phones and desktops.
      const geometry = () => {
        const w = app.screen.width;
        const h = app.screen.height;
        const unit = Math.min(w, h) / 10;
        const r = Math.max(18, unit * 0.48);
        const sx = w / 2 - r - 44; // seat ring, leaving room for name plates
        const sy = h / 2 - r - 40;
        return { w, h, cx: w / 2, cy: h / 2, rx: sx / 1.18, ry: sy / 1.28, sx, sy, unit, r };
      };

      const seatPositions = (total: number) => {
        const { cx, cy, sx, sy } = geometry();
        return Array.from({ length: total }, (_, i) => {
          const a = Math.PI / 2 + (i * 2 * Math.PI) / total; // seat 0 at the bottom
          return { x: cx + Math.cos(a) * sx, y: cy + Math.sin(a) * sy, a };
        });
      };

      const drawTable = () => {
        tableLayer.removeChildren().forEach((c) => c.destroy());
        const { cx, cy, rx, ry, unit } = geometry();
        const g = new Graphics();
        // Spotlight pool on the floor.
        for (let k = 6; k >= 1; k--) g.ellipse(cx, cy, (rx + 60) * (0.8 + k * 0.12), (ry + 60) * (0.8 + k * 0.12)).fill({ color: 0x1c9a6d, alpha: 0.018 });
        g.ellipse(cx, cy + 16, rx + 34, ry + 32).fill({ color: 0x000000, alpha: 0.55 }); // shadow
        // Padded leather rail with a lit top edge.
        g.ellipse(cx, cy, rx + 28, ry + 28).fill(0x24140b);
        g.ellipse(cx, cy - 2, rx + 25, ry + 25).fill(C.rail);
        g.ellipse(cx, cy - 4, rx + 21, ry + 20).stroke({ width: 3, color: C.railHi, alpha: 0.9 });
        g.ellipse(cx, cy - 6, rx + 16, ry + 14).stroke({ width: 1.5, color: 0x7a4b29, alpha: 0.6 });
        // Gold trim.
        g.ellipse(cx, cy, rx + 7, ry + 7).fill(C.goldDark);
        g.ellipse(cx, cy, rx + 4, ry + 4).fill(C.gold);
        g.ellipse(cx, cy, rx + 2, ry + 2).fill(0x8a5f14);
        // Felt: darker at the edge, lit in the middle.
        g.ellipse(cx, cy, rx, ry).fill(0x0a3a2b);
        const rings = 10;
        for (let k = 0; k < rings; k++) {
          const t = k / rings;
          g.ellipse(cx, cy - ry * 0.06 * t, rx * (0.98 - t * 0.55), ry * (0.96 - t * 0.55)).fill({ color: k < 2 ? C.felt : C.feltHi, alpha: k < 2 ? 1 : 0.09 });
        }
        // Inner shadow under the rail.
        g.ellipse(cx, cy, rx - 2, ry - 2).stroke({ width: 8, color: 0x000000, alpha: 0.22 });
        // Betting line.
        g.ellipse(cx, cy, rx * 0.8, ry * 0.76).stroke({ width: 1.5, color: C.gold, alpha: 0.28 });
        tableLayer.addChild(g);
        const logo = new Text({ text: "FELT KINGS", style: { ...DISPLAY, fontSize: unit * 0.7, fill: C.cream, letterSpacing: 6 } });
        logo.alpha = 0.1;
        logo.anchor.set(0.5);
        logo.position.set(cx, cy + ry * 0.42);
        tableLayer.addChild(logo);
      };

      /** Avatar + name plate; returns the seat container. */
      const avatar = (name: string, me: boolean, glow: boolean, sub?: string) => {
        const { unit, r } = geometry();
        const seat = new Container();
        const g = new Graphics();
        const color = parseInt(colorFor(name).slice(1), 16);
        if (glow) {
          g.circle(0, 0, r + 9).fill({ color: C.gold, alpha: 0.18 });
          g.circle(0, 0, r + 5).stroke({ width: 3, color: C.gold });
        }
        g.circle(0, 4, r + 3).fill({ color: 0x000000, alpha: 0.45 });
        g.circle(0, 0, r + 3).fill(me ? C.gold : 0x1a1f1c);
        g.circle(0, 0, r + 1).fill(me ? C.goldDark : 0x2c332f);
        g.circle(0, 0, r - 1).fill(color);
        g.circle(0, r * 0.25, r - 1).fill({ color: 0x000000, alpha: 0.12 });
        g.ellipse(-r * 0.15, -r * 0.45, r * 0.55, r * 0.3).fill({ color: 0xffffff, alpha: 0.2 });
        const ini = new Text({ text: name.slice(0, 2).toUpperCase(), style: { ...DISPLAY, fontSize: r * 0.8 } });
        ini.anchor.set(0.5);
        const fs = Math.max(11, unit * 0.22);
        const label = new Text({
          text: me ? `${name} (you)` : name,
          style: { fontFamily: "Inter Variable", fontWeight: "700", fontSize: fs, fill: C.cream },
        });
        label.anchor.set(0.5);
        const subText = sub
          ? new Text({ text: sub, style: { ...DISPLAY, fontSize: fs * 1.05, fill: C.gold } })
          : null;
        subText?.anchor.set(0.5);
        const pw = Math.max(label.width, subText?.width ?? 0) + 16;
        const ph = label.height + (subText ? subText.height : 0) + 6;
        const plate = new Graphics()
          .roundRect(-pw / 2, r + 4, pw, ph, Math.min(12, ph / 2))
          .fill({ color: 0x020806, alpha: 0.88 })
          .stroke({ width: 1, color: me ? C.gold : 0xffffff, alpha: me ? 0.6 : 0.12 });
        label.position.set(0, r + 7 + label.height / 2);
        seat.addChild(g, ini, plate, label);
        if (subText) {
          subText.position.set(0, r + 7 + label.height + subText.height / 2);
          seat.addChild(subText);
        }
        return seat;
      };

      const drawLobbySeats = () => {
        const p = propsRef.current;
        const { cx, cy, ry, unit, r } = geometry();
        // Viewer first so they sit at the bottom.
        const ordered = [...p.seats].sort((a, b) => Number(!!b.me) - Number(!!a.me));
        seatPositions(p.seatsTotal).forEach((pos, i) => {
          const s = ordered[i];
          let seat: Container;
          if (!s) {
            seat = new Container();
            const g = new Graphics().circle(0, 0, r).fill({ color: 0x000000, alpha: 0.25 }).stroke({ width: 2, color: C.cream, alpha: 0.25 });
            const plus = new Text({ text: "+", style: { ...DISPLAY, fontSize: r, fill: C.cream } });
            plus.alpha = 0.35;
            plus.anchor.set(0.5);
            seat.addChild(g, plus);
          } else {
            seat = avatar(s.name, !!s.me, !!s.ready || s.place === 1);
            if (p.phase !== "finished" && p.phase !== "cancelled") {
              // Beside the avatar, on the side facing the middle of the table.
              const stack = chipStack(4, [0xe0464b, 0x3d7be0, 0x35b26b, 0x1c1c22]);
              const side = pos.x > cx + 1 ? -1 : 1;
              stack.position.set(side * r * 1.75, r * 0.35);
              seat.addChild(stack);
            }
            if (s.place) {
              const medal = new Text({
                text: s.prize ? `#${s.place}  ${s.prize}` : `#${s.place}`,
                style: { ...DISPLAY, fontSize: Math.max(13, unit * 0.3), fill: s.prize ? C.gold : C.cream },
              });
              medal.anchor.set(0.5);
              if (pos.y > cy) {
                // Lower half: beside the avatar, facing the middle, so it stays on the canvas.
                const side = pos.x > cx + 1 ? -1 : 1;
                medal.position.set(side * (r + 10 + medal.width / 2), 0);
              } else {
                medal.position.set(0, -r - 14);
              }
              seat.addChild(medal);
            }
          }
          seat.position.set(pos.x, pos.y);
          seatLayer.addChild(seat);
        });
        // Pot in the middle.
        const pot = new Container();
        pot.position.set(cx, cy - ry * 0.05);
        const stacks = [chipStack(5, [0xe2a72e, 0xffe08a]), chipStack(3, [0xe0464b, 0xffffff]), chipStack(4, [0x3d7be0, 0xffffff])];
        stacks.forEach((st, i) => {
          st.position.set((i - 1) * 26, 0);
          pot.addChild(st);
        });
        const potText = new Text({ text: p.potLabel, style: { ...DISPLAY, fontSize: Math.max(16, unit * 0.42), fill: C.gold } });
        potText.anchor.set(0.5, 0);
        potText.position.set(0, 12);
        pot.addChild(potText);
        seatLayer.addChild(pot);
      };

      // ---- live mode -------------------------------------------------------
      const tweenIn = (obj: Container, from: { x: number; y: number }, delay: number, dur = 0.3) => {
        const to = { x: obj.position.x, y: obj.position.y, r: obj.rotation, s: 1 };
        obj.position.set(from.x, from.y);
        obj.scale.set(0.2);
        tweens.push({ obj, from: { x: from.x, y: from.y, r: 0, s: 0.2 }, to, t: 0, dur, delay });
      };

      const drawLive = (live: LiveTable) => {
        const { cx, cy, ry, unit, r } = geometry();
        const n = live.seats.length;
        // Rotate so the viewer sits at the bottom, keeping the seat order.
        const meIdx = Math.max(0, live.seats.findIndex((s) => s.me));
        const ordered = live.seats.map((_, i) => live.seats[(i + meIdx) % n]);
        const positions = seatPositions(n);
        const newHand = live.handKey !== lastHandKey;
        const boardFrom = newHand ? 0 : lastBoardLen;
        lastHandKey = live.handKey;
        lastBoardLen = live.board.length;
        tweens.length = 0;
        dealLayer.removeChildren().forEach((c) => c.destroy({ children: true }));
        timer = null;
        const cw = Math.max(24, unit * 0.52);
        const fs = Math.max(12, unit * 0.26);
        let dealDelay = 0;

        ordered.forEach((s, i) => {
          const pos = positions[i];
          const toward = { x: cx - pos.x, y: cy - pos.y };
          const seat = avatar(s.name, s.me, s.turn || (s.won ?? 0) > 0, s.out ? "out" : s.allIn ? "ALL-IN" : chips(s.cash));
          seat.position.set(pos.x, pos.y);
          seat.alpha = s.out ? 0.35 : s.folded ? 0.55 : 1;
          seatLayer.addChild(seat);

          if (s.turn) {
            const g = new Graphics();
            seat.addChild(g);
            timer = { g, x: 0, y: 0, r: r + 7 };
          }

          // Last action / win badge above the avatar.
          const badgeText = (s.won ?? 0) > 0 ? `+${chips(s.won!)}` : s.action ? s.action.toUpperCase() : "";
          if (badgeText) {
            const t = new Text({
              text: badgeText,
              style: { ...DISPLAY, fontSize: fs, fill: (s.won ?? 0) > 0 ? C.gold : s.action === "fold" ? 0xbbbbbb : C.cream },
            });
            t.anchor.set(0.5);
            const bg = new Graphics()
              .roundRect(-t.width / 2 - 7, -t.height / 2 - 2, t.width + 14, t.height + 4, 8)
              .fill({ color: (s.won ?? 0) > 0 ? 0x3a2a05 : C.ink, alpha: 0.9 })
              .stroke({ width: 1, color: (s.won ?? 0) > 0 ? C.gold : C.cream, alpha: 0.4 });
            const b = new Container();
            b.addChild(bg, t);
            b.position.set(0, -r - t.height / 2 - 6);
            seat.addChild(b);
          }

          // Dealer button.
          if (s.dealer) {
            const d = new Container();
            d.addChild(new Graphics().circle(0, 2, 11).fill({ color: 0x000000, alpha: 0.4 }).circle(0, 0, 11).fill(0xfbf8f0).stroke({ width: 2, color: C.goldDark }));
            const t = new Text({ text: "D", style: { ...DISPLAY, fontSize: 12, fill: 0x161616 } });
            t.anchor.set(0.5);
            d.addChild(t);
            d.position.set(pos.x + r * 0.95, pos.y - r * 0.75);
            seatLayer.addChild(d);
          }

          // Hole cards, between the seat and the middle.
          if (s.inHand && !s.out) {
            const big = s.me;
            const w = big ? cw * 1.1 : cw * 0.72;
            // Mine: big, beside my avatar (clear of the action badge); others: toward the middle.
            const base = big
              ? { x: pos.x + r + w * 1.2, y: pos.y - r * 0.1 }
              : { x: pos.x + toward.x * 0.3, y: pos.y + toward.y * 0.3 };
            [0, 1].forEach((k) => {
              const known = s.cards?.[k];
              const sprite = cardSprite(w, known !== undefined, known);
              sprite.position.set(base.x + (k - 0.5) * w * 0.62, base.y);
              sprite.rotation = (k - 0.5) * 0.18;
              sprite.alpha = s.folded ? 0.4 : 1;
              dealLayer.addChild(sprite);
              if (newHand) {
                tweenIn(sprite, { x: cx, y: cy }, dealDelay + k * n * 0.08);
              }
            });
            dealDelay += 0.08;
          }

          // Chips bet this street, halfway to the middle.
          if (s.bet > 0) {
            const b = betChips(s.bet, fs);
            b.position.set(pos.x + toward.x * 0.48 - 10, pos.y + toward.y * 0.48);
            seatLayer.addChild(b);
          }
        });

        // Board.
        live.board.forEach((idx, i) => {
          const sprite = cardSprite(cw, true, idx);
          sprite.position.set(cx + (i - 2) * cw * 1.12, cy - ry * 0.18);
          dealLayer.addChild(sprite);
          if (i >= boardFrom) tweenIn(sprite, { x: cx, y: cy - ry * 0.6 }, (i - boardFrom) * 0.12, 0.35);
        });

        // Pot.
        if (live.pot > 0) {
          const pot = new Container();
          pot.position.set(cx, cy + ry * 0.2);
          const st = chipStack(Math.min(8, 2 + Math.floor(Math.log10(live.pot + 1) * 1.5)), [0xe2a72e, 0xffe08a]);
          const t = new Text({ text: `POT ${chips(live.pot)}`, style: { ...DISPLAY, fontSize: Math.max(15, unit * 0.34), fill: C.gold, letterSpacing: 1 } });
          t.anchor.set(0.5, 0.5);
          t.position.set(0, 22);
          const pill = new Graphics()
            .roundRect(-t.width / 2 - 12, 22 - t.height / 2 - 4, t.width + 24, t.height + 8, (t.height + 8) / 2)
            .fill({ color: 0x000000, alpha: 0.45 })
            .stroke({ width: 1, color: C.gold, alpha: 0.35 });
          pot.addChild(st, pill, t);
          seatLayer.addChild(pot);
        }
      };

      const drawSeats = () => {
        seatLayer.removeChildren().forEach((c) => c.destroy({ children: true }));
        const live = propsRef.current.live;
        if (live) {
          if (dealt) {
            dealt.destroy({ children: true });
            dealt = null;
          }
          drawLive(live);
        } else {
          if (lastHandKey !== -1) {
            // Leaving live mode (game over): clear the last hand's cards.
            dealLayer.removeChildren().forEach((c) => c.destroy({ children: true }));
            tweens.length = 0;
            lastHandKey = -1;
            lastBoardLen = 0;
            timer = null;
          }
          drawLobbySeats();
        }
      };

      // Demo deal while a game runs without a live view (spectators, offline).
      const deal = () => {
        if (dealt) {
          dealt.destroy({ children: true });
          dealt = null;
        }
        const p = propsRef.current;
        if (p.phase !== "running" || p.live) return;
        dealt = new Container();
        dealLayer.addChild(dealt);
        const { cx, cy, unit } = geometry();
        const cw = Math.max(22, unit * 0.5);
        const positions = seatPositions(p.seatsTotal).slice(0, p.seats.length);
        let delay = 0;
        for (let round = 0; round < 2; round++) {
          positions.forEach((pos, i) => {
            const k = cardSprite(cw * 0.8, i === 0);
            k.position.set(cx, cy);
            k.scale.set(0.2);
            dealt!.addChild(k);
            const tx = cx + (pos.x - cx) * 0.62 + (round - 0.5) * cw * 0.6;
            const ty = cy + (pos.y - cy) * 0.62;
            tweens.push({ obj: k, from: { x: cx, y: cy, r: 0, s: 0.2 }, to: { x: tx, y: ty, r: (round - 0.5) * 0.25, s: 1 }, t: 0, dur: 0.32, delay });
            delay += 0.09;
          });
        }
        for (let i = 0; i < 5; i++) {
          const k = cardSprite(cw, true);
          k.position.set(cx, cy);
          k.scale.set(0.1);
          dealt.addChild(k);
          const tx = cx + (i - 2) * cw * 1.12;
          const ty = cy - geometry().ry * 0.32;
          const extra = i < 3 ? 0.6 : i === 3 ? 1.8 : 3.0; // flop, turn, river
          tweens.push({ obj: k, from: { x: cx, y: cy, r: 0, s: 0.1 }, to: { x: tx, y: ty, r: 0, s: 1 }, t: 0, dur: 0.35, delay: delay + extra + i * 0.12 });
        }
      };

      redrawRef.current = () => {
        drawTable();
        drawSeats();
        if (!propsRef.current.live && !dealt) deal();
      };
      redrawRef.current();

      app.renderer.on("resize", () => {
        if (propsRef.current.live) lastHandKey = -2; // re-layout without replaying old animations
        tweens.length = 0;
        if (dealt) {
          dealt.destroy({ children: true });
          dealt = null;
        }
        redrawRef.current();
        tweens.forEach((tw) => {
          tw.t = 1;
          tw.delay = 0;
        });
      });

      app.ticker.add((ticker) => {
        const dt = ticker.deltaMS / 1000;
        for (let i = tweens.length - 1; i >= 0; i--) {
          const tw = tweens[i];
          if (tw.obj.destroyed) {
            tweens.splice(i, 1);
            continue;
          }
          if (tw.delay > 0) {
            tw.delay -= dt;
            continue;
          }
          tw.t = Math.min(1, tw.t + dt / tw.dur);
          const e = 1 - Math.pow(1 - tw.t, 3);
          tw.obj.position.set(tw.from.x + (tw.to.x - tw.from.x) * e, tw.from.y + (tw.to.y - tw.from.y) * e);
          tw.obj.rotation = tw.from.r + (tw.to.r - tw.from.r) * e;
          tw.obj.scale.set(tw.from.s + (tw.to.s - tw.from.s) * e);
          if (tw.t >= 1) tweens.splice(i, 1);
        }
        const live = propsRef.current.live;
        if (live && timer && !timer.g.destroyed) {
          // Turn timer: a ring that drains from gold to red.
          const left = Math.max(0, 1 - (Date.now() - live.turnStartedAt) / (live.turnSeconds * 1000));
          const color = left > 0.5 ? C.gold : left > 0.25 ? 0xf59e0b : C.red;
          timer.g.clear();
          timer.g.circle(timer.x, timer.y, timer.r).stroke({ width: 5, color: 0x000000, alpha: 0.35 });
          if (left > 0) {
            timer.g
              .moveTo(timer.x, timer.y - timer.r)
              .arc(timer.x, timer.y, timer.r, -Math.PI / 2, -Math.PI / 2 + left * Math.PI * 2)
              .stroke({ width: 5, color, cap: "round" });
          }
        }
        if (propsRef.current.phase === "running" && !live) {
          dealTimer += dt;
          if (dealTimer > 9) {
            dealTimer = 0;
            deal();
          }
        }
      });
    })();

    return () => {
      cancelled = true;
      if (appRef.current) {
        appRef.current.destroy(true, { children: true });
        appRef.current = null;
      }
    };
  }, []);

  // Redraw when the table changes.
  useEffect(() => {
    redrawRef.current();
  }, [props.seats, props.seatsTotal, props.phase, props.potLabel, props.live]);

  return <div ref={host} className="absolute inset-0" aria-label="Poker table" role="img" />;
}
