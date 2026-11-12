"""The eval's scores, computed from a results file (eval/run.py) and the answer key.

Run from backend/:  uv run python -m eval.metrics [out/eval/<file>.json]   (default: the newest)

Pure code: no model and no database. Every cluster gets a majority kind, the seeded kind most
of its traces are of, and the scores follow from that. A ratio is (how many, out of how many).
Whether a root cause is the right one takes a judge (eval/judge.py): its scores are added
when the file has verdicts. The trace judge, which decides which traces failed before anything
is clustered, is scored on its own against the kinds: how many faulty traces it caught, how many
harmless ones it flagged, per kind too, and whether it blamed the step the fault starts in; its
spend is in the cost.
"""

import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from agent import actions
from eval.ground_truth import FAULTS, cause_of

OUT_DIR = actions.OUT_DIR / "eval"  # where eval/run.py writes its results files


def _mixes(result: dict[str, Any], given: dict[str, str] | None = None) -> dict[str, Counter[str]]:
    """Per cluster: how many of its traces are of each kind (the file's kinds unless given)."""
    kinds: dict[str, str] = result["kinds"] if given is None else given
    return {c["cluster_id"]: Counter(kinds[t] for t in c["trace_ids"]) for c in result["clusters"]}


def majority_kinds(result: dict[str, Any]) -> dict[str, str]:
    """Per cluster: the kind most of its traces are of."""
    return {cluster_id: mix.most_common(1)[0][0] for cluster_id, mix in _mixes(result).items()}


def judge_scores(result: dict[str, Any]) -> dict[str, Any]:
    """The trace judge against the answer key: a faulty trace should be judged failed, a
    harmless one not. A trace the judge could not judge (`judge_failures`) counts as not failed."""
    kinds = result["kinds"]
    failed = {v["trace_id"] for v in result["trace_verdicts"] if v["failed"]}
    # The step the judge blamed in each faulty trace it caught, against the answer key's.
    blamed = [
        v.get("failing_span_name") == FAULTS[kinds[v["trace_id"]]].failing_span
        for v in result["trace_verdicts"]
        if v["failed"] and kinds[v["trace_id"]] in FAULTS
    ]
    by_kind: dict[str, list[int]] = {}
    for trace_id, kind in kinds.items():
        hits = by_kind.setdefault(kind, [0, 0])
        hits[0] += trace_id in failed
        hits[1] += 1
    faulty = [t for t, kind in kinds.items() if kind in FAULTS]
    harmless = [t for t, kind in kinds.items() if kind not in FAULTS]
    return {
        "judge_recall": (sum(t in failed for t in faulty), len(faulty)),
        "judge_false_positives": (sum(t in failed for t in harmless), len(harmless)),
        # Of the faulty traces it caught, how many blame the step the fault starts in.
        "judge_blame": (sum(blamed), len(blamed)),
        "judge_failures": len(result.get("judge_failures", [])),
        # Per seeded kind: (judged failed, traces of it).
        "judge_by_kind": {kind: tuple(by_kind[kind]) for kind in sorted(by_kind)},
    }


def _spend(usage: list[dict[str, Any]]) -> tuple[int, int, float]:
    return (
        sum(entry["calls"] for entry in usage),
        sum(entry["tokens"] for entry in usage),
        sum(entry["cost_usd"] for entry in usage),
    )


