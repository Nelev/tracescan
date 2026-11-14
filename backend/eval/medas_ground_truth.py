"""The answer key of the eval on Medas: what each of its fault switches really breaks.

Medas holds six known bugs, each turned on by one environment variable (`medas-api/faults.py`
in Nelev/medas; its README's "Fault switches" section). One entry per switch, under the name of
its field in Medas's `FaultSettings`. For each: the `Fault` a correct diagnosis matches (the
same contract as the seeded eval's, `eval/ground_truth.py`), the variable that turns it on, and
the questions that trigger it, as ids from Medas's `dataset/traffic/queries.yaml`, the input the
traffic generator's `--ids` takes. Every input set is a different way in: other questions, other
wording, another language.

A trace's kind is the switch that was on when it was sent, not anything read off the trace, so
the diagnoser cannot see the answer. Runs with no switch on are the controls (`CONTROL_SETS`):
whatever is proposed there is a false alarm.

The hard cases:
- Look-alikes (`LOOK_ALIKES`): pairs of faults that fail at the same step and look the same on
  a trace. Run in one window, they must still come out as two clusters with two causes.
- Low volume (`MedasFault.low_volume`): a fault sent only once or twice, which should reach a
  diagnosis through `unclustered` rather than be lost.
- Silent faults (`Fault.silent`): no span has an error status. The empty retrieval shows as 0
  hits, the truncated prompt as `medas.reply.format` `malformed`; the small context and the
  weak model leave no error and a well-formed reply, and on 2026-11-13 the trace judge passed
  every one of their traces.
"""

from collections.abc import Callable, Iterator

from pydantic import BaseModel, ConfigDict, Field

from eval.ground_truth import Fault
from trace_store.models import SpanNode

# The model Medas runs on, whose chat spans a fault in its answer starts in.
MEDAS_MODEL = "openai/gpt-4.1-mini"
# The model the weak-model switch puts in its place: one the OpenRouter key's guardrail allows
# (a blocked one fails every call with a 404, which is another fault) and that does not use the
# agent's tools. openai/gpt-4o-mini is allowed but runs like the usual model.
WEAK_MODEL = "google/gemma-4-31b-it"


class InputSet(BaseModel):
    """The questions one traffic run sends for a fault, each `repeat` times."""

    model_config = ConfigDict(frozen=True)

    ids: tuple[str, ...] = Field(min_length=1)
    repeat: int = Field(default=1, ge=1)


class MedasFault(Fault):
    # The environment of the traffic run: the switch, set on the command line, never in .env.
    switch: dict[str, str]
    # At least two, each a different way of triggering the fault.
    input_sets: tuple[InputSet, ...] = Field(min_length=2)
    # Sent so rarely that it should not form a cluster of its own.
    low_volume: bool = False


FAULTS: dict[str, MedasFault] = {
    "empty_retrieval": MedasFault(
        category="retrieval_miss",
        cause=(
            "The patient record search drops every passage when the search is about "
            "medication, so the record's medication entries are never found and the model "
            "answers without them."
        ),
        symptom=(
            "The record_chunks retrieval returns 0 hits, the agent may search again, and the "
            "answer has no record behind it. Nothing ends in an error."
        ),
        failing_span="retrieval record_chunks",
        silent=True,
        low_volume=True,
        switch={"FAULT_EMPTY_RETRIEVAL": "medication"},
        # Which biologic injection; how to use the inhaler; the same in Italian and misspelled.
        input_sets=(
            InputSet(ids=("N01",)),
            InputSet(ids=("N10",)),
            InputSet(ids=("E03", "E04")),
        ),
    ),
    "tool_schema": MedasFault(
        category="tool_schema_error",
        cause=(
            "search_patient_record is called with an argument named `search_query`, while its "
            "input schema takes `query`: the caller was not updated after a rename, so every "
            "call is refused before the search runs."
        ),
        symptom="The search_patient_record tool call ends in a validation error, every time.",
        failing_span="execute_tool search_patient_record",
        switch={"FAULT_TOOL_SCHEMA": "1"},
        input_sets=(
            InputSet(ids=("N03", "N04")),
            InputSet(ids=("N05", "N14", "E07")),
        ),
    ),
    "truncated_prompt": MedasFault(
        category="prompt_regression",
        cause=(
            "The system prompt is cut before its Output section, so the model no longer knows "
            "the JSON shape the reply must have (message, severity, confidence) and answers in "
            "a shape of its own."
        ),
        symptom=(
            "Nothing ends in an error, and the request's root span says the reply was "
            "malformed (medas.reply.format)."
        ),
        failing_span="invoke_agent medas",
        silent=True,
        switch={"FAULT_TRUNCATED_PROMPT": "1"},
        input_sets=(
            InputSet(ids=("N03", "N04")),
            InputSet(ids=("N07", "N11", "E06")),
        ),
    ),
    "context_tokens": MedasFault(
        category="context_overflow",
        cause=(
            "The agent sends the model only 1,000 tokens after the question, less than one "
            "record search returns, so each search result is dropped with the call that asked "
            "for it and the model searches again for what it never sees."
        ),
        symptom=(
            "The same record search runs many times in one request before the answer. Nothing "
            "ends in an error."
        ),
        failing_span=f"chat {MEDAS_MODEL}",
        silent=True,
        switch={"FAULT_CONTEXT_TOKENS": "1000"},
        # Questions whose record search returns long passages; short ones fit and pass.
        input_sets=(
            InputSet(ids=("N03",)),
            InputSet(ids=("N13", "E05")),
        ),
    ),
    "weak_model": MedasFault(
        category="model_quality",
        cause=(
            f"The agent's model was swapped from {MEDAS_MODEL} for {WEAK_MODEL}, which "
            "answers questions about the patient's record without calling any tool."
        ),
        symptom=(
            f"Each request is one chat call to {WEAK_MODEL} and nothing else: no tool call, "
            "no error."
        ),
        failing_span=f"chat {WEAK_MODEL}",
        silent=True,
        switch={"FAULT_WEAK_MODEL": WEAK_MODEL},
        input_sets=(
            InputSet(ids=("N01", "N03", "N04")),
            InputSet(ids=("N09", "N13", "E04")),
        ),
    ),
    "upstream_timeout": MedasFault(
        category="infra_error",
        cause=(
            "Half the calls to the public health sources (MedlinePlus and PubMed) time out "
            "before connecting, so those tool calls fail and the answer goes without them."
        ),
        symptom=(
            "A search_medlineplus or search_pubmed call ends in a tool-reported error, "
            "'source timed out', on some requests and not others."
        ),
        failing_span="execute_tool search_medlineplus",
        switch={"FAULT_UPSTREAM_TIMEOUT": "0.5"},
        # Intermittent, so each question is sent more than once.
        input_sets=(
            InputSet(ids=("N07", "N11"), repeat=2),
            InputSet(ids=("N06", "N09"), repeat=2),
        ),
    ),
}

