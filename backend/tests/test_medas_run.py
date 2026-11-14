"""The eval on Medas: what it sends, how it matches traces to sends, and how it labels them.

No Medas, no model and no database: the traffic generator is a fake sender, the traces are
hand-made summaries and trees.
"""

from datetime import UTC, datetime, timedelta

import pytest

from eval import medas_run
from eval.medas_ground_truth import (
    CONTEXT_LOOP_SEARCHES,
    CONTROL_SETS,
    FAULTS,
    HEALTHY,
    WEAK_MODEL,
    InputSet,
    kind_of,
)
from eval.medas_run import (
    Send,
    Sent,
    TrafficMismatch,
    assign,
    child_environment,
    faults_on,
    label,
    plan,
    send_all,
)
from eval.metrics import score
from trace_store.models import SpanNode, TraceSummary

T0 = datetime(2026, 11, 14, 10, tzinfo=UTC)


def span(name: str, *children: SpanNode, **fields) -> SpanNode:
    return SpanNode(
        span_id=f"s{abs(hash((name, len(children)))) % 10**8:08x}",
        trace_id="t" * 32,
        name=name,
        start_time=T0,
        end_time=T0,
        children=list(children),
        **fields,
    )


def request(*children: SpanNode, **fields) -> SpanNode:
    return span("invoke_agent medas", *children, **fields)


def retrieval(hits: int) -> SpanNode:
    return span("retrieval record_chunks", attributes={"retrieval.hits": hits})


def record_search(hits: int = 5) -> SpanNode:
    return span("execute_tool search_patient_record", retrieval(hits))


HEALTHY_TREE = request(span("chat openai/gpt-4.1-mini"), record_search(), span("chat x"))

FIRING = {
    "empty_retrieval": request(record_search(0)),
    "tool_schema": request(
        span(
            "execute_tool search_patient_record",
            status="error",
            attributes={"error.type": "pydantic_core._pydantic_core.ValidationError"},
        )
    ),
    "truncated_prompt": request(record_search(), attributes={"medas.reply.format": "malformed"}),
    "context_tokens": request(*[record_search() for _ in range(CONTEXT_LOOP_SEARCHES)]),
    "weak_model": request(span(f"chat {WEAK_MODEL}")),
    "upstream_timeout": request(
        span("execute_tool search_medlineplus", status="error", status_message="source timed out")
    ),
}


@pytest.mark.parametrize("fault", sorted(FAULTS))
def test_a_fault_that_fired_labels_its_trace(fault):
    assert kind_of(fault, FIRING[fault]) == fault


@pytest.mark.parametrize("fault", sorted(FAULTS))
def test_a_trace_the_switch_spared_is_healthy(fault):
    assert kind_of(fault, HEALTHY_TREE) == HEALTHY


def test_pubmed_failing_on_its_own_is_not_the_timeout_fault():
    unavailable = request(
        span("execute_tool search_pubmed", status="error", status_message="source unavailable")
    )

    assert kind_of("upstream_timeout", unavailable) == HEALTHY


def test_a_trace_sent_with_no_switch_is_healthy_whatever_it_shows():
    assert kind_of(None, FIRING["tool_schema"]) == HEALTHY


def test_the_full_plan_sends_every_fault_then_the_controls():
    sends = plan()

    assert [s.fault for s in sends[: -len(CONTROL_SETS)]] == [
        fault for fault, entry in FAULTS.items() for _ in entry.input_sets
    ]
    assert all(s.fault is None for s in sends[-len(CONTROL_SETS) :])


def test_only_sends_those_faults_and_control_sends_the_controls_alone():
    assert {s.fault for s in plan(["tool_schema"])} == {"tool_schema"}
    assert {s.fault for s in plan(control=True)} == {None}


def test_the_child_gets_its_switch_and_none_of_this_processs_settings(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "tracescans-own")
    monkeypatch.setenv("FAULT_TOOL_SCHEMA", "1")
    monkeypatch.setenv("PATH", "/usr/bin")

    env = child_environment(Send("weak_model", InputSet(ids=("N01",))))

    assert env["PATH"] == "/usr/bin"
    assert env["FAULT_WEAK_MODEL"] == WEAK_MODEL
    assert "OPENROUTER_API_KEY" not in env and "FAULT_TOOL_SCHEMA" not in env


@pytest.mark.parametrize(
    ("output", "on"),
    [
        ("Faults on: none\nSending 2 questions", set()),
        ("Faults on: tool_schema\nN01  normal  answered  3.0 s", {"tool_schema"}),
    ],
)
def test_the_generator_says_which_switches_were_on(output, on):
    assert faults_on(output) == on


@pytest.mark.anyio
async def test_a_send_that_ran_with_other_switches_stops_the_run():
    async def sender(send):
        return "Faults on: tool_schema, weak_model"

    with pytest.raises(TrafficMismatch):
        await send_all([Send("tool_schema", InputSet(ids=("N01",)))], sender)


