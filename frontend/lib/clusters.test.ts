import assert from "node:assert/strict";
import { test } from "node:test";
import { clusterIndex } from "./clusters.ts";
import { emptyOverview, type RunOverview } from "./run-overview.ts";
import type { RunRecord } from "./types.ts";

const run = (id: string, created: string): RunRecord => ({
  run_id: id,
  target_app: "medas",
  since: null,
  until: null,
  status: "completed",
  started_by: "local",
  created_at: created,
  ended_at: null,
  failed_traces: 3,
  clusters: 2,
  proposals: 2,
});

const overview = (
  id: string,
  clusters: [string, string[], string | null][],
): RunOverview => ({
  ...emptyOverview(id),
  clusters: clusters.map(([cluster_id, trace_ids, category]) => ({
    cluster_id,
    signature: `sig ${cluster_id}`,
    method: "hdbscan",
    trace_ids,
    exemplar_trace_ids: trace_ids.slice(0, 1),
    diagnosis:
      category === null
        ? null
        : {
            category,
            root_cause: "",
            suggested_fix: "",
            confidence: 0.5,
            evidence: [],
            evidence_check: "valid",
          },
    diagnosis_failed: false,
    usage: { calls: 0, tokens: 0, cost_usd: 0 },
    verification: "unverified",
    decision: null,
  })),
});

test("each trace maps to its clusters, newest run first", () => {
  const index = clusterIndex([
    {
      run: run("new", "2026-11-11T12:00:00Z"),
      overview: overview("new", [
        ["c0", ["t1", "t2"], "infra_error"],
        ["c1", ["t3"], null],
      ]),
    },
    {
      run: run("old", "2026-11-10T12:00:00Z"),
      overview: overview("old", [["c4", ["t1"], "retrieval_miss"]]),
    },
  ]);
  assert.deepEqual(
    index.get("t1")?.map((m) => [m.runId, m.clusterId, m.category]),
    [
      ["new", "c0", "infra_error"],
      ["old", "c4", "retrieval_miss"],
    ],
  );
  assert.equal(index.get("t3")?.[0].category, null);
  assert.equal(index.has("t9"), false);
});
