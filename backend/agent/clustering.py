"""
Group failed traces into clusters. Pure and synchronous: no LangGraph, no LLM calls.

Two stages. HDBSCAN on embeddings of the failure texts finds the dense groups and leaves isolated
failures as noise. Then the noise is regrouped by failing step and error type, and a group that is
big enough becomes a cluster. The second stage matters because HDBSCAN cannot see a single dense
group (it labels the whole group noise), and one fault often causes most of a run's failures. With
too few traces for HDBSCAN, every trace goes straight to the second stage and every group counts,
because with so little data nothing can be called noise.

The cluster map is a 3D projection of the same embeddings, made once the clusters are final, so
the run page can show where each failure sat and which stage grouped it.
"""

import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from importlib import import_module

import numpy as np

from agent.chunks import bucket_word
from agent.const import (
    LATENCY_BUCKETS_S,
    MAP_SEED,
    MAX_EXEMPLARS,
    MIN_CLUSTER_SIZE,
    MIN_MEMBERSHIP,
    MIN_SAMPLES,
    MIN_TRACES_FOR_HDBSCAN,
    TRUST_NEIGHBORS,
    TSNE_MIN_POINTS,
    TSNE_PERPLEXITY,
)
from agent.embeddings import Embedder
from agent.schemas import Cluster, ClusterMap, ClusterMethod, MapPoint, Projection
from trace_store.models import TraceSummary

# Not `from sklearn.cluster import HDBSCAN`: scikit-learn ships no type information, and Pylance's
# bundled sklearn stubs predate HDBSCAN (added in scikit-learn 1.3), so they flag that import.
HDBSCAN = import_module("sklearn.cluster").HDBSCAN
_manifold = import_module("sklearn.manifold")
PCA = import_module("sklearn.decomposition").PCA

UNKNOWN_STEP = "unknown step"
_QUOTED = re.compile(r"'[^']*'|\"[^\"]*\"")
_DIGITS = re.compile(r"\d+")
_SECONDS = re.compile(r"(\d+(?:\.\d+)?)\s?s\b")


def seconds_as_words(message: str) -> str:
    """'timed out after 1.0s' reads 'timed out after normal (0.5-2 s)': the masking of digits
    would make every duration the same, and a 1 s timeout is not the same fault as a 10 s one."""
    return _SECONDS.sub(lambda m: bucket_word(float(m.group(1)), LATENCY_BUCKETS_S), message)


def failure_text(summary: TraceSummary) -> str:
    """One short string per failure: failing step, error and signature.

    Uses only fields already on TraceSummary. Scores and timings are left out and digits in the
    error and signature are masked, so values that differ between traces do not split one cause;
    seconds in the error are read as a latency word first, so a duration's size still counts.
    """
    step = summary.failing_span_name or UNKNOWN_STEP
    error = seconds_as_words(summary.error_message or "no error message")
    tail = _DIGITS.sub("#", f"{error} | {summary.signature}")
    return f"{step}: {tail}"


def normalise_error(message: str | None) -> str:
    """Mask quoted values and numbers so 'missing x' and 'missing y' count as one error type."""
    text = _DIGITS.sub("#", _QUOTED.sub("'x'", seconds_as_words(message or "").lower()))
    return " ".join(text.split())


def _step_and_error(summary: TraceSummary) -> tuple[str, str]:
    return summary.failing_span_name or UNKNOWN_STEP, normalise_error(summary.error_message)


@dataclass(frozen=True)
class Embedded:
    """What HDBSCAN saw and said, one row per trace in input order."""

    vectors: np.ndarray
    labels: np.ndarray  # -1 for noise, including a member under MIN_MEMBERSHIP
    membership: np.ndarray  # HDBSCAN's probabilities_, 0 for noise


@dataclass(frozen=True)
class Grouping:
    clusters: list[Cluster]
    unclustered: list[str]
    summaries: list[TraceSummary]
    embedded: Embedded | None  # None for a small run, which skips the embedding


def _hdbscan(summaries: list[TraceSummary], embedder: Embedder) -> Embedded:
    vectors = np.asarray(embedder.embed([failure_text(s) for s in summaries]), dtype=float)
    # Cosine distance, so the embedder does not have to return unit vectors. copy=True only
    # silences a FutureWarning about the default changing in scikit-learn 1.10.
    model = HDBSCAN(
        min_cluster_size=MIN_CLUSTER_SIZE, min_samples=MIN_SAMPLES, metric="cosine", copy=True
    ).fit(vectors)
    membership = np.asarray(model.probabilities_)
    labels = np.where(membership < MIN_MEMBERSHIP, -1, np.asarray(model.labels_))
    return Embedded(vectors, labels, membership)


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


def isolated_clusters(
    summaries: list[TraceSummary], trace_ids: list[str], first_index: int
) -> list[Cluster]:
    """One-trace clusters for isolated failures, numbered on from the real clusters."""
    by_id = {s.trace_id: s for s in summaries}
    return [
        _cluster(f"c{first_index + i}", [by_id[trace_id]], "isolated")
        for i, trace_id in enumerate(trace_ids)
    ]


