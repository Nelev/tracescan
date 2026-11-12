"use client";

import { useEffect, useRef } from "react";
import { cn } from "@/lib/utils";

/**
 * The sign-in backdrop: TraceScan's pipeline, played slowly behind the form. Traces drift in from
 * the left as small waterfalls of spans; each one crosses the trace judge's beam; the healthy
 * ones fade on, a failed one lights its blamed span red, folds into a single point and flies
 * into the embedding space on the right, where it lands in a cluster (a dot) or stays isolated
 * (a ring, as on the run page's cluster map). Every fifth landing the cluster pulses and shows
 * the category it was diagnosed with.
 *
 * Decoration only: a canvas, hidden from assistive technology, that fades out around the form
 * (Clerk's card) so nothing ever seems to run under it. Under prefers-reduced-motion it draws one still frame of a
 * scene already under way. Colors are the design tokens, read once by painting one pixel, so a
 * token change carries over. Nothing here reads data: every trace is made up.
 */

type Rgb = readonly [number, number, number];

interface Palette {
  muted: Rgb;
  primary: Rgb;
  failure: Rgb;
  mono: string;
}

interface Span {
  offset: number;
  width: number;
}

interface Trace {
  x: number;
  y: number;
  speed: number;
  width: number;
  spans: Span[];
  /** The blamed span's index once the judge has failed the trace. */
  failing: number | null;
  judgedAt: number | null;
  alpha: number;
}

interface Point {
  /** The cluster it flies to, or null for an isolated failure. */
  cluster: number | null;
  fromX: number;
  fromY: number;
  /** Where it lands: a fraction of the cluster area, plus an offset in pixels. */
  fx: number;
  fy: number;
  ox: number;
  oy: number;
  flight: number;
  landedAt: number | null;
  phase: number;
  fade: number;
  dying: boolean;
}

interface Cluster {
  fx: number;
  fy: number;
  label: string;
  weight: number;
  landed: number;
  pulseAt: number | null;
}

interface Scene {
  w: number;
  h: number;
  t: number;
  spawnIn: number;
  traces: Trace[];
  points: Point[];
  clusters: Cluster[];
  /** What the scene fades out around (the form), in canvas pixels. */
  clear: Box[];
  dpr: number;
}

interface Box {
  x: number;
  y: number;
  w: number;
  h: number;
}

/**
 * What the scene must never run under: Clerk's card (a stable appearance class) and anything the
 * page marks with `data-keep-clear`.
 */
const CLEAR_SELECTOR = ".cl-cardBox, [data-keep-clear]";
const FORM_CLEAR = 14;
const FORM_FEATHER = 64;

const ROW = 9;
const BAR = 4;
const FAIL_RATE = 0.3;
const ISOLATED_RATE = 0.1;
const FLIGHT_S = 1.7;
const DETACH_S = 0.9;
const MAX_POINTS = 11;
const PULSE_EVERY = 5;
const PULSE_S = 1.8;
/**
 * The hairline floor of the embedding space: a dot grid. Static, so it is a CSS background the
 * browser draws once, not something the canvas repaints every frame.
 */
const GRID_BACKGROUND =
  "bg-[radial-gradient(circle,color-mix(in_oklch,var(--border)_45%,transparent)_1px,transparent_1px)] bg-size-[28px_28px] bg-position-[14px_14px]";
/** The stage names run along the top; traces start below them. */
const CAPTION_Y = 32;
const SCENE_TOP = 64;

function makeClusters(): Cluster[] {
  return [
    {
      fx: 0.18,
      fy: 0.22,
      label: "tool_schema_error",
      weight: 0.34,
      landed: 0,
      pulseAt: null,
    },
    {
      fx: 0.82,
      fy: 0.4,
      label: "retrieval_miss",
      weight: 0.28,
      landed: 0,
      pulseAt: null,
    },
    {
      fx: 0.12,
      fy: 0.62,
      label: "infra_error",
      weight: 0.22,
      landed: 0,
      pulseAt: null,
    },
    {
      fx: 0.74,
      fy: 0.8,
      label: "context_overflow",
      weight: 0.16,
      landed: 0,
      pulseAt: null,
    },
  ];
}

