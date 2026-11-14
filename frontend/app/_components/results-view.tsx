"use client";

import { useState } from "react";
import {
  type EvalRun,
  EXPERIMENTS,
  type Experiment,
  formatRunTime,
  formatScore,
  headline,
  metricsFor,
  runsOf,
  runTime,
  series,
  share,
} from "@/lib/eval";
import { formatPercent } from "@/lib/format";
import { cn } from "@/lib/utils";
import { Tile } from "./panel";
import {
  CELL_TIGHT,
  HEAD,
  NUMERIC,
  SEGMENT_ACTIVE,
  SEGMENT_ITEM,
  SEGMENT_LIST,
} from "./styles";

const HEAD_CELL = cn("type-h4", CELL_TIGHT, "py-3");
const SPARK_W = 120;
const SPARK_H = 28;
const SPARK_PAD = 3;

/**
 * One metric over an experiment's runs, oldest to newest, as a line with the newest run marked.
 * A ratio runs from 0 to 1, a count from 0 to its largest value; runs that did not score it are
 * skipped.
 */
function Sparkline({
  values,
  ratio,
  label,
}: {
  values: (number | null)[];
  ratio: boolean;
  label: string;
}) {
  const max = ratio ? 1 : Math.max(1, ...values.map((v) => v ?? 0));
  const step =
    values.length > 1 ? (SPARK_W - 2 * SPARK_PAD) / (values.length - 1) : 0;
  const points = values.flatMap((v, i) =>
    v === null
      ? []
      : [
          [
            values.length > 1 ? SPARK_PAD + i * step : SPARK_W / 2,
            SPARK_H - SPARK_PAD - (v / max) * (SPARK_H - 2 * SPARK_PAD),
          ] as const,
        ],
  );
  const last = points.at(-1);
  const scored = values.filter((v) => v !== null);
  const word = (v: number) => (ratio ? formatPercent(v) : String(v));
  const aria =
    scored.length > 0
      ? `${label} over ${scored.length} runs: from ${word(scored[0])} to ${word(scored[scored.length - 1])}`
      : `${label}: not scored`;
  return (
    <svg
      viewBox={`0 0 ${SPARK_W} ${SPARK_H}`}
      role="img"
      aria-label={aria}
      // Narrower on a phone, so the metric's name and question keep the room.
      className="h-auto w-16 shrink-0 overflow-visible sm:w-30"
    >
      <line
        x1={0}
        x2={SPARK_W}
        y1={SPARK_H - SPARK_PAD}
        y2={SPARK_H - SPARK_PAD}
        className="stroke-border"
        strokeWidth={1}
      />
      {points.length > 1 && (
        <polyline
          // A tenth of a unit is finer than a pixel at this size; full floats only bloat the HTML.
          points={points
            .map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`)
            .join(" ")}
          className="fill-none stroke-primary"
          strokeWidth={1.5}
          strokeLinejoin="round"
          strokeLinecap="round"
        />
      )}
      {last && (
        <circle
          cx={last[0].toFixed(1)}
          cy={last[1].toFixed(1)}
          r={2.5}
          className="fill-primary"
        />
      )}
    </svg>
  );
}

function MetricsTable({ runs }: { runs: EvalRun[] }) {
  const newest = runs[runs.length - 1];
  return (
    <div className="surface overflow-x-auto rounded-xl border">
      <table className="type-body w-full border-collapse text-left">
        <caption className="sr-only">
          Each metric of the newest run, with its trend over the runs
        </caption>
        <thead className={HEAD}>
          <tr>
            <th scope="col" className={HEAD_CELL}>
              Metric
            </th>
            <th scope="col" className={cn(HEAD_CELL, NUMERIC)}>
              Newest
            </th>
            <th scope="col" className={cn(HEAD_CELL, "hidden sm:table-cell")}>
              <span className="sr-only">Share</span>
            </th>
            <th scope="col" className={HEAD_CELL}>
              Trend
            </th>
          </tr>
        </thead>
        <tbody>
          {metricsFor(runs).map(({ key, label, question }) => {
            const value = newest.scores[key];
            const ratio = typeof value !== "number";
            // metricsFor keeps only the metrics the newest run scored: never null here.
            const s = share(value) ?? 0;
            return (
              <tr key={key} className="border-t">
                <th
                  scope="row"
                  className="py-2 pr-2 pl-3 text-left align-top font-normal sm:px-4"
                >
                  <span className="font-medium">{label}</span>
                  <span className="block text-pretty text-muted-foreground">
                    {question}
                  </span>
                </th>
                <td className={cn(CELL_TIGHT, NUMERIC, "font-mono")}>
                  {formatScore(value)}
                </td>
                <td className={cn(CELL_TIGHT, "hidden w-40 sm:table-cell")}>
                  {ratio ? (
                    <span className="block h-2 w-32 overflow-hidden rounded-full bg-track">
                      <span
                        className="block h-full bg-primary"
                        style={{ width: `${s * 100}%` }}
                      />
                    </span>
                  ) : null}
                </td>
                <td className={CELL_TIGHT}>
                  <Sparkline
                    values={series(runs, key)}
                    ratio={ratio}
                    label={label}
                  />
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/**
 * The eval's results: one experiment at a time (its runs only compare with each other), the
 * newest run's headline numbers, and every metric with its trend over the experiment's runs.
 */
export function ResultsView({ runs }: { runs: EvalRun[] }) {
  const [experiment, setExperiment] = useState<Experiment>("seeded");
  const shown = runsOf(runs, experiment);
  const newest = shown.at(-1);
  const about = EXPERIMENTS.find((e) => e.id === experiment);

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-1">
        <h1>Results</h1>
        <p className="type-body text-muted-foreground">
          How well TraceScan finds, separates and explains faults whose cause is
          known.
        </p>
      </div>

      <fieldset className="flex min-w-0 flex-col gap-2">
        <legend className="sr-only">Experiment</legend>
        <div className={cn(SEGMENT_LIST, "w-fit max-w-full flex-wrap")}>
          {EXPERIMENTS.map((e) => (
            <label
              key={e.id}
              className={cn(
                SEGMENT_ITEM,
                experiment === e.id && SEGMENT_ACTIVE,
              )}
            >
              <input
                type="radio"
                name="experiment"
                value={e.id}
                checked={experiment === e.id}
                onChange={() => setExperiment(e.id)}
                className="sr-only"
              />
              {e.label}{" "}
              <span className="tabular-nums opacity-80">
                {runsOf(runs, e.id).length}
              </span>
            </label>
          ))}
        </div>
        <p className="type-body text-muted-foreground">{about?.note}</p>
      </fieldset>

      {newest ? (
        <>
          <section aria-labelledby="newest-run" className="flex flex-col gap-3">
            <h2 id="newest-run">
              Newest run{" "}
              <time
                dateTime={runTime(newest.id)}
                className="type-body font-normal text-muted-foreground"
              >
                {formatRunTime(newest.id)}
              </time>
            </h2>
            <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
              {headline(newest).map((t) => (
                <Tile key={t.label} {...t} />
              ))}
            </div>
            <p className="type-body text-muted-foreground">
              Diagnoser {newest.model ?? "unknown"}
              {newest.judgeModel && <>, trace judge {newest.judgeModel}</>}.
              {!newest.graded &&
                experiment !== "control" &&
                " Its root causes are not graded yet: run eval.judge for cause accuracy."}
            </p>
          </section>

          <section aria-labelledby="metrics" className="flex flex-col gap-3">
            <div className="flex flex-wrap items-baseline justify-between gap-x-3">
              <h2 id="metrics">Every metric</h2>
              <span className="type-body text-muted-foreground">
                Trend over {shown.length} runs, since{" "}
                {formatRunTime(shown[0].id)}
              </span>
            </div>
            <MetricsTable runs={shown} />
          </section>
        </>
      ) : (
        <p className="type-body text-muted-foreground">
          No results for this experiment yet. In backend/, run eval.run (or
          eval.medas_run) and eval.judge, then eval.metrics --export, which
          writes them here.
        </p>
      )}
    </div>
  );
}
