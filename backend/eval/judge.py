"""The judge: does a diagnosis name the cause that was injected, or only the symptom?

Run from backend/:  uv run --env-file .env python -m eval.judge [out/eval/<file>.json]
                    ... python -m eval.judge --human c0=2 c1=1     (your own grades, to compare)
                    ... python -m eval.judge --rejudge             (after a change to the rubric)

One short model call per diagnosis of a results file (eval/run.py), on a model of another
vendor than the diagnoser's (JUDGE_MODEL) so it does not grade its own style. The judge sees
the rubric (judge_rubric.md), the true cause, the visible symptom and the diagnosis's root
cause, nothing else. The verdicts go back into the results file, where eval/metrics.py scores
them. A file is judged once: verdicts that are there are kept, so the grades you compared them
with stay comparable, unless --rejudge asks for new ones.
"""

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any, Literal

from langchain_core.language_models import BaseChatModel
from pydantic import BaseModel

from agent.model import build_model
from eval.metrics import answer_key, majority_kinds, results_path

# Another vendor than the diagnoser's; the JUDGE_MODEL environment variable overrides it.
DEFAULT_JUDGE_MODEL = "openai/gpt-6.1-sol"
RUBRIC = (Path(__file__).parent / "judge_rubric.md").read_text()


class Verdict(BaseModel):
    reasoning: str
    score: Literal[0, 1, 2]


async def judge(result: dict[str, Any], model: BaseChatModel) -> list[dict[str, Any]]:
    """One verdict per diagnosis of a fault: its cluster id, the score and the reasoning."""
    grader = model.with_structured_output(Verdict, method="json_schema")
    kinds = majority_kinds(result)
    faults = answer_key(result)

    async def grade(diagnosis: dict[str, Any]) -> dict[str, Any]:
        cluster_id = diagnosis["cluster_id"]
        fault = faults[kinds[cluster_id]]
        answer = (
            f"True cause: {fault.cause}\n"
            f"Visible symptom: {fault.symptom}\n"
            f"Diagnosis to grade: {diagnosis['root_cause']}"
        )
        verdict = Verdict.model_validate(
            await grader.ainvoke([("system", RUBRIC), ("human", answer)])
        )
        return {"cluster_id": cluster_id, **verdict.model_dump()}

    # A diagnosis of a cluster with no fault is a false alarm (eval/metrics.py), not judged.
    of_faults = [d for d in result["diagnoses"] if kinds[d["cluster_id"]] in faults]
    return await asyncio.gather(*(grade(diagnosis) for diagnosis in of_faults))


def main() -> None:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("file", nargs="?", type=Path, help="a results file (default: the newest)")
    parser.add_argument("--human", nargs="+", metavar="CLUSTER=SCORE", help="your own grades")
    parser.add_argument("--rejudge", action="store_true", help="replace the file's verdicts")
    args = parser.parse_args()
    path = results_path(args.file)
    result = json.loads(path.read_text())

    if args.human:
        result["human"] = {c: int(s) for c, s in (grade.split("=") for grade in args.human)}
    if args.rejudge or "verdicts" not in result:
        # The SDK's own retries, unlike the diagnoser: one failed call would lose the others.
        model = build_model("JUDGE_MODEL", DEFAULT_JUDGE_MODEL, max_retries=2)
        result["verdicts"] = asyncio.run(judge(result, model))
        result["judge"] = getattr(model, "model_name", "unknown")
    path.write_text(json.dumps(result, indent=2))

    kinds = majority_kinds(result)
    root_causes = {d["cluster_id"]: d["root_cause"] for d in result["diagnoses"]}
    print(f"{path}, judged by {result['judge']}")
    for verdict in result["verdicts"]:
        cluster_id = verdict["cluster_id"]
        print(f"\n{cluster_id} ({kinds[cluster_id]}): {verdict['score']}")
        print(f"  true:      {answer_key(result)[kinds[cluster_id]].cause}")
        print(f"  diagnosis: {root_causes[cluster_id]}")
        print(f"  judge:     {verdict['reasoning']}")


if __name__ == "__main__":
    main()
