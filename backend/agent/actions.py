"""The dry-run writes of apply_actions: issues as markdown files, regression cases as JSONL.

Plain functions over a directory: no LangGraph and no model call, so they are testable offline.
A dry run writes these files and nothing else. The issue text is the diagnoser's own prose, which
a human approved before it got here; it stays on local disk and is never logged.
"""

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


def require_dry_run(dry_run: bool) -> None:
    """Refuse a run that is not a dry run: the real writers (GitHub, the eval dataset, the
    known-issues store) are not built. The one place that says so; the app checks it at startup
    and apply_actions before it writes. Drop it when they exist."""
    if not dry_run:
        raise NotImplementedError("the real writers are not built yet: run with DRY_RUN on")


def write_dry_run(proposals: list[Proposal], out_dir: Path) -> list[str]:
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
    cases = []
    for proposal in proposals:
        issue = issues / f"{proposal.cluster_id}.md"
        issue.write_text(f"# {proposal.title}\n\n{proposal.body}", encoding="utf-8")
        log.append(f"[dry-run] wrote {ISSUES_DIR}/{issue.name}")
        if proposal.regression_case is not None:
            cases.append(proposal.regression_case.model_dump_json() + "\n")
            log.append(
                f"[dry-run] appended the regression case of {proposal.cluster_id} to {REGRESSION_FILE}"
            )
    if cases:  # one append for the run, after its issues
        with (out_dir / REGRESSION_FILE).open("a", encoding="utf-8") as file:
            file.writelines(cases)
    return log
