// The cluster map of a run, from `cluster_map` in GET /v1/runs/{id}/detail: the failed traces
// projected to 3D, read once into typed values, plus what the map draws from them (mark sizes,
// cluster labels, the words for each stage). Mirrors agent.schemas.ClusterMap by hand. React-free.

import { formatPercent } from "./format.ts";
import { isRecord } from "./guards.ts";
import { type ClusterMethod, isClusterMethod } from "./run-overview.ts";
import { isNum } from "./traces.ts";

export type Projection = "tsne" | "pca";

/** Traces with the same embedding that landed in the same cluster: one dot. */
export type MapPoint = {
  trace_ids: string[];
  /** Each axis in [-1, 1]. */
  x: number;
  y: number;
  z: number;
  cluster_id: string;
  stage: ClusterMethod;
  /** HDBSCAN's own label, -1 for noise. */
  hdbscan_label: number;
  /** HDBSCAN's membership strength, 0 to 1; 0 for noise. */
  membership: number;
};

export type ClusterMap = {
  projection: Projection;
  /** Trustworthiness of the projection, 0 to 1; null when too few points to measure. */
  trust: number | null;
  points: MapPoint[];
};

const within = (v: unknown, lo: number, hi: number): v is number =>
  isNum(v) && v >= lo && v <= hi;

function isPoint(v: unknown): v is MapPoint {
  return (
    isRecord(v) &&
    Array.isArray(v.trace_ids) &&
    v.trace_ids.length > 0 &&
    v.trace_ids.every((t) => typeof t === "string") &&
    within(v.x, -1, 1) &&
    within(v.y, -1, 1) &&
    within(v.z, -1, 1) &&
    typeof v.cluster_id === "string" &&
    isClusterMethod(v.stage) &&
    Number.isInteger(v.hdbscan_label) &&
    within(v.membership, 0, 1)
  );
}

export function isClusterMap(v: unknown): v is ClusterMap {
  return (
    isRecord(v) &&
    (v.projection === "tsne" || v.projection === "pca") &&
    (v.trust === null || within(v.trust, 0, 1)) &&
    Array.isArray(v.points) &&
    v.points.every(isPoint)
  );
}

/** The mark of each stage: a filled dot, a filled square, an open ring. */
export const STAGE_MARK: Record<ClusterMethod, "dot" | "square" | "ring"> = {
  hdbscan: "dot",
  step_error: "square",
  isolated: "ring",
};

export const PROJECTION_LABEL: Record<Projection, string> = {
  tsne: "t-SNE",
  pca: "PCA",
};

/** How far to believe the distances on the map, in a few words. */
export function fidelityText(trust: number | null): string {
  if (trust === null) return "too few points to rate the map";
  const rated = trust.toFixed(2);
  if (trust >= 0.9) return `fidelity ${rated}: neighbours stayed neighbours`;
  if (trust >= 0.75) return `fidelity ${rated}: distances are approximate`;
  return `fidelity ${rated}: read the groups, not the distances`;
}

/** Below this membership a member is shown as on the edge of its group. */
const EDGE = 0.05;

/**
 * HDBSCAN's verdict on a point, in words: "HDBSCAN group 2, membership 58%", or for a table
 * cell (`short`) "group 2 · 58%". A member's strength can be 0: scikit-learn gives that to the
 * points that join a group only at its edge, so 0 means "at the edge", not noise.
 */
export function hdbscanText(point: MapPoint, short = false): string {
  if (point.hdbscan_label < 0) return short ? "noise" : "noise to HDBSCAN";
  const edge = point.membership < EDGE;
  const share = formatPercent(point.membership);
  return short
    ? `group ${point.hdbscan_label} · ${edge ? "edge" : share}`
    : `HDBSCAN group ${point.hdbscan_label}, ${edge ? "at its edge" : `membership ${share}`}`;
}

/** A mark's radius in scene units: grows with the square root of its traces, so area follows count. */
export function markRadius(count: number): number {
  return 0.022 + 0.014 * Math.sqrt(Math.max(1, count));
}

/** The points of each cluster, in the order the clusters first appear. */
export function groupByCluster(points: MapPoint[]): Map<string, MapPoint[]> {
  const by = new Map<string, MapPoint[]>();
  for (const p of points) {
    const list = by.get(p.cluster_id);
    if (list) list.push(p);
    else by.set(p.cluster_id, [p]);
  }
  return by;
}

export function traceCount(points: MapPoint[]): number {
  return points.reduce((n, p) => n + p.trace_ids.length, 0);
}

/** c2 before c10. */
export function clusterOrder(a: string, b: string): number {
  return a.localeCompare(b, undefined, { numeric: true });
}

export type ClusterLabel = {
  cluster_id: string;
  x: number;
  y: number;
  z: number;
  traces: number;
};

/**
 * Where to write each cluster's name: the trace-weighted centre of its points. Only clusters of
 * more than one trace, the `max` largest of them, plus the selected one whatever its size, so a
 * run of many one-off failures does not bury the map in labels.
 */