# Pairs of faults that look alike on a trace, and why. The eval runs each pair in one window.
LOOK_ALIKES: dict[tuple[str, str], str] = {
    ("empty_retrieval", "tool_schema"): (
        "Both break search_patient_record, so the record is never read and the model answers "
        "without it; one fails with a validation error, the other finds 0 passages."
    ),
    ("empty_retrieval", "context_tokens"): (
        "Both make the agent search the record again and again in one request, with no error; "
        "one finds nothing, the other finds passages the model is never shown."
    ),
}

# The kind of a trace sent with no switch on, or sent with one that did not fire: nothing was
# injected into it, so a proposal for it is a false alarm.
HEALTHY = "healthy"
NOT_FAULTS: dict[str, str] = {
    HEALTHY: (
        "Nothing was injected: sent with no switch on, or with one that did not fire on this "
        "request (a timeout share that spared it, a search that was not about medication). "
        "PubMed failing on its own is a real failure, but not one of the faults."
    ),
}

# Record searches in one request from which the small context counts as having fired: a healthy
# request makes up to three, the context fault's loop seven or more.
CONTEXT_LOOP_SEARCHES = 5


def spans(tree: SpanNode) -> Iterator[SpanNode]:
    """Every span of the tree, the root first."""
    yield tree
    for child in tree.children:
        yield from spans(child)


def _named(tree: SpanNode, name: str) -> list[SpanNode]:
    return [span for span in spans(tree) if span.name == name]


# Whether a fault fired on a request, read off its trace by the grader. A switch can be on and
# still spare a request (the timeout's share, a search not about medication), and a trace it
# spared is graded as healthy, not as a fault the agent missed. Never shown to the agent.
FIRED: dict[str, Callable[[SpanNode], bool]] = {
    "empty_retrieval": lambda tree: any(
        span.attributes.get("retrieval.hits") == 0
        for span in _named(tree, "retrieval record_chunks")
    ),
    "tool_schema": lambda tree: any(
        str(span.attributes.get("error.type", "")).endswith("ValidationError")
        for span in _named(tree, "execute_tool search_patient_record")
    ),
    # Any reply but the asked-for one: without its Output section the model may still send a
    # message, only without the triage code (no_severity), or no such object at all (malformed).
    "truncated_prompt": lambda tree: (
        tree.attributes.get("medas.reply.format")
        in (
            "malformed",
            "no_severity",
        )
    ),
    "context_tokens": lambda tree: (
        len(_named(tree, "retrieval record_chunks")) >= CONTEXT_LOOP_SEARCHES
    ),
    "weak_model": lambda tree: bool(_named(tree, f"chat {WEAK_MODEL}")),
    "upstream_timeout": lambda tree: any(
        span.status_message == "source timed out"
        for span in spans(tree)
        if span.name in ("execute_tool search_medlineplus", "execute_tool search_pubmed")
    ),
}


def kind_of(switched: str | None, tree: SpanNode) -> str:
    """A trace's kind in the answer key: the fault that was switched on when it was sent, if
    it fired on this request; else healthy."""
    return switched if switched is not None and FIRED[switched](tree) else HEALTHY


# The traffic of the control runs, with no switch on: every normal and edge question once.
# Proposals made there are false alarms. PubMed sometimes fails on its own ('source
# unavailable', its rate limit, probably): a real failure, which looks like the timeout fault
# but is not one of these.
CONTROL_SETS: tuple[InputSet, ...] = (
    InputSet(ids=tuple(f"N{n:02}" for n in range(1, 15))),
    InputSet(ids=tuple(f"E{n:02}" for n in range(1, 12))),
)
