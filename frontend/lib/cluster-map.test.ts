import assert from "node:assert/strict";
import { test } from "node:test";
import {
  clusterBounds,
  clusterLabels,
  clusterOutline,
  fidelityText,
  groupByCluster,
  hdbscanText,
  isClusterMap,
  type MapPoint,
  markRadius,
  pointRows,
  spansVolume,
} from "./cluster-map.ts";

const point = (over: Partial<MapPoint> = {}): MapPoint => ({
  trace_ids: ["t1"],
  x: 0,
  y: 0,
  z: 0,
  cluster_id: "c0",
  stage: "hdbscan",
  hdbscan_label: 0,
  membership: 1,
  ...over,
});

const MAP = { projection: "pca", trust: 0.98, points: [point()] };

test("a map on contract is read", () => {
  assert.ok(isClusterMap(MAP));
  assert.ok(isClusterMap({ ...MAP, trust: null, points: [] }));
});

test("a map off contract is refused", () => {
  for (const bad of [
    null,
    { ...MAP, projection: "umap" },
    { ...MAP, trust: 1.5 },
    { ...MAP, points: [point({ x: 2 })] },
    { ...MAP, points: [point({ trace_ids: [] })] },
    { ...MAP, points: [point({ stage: "other" as "hdbscan" })] },
    { ...MAP, points: [point({ hdbscan_label: 0.5 })] },
    { ...MAP, points: [point({ membership: -0.1 })] },
  ]) {
    assert.equal(isClusterMap(bad), false, JSON.stringify(bad));
  }
});

test("labels sit at the trace-weighted centre of a cluster", () => {
  const [label] = clusterLabels(
    [
      point({ trace_ids: ["a", "b", "c"], x: 1 }),
      point({ trace_ids: ["d"], x: -1 }),
    ],
    null,
  );
  assert.equal(label.cluster_id, "c0");
  assert.equal(label.traces, 4);
  assert.equal(label.x, 0.5);
});

test("one-trace clusters get no label unless selected, and the largest come first", () => {
  const points = [
    point({ cluster_id: "c10", trace_ids: ["a", "b"] }),
    point({ cluster_id: "c2", trace_ids: ["c", "d"] }),
    point({ cluster_id: "c0", trace_ids: ["e", "f", "g"] }),
    point({ cluster_id: "c3", trace_ids: ["h"], stage: "isolated" }),
  ];
  const ids = (selected: string | null, max?: number) =>
    clusterLabels(points, selected, max).map((l) => l.cluster_id);
  assert.deepEqual(ids(null), ["c0", "c2", "c10"]);
  assert.deepEqual(ids("c3"), ["c0", "c2", "c10", "c3"]);
  assert.deepEqual(ids(null, 1), ["c0"]);
  assert.deepEqual(ids("c10", 1), ["c0", "c10"]);
});

test("table rows go by cluster number, then first trace", () => {
  const rows = pointRows([
    point({ cluster_id: "c10", trace_ids: ["a"] }),
    point({ cluster_id: "c2", trace_ids: ["z"] }),
    point({ cluster_id: "c2", trace_ids: ["b"] }),
  ]);
  assert.deepEqual(
    rows.map((p) => `${p.cluster_id}:${p.trace_ids[0]}`),
    ["c2:b", "c2:z", "c10:a"],
  );
});

test("a mark's area grows with its traces", () => {
  const area = (n: number) => markRadius(n) ** 2;
  assert.ok(area(4) > area(1));
  assert.equal(markRadius(0), markRadius(1));
});

