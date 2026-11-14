"""The dry-run writer and the apply_actions node, on a temporary directory. The GitHub writer
has its own tests (test_github.py)."""

import json
from dataclasses import replace
from pathlib import Path

import pytest
from langgraph.runtime import ExecutionInfo, Runtime

from agent.actions import REGRESSION_FILE, write_dry_run
from agent.context import TraceContext
from agent.nodes.apply_actions import apply_actions
from agent.schemas import Proposal, RegressionCase, SpanRef
from agent.state import TriageState
from tests.fakes import FakeKnownIssues, FakeTraces, fake_context, files_under


def proposal(cluster_id: str = "c0", *, diagnosed: bool = True) -> Proposal:
    case = None
    if diagnosed:
        case = RegressionCase(
            cluster_id=cluster_id,
            signature="retrieve: empty result",
            category="retrieval_miss",
            exemplar_trace_ids=["tr_1"],
            failing_spans=[SpanRef(trace_id="tr_1", span_id="tr_1_root")],
        )
    return Proposal(
        cluster_id=cluster_id,
        title=f"[retrieval_miss] {cluster_id}",
        body="## Summary\n\nThe retriever returned nothing.\n",
        diagnosed=diagnosed,
        regression_case=case,
    )


def test_a_dry_run_writes_the_issue_and_the_regression_case_and_nothing_else(tmp_path):
    log = write_dry_run([proposal("c0")], tmp_path)

    assert files_under(tmp_path) == ["issues/c0.md", REGRESSION_FILE]
    issue = (tmp_path / "issues" / "c0.md").read_text()
    assert issue.startswith("# [retrieval_miss] c0\n\n## Summary")
    [line] = (tmp_path / REGRESSION_FILE).read_text().splitlines()
    assert RegressionCase.model_validate_json(line) == proposal("c0").regression_case
    assert log == [
        "[dry-run] wrote issues/c0.md",
        f"[dry-run] appended the regression case of c0 to {REGRESSION_FILE}",
    ]
    assert str(tmp_path) not in "".join(log)  # paths in the log are relative


def test_an_undiagnosed_proposal_writes_its_issue_but_no_regression_case(tmp_path):
    log = write_dry_run([proposal("c1", diagnosed=False)], tmp_path)
    assert files_under(tmp_path) == ["issues/c1.md"]
    assert log == ["[dry-run] wrote issues/c1.md"]


def test_regression_cases_are_appended_one_line_each(tmp_path):
    write_dry_run([proposal("c0"), proposal("c1")], tmp_path)
    write_dry_run([proposal("c2")], tmp_path)
    lines = (tmp_path / REGRESSION_FILE).read_text().splitlines()
    assert [json.loads(line)["cluster_id"] for line in lines] == ["c0", "c1", "c2"]


def test_an_apply_that_runs_again_does_not_repeat_its_regression_cases(tmp_path):
    # A resumed run applies its review again: the issue is rewritten, its case is not appended twice.
    first = write_dry_run([proposal("c0")], tmp_path, "run-1")
    again = write_dry_run([proposal("c0"), proposal("c1")], tmp_path, "run-1")
    other = write_dry_run([proposal("c0")], tmp_path, "run-2")  # another run's c0 is its own
    lines = [json.loads(line) for line in (tmp_path / REGRESSION_FILE).read_text().splitlines()]
    assert [(c["run_id"], c["cluster_id"]) for c in lines] == [
        ("run-1", "c0"),
        ("run-1", "c1"),
        ("run-2", "c0"),
    ]
    assert len(first) == len(other) == 2 and again[-1].endswith(f"c1 to {REGRESSION_FILE}")
    assert not any(f"c0 to {REGRESSION_FILE}" in line for line in again)


def test_nothing_to_write_creates_nothing(tmp_path):
    assert write_dry_run([], tmp_path) == []
    assert files_under(tmp_path) == []


@pytest.mark.parametrize("cluster_id", ["../escape", "a/b", "c0.md", ""])
def test_a_cluster_id_that_is_not_a_safe_file_name_is_refused_before_any_write(
    tmp_path, cluster_id
):
    out = tmp_path / "out"
    with pytest.raises(ValueError):
        write_dry_run([proposal("c0"), proposal(cluster_id)], out)
    assert files_under(tmp_path) == []  # nothing in the directory, and nothing escaped it


