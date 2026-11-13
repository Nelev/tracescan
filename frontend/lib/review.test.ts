import assert from "node:assert/strict";
import { test } from "node:test";
import {
  issueSections,
  loadProblem,
  parseReviewResult,
  parseRunDetail,
  retryAfterSeconds,
  startProblem,
  submitProblem,
  tally,
  tallyText,
} from "./review.ts";

const DIAGNOSED = {
  cluster_id: "c0",
  title: "[retrieval_miss] retrieve returned no chunks",
  body: "## Summary\n\ntext",
  verification: "unverified",
  diagnosed: true,
  regression_case: {
    cluster_id: "c0",
    signature: "retrieve returned no chunks",
    category: "retrieval_miss",
    exemplar_trace_ids: ["tr_1", "tr_2"],
    failing_spans: [{ trace_id: "tr_1", span_id: "sp_1" }],
  },
};
const STUB = {
  cluster_id: "c1",
  title: "Undiagnosed failure",
  body: "## Summary\n\nno diagnosis",
  verification: "unverified",
  diagnosed: false,
  regression_case: null,
};
const SUMMARY = {
  run_id: "3f9a1c2e-0000-4000-8000-000000000000",
  failed_traces: 3,
  clusters: 2,
  unclustered: 0,
  diagnoses: 1,
  diagnosis_failures: 1,
  proposals: 2,
  actions_log: [],
};
const DETAIL = {
  status: "review_required",
  summary: SUMMARY,
  proposals: [DIAGNOSED, STUB],
};

test("a run's detail is read into its status, actions log and proposals", () => {
  const detail = parseRunDetail(DETAIL);
  assert.equal(detail?.status, "review_required");
  assert.deepEqual(detail?.actionsLog, []);
  assert.deepEqual(detail?.proposals, [
    {
      cluster_id: "c0",
      title: DIAGNOSED.title,
      body: DIAGNOSED.body,
      verification: "unverified",
      diagnosed: true,
      regression: { traces: 2, spans: 1 },
    },
    {
      cluster_id: "c1",
      title: STUB.title,
      body: STUB.body,
      verification: "unverified",
      diagnosed: false,
      regression: null,
    },
  ]);
});

test("one unreadable proposal makes the run unreadable, never a partial review", () => {
  const { title: _, ...untitled } = STUB;
  assert.equal(
    parseRunDetail({ ...DETAIL, proposals: [DIAGNOSED, untitled] }),
    null,
  );
  assert.equal(parseRunDetail({ ...DETAIL, status: "paused" }), null);
  assert.equal(parseRunDetail({ ...DETAIL, summary: {} }), null);
  assert.equal(parseRunDetail({ ...DETAIL, proposals: "none" }), null);
  assert.equal(parseRunDetail([DETAIL]), null);
  assert.equal(parseRunDetail(null), null);
});

test("a review's answer is read into the run's status and what was written", () => {
  const log = ["wrote issues/c0.md", "appended regression_cases.jsonl"];
  assert.deepEqual(
    parseReviewResult({
      status: "completed",
      summary: { ...SUMMARY, actions_log: log },
    }),
    { status: "completed", actionsLog: log },
  );
  assert.equal(parseReviewResult({ status: "completed" }), null);
  assert.equal(
    parseReviewResult({ status: "completed", summary: { actions_log: [1] } }),
    null,
  );
});

test("a review is complete only when every proposal is decided", () => {
  const proposals = parseRunDetail(DETAIL)?.proposals ?? [];
  assert.equal(tally(proposals, {}).complete, false);
  assert.equal(tally(proposals, { c0: "approve" }).complete, false);
  // A decision for a cluster the run does not have decides nothing.
  assert.equal(
    tally(proposals, { c0: "approve", c9: "reject" }).complete,
    false,
  );
  assert.deepEqual(tally(proposals, { c0: "approve", c1: "reject" }), {
    approved: 1,
    rejected: 1,
    total: 2,
    complete: true,
  });
  assert.equal(
    tallyText(tally(proposals, { c0: "approve" })),
    "1 of 2 decided · 1 approved · 0 rejected",
  );
  assert.equal(tally([], {}).complete, true);
});

test("an issue body is split at its headings and otherwise left as written", () => {
  const body =
    "## Summary\n\n`sig`\n\n3 traces\n\n## Evidence\n\n- trace `tr_1`: note\n\n## Suggested fix\n\nfix it\n";
  assert.deepEqual(issueSections(body), [
    { heading: "Summary", text: "`sig`\n\n3 traces" },
    { heading: "Evidence", text: "- trace `tr_1`: note" },
    { heading: "Suggested fix", text: "fix it" },
  ]);
  assert.deepEqual(issueSections("intro\n## Cause\nwhy"), [
    { heading: "", text: "intro" },
    { heading: "Cause", text: "why" },
  ]);
  assert.deepEqual(issueSections(""), []);
});

const refused = (status: number | null) => ({ status, unreadable: false });
const UNREADABLE = { status: 200, unreadable: true };

test("each way a review can fail has its own words", () => {
  const failures = [null, 409, 422, 502, 500].map(refused);
  const words = [...failures, UNREADABLE].map(submitProblem);
  assert.equal(new Set(words).size, words.length);
  assert.match(submitProblem(refused(409)), /no longer waiting/);
  assert.match(loadProblem(refused(404)), /does not know this run/);
  // A 401 is a session that ended, and a review refused with it was not sent.
  assert.match(loadProblem(refused(401)), /sign in again/);
  assert.match(submitProblem(refused(401)), /sign in again.*were not sent/);
  assert.equal(loadProblem(refused(null)), submitProblem(refused(null)));
  assert.match(loadProblem(refused(500)), /HTTP 500/);
});

test("an answer that could not be read is not reported as a refusal", () => {
  // The server answered a 2xx: a review was sent, and a run was found.
  assert.match(submitProblem(UNREADABLE), /was sent/);
  assert.doesNotMatch(submitProblem(UNREADABLE), /not taken|HTTP/);
  assert.match(loadProblem(UNREADABLE), /could not be read/);
});

test("Retry-After is read as whole seconds, anything else as unknown", () => {
  assert.equal(retryAfterSeconds("720"), 720);
  assert.equal(retryAfterSeconds(" 5 "), 5);
  assert.equal(retryAfterSeconds(null), null);
  assert.equal(retryAfterSeconds("Wed, 21 Oct 2026 07:28:00 GMT"), null);
  assert.equal(retryAfterSeconds("-3"), null);
});

test("a run past its limit names the wait in whole minutes, rounded up", () => {
  const limited = (retryAfterS: number | null) =>
    startProblem({ status: 429, unreadable: false, retryAfterS });
  assert.match(limited(720), /Try again in 12 min\.$/);
  assert.match(limited(61), /Try again in 2 min\.$/);
  assert.match(limited(0), /Try again in 1 min\.$/);
  assert.match(limited(3600), /Try again in 1 h\.$/);
  assert.match(limited(null), /Try again later\.$/);
  assert.match(startProblem({ status: 500, unreadable: false }), /HTTP 500/);
});

test("a resume the server refuses says why", () => {
  assert.match(
    startProblem({ status: 409, unreadable: false }),
    /cannot be resumed/,
  );
  assert.match(
    startProblem({ status: 404, unreadable: false }),
    /does not know this run/,
  );
});
