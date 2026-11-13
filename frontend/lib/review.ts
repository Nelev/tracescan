// The review of a run: its detail and the review's answer read once into what the review screen
// shows, and the words it uses.

import { formatAge } from "./format.ts";
import { isRecord } from "./guards.ts";
import { isRunStatus, isText } from "./runs.ts";
import type { Decision, RunStatus } from "./types.ts";

/** The reviewer's answers so far, by cluster id. */
export type Decisions = Record<string, Decision>;

/**
 * One drafted proposal as the review screen shows it: read from Proposal in
 * backend/agent/schemas.py, not a mirror of it. The body is the diagnoser's own prose as
 * markdown, so it can hold clinical text: show it to the reviewer, never log it. Of the
 * regression case only its size is kept.
 */
export type Proposal = {
  cluster_id: string;
  title: string;
  body: string;
  verification: string; // "unverified" until the reproducer exists
  diagnosed: boolean; // false: a stub for a cluster whose diagnosis failed
  regression: { traces: number; spans: number } | null;
};

/** Where a run stands and what it wrote, or would write in a dry run. */
export type ReviewResult = { status: RunStatus; actionsLog: string[] };

/** A run opened for review: the same, with its proposals. */
export type RunDetail = ReviewResult & { proposals: Proposal[] };

function parseProposal(value: unknown): Proposal | null {
  if (!isRecord(value)) return null;
  const { cluster_id, title, body, verification, diagnosed } = value;
  if (!isText(cluster_id) || !isText(title) || !isText(body)) return null;
  if (!isText(verification) || typeof diagnosed !== "boolean") return null;

  let regression: Proposal["regression"] = null;
  const sent = value.regression_case;
  if (sent !== null && sent !== undefined) {
    if (!isRecord(sent)) return null;
    const { exemplar_trace_ids, failing_spans } = sent;
    if (!Array.isArray(exemplar_trace_ids) || !Array.isArray(failing_spans)) {
      return null;
    }
    regression = {
      traces: exemplar_trace_ids.length,
      spans: failing_spans.length,
    };
  }
  return { cluster_id, title, body, verification, diagnosed, regression };
}

/**
 * The body of POST /v1/runs/{run_id}/review (ReviewResponse in backend/api/schemas.py), or null
 * when it is off contract: the run's status and its summary's actions log.
 */
export function parseReviewResult(body: unknown): ReviewResult | null {
  if (!isRecord(body) || !isRunStatus(body.status)) return null;
  if (!isRecord(body.summary)) return null;
  const log = body.summary.actions_log;
  if (!Array.isArray(log) || !log.every(isText)) return null;
  return { status: body.status, actionsLog: log };
}

/**
 * The body of GET /v1/runs/{run_id} (RunStatus in backend/runs/service.py), or null when it is
 * off contract. One proposal that cannot be read makes the whole run unreadable: a review needs
 * a decision for every proposal, so showing only some of them would be a review that cannot be
 * sent.
 */
export function parseRunDetail(body: unknown): RunDetail | null {
  const stand = parseReviewResult(body);
  if (stand === null || !isRecord(body)) return null;
  if (!Array.isArray(body.proposals)) return null;
  const proposals: Proposal[] = [];
  for (const value of body.proposals) {
    const proposal = parseProposal(value);
    if (proposal === null) return null;
    proposals.push(proposal);
  }
  return { ...stand, proposals };
}

/** How far the review is: the server takes it only when every proposal is decided. */
export function tally(proposals: Proposal[], decisions: Decisions) {
  const made = proposals.map((p) => decisions[p.cluster_id]);
  const approved = made.filter((d) => d === "approve").length;
  const rejected = made.filter((d) => d === "reject").length;
  return {
    approved,
    rejected,
    total: proposals.length,
    complete: approved + rejected === proposals.length,
  };
}