test("the words for fidelity and HDBSCAN's verdict", () => {
  assert.match(fidelityText(0.95), /^fidelity 0\.95: neighbours/);
  assert.match(fidelityText(0.8), /approximate/);
  assert.match(fidelityText(0.5), /not the distances/);
  assert.equal(fidelityText(null), "too few points to rate the map");
  assert.equal(hdbscanText(point({ hdbscan_label: -1 })), "noise to HDBSCAN");
  assert.equal(
    hdbscanText(point({ hdbscan_label: 2, membership: 0.583 })),
    "HDBSCAN group 2, membership 58%",
  );
  assert.equal(
    hdbscanText(point({ hdbscan_label: 2, membership: 0 })),
    "HDBSCAN group 2, at its edge",
  );
  assert.equal(hdbscanText(point({ hdbscan_label: -1 }), true), "noise");
  assert.equal(
    hdbscanText(point({ hdbscan_label: 2, membership: 0 }), true),
    "group 2 · edge",
  );
  assert.equal(
    hdbscanText(point({ hdbscan_label: 2, membership: 0.583 }), true),
    "group 2 · 58%",
  );
});

test("a cluster spanning a volume gets a hull a little larger than its points", () => {
  const corners: [number, number, number][] = [
    [0, 0, 0],
    [0.5, 0, 0],
    [0, 0.5, 0],
    [0, 0, 0.5],
  ];
  const points = corners.map(([x, y, z], i) =>
    point({ x, y, z, trace_ids: [`t${i}`] }),
  );
  const outline = clusterOutline(points, "c0");
  assert.equal(outline?.kind, "hull");
  if (outline?.kind !== "hull") return;
  assert.equal(outline.vertices.length, 4);
  const far = (v: number[]) =>
    Math.hypot(v[0] - 0.125, v[1] - 0.125, v[2] - 0.125);
  outline.vertices.forEach((v, i) => {
    assert.ok(far(v) > far(corners[i]));
  });
});

test("flat or small clusters get spokes, a single point nothing", () => {
  const flat = [0, 1, 2, 3].map((i) =>
    point({ x: i / 4, y: (i % 2) / 4, z: 0, trace_ids: [`t${i}`] }),
  );
  assert.equal(clusterOutline(flat, "c0")?.kind, "spokes");
  const two = [point({ x: 0 }), point({ x: 0.4, trace_ids: ["t2"] })];
  const spokes = clusterOutline(two, "c0");
  assert.deepEqual(spokes, {
    kind: "spokes",
    center: [0.2, 0, 0],
    ends: [
      [0, 0, 0],
      [0.4, 0, 0],
    ],
  });
  assert.equal(clusterOutline([point()], "c0"), null);
  assert.equal(clusterOutline(two, "c9"), null);
});

test("spansVolume needs four points off one plane", () => {
  assert.equal(
    spansVolume([
      [0, 0, 0],
      [1, 0, 0],
      [0, 1, 0],
    ]),
    false,
  );
  assert.equal(
    spansVolume([
      [0, 0, 0],
      [1, 0, 0],
      [2, 0, 0],
      [3, 0, 0],
    ]),
    false,
  );
  assert.equal(
    spansVolume([
      [0, 0, 0],
      [1, 0, 0],
      [0, 1, 0],
      [1, 1, 0],
    ]),
    false,
  );
  assert.equal(
    spansVolume([
      [0, 0, 0],
      [1, 0, 0],
      [0, 1, 0],
      [0, 0, 1],
    ]),
    true,
  );
});

test("the box to fly to is padded and never smaller than the minimum side", () => {
  const bounds = clusterBounds(
    [point({ x: -0.5 }), point({ x: 0.5, trace_ids: ["t2"] })],
    "c0",
    0.1,
    0.6,
  );
  assert.deepEqual(bounds, { min: [-0.6, -0.3, -0.3], max: [0.6, 0.3, 0.3] });
  assert.equal(clusterBounds([point()], "c4"), null);
});

test("points group by cluster in first-seen order", () => {
  const by = groupByCluster([
    point({ cluster_id: "c1", trace_ids: ["a"] }),
    point({ cluster_id: "c0", trace_ids: ["b"] }),
    point({ cluster_id: "c1", trace_ids: ["c"] }),
  ]);
  assert.deepEqual([...by.keys()], ["c1", "c0"]);
  assert.deepEqual(
    by.get("c1")?.map((p) => p.trace_ids[0]),
    ["a", "c"],
  );
});
