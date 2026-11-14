// The eval's results as the results page reads them: data/eval-results.json, which the backend's
// `python -m eval.metrics` writes (scores and run metadata only, oldest run first).

import { formatDuration, formatPercent } from "./format.ts";
import { isRecord } from "./guards.ts";
import { formatWhen, isCount, isText, isTextOrNull } from "./runs.ts";

export const EXPERIMENTS = [
  {
    id: "seeded",
    label: "Seeded day",
    note: "A synthetic day of Medas traces with known faults, graded against the injected cause.",
  },
  {
    id: "medas",
    label: "Medas faults",
    note: "Medas's own fault switches, on real requests among healthy ones.",
  },
  {
    id: "control",
    label: "Control",
    note: "A day with no fault seeded: anything found is a false alarm.",
  },
] as const;

export type Experiment = (typeof EXPERIMENTS)[number]["id"];

type Ratio = { hits: number; total: number };

export type EvalRun = {
  /** The results file's name: its UTC start, as `20261114T074549Z`. */
  id: string;
  experiment: Experiment;
  model: string | null;
  judgeModel: string | null;
  /** Whether the grader scored the root causes (eval.judge). */
  graded: boolean;
  scores: Record<string, Ratio | number>;
};

/** The metrics the page lists, in reading order, with the question each answers. */
const METRICS: { key: string; label: string; question: string }[] = [
  {
    key: "judge_recall",
    label: "Judge recall",
    question: "Did the trace judge catch every faulty trace?",
  },
  {
    key: "judge_false_positives",
    label: "Judge false positives",
    question: "How many harmless traces did it flag? Lower is better.",
  },
  {
    key: "judge_blame",
    label: "Judge blame",
    question: "Did it blame the step the answer key names?",
  },
  {
    key: "detection",
    label: "Detection",
    question: "How many faults got a diagnosis of their own?",
  },
  {
    key: "purity",
    label: "Purity",
    question: "How many traces sit in a cluster of their own fault?",
  },
  {
    key: "separation",
    label: "Separation",
    question: "How many faults are alone in exactly one cluster?",
  },
  {
    key: "rare_recall",
    label: "Rare recall",
    question: "Was the one-off fault found?",
  },
  {
    key: "trace_recall",
    label: "Trace recall",
    question: "How many faulty traces reached a cluster?",
  },
  {
    key: "category_accuracy",
    label: "Category accuracy",
    question: "Did the diagnosis get the category right?",
  },
  {
    key: "cause_accuracy",
    label: "Cause accuracy",
    question: "Did it name the injected cause, not just the symptom?",
  },
  {
    key: "evidence_valid",
    label: "Evidence valid",
    question: "Are the cited spans spans of the cluster's traces?",
  },
  {
    key: "evidence_relevant",
    label: "Evidence relevant",
    question: "Does a citation point at the span the trace failed in?",
  },
  {
    key: "false_alarms",
    label: "False alarms",
    question: "How many clusters hold traces with no fault? Lower is better.",
  },
];

const RUN_ID = /^(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})Z$/;
const EXPERIMENT_IDS: readonly string[] = EXPERIMENTS.map((e) => e.id);

function isRatio(value: unknown): value is Ratio {
  return isRecord(value) && isCount(value.hits) && isCount(value.total);
}

function parseRun(raw: unknown): EvalRun | null {
  if (!isRecord(raw) || !isRecord(raw.scores)) return null;
  const { id, experiment, model, judge_model, graded } = raw;
  if (!isText(id) || !RUN_ID.test(id)) return null;
  if (!isText(experiment) || !EXPERIMENT_IDS.includes(experiment)) return null;
  const scores: Record<string, Ratio | number> = {};
  for (const [key, value] of Object.entries(raw.scores)) {
    if (typeof value === "number" || isRatio(value)) scores[key] = value;
  }
  return {
    id,
    experiment: experiment as Experiment,
    model: isTextOrNull(model) ? model : null,
    judgeModel: isTextOrNull(judge_model) ? judge_model : null,
    graded: graded === true,
    scores,
  };
}

/**
 * The runs of the export, in its order (oldest first, as `eval.metrics --export` writes them); a
 * row off the contract is left out, never a throw.
 */
export function parseEvalRuns(raw: unknown): EvalRun[] {
  if (!Array.isArray(raw)) return [];
  return raw.map(parseRun).filter((r): r is EvalRun => r !== null);
}

/** When a run started, as an ISO string, read from its id. */
export function runTime(id: string): string {
  const m = RUN_ID.exec(id);
  if (!m) return id;
  return `${m[1]}-${m[2]}-${m[3]}T${m[4]}:${m[5]}:${m[6]}Z`;
}

/**
 * When a run started, in the runs page's words, in UTC on purpose: the page is prerendered, so a
 * time in the reader's own zone would differ between the server's render and theirs.
 */
export function formatRunTime(id: string): string {
  return `${formatWhen(runTime(id), "en-GB", "UTC")} UTC`;
}

export function runsOf(runs: EvalRun[], experiment: Experiment): EvalRun[] {
  return runs.filter((r) => r.experiment === experiment);
}

/** A ratio as a share from 0 to 1, a count as itself; null when there was nothing to count. */
export function share(value: Ratio | number | undefined): number | null {
  if (value === undefined) return null;
  if (typeof value === "number") return value;
  return value.total > 0 ? value.hits / value.total : null;
}

/** One metric over the runs, oldest first: its share (a ratio) or its count, null where absent. */
export function series(runs: EvalRun[], key: string): (number | null)[] {
  return runs.map((r) => share(r.scores[key]));
}

/**
 * The metrics worth a row for one experiment: the ones its newest run scored (a ratio out of
 * something, or a count), so a control day has no detection row and an old file adds no
 * metric it predates.
 */
export function metricsFor(runs: EvalRun[]): typeof METRICS {
  const newest = runs.at(-1);
  if (!newest) return [];
  return METRICS.filter(({ key }) => share(newest.scores[key]) !== null);
}

/** A ratio as "8/9", or a count as itself. */
export function formatScore(value: Ratio | number): string {
  if (typeof value === "number") return String(value);
  return `${value.hits}/${value.total}`;
}

type HeadlineTile = { label: string; value: string; hint: string };

/** The headline tiles of an experiment's newest run. */
export function headline(run: EvalRun): HeadlineTile[] {
  const percent = (key: string, of: string): HeadlineTile[] => {
    const value = run.scores[key];
    const s = share(value);
    if (s === null || typeof value !== "object") return [];
    return [
      {
        label: METRICS.find((m) => m.key === key)?.label ?? key,
        value: formatPercent(s),
        hint: `${value.hits} of ${value.total} ${of}`,
      },
    ];
  };
  const { cost_usd: cost, seconds, false_alarms: alarms } = run.scores;
  const tiles =
    run.experiment === "control"
      ? [
          {
            label: "False alarms",
            value: typeof alarms === "number" ? String(alarms) : "—",
            hint: "clusters found on a day with no fault",
          },
          ...percent("judge_false_positives", "harmless traces flagged"),
        ]
      : [
          ...percent("cause_accuracy", "diagnoses"),
          ...percent("detection", "faults"),
          ...percent("judge_recall", "faulty traces"),
        ];
  tiles.push({
    label: "Cost",
    value: typeof cost === "number" ? `$${cost.toFixed(2)}` : "—",
    hint:
      typeof seconds === "number"
        ? `judge and diagnoser, ${formatDuration(seconds * 1000)}`
        : "judge and diagnoser",
  });
  return tiles;
}