interface Layout {
  judgeX: number;
  left: number;
  right: number;
}

let layoutFor = -1;
let layoutMemo: Layout = { judgeX: 0, left: 0, right: 0 };

/**
 * Where each stage sits: the judge's beam left of the form, the clusters right of it. Called for
 * every point and tail dot of every frame, so it is worked out once per width.
 */
function layout(w: number): Layout {
  if (w !== layoutFor) {
    const left = Math.min(w / 2 + 270, w * 0.72);
    layoutMemo = {
      judgeX: Math.min(Math.max(w / 2 - 260, w * 0.2), w * 0.36),
      left,
      right: Math.min(w * 0.95, left + 560),
    };
    layoutFor = w;
  }
  return layoutMemo;
}

function clusterCenter(s: Scene, fx: number, fy: number): [number, number] {
  const { left, right } = layout(s.w);
  return [left + fx * (right - left), s.h * (0.1 + fy * 0.8)];
}

function makeTrace(s: Scene): Trace {
  const count = 3 + Math.floor(Math.random() * 4);
  const width = 88 + Math.random() * 100;
  const spans: Span[] = [{ offset: 0, width }];
  for (let i = 1; i < count; i++) {
    const offset = 8 + Math.random() * width * 0.55;
    spans.push({
      offset,
      width: Math.max(12, Math.random() * (width - offset)),
    });
  }
  const height = count * ROW;
  return {
    x: -width - 20,
    y: SCENE_TOP + Math.random() * (s.h * 0.94 - SCENE_TOP - height),
    speed: 22 + Math.random() * 16,
    width,
    spans,
    failing: null,
    judgedAt: null,
    alpha: 0,
  };
}

function pickCluster(clusters: Cluster[]): number | null {
  if (Math.random() < ISOLATED_RATE) return null;
  let r = Math.random();
  for (const [i, c] of clusters.entries()) {
    r -= c.weight;
    if (r <= 0) return i;
  }
  return 0;
}

function gaussian(): number {
  return (Math.random() + Math.random() + Math.random() - 1.5) / 1.5;
}

function detach(s: Scene, tr: Trace, failing: number) {
  const span = tr.spans[failing];
  const cluster = pickCluster(s.clusters);
  const target = cluster === null ? null : s.clusters[cluster];
  s.points.push({
    cluster,
    fromX: tr.x + span.offset + span.width / 2,
    fromY: tr.y + failing * ROW,
    fx: target ? target.fx : 0.3 + Math.random() * 0.4,
    fy: target ? target.fy : Math.random(),
    ox: target ? gaussian() * 26 : 0,
    oy: target ? gaussian() * 22 : 0,
    flight: 0,
    landedAt: null,
    phase: Math.random() * Math.PI * 2,
    fade: 1,
    dying: false,
  });
}

function land(s: Scene, p: Point) {
  p.landedAt = s.t;
  if (p.cluster === null) return;
  const c = s.clusters[p.cluster];
  c.landed += 1;
  if (c.landed % PULSE_EVERY === 0) c.pulseAt = s.t;
  let count = 0;
  let oldest: Point | null = null;
  for (const q of s.points) {
    if (q.cluster !== p.cluster || q.landedAt === null || q.dying) continue;
    count += 1;
    oldest ??= q;
  }
  if (oldest && count > MAX_POINTS) oldest.dying = true;
}

