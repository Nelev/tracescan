"""The GitHub writer (agent.github) and apply_actions with dry run off, against a fake GitHub.

The fake answers githubkit through httpx2's MockTransport, so no test reaches the network.
"""

import json

import httpx2
import pytest
from githubkit.exception import RequestFailed

from agent.actions import REGRESSION_FILE
from agent.github import LABEL, GitHubIssues, github_from_env, marker
from agent.nodes.apply_actions import apply_actions
from tests.test_actions import proposal, runtime, state

REPO = "acme/triage-test"


class FakeGitHub:
    """One repo's issues, kept in memory. `fail_on` makes that create (1-based) answer 422."""

    def __init__(self, *, private: bool = True, fail_on: int | None = None) -> None:
        self.private = private
        self.fail_on = fail_on
        self.issues: list[dict] = []
        self.creates = 0

    def handle(self, request: httpx2.Request) -> httpx2.Response:
        path = request.url.path
        if request.method == "GET" and path == f"/repos/{REPO}":
            return httpx2.Response(200, json={"private": self.private})
        if path == f"/repos/{REPO}/issues" and request.method == "GET":
            label = request.url.params.get("labels")
            return httpx2.Response(200, json=[i for i in self.issues if label in i["labels"]])
        if path == f"/repos/{REPO}/issues" and request.method == "POST":
            self.creates += 1
            if self.creates == self.fail_on:
                return httpx2.Response(422, json={"message": "Validation Failed"})
            sent = json.loads(request.content)
            number = len(self.issues) + 1
            issue = {
                "number": number,
                "html_url": f"https://github.com/{REPO}/issues/{number}",
                "title": sent["title"],
                "body": sent["body"],
                "labels": sent["labels"],
            }
            self.issues.append(issue)
            return httpx2.Response(201, json=issue)
        return httpx2.Response(404, json={"message": "Not Found"})

    def client(self) -> GitHubIssues:
        return GitHubIssues(REPO, "token", httpx2.MockTransport(self.handle))


@pytest.mark.anyio
async def test_check_accepts_a_private_repo_and_refuses_a_public_one():
    await FakeGitHub().client().check()
    with pytest.raises(RuntimeError):
        await FakeGitHub(private=False).client().check()


def test_the_writer_comes_from_both_variables_or_neither(monkeypatch):
    monkeypatch.delenv("GITHUB_REPO", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    assert github_from_env() is None
    monkeypatch.setenv("GITHUB_REPO", REPO)
    with pytest.raises(ValueError):
        github_from_env()
    monkeypatch.setenv("GITHUB_TOKEN", "token")
    assert isinstance(github_from_env(), GitHubIssues)


@pytest.mark.parametrize("repo", ["acme", "acme/", "/repo", "a/b/c"])
def test_a_repo_that_is_not_owner_slash_name_is_refused(repo):
    with pytest.raises(ValueError):
        GitHubIssues(repo, "token")


@pytest.mark.anyio
async def test_one_issue_is_opened_per_proposal_with_the_label_and_the_marker():
    github = FakeGitHub()
    log = await github.client().open_issues("run-1", [proposal("c0"), proposal("c1")])

    assert [i["title"] for i in github.issues] == ["[retrieval_miss] c0", "[retrieval_miss] c1"]
    assert all(i["labels"] == [LABEL] for i in github.issues)
    assert github.issues[0]["body"].startswith("## Summary")
    assert marker("run-1", "c0") in github.issues[0]["body"]
    assert log == [
        f"opened issue for c0: https://github.com/{REPO}/issues/1",
        f"opened issue for c1: https://github.com/{REPO}/issues/2",
    ]


@pytest.mark.anyio
async def test_a_retry_after_a_failure_opens_only_the_missing_issues():
    github = FakeGitHub(fail_on=2)
    proposals = [proposal("c0"), proposal("c1"), proposal("c2")]
    with pytest.raises(RequestFailed):
        await github.client().open_issues("run-1", proposals)
    assert len(github.issues) == 1

    log = await github.client().open_issues("run-1", proposals)

    assert [i["title"][-2:] for i in github.issues] == ["c0", "c1", "c2"]
    assert log[0] == f"issue for c0 already open: https://github.com/{REPO}/issues/1"


@pytest.mark.anyio
async def test_another_run_opens_its_own_issue_for_the_same_cluster():
    github = FakeGitHub()
    await github.client().open_issues("run-1", [proposal("c0")])
    await github.client().open_issues("run-2", [proposal("c0")])
    assert len(github.issues) == 2


@pytest.mark.anyio
async def test_a_real_run_opens_the_approved_issues_and_appends_their_regression_cases(tmp_path):
    github = FakeGitHub()
    run = runtime(tmp_path, dry_run=False, github=github.client())

    result = await apply_actions(state({"c0": "reject", "c1": "approve"}), run)

    assert [i["title"] for i in github.issues] == ["[retrieval_miss] c1"]
    assert marker("run-1", "c1") in github.issues[0]["body"]
    assert not (tmp_path / "issues").exists()  # no local issue files in a real run
    [line] = (tmp_path / REGRESSION_FILE).read_text().splitlines()
    assert json.loads(line)["cluster_id"] == "c1"
    assert result["actions_log"] == [
        f"opened issue for c1: https://github.com/{REPO}/issues/1",
        f"appended the regression case of c1 to {REGRESSION_FILE}",
    ]