def score(result: dict[str, Any]) -> dict[str, Any]:
    # Kinds that share a cause count as one fault: one cluster for both is one issue, not a merge.
    kinds = {trace_id: cause_of(kind) for trace_id, kind in result["kinds"].items()}
    diagnoses = list(result["diagnoses"])
    mixes = _mixes(result, kinds)
    majority = {cluster_id: mix.most_common(1)[0][0] for cluster_id, mix in mixes.items()}
    expected = {c: FAULTS[kind].category for c, kind in majority.items() if kind in FAULTS}
    seeded = Counter(kind for kind in kinds.values() if kind in FAULTS)

    detected = {majority[d["cluster_id"]] for d in diagnoses} & set(seeded)
    # A diagnosis of a cluster with no fault is a false alarm, counted there and nowhere else.
    of_faults = [d for d in diagnoses if d["cluster_id"] in expected]
    rare = {fault for fault, count in seeded.items() if count == 1}
    failing = result["failing_spans"]
    calls, tokens, cost = _spend(result["model_usage"])
    # Files from before the judge's spend was kept have none: their cost is the diagnoser's alone.
    judge_calls, judge_tokens, judge_cost = _spend(result.get("judge_usage", []))
    scores: dict[str, Any] = {
        "detection": (len(detected), len(seeded)),
        "purity": (
            sum(mix.most_common(1)[0][1] for mix in mixes.values()),
            sum(mix.total() for mix in mixes.values()),
        ),
        # A fault is separated when one cluster holds all of its traces and nothing else.
        "separation": (
            sum({fault: count} in mixes.values() for fault, count in seeded.items()),
            len(seeded),
        ),
        "rare_recall": (len(rare & detected), len(rare)),
        # Traces of a fault that reached a cluster at all; a failure with no error never does.
        "trace_recall": (
            sum(sum(n for kind, n in mix.items() if kind in FAULTS) for mix in mixes.values()),
            seeded.total(),
        ),
        "false_alarms": sum(any(kind not in FAULTS for kind in mix) for mix in mixes.values()),
        "category_accuracy": (
            sum(d["category"] == expected[d["cluster_id"]] for d in of_faults),
            len(of_faults),
        ),
        "evidence_valid": (
            sum(d.get("evidence_check") == "valid" for d in diagnoses),
            len(diagnoses),
        ),
        # The diagnosis cites the span one of its traces failed in.
        "evidence_relevant": (
            sum(
                any(failing.get(e["trace_id"]) == e["span_id"] for e in d["evidence"])
                for d in diagnoses
            ),
            len(diagnoses),
        ),
        # The whole run's model spend: the diagnoser's and the trace judge's.
        "calls": calls + judge_calls,
        "tokens": tokens + judge_tokens,
        "cost_usd": round(cost + judge_cost, 4),
        "judge_cost_usd": round(judge_cost, 4),
        "seconds": result["seconds"],
    }
    if "trace_verdicts" in result:  # files from before the trace judge have none
        scores |= judge_scores(result)
    if verdicts := result.get("verdicts"):  # the file has been judged (eval/judge.py)
        # The headline: diagnoses that name the injected cause (2 on the rubric's 0 to 2).
        scores["cause_accuracy"] = (sum(v["score"] == 2 for v in verdicts), len(verdicts))
        scores["root_cause_mean"] = round(sum(v["score"] for v in verdicts) / len(verdicts), 2)
        if human := result.get("human"):  # your own grades, by cluster id
            graded = [v for v in verdicts if v["cluster_id"] in human]
            scores["judge_agreement"] = (
                sum(human[v["cluster_id"]] == v["score"] for v in graded),
                len(graded),
            )
    return scores


def results_path(given: Path | None) -> Path:
    """The results file to read: the one given, else the newest one eval/run.py wrote."""
    path = given or max(OUT_DIR.glob("*.json"), default=None)
    if path is None:
        raise SystemExit(f"no results file in {OUT_DIR}: run `python -m eval.run` first")
    return path


def main() -> None:
    path = results_path(Path(sys.argv[1]) if len(sys.argv) > 1 else None)
    print(path)
    result = json.loads(path.read_text())
    if result.get("control"):
        print("  control day: no fault was seeded, so anything found is a false alarm")
    for name, value in score(result).items():
        if isinstance(value, dict):
            print(f"  {name}")
            for kind, ratio in value.items():
                print(f"    {kind:22} {_ratio(ratio)}")
            continue
        print(f"  {name:22} {_ratio(value) if isinstance(value, tuple) else value}")


def _ratio(value: tuple[int, int]) -> str:
    hits, total = value
    return f"{hits}/{total}" + (f" ({hits / total:.0%})" if total else "")


if __name__ == "__main__":
    main()