function step(s: Scene, dt: number) {
  s.t += dt;
  const { judgeX } = layout(s.w);
  s.spawnIn -= dt;
  if (s.spawnIn <= 0) {
    s.traces.push(makeTrace(s));
    s.spawnIn = 0.5 + Math.random() * 0.7;
  }
  for (const tr of s.traces) {
    tr.x += tr.speed * dt;
    if (tr.judgedAt === null) {
      tr.alpha = Math.min(1, tr.alpha + dt * 1.2);
      if (tr.x + tr.width >= judgeX) {
        tr.judgedAt = s.t;
        if (Math.random() < FAIL_RATE) {
          tr.failing = 1 + Math.floor(Math.random() * (tr.spans.length - 1));
        }
      }
    } else if (tr.failing !== null) {
      if (s.t - tr.judgedAt >= DETACH_S) {
        detach(s, tr, tr.failing);
        tr.alpha = 0;
      }
    } else {
      tr.alpha -= dt * 0.55;
    }
  }
  s.traces = s.traces.filter((tr) => tr.alpha > 0 || tr.judgedAt === null);
  for (const p of s.points) {
    if (p.landedAt === null) {
      p.flight = Math.min(1, p.flight + dt / FLIGHT_S);
      if (p.flight >= 1) land(s, p);
    } else if (p.cluster === null && s.t - p.landedAt > 9) {
      p.dying = true;
    }
    if (p.dying) p.fade -= dt * 0.5;
  }
  s.points = s.points.filter((p) => p.fade > 0);
}

function ease(t: number): number {
  const c = Math.min(1, Math.max(0, t));
  return c < 0.5 ? 4 * c * c * c : 1 - (-2 * c + 2) ** 3 / 2;
}

function rgba([r, g, b]: Rgb, a: number): string {
  return `rgba(${r}, ${g}, ${b}, ${Math.max(0, Math.min(1, a))})`;
}

function mix(a: Rgb, b: Rgb, t: number): Rgb {
  return [
    a[0] + (b[0] - a[0]) * t,
    a[1] + (b[1] - a[1]) * t,
    a[2] + (b[2] - a[2]) * t,
  ];
}

/** Where a point is: on its arc while it flies, then wobbling gently around its spot. */
function pointAt(s: Scene, p: Point, flight: number): [number, number] {
  const [cx, cy] = clusterCenter(s, p.fx, p.fy);
  const tx = cx + p.ox;
  const ty = cy + p.oy;
  if (flight >= 1) {
    return [
      tx + Math.sin(s.t * 0.7 + p.phase) * 2.2,
      ty + Math.cos(s.t * 0.5 + p.phase) * 1.8,
    ];
  }
  const e = ease(flight);
  const mx = (p.fromX + tx) / 2;
  const my = Math.min(p.fromY, ty) - 90;
  const u = 1 - e;
  return [
    u * u * p.fromX + 2 * u * e * mx + e * e * tx,
    u * u * p.fromY + 2 * u * e * my + e * e * ty,
  ];
}

function drawTraces(ctx: CanvasRenderingContext2D, s: Scene, pal: Palette) {
  for (const tr of s.traces) {
    const since = tr.judgedAt === null ? null : s.t - tr.judgedAt;
    // The judge's look: a short brightening as the trace crosses the beam.
    const flash = since !== null && since < 0.5 ? 1 - since / 0.5 : 0;
    // A failed trace thins out as it folds into its point.
    const fold =
      tr.failing !== null && since !== null
        ? Math.max(0, 1 - since / DETACH_S)
        : 1;
    ctx.fillStyle = rgba(pal.muted, 0.25 * tr.alpha * fold);
    ctx.fillRect(tr.x, tr.y + BAR, 1, (tr.spans.length - 1) * ROW);
    for (const [i, span] of tr.spans.entries()) {
      const blamed = tr.failing === i;
      const y = tr.y + i * ROW;
      ctx.fillStyle = blamed
        ? rgba(pal.failure, 0.95)
        : rgba(
            pal.muted,
            ((since === null ? 0.5 : 0.34) + flash * 0.4) * tr.alpha * fold,
          );
      ctx.beginPath();
      ctx.roundRect(tr.x + span.offset, y, span.width, BAR, BAR / 2);
      ctx.fill();
    }
  }
}

