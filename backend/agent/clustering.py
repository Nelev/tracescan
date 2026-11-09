"""
Group failed traces into clusters. Pure and synchronous: no LangGraph, no LLM calls.

Two stages. HDBSCAN on embeddings of the failure texts finds the dense groups and leaves isolated
failures as noise. Then the noise is regrouped by failing step and error type, and a group that is
big enough becomes a cluster. The second stage matters because HDBSCAN cannot see a single dense
group (it labels the whole group noise), and one fault often causes most of a run's failures. With
too few traces for HDBSCAN, every trace goes straight to the second stage and every group counts,
because with so little data nothing can be called noise.
"""

import re
from collections import Counter, defaultdict
from importlib import import_module

import numpy as np

from agent.const import MAX_EXEMPLARS, MIN_CLUSTER_SIZE, MIN_SAMPLES, MIN_TRACES_FOR_HDBSCAN
from agent.embeddings import Embedder
from agent.schemas import Cluster, ClusterMethod
from trace_store.models import TraceSummary

# Not `from sklearn.cluster import HDBSCAN`: scikit-learn ships no type information, and Pylance's
# bundled sklearn stubs predate HDBSCAN (added in scikit-learn 1.3), so they flag that import.
HDBSCAN = import_module("sklearn.cluster").HDBSCAN

UNKNOWN_STEP = "unknown step"
_QUOTED = re.compile(r"'[^']*'|\"[^\"]*\"")
_DIGITS = re.compile(r"\d+")


def failure_text(summary: TraceSummary) -> str:
    """One short string per failure: failing step, error and signature.

    Uses only fields already on TraceSummary. Scores and timings are left out and digits in the
    error and signature are masked, so values that differ between traces do not split one cause.
    """
    step = summary.failing_span_name or UNKNOWN_STEP
    error = summary.error_message or "no error message"
    tail = _DIGITS.sub("#", f"{error} | {summary.signature}")
    return f"{step}: {tail}"


def normalise_error(message: str | None) -> str:
    """Mask quoted values and numbers so 'missing x' and 'missing y' count as one error type."""
    text = _DIGITS.sub("#", _QUOTED.sub("'x'", (message or "").lower()))
    return " ".join(text.split())


def _step_and_error(summary: TraceSummary) -> tuple[str, str]:
    return summary.failing_span_name or UNKNOWN_STEP, normalise_error(summary.error_message)


def _hdbscan_labels(summaries: list[TraceSummary], embedder: Embedder) -> np.ndarray:
    """One label per trace, -1 for noise."""
    vectors = embedder.embed([failure_text(s) for s in summaries])
    # Cosine distance, so the embedder does not have to return unit vectors. copy=True only
    # silences a FutureWarning about the default changing in scikit-learn 1.10.
    return HDBSCAN(
        min_cluster_size=MIN_CLUSTER_SIZE, min_samples=MIN_SAMPLES, metric="cosine", copy=True
    ).fit_predict(vectors)


def _signature(members: list[TraceSummary]) -> str:
    """The most common failing step and normalised error among the traces (ties alphabetical)."""
    keys = Counter(_step_and_error(s) for s in members)
    step, error = min(keys, key=lambda key: (-keys[key], key))
    return f"{step}: {error}"


def _cluster(cluster_id: str, members: list[TraceSummary], method: ClusterMethod) -> Cluster:
    newest = sorted(members, key=lambda s: (s.start_time, s.trace_id), reverse=True)
    return Cluster(
        cluster_id=cluster_id,
        trace_ids=sorted(s.trace_id for s in members),
        signature=_signature(members),
        exemplar_trace_ids=[s.trace_id for s in newest[:MAX_EXEMPLARS]],
        method=method,
    )


def cluster_summaries(
    summaries: list[TraceSummary], embedder: Embedder
) -> tuple[list[Cluster], list[str]]:
    """Return (clusters, unclustered trace ids)."""
    small = len(summaries) < MIN_TRACES_FOR_HDBSCAN  # too few for HDBSCAN: nothing is noise
    labels = np.full(len(summaries), -1) if small else _hdbscan_labels(summaries, embedder)
    min_size = 1 if small else MIN_CLUSTER_SIZE

    by_label: dict[int, list[TraceSummary]] = defaultdict(list)
    for s, label in zip(summaries, labels, strict=True):
        by_label[int(label)].append(s)
    noise = by_label.pop(-1, [])
    groups: list[tuple[list[TraceSummary], ClusterMethod]] = [
        (members, "hdbscan") for members in by_label.values()
    ]

    # Second stage: noise that shares a failing step and error is still a cluster if big enough.
    by_step_error: dict[tuple[str, str], list[TraceSummary]] = defaultdict(list)
    for s in noise:
        by_step_error[_step_and_error(s)].append(s)
    unclustered: list[str] = []
    for members in by_step_error.values():
        if len(members) >= min_size:
            groups.append((members, "step_error"))
        else:
            unclustered.extend(s.trace_id for s in members)

    # Biggest first; the lowest trace id makes the order independent of the input order.
    groups.sort(key=lambda g: (-len(g[0]), _signature(g[0]), min(s.trace_id for s in g[0])))
    clusters = [_cluster(f"c{i}", members, method) for i, (members, method) in enumerate(groups)]
    return clusters, sorted(unclustered)
