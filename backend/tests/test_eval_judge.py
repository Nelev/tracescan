"""The judge: what it is shown for each diagnosis, and what it gives back."""

from typing import Any, cast

import pytest
from langchain_core.language_models import BaseChatModel

from eval.ground_truth import FAULTS
from eval.judge import Verdict, judge


class FakeJudge:
    """Stands in for the chat model: scores every diagnosis 2 and keeps what it was asked."""

    def __init__(self) -> None:
        self.asked: list[str] = []

    def with_structured_output(self, schema: type, **_: Any) -> "FakeJudge":
        assert schema is Verdict
        return self

    async def ainvoke(self, messages: list[tuple[str, str]]) -> Verdict:
        self.asked.append(messages[1][1])
        return Verdict(reasoning="names the cause", score=2)


RESULT = {
    "kinds": {"t1": "source_timeout", "t2": "source_timeout", "h1": "healthy"},
    "clusters": [
        {"cluster_id": "c0", "trace_ids": ["t1", "t2"]},
        {"cluster_id": "c1", "trace_ids": ["h1"]},
    ],
    "diagnoses": [
        {"cluster_id": "c0", "category": "infra_error", "root_cause": "PubMed is slow"},
        {"cluster_id": "c1", "category": "model_quality", "root_cause": "the model is weak"},
    ],
}


@pytest.mark.anyio
async def test_a_diagnosis_is_judged_against_the_cause_of_its_clusters_kind():
    model = FakeJudge()

    verdicts = await judge(RESULT, cast(BaseChatModel, model))

    assert verdicts == [
        # A diagnosis of healthy traces is a false alarm, counted by the metrics: not judged.
        {"cluster_id": "c0", "reasoning": "names the cause", "score": 2},
    ]
    (asked,) = model.asked
    fault = FAULTS["source_timeout"]
    assert fault.cause in asked and fault.symptom in asked and "PubMed is slow" in asked
    assert "infra_error" not in asked  # the category is graded in code, not shown to the judge