function drawBeam(ctx: CanvasRenderingContext2D, s: Scene, pal: Palette) {
  const { judgeX } = layout(s.w);
  ctx.fillStyle = rgba(pal.primary, 0.1);
  ctx.fillRect(judgeX, 0, 1, s.h);
  const len = 180;
  const y = ((s.t * 80) % (s.h + len)) - len;
  const sweep = ctx.createLinearGradient(0, y, 0, y + len);
  sweep.addColorStop(0, rgba(pal.primary, 0));
  sweep.addColorStop(0.7, rgba(pal.primary, 0.55));
  sweep.addColorStop(1, rgba(pal.primary, 0));
  ctx.fillStyle = sweep;
  ctx.fillRect(judgeX - 0.5, y, 2, len);
}

function drawClusters(ctx: CanvasRenderingContext2D, s: Scene, pal: Palette) {
  ctx.font = `500 11px ${pal.mono}`;
  ctx.textAlign = "center";
  const landed: Point[][] = s.clusters.map(() => []);
  for (const p of s.points) {
    if (p.cluster !== null && p.landedAt !== null) landed[p.cluster].push(p);
  }
  for (const [i, c] of s.clusters.entries()) {
    const [cx, cy] = clusterCenter(s, c.fx, c.fy);
    const members = landed[i];
    let reach = 18;
    for (const p of members) {
      const [x, y] = pointAt(s, p, 1);
      reach = Math.max(reach, Math.hypot(x - cx, y - cy));
      ctx.strokeStyle = rgba(pal.primary, 0.22 * p.fade);
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(cx, cy);
      ctx.lineTo(x, y);
      ctx.stroke();
    }
    const hull = reach + 12;
    ctx.strokeStyle = rgba(pal.muted, members.length > 0 ? 0.35 : 0.15);
    ctx.setLineDash([2, 5]);
    ctx.beginPath();
    ctx.arc(cx, cy, hull, 0, Math.PI * 2);
    ctx.stroke();
    ctx.setLineDash([]);
    if (c.pulseAt !== null) {
      const since = s.t - c.pulseAt;
      if (since < PULSE_S) {
        const k = since / PULSE_S;
        ctx.strokeStyle = rgba(pal.primary, 0.6 * (1 - k));
        ctx.lineWidth = 1.5;
        ctx.beginPath();
        ctx.arc(cx, cy, hull + ease(k) * 42, 0, Math.PI * 2);
        ctx.stroke();
        ctx.lineWidth = 1;
      }
      // The diagnosis stays once made, brightest just after the pulse.
      const glow = since < PULSE_S ? 1 - since / PULSE_S : 0;
      ctx.fillStyle = rgba(pal.muted, 0.6 + glow * 0.4);
      ctx.fillText(`c${i} · ${c.label}`, cx, cy - hull - 10);
    }
    ctx.fillStyle = rgba(pal.primary, 0.5);
    ctx.fillRect(cx - 1, cy - 1, 2, 2);
  }
}

function drawPoints(ctx: CanvasRenderingContext2D, s: Scene, pal: Palette) {
  for (const p of s.points) {
    if (p.landedAt === null) {
      // A short tail along the arc, red turning to the accent as the failure finds its group.
      for (let k = 6; k >= 0; k--) {
        const f = p.flight - k * 0.022;
        if (f <= 0) continue;
        const [x, y] = pointAt(s, p, f);
        ctx.fillStyle = rgba(
          mix(pal.failure, pal.primary, ease(f)),
          (1 - k / 7) * 0.8,
        );
        ctx.beginPath();
        ctx.arc(x, y, k === 0 ? 2.6 : 1.6, 0, Math.PI * 2);
        ctx.fill();
      }
      continue;
    }
    const [x, y] = pointAt(s, p, 1);
    const settle = Math.min(1, (s.t - p.landedAt) / 0.6);
    if (p.cluster === null) {
      ctx.strokeStyle = rgba(pal.primary, 0.8 * p.fade);
      ctx.lineWidth = 1.2;
      ctx.beginPath();
      ctx.arc(x, y, 4, 0, Math.PI * 2);
      ctx.stroke();
      ctx.lineWidth = 1;
    } else {
      ctx.fillStyle = rgba(pal.primary, 0.85 * p.fade);
      ctx.beginPath();
      ctx.arc(x, y, 3 + (1 - settle) * 3, 0, Math.PI * 2);
      ctx.fill();
    }
  }
}