def runtime(tmp_path: Path, *, dry_run: bool = True, **context) -> Runtime[TraceContext]:
    """A node's runtime on thread `run-1`, the way a run with a checkpointer gives it."""
    run = replace(fake_context(FakeTraces()), dry_run=dry_run, out_dir=tmp_path, **context)
    info = ExecutionInfo(checkpoint_id="", checkpoint_ns="", task_id="", thread_id="run-1")
    return Runtime(context=run, execution_info=info)


def state(decisions: dict) -> TriageState:
    proposals = [proposal("c0"), proposal("c1")]
    return {
        "target_app": "medas",
        "proposals": [p.model_dump(mode="json") for p in proposals],
        "decisions": decisions,
    }


@pytest.mark.anyio
async def test_the_node_writes_only_the_approved_proposals(tmp_path):
    result = await apply_actions(state({"c0": "reject", "c1": "approve"}), runtime(tmp_path))
    assert files_under(tmp_path) == ["issues/c1.md", REGRESSION_FILE]
    assert result["actions_log"][0] == "[dry-run] wrote issues/c1.md"


@pytest.mark.anyio
async def test_the_node_refuses_dry_run_off_without_github_and_writes_nothing(tmp_path):
    with pytest.raises(RuntimeError):
        await apply_actions(
            state({"c0": "approve", "c1": "approve"}), runtime(tmp_path, dry_run=False)
        )
    assert files_under(tmp_path) == []


def reviewed(decisions: dict) -> TriageState:
    """state() plus the clusters and diagnoses the memory is built from."""
    clusters = [
        {
            "cluster_id": c,
            "trace_ids": ["tr_1"],
            "signature": "retrieve: empty result",
            "exemplar_trace_ids": ["tr_1"],
            "method": "step_error",
        }
        for c in ("c0", "c1")
    ]
    diagnoses = [
        {
            "cluster_id": c,
            "category": "retrieval_miss",
            "root_cause": f"cause of {c}",
            "suggested_fix": "fix it",
            "failing_step": "step: retrieve",
        }
        for c in ("c0", "c1")
    ]
    return {**state(decisions), "clusters": clusters, "diagnoses": diagnoses}  # type: ignore[typeddict-item]


@pytest.mark.anyio
async def test_the_node_remembers_approved_and_rejected_diagnoses_under_the_run(tmp_path):
    memory = FakeKnownIssues()
    result = await apply_actions(
        reviewed({"c0": "reject", "c1": "approve"}), runtime(tmp_path, known_issues=memory)
    )
    assert {key: m["verdict"] for key, m in memory.saved.items()} == {
        ("medas", "run-1", "c0"): "rejected",
        ("medas", "run-1", "c1"): "approved",
    }
    assert result["actions_log"][-1] == "remembered 2 decided diagnosis(es) for later runs"
    assert files_under(tmp_path) == ["issues/c1.md", REGRESSION_FILE]  # only approved ones written


@pytest.mark.anyio
async def test_all_rejected_writes_no_issue_but_is_remembered(tmp_path):
    memory = FakeKnownIssues()
    await apply_actions(
        reviewed({"c0": "reject", "c1": "reject"}), runtime(tmp_path, known_issues=memory)
    )
    assert files_under(tmp_path) == []
    assert len(memory.saved) == 2


@pytest.mark.anyio
async def test_a_decided_diagnosis_reaches_the_next_runs_diagnoser(tmp_path):
    """The memory end to end: what one run's apply_actions saves, the next run's diagnoser sees."""
    from agent.nodes.diagnose_cluster import known_issues_section

    memory = FakeKnownIssues()
    await apply_actions(
        reviewed({"c0": "approve", "c1": "reject"}), runtime(tmp_path, known_issues=memory)
    )
    task = {"cluster": {"cluster_id": "c7"}, "target_app": "medas", "failing_span": None}
    context = replace(fake_context(FakeTraces()), known_issues=memory)
    section, shown = await known_issues_section(task, "step: retrieve", context)  # type: ignore[arg-type]
    assert shown == 2
    assert "cause: cause of c0" in section and "cause: cause of c1" in section
