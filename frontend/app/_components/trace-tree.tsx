"use client";

import {
  AlertTriangle,
  Bot,
  Circle,
  Crosshair,
  Database,
  type LucideIcon,
  MessageSquare,
  Star,
  Wrench,
} from "lucide-react";
import { type ReactNode, useState } from "react";
import { formatDuration } from "@/lib/format";
import {
  blamedBy,
  formatValue,
  REDACTED,
  type SpanKind,
  type SpanNode,
  spanKind,
  type TraceDetail,
  type WaterfallRow,
  waterfall,
} from "@/lib/traces";
import { cn } from "@/lib/utils";
import { Chip } from "./chip";

const KIND_ICON: Record<SpanKind, { Icon: LucideIcon; label: string }> = {
  agent: { Icon: Bot, label: "Agent" },
  chat: { Icon: MessageSquare, label: "Model call" },
  tool: { Icon: Wrench, label: "Tool call" },
  retrieval: { Icon: Database, label: "Retrieval" },
  other: { Icon: Circle, label: "Span" },
};

/** A titled block in a detail view (span details, cluster cards). */
export function Section({
  title,
  children,
}: {
  title: string;
  children: ReactNode;
}) {
  return (
    <section className="flex flex-col gap-2">
      <h4 className="type-h4">{title}</h4>
      {children}
    </section>
  );
}

function barColor(span: SpanNode, blamed: boolean): string {
  if (blamed) return "bg-destructive";
  // An error the scores did not count against the trace: recovered, or expected.
  if (span.status === "error") return "bg-destructive/40";
  return "bg-primary/60";
}

function Marks({
  blamed,
  cited,
  error,
}: {
  blamed: boolean;
  cited: boolean;
  error: boolean;
}) {
  return (
    <span className="flex w-8 shrink-0 items-center justify-end gap-0.5">
      {cited && (
        <Star
          className="size-3.5 shrink-0 fill-primary text-primary"
          aria-label="Cited by the diagnosis"
        />
      )}
      {blamed ? (
        <Crosshair
          className="size-3.5 shrink-0 text-destructive"
          aria-label="Blamed by a score"
        />
      ) : (
        error && (
          <AlertTriangle
            className="size-3.5 shrink-0 text-destructive/70"
            aria-label="Error"
          />
        )
      )}
    </span>
  );
}