function drawCaptions(ctx: CanvasRenderingContext2D, s: Scene, pal: Palette) {
  if (s.w < 900) return;
  const { judgeX, left, right } = layout(s.w);
  const captions: [string, number][] = [
    ["INCOMING TRACES", judgeX / 2],
    ["TRACE JUDGE", judgeX],
    ["FAILURE CLUSTERS", (left + right) / 2],
  ];
  ctx.save();
  ctx.font = `500 12px ${pal.mono}`;
  ctx.letterSpacing = "0.12em";
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  for (const [text, x] of captions) {
    // A clean patch under each caption: nothing passing below it makes it harder to read.
    const w = ctx.measureText(text).width + 24;
    ctx.globalCompositeOperation = "destination-out";
    ctx.fillStyle = "black";
    ctx.fillRect(x - w / 2, CAPTION_Y - 12, w, 24);
    ctx.globalCompositeOperation = "source-over";
    ctx.fillStyle = rgba(pal.muted, 1);
    ctx.fillText(text, x, CAPTION_Y);
    // The stage's mark: a short accent line under its name.
    ctx.fillStyle = rgba(pal.primary, 0.8);
    ctx.fillRect(x - 8, CAPTION_Y + 12, 16, 1.5);
  }
  ctx.restore();
}

function draw(
  ctx: CanvasRenderingContext2D,
  s: Scene,
  pal: Palette,
  mask: Mask | null,
) {
  ctx.clearRect(0, 0, s.w, s.h);
  drawBeam(ctx, s, pal);
  drawTraces(ctx, s, pal);
  drawClusters(ctx, s, pal);
  drawPoints(ctx, s, pal);
  clearForm(ctx, mask);
  drawCaptions(ctx, s, pal);
}

interface Mask {
  image: HTMLCanvasElement;
  x: number;
  y: number;
  w: number;
  h: number;
}

/**
 * The soft-edged shape erased around the form, so traces and points fade out before they reach
 * it instead of being cut off by its border, which reads as something hidden behind it. Blurring
 * is the costliest thing the scene draws, so it is done once per form position into a canvas
 * just big enough for it, and only stamped each frame.
 */
function makeMask(boxes: Box[], dpr: number): Mask | null {
  if (boxes.length === 0) return null;
  const reach = FORM_CLEAR + FORM_FEATHER;
  const x = Math.min(...boxes.map((b) => b.x)) - reach;
  const y = Math.min(...boxes.map((b) => b.y)) - reach;
  const w = Math.max(...boxes.map((b) => b.x + b.w)) + reach - x;
  const h = Math.max(...boxes.map((b) => b.y + b.h)) + reach - y;
  const image = document.createElement("canvas");
  image.width = Math.ceil(w * dpr);
  image.height = Math.ceil(h * dpr);
  const g = image.getContext("2d");
  if (!g) return null;
  g.setTransform(dpr, 0, 0, dpr, -x * dpr, -y * dpr);
  g.fillStyle = "black";
  g.shadowColor = "black";
  // The shadow is in device pixels: the canvas transform does not scale it.
  g.shadowBlur = FORM_FEATHER * dpr;
  for (const f of boxes) {
    g.beginPath();
    g.roundRect(
      f.x - FORM_CLEAR,
      f.y - FORM_CLEAR,
      f.w + 2 * FORM_CLEAR,
      f.h + 2 * FORM_CLEAR,
      24,
    );
    g.fill();
  }
  return { image, x, y, w, h };
}

function clearForm(ctx: CanvasRenderingContext2D, mask: Mask | null) {
  if (!mask) return;
  ctx.save();
  ctx.globalCompositeOperation = "destination-out";
  ctx.drawImage(mask.image, mask.x, mask.y, mask.w, mask.h);
  ctx.restore();
}

