"""The local writes of apply_actions: issues as markdown files (a dry run), regression cases as JSONL.

Plain functions over a directory: no LangGraph and no model call, so they are testable offline.
A dry run writes these files and nothing else; a real run opens GitHub issues (agent.github) and
appends the same regression cases. The issue text is the diagnoser's own prose, which
a human approved before it got here; it stays on local disk and is never logged.
"""

import json
import re
from pathlib import Path

from agent.schemas import Proposal

# The layout of a dry run's output. OUT_DIR is relative to the working directory: backend/out when
# the app runs from backend/. Gitignored.
OUT_DIR = Path("out")
ISSUES_DIR = "issues"
REGRESSION_FILE = "regression_cases.jsonl"

# A cluster id becomes a file name, so it may not hold a path separator or a dot.
_SAFE_ID = re.compile(r"[A-Za-z0-9_-]+")


def _written(path: Path, run_id: str) -> set[str]:
    """The cluster ids whose case `run_id` already appended to the file."""
    if not path.exists():
        return set()
    lines = (json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line)
    return {case["cluster_id"] for case in lines if case.get("run_id") == run_id}


def append_regression_cases(
    proposals: list[Proposal], out_dir: Path, run_id: str | None = None
) -> list[str]:
    """Append the regression case of each proposal that has one to `regression_cases.jsonl`, in
    one append, stamped with `run_id`; return the log lines. A proposal without one (never
    diagnosed) adds nothing, and neither does a case this run already appended, so an apply that
    runs again (a resumed run) does not repeat it. Without a run id nothing is skipped."""
    cases = {p.cluster_id: p.regression_case for p in proposals if p.regression_case is not None}
    path = out_dir / REGRESSION_FILE
    if run_id is not None:
        done = _written(path, run_id)
        cases = {c: case for c, case in cases.items() if c not in done}
    if not cases:
        return []
    out_dir.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as file:
        file.writelines(
            case.model_copy(update={"run_id": run_id}).model_dump_json() + "\n"
            for case in cases.values()
        )
    return [f"appended the regression case of {c} to {REGRESSION_FILE}" for c in cases]


def write_dry_run(proposals: list[Proposal], out_dir: Path, run_id: str | None = None) -> list[str]:
    """Write each proposal's issue and regression case under `out_dir`; return the actions log.

    An issue goes to `issues/<cluster_id>.md`, replacing that file if an earlier run wrote it. A
    regression case is appended as one line to `regression_cases.jsonl`; a proposal without one
    (a cluster that was never diagnosed) writes its issue only. The log names paths relative to
    `out_dir`. Raises ValueError before writing anything when a cluster id is not a safe file name.
    """
    for proposal in proposals:
        if not _SAFE_ID.fullmatch(proposal.cluster_id):
            raise ValueError("a cluster id is not safe as a file name")
    if not proposals:
        return []
    issues = out_dir / ISSUES_DIR
    issues.mkdir(parents=True, exist_ok=True)
    log = []
    for proposal in proposals:
        issue = issues / f"{proposal.cluster_id}.md"
        issue.write_text(f"# {proposal.title}\n\n{proposal.body}", encoding="utf-8")
        log.append(f"[dry-run] wrote {ISSUES_DIR}/{issue.name}")
    # One append for the run, after its issues.
    appended = append_regression_cases(proposals, out_dir, run_id)
    return log + [f"[dry-run] {line}" for line in appended]
