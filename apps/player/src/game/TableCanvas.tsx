/**
 * The poker table, drawn with PixiJS (WebGL, falls back to canvas).
 *
 * It shows seats around the felt with the viewer at the bottom, ready glows,
 * finishing places and prizes. While a game runs it plays a demo deal; live
 * hands will be driven by the game-server protocol (Phase 2b) through the same
 * component, so the web app and the Capacitor apps share one renderer.
 */
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

export interface TableCanvasProps {
  seatsTotal: number;
  seats: CanvasSeat[];
  phase: "waiting" | "ready" | "running" | "finished" | "cancelled";
  potLabel: string;
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
};

const DISPLAY: TextStyleOptions = { fontFamily: "Lilita One", fill: C.cream };
const SUITS = ["♠", "♥", "♦", "♣"];
const RANKS = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A"];

interface Tween {
  obj: Container;
  from: { x: number; y: number; r: number; s: number };
  to: { x: number; y: number; r: number; s: number };
  t: number;
  dur: number;
  delay: number;
}

function card(w: number, faceUp: boolean): Container {
  const h = w * 1.4;
  const c = new Container();
  const g = new Graphics()
    .roundRect(-w / 2, -h / 2, w, h, w * 0.12)
    .fill(faceUp ? 0xffffff : C.red)
    .stroke({ width: 1.5, color: faceUp ? 0xd7d0bd : 0x7d1d21 });
  c.addChild(g);
  if (faceUp) {
    const suit = SUITS[Math.floor(Math.random() * 4)];
    const rank = RANKS[Math.floor(Math.random() * 13)];
    const red = suit === "♥" || suit === "♦";
    const t = new Text({
      text: `${rank}\n${suit}`,
      style: { ...DISPLAY, fontSize: w * 0.42, fill: red ? 0xd62f36 : 0x161616, align: "center", lineHeight: w * 0.45 },
    });
    t.anchor.set(0.5);
    c.addChild(t);
  } else {
    const inner = new Graphics()
      .roundRect(-w / 2 + 4, -h / 2 + 4, w - 8, h - 8, w * 0.08)
      .stroke({ width: 1.5, color: 0xffffff, alpha: 0.55 });
    c.addChild(inner);
  }
  return c;
}