@pytest.mark.anyio
async def test_every_send_is_timed_in_order():
    sends = [Send("tool_schema", InputSet(ids=("N01",))), Send(None, InputSet(ids=("N02",)))]

    async def sender(send):
        return f"Faults on: {send.fault or 'none'}"

    sent = await send_all(sends, sender)

    assert [s.send for s in sent] == sends
    assert sent[0].started <= sent[0].ended <= sent[1].started <= sent[1].ended


def summary(trace_id: str, start: datetime) -> TraceSummary:
    return TraceSummary(
        trace_id=trace_id,
        app="medas",
        start_time=start,
        duration_ms=1.0,
        status="unset",
        signature="invoke_agent medas",
    )


def sent(fault: str | None, ids: tuple[str, ...], minute: int) -> Sent:
    start = T0 + timedelta(minutes=minute)
    return Sent(Send(fault, InputSet(ids=ids)), start, start + timedelta(minutes=1))


def at(minute: int, second: int = 30) -> datetime:
    return T0 + timedelta(minutes=minute, seconds=second)


def test_each_trace_goes_to_the_send_whose_run_holds_it():
    first, second = sent("tool_schema", ("N01", "N02"), 0), sent(None, ("N03",), 1)
    summaries = [summary("a", at(0, 5)), summary("b", at(0, 50)), summary("c", at(1))]

    assigned = assign(summaries, [first, second])

    assert assigned == {"a": first, "b": first, "c": second}


def test_a_trace_no_send_made_stops_the_run():
    with pytest.raises(TrafficMismatch, match="stray"):
        assign([summary("stray", at(5))], [sent(None, ("N01",), 0)])


def test_a_send_missing_traces_stops_the_run():
    with pytest.raises(TrafficMismatch, match="1 traces for 2 questions"):
        assign([summary("a", at(0))], [sent(None, ("N01", "N02"), 0)])


@pytest.mark.anyio
async def test_the_answer_key_labels_each_trace_from_its_tree():
    schema = sent("tool_schema", ("N01", "N02"), 0)
    trees = {"fired": FIRING["tool_schema"], "spared": HEALTHY_TREE}

    async def tree_of(trace_id):
        return trees[trace_id]

    kinds = await label({"fired": schema, "spared": schema}, tree_of)

    assert kinds == {"fired": "tool_schema", "spared": HEALTHY}


@pytest.mark.anyio
async def test_a_trace_that_is_not_whole_stops_the_run():
    async def tree_of(trace_id):
        return None

    with pytest.raises(TrafficMismatch):
        await label({"a": sent(None, ("N01",), 0)}, tree_of)


def test_a_medas_env_file_that_turns_a_switch_on_is_refused(tmp_path):
    api = tmp_path / "medas-api"
    api.mkdir()
    (api / "faults.py").write_text("")
    (api / ".env").write_text("OPENROUTER_API_KEY=x\nFAULT_TOOL_SCHEMA=1\n")

    with pytest.raises(SystemExit):
        medas_run.check_medas(tmp_path)


def test_a_medas_results_file_is_scored_against_the_medas_faults():
    result = {
        "answer_key": "medas",
        "kinds": {"v1": "tool_schema", "v2": "tool_schema", "h1": HEALTHY},
        "failing_spans": {"v1": "s1", "v2": "s2"},
        "clusters": [{"cluster_id": "c0", "trace_ids": ["v1", "v2"]}],
        "diagnoses": [
            {
                "cluster_id": "c0",
                "category": "tool_schema_error",
                "evidence_check": "valid",
                "evidence": [{"trace_id": "v1", "span_id": "s1"}],
            }
        ],
        "model_usage": [],
        "seconds": 1.0,
    }

    scores = score(result)

    assert scores["detection"] == (1, 1)
    assert scores["category_accuracy"] == (1, 1)
    assert scores["false_alarms"] == 0


def test_a_reply_without_its_triage_code_is_the_truncated_prompt_too():
    tree = request(record_search(), attributes={"medas.reply.format": "no_severity"})

    assert kind_of("truncated_prompt", tree) == "truncated_prompt"


def test_a_results_files_sends_read_back_as_they_were_sent():
    each = sent("upstream_timeout", ("N07", "N11"), 3)

    assert medas_run.sent_from([each.record(4)]) == [each]


@pytest.mark.anyio
async def test_a_retriage_keeps_the_files_traces_answer_key_and_sends(monkeypatch):
    earlier = {
        "since": T0.isoformat(),
        "until": (T0 + timedelta(minutes=5)).isoformat(),
        "kinds": {"a": "tool_schema", "b": HEALTHY},
        "control": False,
        "sent": [sent("tool_schema", ("N01", "N02"), 0).record(2)],
        "clusters": [{"cluster_id": "old"}],
    }
    asked = []

    async def triage(since, until, kinds, url):
        asked.append((since, until, kinds))
        return {"answer_key": "medas", "kinds": kinds, "clusters": []}

    monkeypatch.setattr(medas_run, "triage", triage)

    again = await medas_run.retriage(earlier, "postgresql://unused")

    assert asked == [(T0, T0 + timedelta(minutes=5), earlier["kinds"])]
    assert again["sent"] == earlier["sent"] and again["clusters"] == []
