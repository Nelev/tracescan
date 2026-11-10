"use client";

import { Check, type LucideIcon, X } from "lucide-react";
import type { ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { SEGMENT_ITEM, SEGMENT_LIST } from "@/components/ui/tabs";
import {
  type Decisions,
  issueSections,
  type Proposal,
  type ReviewResult,
  type RunDetail,
  tally,
  tallyText,
} from "@/lib/review";
import { RUN_STATUS, shortId } from "@/lib/runs";
import type { Decision } from "@/lib/types";
import { cn } from "@/lib/utils";
import { Chip } from "./chip";
import { useReview } from "./use-review";

// A decision is a status of its proposal, so it takes the status colors, and a mark of its own.
const OPTIONS: {
  value: Decision;
  label: string;
  Icon: LucideIcon;
  chosen: string;
}[] = [
  {
    value: "approve",
    label: "Approve",
    Icon: Check,
    chosen: "bg-success/10 text-success hover:text-success",
  },
  {
    value: "reject",
    label: "Reject",
    Icon: X,
    chosen: "bg-destructive/10 text-destructive hover:text-destructive",
  },
];

function DecisionPicker({
  clusterId,
  decision,
  disabled,
  onDecide,
}: {
  clusterId: string;
  decision: Decision | undefined;
  disabled: boolean;
  onDecide: (decision: Decision) => void;
}) {
  return (
    <fieldset disabled={disabled} className="shrink-0 disabled:opacity-50">
      <legend className="sr-only">Decision for {clusterId}</legend>
      <div className={SEGMENT_LIST}>
        {OPTIONS.map(({ value, label, Icon, chosen }) => (
          <label
            key={value}
            className={cn(
              SEGMENT_ITEM,
              "inline-flex items-center gap-1.5 has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-ring",
              decision === value && chosen,
            )}
          >
            <input
              type="radio"
              name={`decision-${clusterId}`}
              value={value}
              checked={decision === value}
              onChange={() => onDecide(value)}
              className="sr-only"
            />
            <Icon className="size-4" aria-hidden="true" />
            {label}
          </label>
        ))}
      </div>
    </fieldset>
  );
}

const count = (n: number, noun: string) => `${n} ${noun}${n === 1 ? "" : "s"}`;

/** What kind of proposal this is, in a line: its cluster, how far it was checked, its case. */
function facts({ cluster_id, verification, diagnosed, regression }: Proposal) {
  return [
    cluster_id,
    diagnosed ? verification : "not diagnosed",
    regression &&
      `regression case: ${count(regression.traces, "trace")}, ${count(regression.spans, "span")}`,
  ]
    .filter(Boolean)
    .join(" · ");
}

/** One proposal: what it is, the issue it would open, and `children` for the decision. */
function ProposalCard({
  proposal,
  children,
}: {
  proposal: Proposal;
  children: ReactNode;
}) {
  return (
    <li className="flex flex-col gap-3 rounded-lg border bg-card p-4">
      {/* Stays at the top of the pane while its issue is read, so the decision is always at hand. */}
      <div className="sticky top-0 z-10 -mx-4 -mt-4 flex flex-wrap items-start justify-between gap-3 rounded-t-lg border-b bg-card px-4 py-3">
        <div className="flex min-w-0 flex-col gap-1">
          <p className="type-body font-mono text-muted-foreground">
            {facts(proposal)}
          </p>
          <h3 className="[overflow-wrap:anywhere]">{proposal.title}</h3>
        </div>
        {children}
      </div>
      {issueSections(proposal.body).map(({ heading, text }) => (
        <section key={heading} className="flex flex-col gap-1">
          {heading && <h4>{heading}</h4>}
          <p className="type-body whitespace-pre-wrap [overflow-wrap:anywhere]">
            {text}
          </p>
        </section>
      ))}
    </li>
  );
}

function ActionsLog({ log }: { log: string[] }) {
  return (
    <section className="flex flex-col gap-1">
      <h4>Actions</h4>
      {log.length === 0 ? (
        <p className="type-body text-muted-foreground">Nothing was written.</p>
      ) : (
        <ul className="type-body font-mono [overflow-wrap:anywhere]">
          {log.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
      )}
    </section>
  );
}

function RunChip({ status }: { status: RunDetail["status"] }) {
  const { label, tone } = RUN_STATUS[status];
  return <Chip tone={tone}>{label}</Chip>;
}

/** After the review: what the run did with it, and what was decided. */
function Reviewed({
  detail,
  result,
  decisions,
}: {
  detail: RunDetail;
  result: ReviewResult;
  decisions: Decisions;
}) {
  const { approved, rejected } = tally(detail.proposals, decisions);
  return (
    <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto p-4">
      <output className="flex flex-wrap items-center gap-3">
        <RunChip status={result.status} />
        <span className="type-body">
          Review recorded: {approved} approved, {rejected} rejected.
        </span>
      </output>
      <ActionsLog log={result.actionsLog} />
      <section className="flex flex-col gap-1">
        <h4>Decisions</h4>
        <ul className="type-body flex flex-col gap-1">
          {detail.proposals.map(({ cluster_id, title }) => (
            <li key={cluster_id} className="[overflow-wrap:anywhere]">
              <span className="font-mono text-muted-foreground">
                {cluster_id} · {decisions[cluster_id]} ·{" "}
              </span>
              {title}
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}

/**
 * The review of one run: its proposals, a decision for each, and one send for all of them (the
 * server takes a review only whole). A run that does not wait for a review is shown as it stands.
 * The issue text is the diagnoser's own prose: this screen is where a person reads it before
 * anything is written. It fills its parent, a flex column that sets the pane's height.
 */
export function ReviewPane({
  runId,
  onReviewed,
}: {
  runId: string;
  onReviewed: (runId: string) => void;
}) {
  const { state, decisions, decide, submit, reload } = useReview(
    runId,
    onReviewed,
  );

  if (state.step === "loading") {
    return (
      <p className="type-body p-4 text-muted-foreground">
        Loading run {shortId(runId)}…
      </p>
    );
  }
  if (state.step === "unavailable") {
    return (
      <div className="flex flex-col items-start gap-3 p-4">
        <p role="alert" className="type-body text-destructive">
          {state.problem}
        </p>
        <Button variant="outline" onClick={reload}>
          Try again
        </Button>
      </div>
    );
  }
  if (state.step === "reviewed") {
    return (
      <Reviewed
        detail={state.detail}
        result={state.result}
        decisions={decisions}
      />
    );
  }

  const { detail, sending, problem } = state;
  if (detail.status !== "review_required") {
    return (
      <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto p-4">
        <div className="flex flex-wrap items-center gap-3">
          <RunChip status={detail.status} />
          <span className="type-body">
            This run is not waiting for a review.
          </span>
        </div>
        <ActionsLog log={detail.actionsLog} />
      </div>
    );
  }

  const progress = tally(detail.proposals, decisions);
  return (
    <form
      className="flex min-h-0 flex-1 flex-col"
      onSubmit={(event) => {
        event.preventDefault();
        void submit();
      }}
    >
      <ul className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto p-4">
        {detail.proposals.map((proposal) => (
          <ProposalCard key={proposal.cluster_id} proposal={proposal}>
            <DecisionPicker
              clusterId={proposal.cluster_id}
              decision={decisions[proposal.cluster_id]}
              disabled={sending}
              onDecide={(decision) => decide(proposal.cluster_id, decision)}
            />
          </ProposalCard>
        ))}
      </ul>
      <div className="flex flex-wrap items-center justify-between gap-3 border-t px-4 py-3">
        <div className="flex min-w-0 flex-col gap-1">
          <span className="type-h4">{tallyText(progress)}</span>
          {problem && (
            <p role="alert" className="type-body text-destructive">
              {problem}
            </p>
          )}
        </div>
        <div className="flex gap-2">
          {problem && (
            <Button
              type="button"
              variant="outline"
              onClick={reload}
              disabled={sending}
            >
              Reload run
            </Button>
          )}
          <Button type="submit" disabled={!progress.complete || sending}>
            {sending ? "Sending…" : "Submit review"}
          </Button>
        </div>
      </div>
    </form>
  );
}