/** The tokens as RGB: the canvas cannot blend an oklch string with an alpha of its own. */
function readPalette(): Palette {
  const style = getComputedStyle(document.documentElement);
  const probe = document.createElement("canvas");
  probe.width = 1;
  probe.height = 1;
  const ctx = probe.getContext("2d", { willReadFrequently: true });
  const read = (token: string, fallback: string): Rgb => {
    if (!ctx) return [128, 128, 128];
    ctx.clearRect(0, 0, 1, 1);
    ctx.fillStyle = fallback;
    ctx.fillStyle = style.getPropertyValue(token).trim() || fallback;
    ctx.fillRect(0, 0, 1, 1);
    const [r, g, b] = ctx.getImageData(0, 0, 1, 1).data;
    return [r, g, b];
  };
  return {
    muted: read("--muted-foreground", "#a3a8b8"),
    primary: read("--primary", "#9fa2ff"),
    failure: read("--destructive", "#f07a76"),
    mono:
      style.getPropertyValue("--font-geist-mono").trim() ||
      "ui-monospace, monospace",
  };
}

export function TraceField({ className }: { className?: string }) {
  const ref = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = ref.current;
    const ctx = canvas?.getContext("2d");
    if (!canvas || !ctx) return;
    const palette = readPalette();
    const still = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const scene: Scene = {
      w: 0,
      h: 0,
      t: 0,
      spawnIn: 0,
      traces: [],
      points: [],
      clusters: makeClusters(),
      clear: [],
      dpr: 1,
    };
    let mask: Mask | null = null;

    const resize = () => {
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      scene.w = canvas.clientWidth;
      scene.h = canvas.clientHeight;
      canvas.width = Math.round(scene.w * dpr);
      canvas.height = Math.round(scene.h * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      scene.dpr = dpr;
      mask = makeMask(scene.clear, dpr);
      if (still) draw(ctx, scene, palette, mask);
    };
    // The form loads after the page, changes height between Clerk's steps and scrolls on a short
    // screen: its box is read again often enough to follow it.
    const findForm = () => {
      const next = [...document.querySelectorAll(CLEAR_SELECTOR)].map((el) => {
        const b = el.getBoundingClientRect();
        return { x: b.x, y: b.y, w: b.width, h: b.height };
      });
      const key = (boxes: Box[]) =>
        boxes.map((b) => `${b.x},${b.y},${b.w},${b.h}`).join(";");
      if (key(next) === key(scene.clear)) return;
      scene.clear = next;
      mask = makeMask(next, scene.dpr);
      if (still) draw(ctx, scene, palette, mask);
    };
    resize();
    findForm();
    const watch = window.setInterval(findForm, 300);
    window.addEventListener("scroll", findForm, { passive: true });
    const stop = () => {
      window.clearInterval(watch);
      window.removeEventListener("scroll", findForm);
      window.removeEventListener("resize", resize);
    };
    // Open on a scene already under way: traces on screen, clusters formed and named.
    for (let i = 0; i < 90 * 30; i++) step(scene, 1 / 30);

    window.addEventListener("resize", resize);
    if (still) {
      draw(ctx, scene, palette, mask);
      return stop;
    }
    let frame = 0;
    let last = performance.now();
    const tick = (now: number) => {
      // A hidden tab gets no frames; on return it resumes, not jumps.
      const dt = Math.min(0.05, (now - last) / 1000);
      last = now;
      step(scene, dt);
      draw(ctx, scene, palette, mask);
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => {
      cancelAnimationFrame(frame);
      stop();
    };
  }, []);

  // Hidden on a wrapper: Biome counts a canvas as focusable, so it may not carry aria-hidden.
  return (
    <div aria-hidden="true" className={cn(GRID_BACKGROUND, className)}>
      <canvas ref={ref} className="size-full" />
    </div>
  );
}
