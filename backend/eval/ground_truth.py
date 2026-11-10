"""The answer key of the eval: what each kind of seeded failure really is.

One entry per failure the seed script makes (scripts/seed_traces.py), under the name of its
maker there; `seed_traces.kinds(end)` says which trace is of which kind, and a kind with no
entry here (healthy) has no fault, so nothing should be proposed for it. A diagnosis is graded
on the cause, not on the symptom: the symptom is what anyone can read off the trace, the cause
is what was injected.
"""

from pydantic import BaseModel, ConfigDict

from agent.schemas import FailureCategory


class Fault(BaseModel):
    model_config = ConfigDict(frozen=True)

    category: FailureCategory  # the category a correct diagnosis gives
    cause: str  # what was injected: the component and what goes wrong in it
    symptom: str  # what is visible without understanding the cause
    failing_span: str  # the name of the span the failure starts in, which good evidence cites


FAULTS: dict[str, Fault] = {
    "source_timeout": Fault(
        category="infra_error",
        cause=(
            "The public PubMed source does not answer within the search_pubmed tool's "
            "10 second timeout, so the tool call fails."
        ),
        symptom="The search_pubmed tool call ends in an error and the answer has no PubMed source.",
        failing_span="execute_tool search_pubmed",
    ),
    "tool_arguments": Fault(
        category="tool_schema_error",
        cause=(
            "The model calls export_conversation with a `format` argument that is not a string, "
            "which the tool's input schema refuses."
        ),
        symptom="The export_conversation tool call ends in a validation error.",
        failing_span="execute_tool export_conversation",
    ),
    "model_unavailable": Fault(
        category="infra_error",
        cause=(
            "The model provider answers the request's first chat call with a server error "
            "(502 or 503), so the agent has no model to answer with."
        ),
        symptom="The request fails with: the agent could not answer.",
        failing_span="chat openai/gpt-4.1-mini",
    ),
    "context_overflow": Fault(
        category="context_overflow",
        cause=(
            "The patient record search puts more text into the conversation than the model's "
            "context length allows, so the provider rejects the next chat call."
        ),
        symptom="A chat call is rejected with a 400 error and the request fails.",
        failing_span="chat openai/gpt-4.1-mini",
    ),
    "store_down": Fault(
        category="infra_error",
        cause=(
            "The database behind the patient record search refuses the connection, "
            "so the retrieval cannot run."
        ),
        symptom="The search_patient_record tool call ends in an error and the request fails.",
        failing_span="retrieval record_chunks",
    ),
}
