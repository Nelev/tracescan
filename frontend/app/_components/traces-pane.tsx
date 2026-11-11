"use client";

import { AlertTriangle, ArrowLeft, Crosshair } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { formatWhen, shortId } from "@/lib/runs";
import {
  blamedBy,
  formatDuration,
  formatScore,
  formatValue,
  REDACTED,
  type SpanNode,
  type TraceDetail,
  type TraceRow,
  traceVerdict,
  type WaterfallRow,
  waterfall,
} from "@/lib/traces";
import { cn } from "@/lib/utils";
import { Chip } from "./chip";
import { CELL, LINK, NUMERIC, PANE_HEIGHT } from "./console-styles";
import { useTrace } from "./use-traces";

const COLUMNS = [
  { label: "Started" },
  { label: "Verdict" },
  { label: "Duration", numeric: true },
  { label: "Spans", numeric: true },
  { label: "Lowest score", numeric: true },
  { label: "Failing span" },
  { label: "Why" },
  { label: "Trace" },
];

function TraceListRow({
  trace,
  onOpen,
}: {
  trace: TraceRow;
  onOpen: (traceId: string) => void;
}) {
  const { label, tone } = traceVerdict(trace);
  const why = trace.error_type ?? trace.failing_check;
  return (
    <tr
      className="cursor-pointer border-t hover:bg-foreground/5"
      onClick={() => onOpen(trace.trace_id)}
    >
      <td className={CELL}>
        <time dateTime={trace.start_time}>{formatWhen(trace.start_time)}</time>
      </td>
      <td className={CELL}>
        <Chip tone={tone} size="sm">
          {label}
        </Chip>
      </td>
      <td className={cn(CELL, NUMERIC)}>{formatDuration(trace.duration_ms)}</td>
      <td className={cn(CELL, NUMERIC)}>{trace.spans}</td>
      <td className={cn(CELL, NUMERIC)}>{formatScore(trace.min_score)}</td>
      <td className={cn(CELL, "font-mono")}>{trace.failing_span_name ?? ""}</td>
      <td className={cn(CELL, "font-mono text-muted-foreground")}>
        {why ?? ""}
      </td>
      <td className={CELL}>
        <button
          type="button"
          className={LINK}
          title={trace.trace_id}
          onClick={(e) => {
            e.stopPropagation();
            onOpen(trace.trace_id);
          }}
          aria-label={`Open trace ${shortId(trace.trace_id)}`}
        >
          {shortId(trace.trace_id)}
        </button>
      </td>
    </tr>
  );
}