function SpanRow({
  row,
  blamed,
  cited,
  selected,
  narrow,
  onSelect,
}: {
  row: WaterfallRow;
  blamed: boolean;
  cited: boolean;
  selected: boolean;
  /** Inside a card: the names get less room, so the timeline keeps some. */
  narrow: boolean;
  onSelect: () => void;
}) {
  const { span } = row;
  const kind = KIND_ICON[spanKind(span.name)];
  const notes = [
    cited && "cited by the diagnosis",
    blamed ? "blamed by a score" : span.status === "error" && "error",
  ].filter(Boolean);
  return (
    <li>
      <button
        type="button"
        onClick={onSelect}
        aria-pressed={selected}
        aria-label={`${span.name}, ${formatDuration(row.durationMs)}${notes.length > 0 ? `, ${notes.join(", ")}` : ""}`}
        className={cn(
          "grid w-full items-center gap-3 px-3 py-1.5 text-left hover:bg-hover focus-visible:bg-hover focus-visible:outline-none",
          narrow
            ? "grid-cols-[minmax(0,55%)_minmax(0,1fr)_4rem]"
            : "grid-cols-[minmax(0,17rem)_minmax(0,1fr)_4.5rem]",
          selected && "bg-primary/10 hover:bg-primary/15",
        )}
      >
        <span className="flex min-w-0 items-center gap-1.5 font-mono">
          <Marks
            blamed={blamed}
            cited={cited}
            error={span.status === "error"}
          />
          <span
            className="flex min-w-0 items-center gap-1.5"
            style={{ paddingLeft: `${row.depth * 0.875}rem` }}
          >
            <kind.Icon
              className={cn(
                "size-3.5 shrink-0",
                span.status === "error"
                  ? "text-destructive"
                  : "text-muted-foreground",
              )}
              aria-label={kind.label}
            />
            <span
              className={cn("truncate", blamed && "text-destructive")}
              title={span.name}
            >
              {span.name}
            </span>
          </span>
        </span>
        <span className="relative h-2.5 bg-track">
          <span
            className={cn(
              "absolute inset-y-0 min-w-0.5",
              barColor(span, blamed),
              cited && "ring-2 ring-primary ring-offset-1 ring-offset-card",
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

function SpanDetail({
  row,
  blamedChecks,
  note,
}: {
  row: WaterfallRow;
  blamedChecks: string[];
  /** What the diagnosis says about this span, when it cites it. */
  note: string | null;
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
      {note !== null && (
        <Section title="Cited by the diagnosis">
          <p>{note}</p>
        </Section>
      )}
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

const NO_CITATIONS: ReadonlyMap<string, string> = new Map();

/**
 * One trace as an indented span tree laid over the root's timeline, and the picked span's
 * details. Spans a failed score blames are red and marked, spans a diagnosis cites (`cited`, by span
 * id, with the diagnosis's note) are starred and ringed. `split` puts the details beside the tree
 * (a page of its own), `stacked` below it (inside a card). It opens on `initialSpan`, else the
 * first cited span, else the first blamed one, else the root. Attributes come redacted by the
 * server outside its allowlist; nothing here is logged.
 */
export function TraceTree({
  trace,
  cited = NO_CITATIONS,
  initialSpan = null,
  layout,
}: {
  trace: TraceDetail;
  cited?: ReadonlyMap<string, string>;
  initialSpan?: string | null;
  layout: "split" | "stacked";
}) {
  const rows = waterfall(trace.tree);
  const blamed = blamedBy(trace.scores);
  const byId = new Map(rows.map((r) => [r.span.span_id, r]));
  const firstOf = (marked: { has: (id: string) => boolean }) =>
    rows.find((r) => marked.has(r.span.span_id))?.span.span_id;
  const [selected, setSelected] = useState(
    () =>
      (initialSpan !== null && byId.has(initialSpan) ? initialSpan : null) ??
      firstOf(cited) ??
      firstOf(blamed) ??
      trace.tree.span_id,
  );
  const current = byId.get(selected) ?? rows[0];

  return (
    <div
      className={cn(
        "grid min-h-0",
        layout === "split"
          ? "flex-1 grid-rows-[minmax(0,1fr)_minmax(0,1fr)] lg:grid-cols-[minmax(0,1fr)_24rem] lg:grid-rows-1"
          : "grid-cols-1",
      )}
    >
      <ol
        aria-label="Spans, as a tree over the trace's timeline"
        className={cn(
          "type-body py-1",
          layout === "split" && "overflow-auto overscroll-contain",
        )}
      >
        {rows.map((row) => (
          <SpanRow
            key={row.span.span_id}
            row={row}
            blamed={blamed.has(row.span.span_id)}
            cited={cited.has(row.span.span_id)}
            selected={row.span.span_id === current.span.span_id}
            narrow={layout === "stacked"}
            onSelect={() => setSelected(row.span.span_id)}
          />
        ))}
      </ol>
      <div
        className={cn(
          layout === "split"
            ? "overflow-auto overscroll-contain border-t lg:border-t-0 lg:border-l"
            : "border-t",
        )}
      >
        <SpanDetail
          row={current}
          blamedChecks={blamed.get(current.span.span_id) ?? []}
          note={cited.get(current.span.span_id) ?? null}
        />
      </div>
    </div>
  );
}

/** The legend of the tree's marks; `cited` when the tree can show a diagnosis's citations. */
export function TreeLegend({ cited = false }: { cited?: boolean }) {
  return (
    <ul className="type-body flex flex-wrap gap-x-4 gap-y-1 text-muted-foreground">
      <li className={cn("flex items-center gap-1.5", !cited && "hidden")}>
        <Star
          className="size-3.5 fill-primary text-primary"
          aria-hidden="true"
        />
        Cited by the diagnosis
      </li>
      <li className="flex items-center gap-1.5">
        <Crosshair className="size-3.5 text-destructive" aria-hidden="true" />
        Blamed by a score
      </li>
      <li className="flex items-center gap-1.5">
        <AlertTriangle
          className="size-3.5 text-destructive/70"
          aria-hidden="true"
        />
        Error, not counted
      </li>
    </ul>
  );
}