def cluster_summaries(
    summaries: list[TraceSummary], embedder: Embedder
) -> tuple[list[Cluster], list[str]]:
    """Return (clusters, unclustered trace ids)."""
    grouping = group_failures(summaries, embedder)
    return grouping.clusters, grouping.unclustered


def group_failures(summaries: list[TraceSummary], embedder: Embedder) -> Grouping:
    """The clusters and unclustered ids, plus what HDBSCAN saw, for the cluster map."""
    small = len(summaries) < MIN_TRACES_FOR_HDBSCAN  # too few for HDBSCAN: nothing is noise
    embedded = None if small else _hdbscan(summaries, embedder)
    labels = np.full(len(summaries), -1) if embedded is None else embedded.labels
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
    return Grouping(clusters, sorted(unclustered), summaries, embedded)


def _unit(vectors: np.ndarray) -> np.ndarray:
    """Rows scaled to length 1, so Euclidean distance orders points as cosine distance does."""
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    return vectors / np.where(norms == 0, 1, norms)


def _trust(vectors: np.ndarray, coords: np.ndarray) -> float | None:
    neighbors = min(TRUST_NEIGHBORS, (len(vectors) - 1) // 2)
    if neighbors < 1:
        return None
    value = _manifold.trustworthiness(vectors, coords, n_neighbors=neighbors)
    return round(float(value), 3)


def _scaled(coords: np.ndarray) -> np.ndarray:
    coords = coords - coords.mean(axis=0)
    scale = np.abs(coords).max()
    return coords / scale if scale > 0 else coords


def _pca(unit: np.ndarray) -> np.ndarray:
    n = len(unit)
    components = min(3, n, unit.shape[1])
    coords = np.zeros((n, 3))
    if n > 1:
        # "full": exact and deterministic. For wide data "auto" picks randomized SVD, unseeded.
        coords[:, :components] = PCA(n_components=components, svd_solver="full").fit_transform(unit)
    return coords


def _tsne(unit: np.ndarray) -> np.ndarray:
    perplexity = min(TSNE_PERPLEXITY, (len(unit) - 1) / 3)
    return _manifold.TSNE(
        n_components=3, perplexity=perplexity, init="pca", random_state=MAP_SEED
    ).fit_transform(unit)


def project(vectors: np.ndarray) -> tuple[np.ndarray, Projection, float | None]:
    """Distinct embeddings to 3D: (coordinates in [-1, 1], method, trustworthiness).

    PCA always; from TSNE_MIN_POINTS on, t-SNE (seeded) too, and the map keeps whichever kept
    near neighbours near more faithfully (PCA on a tie). On few points t-SNE is unstable, and on
    clearly separated groups PCA often wins outright. Fewer than three points, or points that
    span fewer than three directions, leave the missing axes at 0.
    """
    unit = _unit(vectors)
    candidates: list[tuple[Projection, np.ndarray]] = [("pca", _pca(unit))]
    if len(unit) >= TSNE_MIN_POINTS:
        candidates.append(("tsne", _tsne(unit)))
    scored: list[tuple[Projection, np.ndarray, float | None]] = [
        (method, coords, _trust(unit, coords)) for method, coords in candidates
    ]
    method, coords, trust = max(scored, key=lambda c: -1.0 if c[2] is None else c[2])
    return _scaled(coords), method, trust


def cluster_map(grouping: Grouping, clusters: list[Cluster]) -> ClusterMap | None:
    """Where each failure sat in the embedding space, by final cluster; None without embeddings.

    `clusters` are the final ones, isolated ones included. Traces with the same embedding become
    one point per cluster they landed in (masked digits make many failure texts identical).
    """
    embedded = grouping.embedded
    if embedded is None:
        return None
    distinct, row_of = np.unique(embedded.vectors, axis=0, return_inverse=True)
    row_of = np.asarray(row_of).reshape(-1)
    coords, projection, trust = project(distinct)
    placed = {t: c for c in clusters for t in c["trace_ids"]}

    points: dict[tuple[int, str], list[int]] = defaultdict(list)
    for i, s in enumerate(grouping.summaries):
        points[(int(row_of[i]), placed[s.trace_id]["cluster_id"])].append(i)
    out = []
    for (row, cluster_id), members in points.items():
        first = members[0]
        x, y, z = (round(float(v), 4) for v in coords[row])
        out.append(
            MapPoint(
                trace_ids=sorted(grouping.summaries[i].trace_id for i in members),
                x=x,
                y=y,
                z=z,
                cluster_id=cluster_id,
                stage=placed[grouping.summaries[first].trace_id]["method"],
                hdbscan_label=int(embedded.labels[first]),
                membership=round(float(max(embedded.membership[i] for i in members)), 3),
            )
        )
    order = {c["cluster_id"]: i for i, c in enumerate(clusters)}
    out.sort(key=lambda p: (order[p.cluster_id], p.trace_ids[0]))
    return ClusterMap(projection=projection, trust=trust, points=out)