function TraceList({
  status,
  traces,
  failedOnly,
  onOpen,
}: {
  status: "loading" | "ready" | "error";
  traces: TraceRow[];
  failedOnly: boolean;
  onOpen: (traceId: string) => void;
}) {
  return (
    <div className={cn(PANE_HEIGHT, "overflow-auto")}>
      {status === "error" && (
        <p role="alert" className="type-body px-4 pt-4 text-destructive">
          Could not load the traces. Check that the backend is running, then
          refresh.
        </p>
      )}
      {traces.length === 0 ? (
        status !== "error" && (
          <p className="type-body p-4 text-muted-foreground">
            {status === "loading"
              ? "Loading traces…"
              : failedOnly
                ? "No failed traces stored."
                : "No traces stored yet. Point an instrumented app at /v1/traces."}
          </p>
        )
      ) : (
        <table className="type-body w-full border-collapse text-left">
          <caption className="sr-only">Stored traces, newest first</caption>
          <thead className="sticky top-0 z-10 bg-muted">
            <tr>
              {COLUMNS.map(({ label, numeric }) => (
                <th
                  key={label}
                  scope="col"
                  className={cn("type-h4", CELL, "py-3", numeric && NUMERIC)}
                >
                  {label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {traces.map((trace) => (
              <TraceListRow
                key={trace.trace_id}
                trace={trace}
                onOpen={onOpen}
              />
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function barColor(span: SpanNode, blamed: boolean): string {
  if (blamed) return "bg-destructive";
  // An error the scores did not count against the trace: recovered, or expected.
  if (span.status === "error") return "bg-destructive/40";
  return "bg-primary/60";
}

function SpanRow({
  row,
  blamed,
  selected,
  onSelect,
}: {
  row: WaterfallRow;
  blamed: boolean;
  selected: boolean;
  onSelect: () => void;
}) {
  const { span } = row;
  return (
    <li>
      <button
        type="button"
        onClick={onSelect}
        aria-pressed={selected}
        aria-label={`${span.name}, ${formatDuration(row.durationMs)}${
          blamed
            ? ", blamed by a score"
            : span.status === "error"
              ? ", error"
              : ""
        }`}
        className={cn(
          "grid w-full grid-cols-[minmax(0,15rem)_minmax(0,1fr)_4.5rem] items-center gap-3 px-4 py-1.5 text-left hover:bg-foreground/5 focus-visible:bg-foreground/5 focus-visible:outline-none",
          selected && "bg-primary/10 hover:bg-primary/15",
        )}
      >
        <span
          className="flex min-w-0 items-center gap-1.5 font-mono"
          style={{ paddingLeft: `${row.depth * 0.875}rem` }}
        >
          {blamed ? (
            <Crosshair
              className="size-3.5 shrink-0 text-destructive"
              aria-label="Blamed by a score"
            />
          ) : span.status === "error" ? (
            <AlertTriangle
              className="size-3.5 shrink-0 text-destructive/70"
              aria-label="Error"
            />
          ) : (
            <span className="size-3.5 shrink-0" aria-hidden="true" />
          )}
          <span className="truncate" title={span.name}>
            {span.name}
          </span>
        </span>
        <span className="relative h-2.5 rounded-full bg-foreground/5">
          <span
            className={cn(
              "absolute inset-y-0 min-w-0.5 rounded-full",
              barColor(span, blamed),
            )}
            style={{ left: `${row.left * 100}%`, width: `${row.width * 100}%` }}
          />
        </span>
        <span className="text-right tabular-nums text-muted-foreground">
          {formatDuration(row.durationMs)}
        </span>
      </button>
    </li>
  );
}

function Attributes({ attributes }: { attributes: Record<string, unknown> }) {
  const entries = Object.entries(attributes);
  if (entries.length === 0) {
    return <p className="text-muted-foreground">None</p>;
  }
  return (
    <dl className="grid grid-cols-[minmax(0,auto)_minmax(0,1fr)] gap-x-3 gap-y-1 font-mono">
      {entries.map(([key, value]) => {
        const text = formatValue(value);
        return (
          <div key={key} className="contents">
            <dt className="truncate text-muted-foreground" title={key}>
              {key}
            </dt>
            <dd
              className={cn(
                "[overflow-wrap:anywhere]",
                text === REDACTED && "text-muted-foreground italic",
              )}
            >
              {text}
            </dd>
          </div>
        );
      })}
    </dl>
  );
}

/** A titled block in a detail view (span details here, cluster cards under Run). */
export function Section({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section className="flex flex-col gap-2">
      <h4 className="type-h4">{title}</h4>
      {children}
    </section>
  );
}

function SpanDetail({
  row,
  blamedChecks,
}: {
  row: WaterfallRow;
  blamedChecks: string[];
}) {
  const { span } = row;
  return (
    <div className="type-body flex flex-col gap-4 p-4">
      <div className="flex flex-col gap-2">
        <h3 className="type-h3 font-mono [overflow-wrap:anywhere]">
          {span.name}
        </h3>
        <div className="flex flex-wrap gap-2">
          {blamedChecks.length > 0 && (
            <Chip tone="destructive" size="sm">
              Blamed by {blamedChecks.join(", ")}
            </Chip>
          )}
          {span.status === "error" && blamedChecks.length === 0 && (
            <Chip tone="neutral" size="sm">
              Error, not counted
            </Chip>
          )}
        </div>
      </div>
      <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-1">
        <dt className="text-muted-foreground">Status</dt>
        <dd>{span.status}</dd>
        <dt className="text-muted-foreground">Kind</dt>
        <dd>{span.kind}</dd>
        <dt className="text-muted-foreground">Starts at</dt>
        <dd className="tabular-nums">+{formatDuration(row.offsetMs)}</dd>
        <dt className="text-muted-foreground">Duration</dt>
        <dd className="tabular-nums">{formatDuration(row.durationMs)}</dd>
        <dt className="text-muted-foreground">Span</dt>
        <dd className="font-mono [overflow-wrap:anywhere]">{span.span_id}</dd>
      </dl>
      {span.status_message && (
        <Section title="Status message">
          <p className="font-mono [overflow-wrap:anywhere]">
            {span.status_message}
          </p>
        </Section>
      )}
      <Section title="Attributes">
        <Attributes attributes={span.attributes} />
      </Section>
      {span.events.length > 0 && (
        <Section title="Events">
          <ol className="flex flex-col gap-3">
            {span.events.map((event, i) => (
              <li
                // Events have no id; their order never changes.
                // biome-ignore lint/suspicious/noArrayIndexKey: see above
                key={i}
                className="flex flex-col gap-1"
              >
                <span className="font-mono">{event.name}</span>
                <Attributes attributes={event.attributes} />
              </li>
            ))}
          </ol>
        </Section>
      )}
    </div>
  );
}

function TraceView({
  trace,
  initialSpan,
}: {
  trace: TraceDetail;
  initialSpan: string | null;
}) {
  const rows = waterfall(trace.tree);
  const blamed = blamedBy(trace.scores);
  // Opens on the span asked for, else the first one the scores blame, else the root.
  const [selected, setSelected] = useState(
    () =>
      rows.find((r) => r.span.span_id === initialSpan)?.span.span_id ??
      rows.find((r) => blamed.has(r.span.span_id))?.span.span_id ??
      trace.tree.span_id,
  );
  const current = rows.find((r) => r.span.span_id === selected) ?? rows[0];
  const verdict = traceVerdict(trace);

  return (
    <>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b px-4 py-3">
        <Chip tone={verdict.tone} size="sm">
          {verdict.label}
        </Chip>
        <span className="type-body">
          {formatWhen(trace.tree.start_time)} ·{" "}
          {formatDuration(rows[0].durationMs)} · {rows.length}{" "}
          {rows.length === 1 ? "span" : "spans"}
        </span>
        <ul className="flex flex-wrap gap-2" aria-label="Scores">
          {trace.scores.map((s) => (
            <li
              key={s.evaluator}
              className={cn(
                "type-body rounded-md border px-2 font-mono",
                s.failed
                  ? "border-destructive/40 text-destructive"
                  : "text-muted-foreground",
              )}
            >
              {s.evaluator} {formatScore(s.value)}
            </li>
          ))}
        </ul>
      </div>
      <div className="grid min-h-0 flex-1 grid-rows-[minmax(0,1fr)_minmax(0,1fr)] lg:grid-cols-[minmax(0,1fr)_22rem] lg:grid-rows-1">
        <ol
          aria-label="Spans, as a waterfall"
          className="type-body overflow-auto py-2"
        >
          {rows.map((row) => (
            <SpanRow
              key={row.span.span_id}
              row={row}
              blamed={blamed.has(row.span.span_id)}
              selected={row.span.span_id === current.span.span_id}
              onSelect={() => setSelected(row.span.span_id)}
            />
          ))}
        </ol>
        <div className="overflow-auto border-t lg:border-t-0 lg:border-l">
          <SpanDetail
            row={current}
            blamedChecks={blamed.get(current.span.span_id) ?? []}
          />
        </div>
      </div>
    </>
  );
}

function OpenTrace({
  traceId,
  spanId,
  onBack,
}: {
  traceId: string;
  spanId: string | null;
  onBack: () => void;
}) {
  const state = useTrace(traceId);
  return (
    <div className={cn(PANE_HEIGHT, "flex flex-col")}>
      <div className="flex items-center gap-3 border-b px-2 py-2">
        <Button variant="ghost" onClick={onBack}>
          <ArrowLeft aria-hidden="true" />
          All traces
        </Button>
        <span className="type-body font-mono text-muted-foreground">
          {traceId}
        </span>
      </div>
      {state.status === "loading" && state.value === null && (
        <p className="type-body p-4 text-muted-foreground">Loading trace…</p>
      )}
      {state.status === "error" && (
        <p role="alert" className="type-body p-4 text-destructive">
          {state.missing
            ? "The server has no whole trace by this id: unknown, of another app, or still missing spans."
            : "Could not load the trace. Check that the backend is running, then try again."}
        </p>
      )}
      {state.value && <TraceView trace={state.value} initialSpan={spanId} />}
    </div>
  );
}

/**
 * The trace store, read-only: the newest traces with the verdict their scores give, and one
 * trace as a waterfall of its spans, the span its lowest score blames picked first. Span
 * attributes come redacted by the server outside its allowlist; status messages are shown as
 * sent (truncated), so they are never logged here.
 */
export function TracesPane({
  open,
  status,
  traces,
  failedOnly,
  onOpen,
  onBack,
}: {
  /** The trace open, and the span to show first in it; null shows the list. */
  open: { traceId: string; spanId: string | null } | null;
  status: "loading" | "ready" | "error";
  traces: TraceRow[];
  failedOnly: boolean;
  onOpen: (traceId: string) => void;
  onBack: () => void;
}) {
  if (open) {
    return (
      <OpenTrace
        key={`${open.traceId}:${open.spanId}`}
        traceId={open.traceId}
        spanId={open.spanId}
        onBack={onBack}
      />
    );
  }
  return (
    <TraceList
      status={status}
      traces={traces}
      failedOnly={failedOnly}
      onOpen={onOpen}
    />
  );
}
