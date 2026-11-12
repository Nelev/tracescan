"""The GitHub writer of apply_actions: one issue per approved proposal, through githubkit.

The repo and the token come from the server's environment (GITHUB_REPO, GITHUB_TOKEN), never from
a request. The issue text is the diagnoser's prose, which may hold clinical text, so the repo must
be private (`check`, at startup) and nothing here logs a title, a body or a response.

Responses are read as plain JSON (`.json()`, typed but not validated), not as githubkit's
`parsed_data`, which checks every field of GitHub's schema: only `private`, `html_url` and `body` are
read, so a field GitHub adds or drops elsewhere changes nothing here, and a test fake stays small.

A retry never opens an issue twice: each body ends with a hidden marker naming the run and the
cluster, and the issues already labelled `tracescan` are read first, so a review resubmitted after
a failure opens only the issues still missing.
"""

import os

import httpx2
from githubkit import GitHub

from agent.schemas import Proposal

LABEL = "tracescan"


def marker(run_id: str, cluster_id: str) -> str:
    """The hidden line that ties an issue to its run and cluster."""
    return f"<!-- tracescan run={run_id} cluster={cluster_id} -->"


class GitHubIssues:
    def __init__(
        self, repo: str, token: str, transport: httpx2.AsyncBaseTransport | None = None
    ) -> None:
        owner, _, name = repo.partition("/")
        if not owner or not name or "/" in name:
            raise ValueError("GITHUB_REPO must be owner/name")
        self._owner, self._name = owner, name
        # No HTTP cache: a cached issue list could miss an issue this process just opened.
        self._github = GitHub(token, http_cache=False, async_transport=transport)

    async def check(self) -> None:
        """Refuse a public repo: the issue body may hold clinical text."""
        repo = (await self._github.rest.repos.async_get(self._owner, self._name)).json()
        if not repo["private"]:
            raise RuntimeError("GITHUB_REPO must be a private repository")

    async def _opened(self, wanted: set[str]) -> dict[str, str]:
        """Which of the `wanted` markers an issue already holds, each with its issue's URL."""
        found = {}
        async for issue in self._github.rest.paginate(
            self._github.rest.issues.async_list_for_repo,
            map_func=lambda response: response.json(),
            owner=self._owner,
            repo=self._name,
            labels=LABEL,
            state="all",
            per_page=100,
        ):
            for line in (issue.get("body") or "").splitlines():
                if line in wanted:
                    found[line] = issue["html_url"]
        return found

    async def open_issues(self, run_id: str, proposals: list[Proposal]) -> list[str]:
        """Open one issue per proposal, skipping those this run already opened; return the log."""
        if not proposals:
            return []
        tags = {p.cluster_id: marker(run_id, p.cluster_id) for p in proposals}
        log = []
        async with self._github:  # one connection pool for the whole batch
            opened = await self._opened(set(tags.values()))
            for proposal in proposals:  # one at a time: GitHub limits how fast content is made
                tag = tags[proposal.cluster_id]
                if tag in opened:
                    log.append(f"issue for {proposal.cluster_id} already open: {opened[tag]}")
                    continue
                issue = (
                    await self._github.rest.issues.async_create(
                        self._owner,
                        self._name,
                        title=proposal.title,
                        body=f"{proposal.body}\n{tag}\n",
                        labels=[LABEL],
                    )
                ).json()
                log.append(f"opened issue for {proposal.cluster_id}: {issue['html_url']}")
        return log


def github_from_env() -> GitHubIssues | None:
    """The writer named by GITHUB_REPO and GITHUB_TOKEN, or None when neither is set."""
    repo, token = os.environ.get("GITHUB_REPO"), os.environ.get("GITHUB_TOKEN")
    if not repo and not token:
        return None
    if not repo or not token:
        raise ValueError("set both GITHUB_REPO and GITHUB_TOKEN, or neither")
    return GitHubIssues(repo, token)