/** A tally in words, for the line next to the submit button. */
export function tallyText({
  approved,
  rejected,
  total,
}: ReturnType<typeof tally>): string {
  return `${approved + rejected} of ${total} decided · ${approved} approved · ${rejected} rejected`;
}

export type IssueSection = { heading: string; text: string };

/**
 * An issue body (markdown with `## ` headings, as backend/agent/proposals.py writes it) as its
 * sections, so the screen can set the headings apart without a markdown renderer. Text before the
 * first heading comes back under an empty heading; everything else is left as written.
 */
export function issueSections(body: string): IssueSection[] {
  const sections: IssueSection[] = [];
  let heading = "";
  let lines: string[] = [];
  const close = () => {
    const text = lines.join("\n").trim();
    if (heading || text) sections.push({ heading, text });
  };
  for (const line of body.split("\n")) {
    if (line.startsWith("## ")) {
      close();
      heading = line.slice(3).trim();
      lines = [];
    } else {
      lines.push(line);
    }
  }
  close();
  return sections;
}

/**
 * How a request to the backend went wrong (`RunError` in lib/api.ts): not reached (`status`
 * null), refused with a status, or answered with something that could not be read
 * (`unreadable`), which for a review means it was sent and most likely taken. `retryAfterS`: the
 * wait a 429 named, in seconds.
 */
export type Failure = {
  status: number | null;
  unreadable: boolean;
  retryAfterS?: number | null;
};

/** Retry-After as whole seconds, or null when it is missing or not a number of seconds. */
export function retryAfterSeconds(header: string | null): number | null {
  const value = header?.trim() ?? "";
  return /^\d+$/.test(value) ? Number(value) : null;
}

const UNREACHABLE = "Could not reach the backend. Check that it is running.";
const UNKNOWN_RUN = "The server does not know this run.";

/** A 401 from the backend: the session token was missing or no longer good. */
export const SIGNED_OUT =
  "Your session has ended or could not be checked. Reload the page to sign in again.";

/** Why a run did not start. A 429 says how long to wait, in whole minutes rounded up. */
export function startProblem({ status, retryAfterS }: Failure): string {
  switch (status) {
    case null:
      return UNREACHABLE;
    case 401:
      return SIGNED_OUT;
    case 404:
      return UNKNOWN_RUN;
    case 409:
      return "This run cannot be resumed: it is running, waits for review, has ended, or is being resumed already.";
    case 429: {
      const base =
        "You have started or resumed as many runs as allowed for now.";
      if (retryAfterS == null) return `${base} Try again later.`;
      const minutes = Math.max(1, Math.ceil(retryAfterS / 60));
      return `${base} Try again in ${formatAge(minutes * 60_000)}.`;
    }
    default:
      return `The run did not start (HTTP ${status}). Check that the backend is running, then its log.`;
  }
}

/** Why a run could not be opened for review. */
export function loadProblem({ status, unreadable }: Failure): string {
  if (unreadable) return "The server's answer for this run could not be read.";
  if (status === null) return UNREACHABLE;
  if (status === 401) return SIGNED_OUT;
  if (status === 404) return UNKNOWN_RUN;
  return `The run could not be loaded (HTTP ${status}).`;
}

/**
 * Why a review did not come back as taken. Unless the answer was `unreadable`, the review was
 * not taken and the decisions stay on the screen.
 */
export function submitProblem({ status, unreadable }: Failure): string {
  if (unreadable) {
    return "The review was sent, but the answer could not be read. Check the run under Runs.";
  }
  switch (status) {
    case null:
      return UNREACHABLE;
    case 401:
      return `${SIGNED_OUT} Your decisions were not sent.`;
    case 409:
      return "This run is no longer waiting for review. It may have been reviewed elsewhere: check it under Runs.";
    case 422:
      return "The decisions do not match the run's proposals. Reload the run and decide again.";
    case 502:
      return "The review could not be applied. Check the run under Runs before trying again.";
    default:
      return `The review was not taken (HTTP ${status}).`;
  }
}