export function clusterLabels(
  points: MapPoint[],
  selected: string | null,
  max = 8,
): ClusterLabel[] {
  const labels: ClusterLabel[] = [];
  for (const [cluster_id, members] of groupByCluster(points)) {
    const traces = traceCount(members);
    const at = (axis: "x" | "y" | "z") =>
      members.reduce((sum, p) => sum + p[axis] * p.trace_ids.length, 0) /
      traces;
    labels.push({ cluster_id, x: at("x"), y: at("y"), z: at("z"), traces });
  }
  labels.sort(
    (a, b) => b.traces - a.traces || clusterOrder(a.cluster_id, b.cluster_id),
  );
  const shown = labels.filter((l) => l.traces > 1).slice(0, max);
  const pick = labels.find((l) => l.cluster_id === selected);
  if (pick && !shown.includes(pick)) shown.push(pick);
  return shown;
}

/** The map's points, one row each, by cluster then first trace: the table view. */
export function pointRows(points: MapPoint[]): MapPoint[] {
  return [...points].sort(
    (a, b) =>
      clusterOrder(a.cluster_id, b.cluster_id) ||
      a.trace_ids[0].localeCompare(b.trace_ids[0]),
  );
}

export type Vec3 = [number, number, number];

/** How the selected cluster is outlined: a hull around 4+ points with volume, else spokes. */
export type Outline =
  | { kind: "hull"; vertices: Vec3[] }
  | { kind: "spokes"; center: Vec3; ends: Vec3[] };

/** How far an outline stands off its points, so it wraps the marks instead of cutting them. */
const OUTLINE_MARGIN = 0.08;

const sub = (a: Vec3, b: Vec3): Vec3 => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
const cross = (a: Vec3, b: Vec3): Vec3 => [
  a[1] * b[2] - a[2] * b[1],
  a[2] * b[0] - a[0] * b[2],
  a[0] * b[1] - a[1] * b[0],
];
const dot = (a: Vec3, b: Vec3) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
const EPS = 1e-6;

/** Whether the points span a volume: some four of them are not on one plane. */
export function spansVolume(vs: Vec3[]): boolean {
  if (vs.length < 4) return false;
  const [a] = vs;
  const b = vs.find((v) => dot(sub(v, a), sub(v, a)) > EPS);
  if (!b) return false;
  const ab = sub(b, a);
  const c = vs.find((v) => {
    const n = cross(ab, sub(v, a));
    return dot(n, n) > EPS;
  });
  if (!c) return false;
  const normal = cross(ab, sub(c, a));
  const length = Math.sqrt(dot(normal, normal));
  return vs.some((v) => Math.abs(dot(normal, sub(v, a))) / length > 1e-3);
}

function centre(vs: Vec3[]): Vec3 {
  const n = vs.length;
  return [0, 1, 2].map((i) => vs.reduce((s, v) => s + v[i], 0) / n) as Vec3;
}

/** Each vertex pushed `margin` further from the centre (a vertex on the centre stays put). */
function inflate(vs: Vec3[], c: Vec3, margin: number): Vec3[] {
  return vs.map((v) => {
    const d = sub(v, c);
    const length = Math.sqrt(dot(d, d));
    if (length < EPS) return v;
    const k = (length + margin) / length;
    return [c[0] + d[0] * k, c[1] + d[1] * k, c[2] + d[2] * k];
  });
}

/**
 * The outline of one cluster: a slightly inflated convex hull when its distinct points span a
 * volume, else spokes from its centre to each point (2 or 3 points, or all on one plane), else
 * null (a single point needs no outline).
 */
export function clusterOutline(
  points: MapPoint[],
  clusterId: string,
): Outline | null {
  const vs = points
    .filter((p) => p.cluster_id === clusterId)
    .map((p): Vec3 => [p.x, p.y, p.z]);
  if (vs.length < 2) return null;
  const c = centre(vs);
  if (spansVolume(vs))
    return { kind: "hull", vertices: inflate(vs, c, OUTLINE_MARGIN) };
  return { kind: "spokes", center: c, ends: vs };
}

/** The box to fly the camera to for a cluster: its points' extent, padded, never too small. */
export function clusterBounds(
  points: MapPoint[],
  clusterId: string,
  pad = 0.3,
  minSide = 1.2,
): { min: Vec3; max: Vec3 } | null {
  const vs = points.filter((p) => p.cluster_id === clusterId);
  if (vs.length === 0) return null;
  const min: Vec3 = [Infinity, Infinity, Infinity];
  const max: Vec3 = [-Infinity, -Infinity, -Infinity];
  for (const p of vs) {
    [p.x, p.y, p.z].forEach((v, i) => {
      min[i] = Math.min(min[i], v);
      max[i] = Math.max(max[i], v);
    });
  }
  for (let i = 0; i < 3; i++) {
    const half = Math.max((max[i] - min[i]) / 2 + pad, minSide / 2);
    const mid = (min[i] + max[i]) / 2;
    min[i] = mid - half;
    max[i] = mid + half;
  }
  return { min, max };
}
