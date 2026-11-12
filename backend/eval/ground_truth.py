"""The answer key of the eval: what each kind of seeded failure really is.

One entry per failure the seed script makes (scripts/seed_traces.py), under the name of its
maker there; `seed_traces.kinds(end)` says which trace is of which kind. A kind in NOT_FAULTS
has no fault, so nothing should be proposed for it. A diagnosis is graded on the cause, not on
the symptom: the symptom is what anyone can read off the trace, the cause is what was injected.

The first five faults are plain: each raises its own exception. The rest are the hard cases:
a look-alike (tight_timeout), two errors in one request (double_failure), a failure with no
error (silent_no_hits) and one with no visible cause (unexplained). model_unavailable is one
cause with two faces. NOT_FAULTS holds the errors that are not faults.

A kind whose cause is another kind's names it in `same_cause_as`: grouping the two is one issue
for one cause, so the clustering scores count them as one fault (`cause_of`).
"""

from pydantic import BaseModel, ConfigDict

from agent.schemas import FailureCategory


class Fault(BaseModel):
    model_config = ConfigDict(frozen=True)

    category: FailureCategory  # the category a correct diagnosis gives
    cause: str  # what was injected: the component and what goes wrong in it
    symptom: str  # what is visible without understanding the cause
    failing_span: str  # the name of the span the failure starts in, which good evidence cites
    # No span has an error status, so a reader that looks for errors never collects the trace.
    silent: bool = False
    # The kind whose injected cause this one shares; the clustering scores count both as that kind.
    same_cause_as: str | None = None


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
            "The model provider is unavailable for the request's first chat call: it answers "
            "with a server error (502 or 503) or does not answer in time, so the agent has no "
            "model to answer with."
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
    "tight_timeout": Fault(
        category="infra_error",
        cause=(
            "The search_pubmed tool's own timeout is set to 1 second, far below the time PubMed "
            "normally takes, so the tool gives up on calls that would have been answered."
        ),
        symptom="The search_pubmed tool call ends in a read timeout.",
        failing_span="execute_tool search_pubmed",
    ),
    "double_failure": Fault(
        category="infra_error",
        cause=(
            "The model provider answers the request's last chat call with a server error (503), "
            "so the agent cannot answer. The PubMed timeout earlier in the same request was "
            "tolerated and did not make the request fail."
        ),
        symptom="A search_pubmed call times out and the request fails.",
        failing_span="chat openai/gpt-4.1-mini",
        same_cause_as="model_unavailable",
    ),
    "silent_no_hits": Fault(
        category="retrieval_miss",
        cause=(
            "The patient record search returns no chunks, and the model answers anyway, "
            "without the record it needed."
        ),
        symptom="Nothing fails: every span ends without an error.",
        failing_span="retrieval record_chunks",
        silent=True,
    ),
    "unexplained": Fault(
        category="unknown",
        cause=(
            "The trace does not show the cause: only the request's root span fails, with a "
            "generic 'the agent could not answer', and every span under it succeeded. A correct "
            "diagnosis says the evidence is missing and does not invent a cause."
        ),
        symptom="The request fails with: the agent could not answer.",
        failing_span="invoke_agent medas",
    ),
}

# Kinds with no fault, and why: a proposal for one of them is a false alarm.
NOT_FAULTS: dict[str, str] = {
    "healthy": "Nothing went wrong.",
    "retried_ok": "A source refused one call for its rate limit; the retry worked and the request succeeded.",
    "not_found": "The user asked for a record that does not exist; the tool said so and the model told the user.",
}


def cause_of(kind: str) -> str:
    """The kind a trace counts as in the clustering scores: its own, or the one it shares a cause with."""
    fault = FAULTS.get(kind)
    return (fault.same_cause_as or kind) if fault else kind
