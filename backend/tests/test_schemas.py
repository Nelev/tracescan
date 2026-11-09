"""The Diagnosis contract: what the diagnoser may return and what it may not."""

import pytest
from pydantic import ValidationError

from agent.schemas import Diagnosis


def diagnosis(**overrides) -> dict:
    return {
        "cluster_id": "c0",
        "category": "retrieval_miss",
        "root_cause": "The retriever's filter excludes the drug-interaction category.",
        "suggested_fix": "Include the category in the retriever filter.",
        "confidence": 0.8,
        "evidence": [{"trace_id": "t1", "span_id": "s1", "note": "retrieve returned 0 chunks"}],
        **overrides,
    }


def test_a_valid_diagnosis_round_trips_through_a_plain_dict():
    parsed = Diagnosis.model_validate(diagnosis())
    assert Diagnosis.model_validate(parsed.model_dump(mode="json")) == parsed


@pytest.mark.parametrize(
    "overrides",
    [
        {"category": "bad_luck"},
        {"confidence": 1.5},
        {"confidence": -0.1},
        {"evidence": []},
        {"root_cause": ""},
        {"evidence": [{"trace_id": "t1", "span_id": "not a valid id!", "note": "x"}]},
        {"evidence": [{"trace_id": "t1", "span_id": "s1", "note": ""}]},
    ],
)
def test_a_diagnosis_outside_the_contract_is_rejected(overrides):
    with pytest.raises(ValidationError):
        Diagnosis.model_validate(diagnosis(**overrides))
