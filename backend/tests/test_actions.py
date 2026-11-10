"""The dry-run writer and the apply_actions node, on a temporary directory."""

import json
from dataclasses import replace
from pathlib import Path

import pytest
from langgraph.runtime import Runtime

from agent.actions import REGRESSION_FILE, require_dry_run, write_dry_run
from agent.nodes.apply_actions import apply_actions
from agent.schemas import Proposal, RegressionCase
from tests.fakes import FakeTraces, fake_context, files_under


def proposal(cluster_id: str = "c0", *, diagnosed: bool = True) -> Proposal:
    case = None
    if diagnosed:
        case = RegressionCase(
            cluster_id=cluster_id,
            signature="retrieve: empty result",
            category="retrieval_miss",
            exemplar_trace_ids=["tr_1"],
            failing_spans=[{"trace_id": "tr_1", "span_id": "tr_1_root"}],
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


def test_only_a_dry_run_is_allowed_until_the_real_writers_exist():
    require_dry_run(True)
    with pytest.raises(NotImplementedError):
        require_dry_run(False)


def runtime(tmp_path: Path, *, dry_run: bool = True) -> Runtime:
    context = replace(fake_context(FakeTraces()), dry_run=dry_run, out_dir=tmp_path)
    return Runtime(context=context)


def state(decisions: dict) -> dict:
    proposals = [proposal("c0"), proposal("c1")]
    return {
        "target_app": "medas",
        "proposals": [p.model_dump(mode="json") for p in proposals],
        "decisions": decisions,
    }


def test_the_node_writes_only_the_approved_proposals(tmp_path):
    result = apply_actions(state({"c0": "reject", "c1": "approve"}), runtime(tmp_path))
    assert files_under(tmp_path) == ["issues/c1.md", REGRESSION_FILE]
    assert result["actions_log"][0] == "[dry-run] wrote issues/c1.md"


def test_the_node_refuses_to_run_with_dry_run_off_and_writes_nothing(tmp_path):
    with pytest.raises(NotImplementedError):
        apply_actions(state({"c0": "approve", "c1": "approve"}), runtime(tmp_path, dry_run=False))
    assert files_under(tmp_path) == []
