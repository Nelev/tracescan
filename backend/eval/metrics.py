"""The eval's scores, computed from a results file (eval/run.py) and the answer key.

Run from backend/:  uv run python -m eval.metrics [out/eval/<file>.json]   (default: the newest)

Pure code: no model and no database. Every cluster gets a majority kind, the seeded kind most
of its traces are of, and the scores follow from that. A ratio is (how many, out of how many).
Whether a root cause is the right one takes a judge (eval/judge.py): its scores are added
when the file has verdicts.
"""

import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from agent import actions
from eval.ground_truth import FAULTS

OUT_DIR = actions.OUT_DIR / "eval"  # where eval/run.py writes its results files


def _mixes(result: dict[str, Any]) -> dict[str, Counter[str]]:
    """Per cluster: how many of its traces are of each kind."""
    kinds = result["kinds"]
    return {c["cluster_id"]: Counter(kinds[t] for t in c["trace_ids"]) for c in result["clusters"]}


def majority_kinds(result: dict[str, Any]) -> dict[str, str]:
    """Per cluster: the kind most of its traces are of."""
    return {cluster_id: mix.most_common(1)[0][0] for cluster_id, mix in _mixes(result).items()}


def score(result: dict[str, Any]) -> dict[str, Any]:
    kinds = result["kinds"]
    diagnoses = list(result["diagnoses"])
    mixes = _mixes(result)
    majority = {cluster_id: mix.most_common(1)[0][0] for cluster_id, mix in mixes.items()}
    expected = {c: FAULTS[kind].category for c, kind in majority.items() if kind in FAULTS}
    seeded = Counter(kind for kind in kinds.values() if kind in FAULTS)

    detected = {majority[d["cluster_id"]] for d in diagnoses} & set(seeded)
    # A diagnosis of a cluster with no fault is a false alarm, counted there and nowhere else.
    of_faults = [d for d in diagnoses if d["cluster_id"] in expected]
    rare = {fault for fault, count in seeded.items() if count == 1}
    failing = result["failing_spans"]
    usage = result["model_usage"]
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
        "calls": sum(entry["calls"] for entry in usage),
        "tokens": sum(entry["tokens"] for entry in usage),
        "cost_usd": round(sum(entry["cost_usd"] for entry in usage), 4),
        "seconds": result["seconds"],
    }
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
    for name, value in score(json.loads(path.read_text())).items():
        if isinstance(value, tuple):
            hits, total = value
            value = f"{hits}/{total}" + (f" ({hits / total:.0%})" if total else "")
        print(f"  {name:18} {value}")


if __name__ == "__main__":
    main()