function chipStack(n: number, colors: number[]): Graphics {
  const g = new Graphics();
  for (let i = 0; i < n; i++) {
    const col = colors[i % colors.length];
    g.ellipse(0, -i * 3, 11, 5).fill(col).stroke({ width: 1, color: 0x000000, alpha: 0.35 });
  }
  return g;
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
        const sy = h / 2 - r - 36;
        return { w, h, cx: w / 2, cy: h / 2, rx: sx / 1.18, ry: sy / 1.28, sx, sy, unit, r };
      };

      const seatPositions = () => {
        const { cx, cy, sx, sy } = geometry();
        const total = propsRef.current.seatsTotal;
        return Array.from({ length: total }, (_, i) => {
          const a = Math.PI / 2 + (i * 2 * Math.PI) / total; // seat 0 at the bottom
          return { x: cx + Math.cos(a) * sx, y: cy + Math.sin(a) * sy, a };
        });
      };

      const drawTable = () => {
        tableLayer.removeChildren().forEach((c) => c.destroy());
        const { cx, cy, rx, ry, unit } = geometry();
        const g = new Graphics();
        g.ellipse(cx, cy + 10, rx + 30, ry + 30).fill({ color: 0x000000, alpha: 0.45 }); // shadow
        g.ellipse(cx, cy, rx + 26, ry + 26).fill(C.rail);
        g.ellipse(cx, cy - 3, rx + 22, ry + 22).stroke({ width: 4, color: C.railHi, alpha: 0.8 });
        g.ellipse(cx, cy, rx + 6, ry + 6).fill(C.goldDark);
        g.ellipse(cx, cy, rx + 3, ry + 3).fill(C.gold);
        g.ellipse(cx, cy, rx, ry).fill(C.feltDark);
        g.ellipse(cx, cy, rx * 0.97, ry * 0.95).fill(C.felt);
        g.ellipse(cx, cy - ry * 0.08, rx * 0.72, ry * 0.62).fill({ color: C.feltHi, alpha: 0.35 });
        for (let i = 0; i < 64; i++) {
          const a = (i / 64) * Math.PI * 2;
          g.circle(cx + Math.cos(a) * rx * 0.8, cy + Math.sin(a) * ry * 0.76, 1.6).fill({ color: C.gold, alpha: 0.35 });
        }
        tableLayer.addChild(g);
        const logo = new Text({ text: "FELT KINGS", style: { ...DISPLAY, fontSize: unit * 0.75, fill: C.cream, letterSpacing: 4 } });
        logo.alpha = 0.12;
        logo.anchor.set(0.5);
        logo.position.set(cx, cy + ry * 0.38);
        tableLayer.addChild(logo);
      };

      const drawSeats = () => {
        seatLayer.removeChildren().forEach((c) => c.destroy({ children: true }));
        const p = propsRef.current;
        const { cx, cy, ry, unit, r } = geometry();
        // Viewer first so they sit at the bottom.
        const ordered = [...p.seats].sort((a, b) => Number(!!b.me) - Number(!!a.me));
        seatPositions().forEach((pos, i) => {
          const s = ordered[i];
          const seat = new Container();
          seat.position.set(pos.x, pos.y);
          const g = new Graphics();
          if (!s) {
            g.circle(0, 0, r).fill({ color: 0x000000, alpha: 0.25 }).stroke({ width: 2, color: C.cream, alpha: 0.25 });
            const plus = new Text({ text: "+", style: { ...DISPLAY, fontSize: r, fill: C.cream } });
            plus.alpha = 0.35;
            plus.anchor.set(0.5);
            seat.addChild(g, plus);
          } else {
            const color = parseInt(colorFor(s.name).slice(1), 16);
            if (s.ready || s.place === 1) {
              g.circle(0, 0, r + 9).fill({ color: C.gold, alpha: 0.18 });
              g.circle(0, 0, r + 5).stroke({ width: 3, color: C.gold });
            }
            g.circle(0, 3, r).fill({ color: 0x000000, alpha: 0.35 });
            g.circle(0, 0, r).fill(color).stroke({ width: 3, color: s.me ? C.gold : 0x000000, alpha: s.me ? 1 : 0.4 });
            g.circle(-r * 0.3, -r * 0.35, r * 0.35).fill({ color: 0xffffff, alpha: 0.18 });
            const ini = new Text({ text: s.name.slice(0, 2).toUpperCase(), style: { ...DISPLAY, fontSize: r * 0.8 } });
            ini.anchor.set(0.5);
            const label = new Text({
              text: s.me ? `${s.name} (you)` : s.name,
              style: { fontFamily: "Inter Variable", fontWeight: "700", fontSize: Math.max(11, unit * 0.22), fill: C.cream },
            });
            label.anchor.set(0.5);
            const plate = new Graphics()
              .roundRect(-label.width / 2 - 8, r + 4, label.width + 16, label.height + 6, 8)
              .fill({ color: C.ink, alpha: 0.85 })
              .stroke({ width: 1, color: C.gold, alpha: 0.35 });
            label.position.set(0, r + 7 + label.height / 2);
            seat.addChild(g, ini, plate, label);
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
                // Lower half: beside the avatar, facing the middle (where chips sit in play),
                // so it stays inside the canvas and off the rail.
                const side = pos.x > cx + 1 ? -1 : 1;
                medal.position.set(side * (r + 10 + medal.width / 2), 0);
              } else {
                medal.position.set(0, -r - 14);
              }
              seat.addChild(medal);
            }
          }
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

      const deal = () => {
        if (dealt) {
          dealt.destroy({ children: true });
          dealt = null;
        }
        const p = propsRef.current;
        if (p.phase !== "running") return;
        dealt = new Container();
        dealLayer.addChild(dealt);
        const { cx, cy, unit } = geometry();
        const cw = Math.max(22, unit * 0.5);
        const positions = seatPositions().slice(0, p.seats.length);
        let delay = 0;
        for (let round = 0; round < 2; round++) {
          positions.forEach((pos, i) => {
            const k = card(cw * 0.8, i === 0); // the viewer sees their own cards
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
          const k = card(cw, true);
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
      };
      redrawRef.current();
      deal();

      app.renderer.on("resize", () => {
        redrawRef.current();
        tweens.length = 0;
        deal();
      });

      app.ticker.add((ticker) => {
        const dt = ticker.deltaMS / 1000;
        for (let i = tweens.length - 1; i >= 0; i--) {
          const tw = tweens[i];
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
        if (propsRef.current.phase === "running") {
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

  // Redraw seats when the table changes.
  useEffect(() => {
    redrawRef.current();
  }, [props.seats, props.seatsTotal, props.phase, props.potLabel]);

  return <div ref={host} className="absolute inset-0" aria-label="Poker table" role="img" />;
}
