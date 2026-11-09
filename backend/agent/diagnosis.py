"""The diagnosis contract. For now only the failure categories; the Diagnosis model comes with the diagnoser."""

from typing import Literal, get_args

FailureCategory = Literal[
    # single-agent causes
    "retrieval_miss",
    "tool_schema_error",
    "context_overflow",
    "prompt_regression",
    "model_quality",
    "infra_error",
    # MAST top-level categories, for multi-agent targets
    "system_design",
    "inter_agent_misalignment",
    "task_verification",
    "unknown",
]

# Every category has a section in taxonomy.md; tests/test_taxonomy.py keeps the two in step.
FAILURE_CATEGORIES: tuple[str, ...] = get_args(FailureCategory)
