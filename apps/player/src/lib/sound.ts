/**
 * Tiny synthesized sound effects (no audio files to ship or license).
 * Muting is remembered per device.
 */
type Effect = "click" | "chip" | "ready" | "win" | "tick" | "error";

const MUTE_KEY = "fk.muted";
let ctx: AudioContext | null = null;

export function isMuted(): boolean {
  try {
    return localStorage.getItem(MUTE_KEY) === "1";
  } catch {
    return false;
  }
}

export function setMuted(muted: boolean): void {
  try {
    localStorage.setItem(MUTE_KEY, muted ? "1" : "0");
  } catch {
    /* ignore */
  }
}

function tone(freq: number, start: number, dur: number, type: OscillatorType, gain = 0.08) {
  if (!ctx) return;
  const osc = ctx.createOscillator();
  const g = ctx.createGain();
  osc.type = type;
  osc.frequency.setValueAtTime(freq, ctx.currentTime + start);
  g.gain.setValueAtTime(0, ctx.currentTime + start);
  g.gain.linearRampToValueAtTime(gain, ctx.currentTime + start + 0.01);
  g.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + start + dur);
  osc.connect(g).connect(ctx.destination);
  osc.start(ctx.currentTime + start);
  osc.stop(ctx.currentTime + start + dur + 0.02);
}

export function play(effect: Effect): void {
  if (isMuted()) return;
  try {
    ctx ??= new AudioContext();
    if (ctx.state === "suspended") void ctx.resume();
  } catch {
    return;
  }
  switch (effect) {
    case "click":
      tone(660, 0, 0.06, "square", 0.03);
      break;
    case "chip":
      tone(1800, 0, 0.05, "triangle", 0.06);
      tone(2400, 0.04, 0.05, "triangle", 0.05);
      break;
    case "ready":
      tone(523, 0, 0.12, "triangle");
      tone(784, 0.1, 0.18, "triangle");
      break;
    case "win":
      [523, 659, 784, 1047].forEach((f, i) => tone(f, i * 0.11, 0.25, "triangle", 0.07));
      break;
    case "tick":
      tone(1200, 0, 0.03, "sine", 0.04);
      break;
    case "error":
      tone(220, 0, 0.18, "sawtooth", 0.04);
      break;
  }
}
