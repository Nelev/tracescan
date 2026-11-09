"""Clustering: the fixture's known groups, the noise rescue and the small-run fallback, then the node.

The fixture has four groups of six failures (trace id prefixes ret, tool, ctx, to) and two
unrelated one-offs (odd). Tests use the offline HashingEmbedder; one opt-in test repeats the
group check with the real fastembed model.
"""

import json
import os
import random
from functools import cache
from pathlib import Path

import pytest

from agent.clustering import cluster_summaries, failure_text, isolated_clusters, normalise_error
from agent.const import MAX_EXEMPLARS
from agent.embeddings import FastEmbedEmbedder
from agent.graph import build_graph
from tests.fakes import (
    DIAGNOSIS,
    FakeTraces,
    HashingEmbedder,
    fake_context,
    fake_diagnoser,
    span_tree,
    summary,
)
from trace_store.models import TraceSummary

FIXTURE = Path(__file__).parent / "fixtures" / "failure_summaries.json"
GROUPS = {"ret", "tool", "ctx", "to"}
OUTLIERS = {"tr_odd_01", "tr_odd_02"}


def group_of(trace_id: str) -> str:
    return trace_id.split("_")[1]


@cache
def all_failures() -> tuple[TraceSummary, ...]:
    rows = json.loads(FIXTURE.read_text())["summaries"]
    return tuple(TraceSummary.model_validate(r) for r in rows)


def load(*groups: str) -> list[TraceSummary]:
    return [s for s in all_failures() if not groups or group_of(s.trace_id) in groups]


def clustered(*groups: str):
    """Cluster the fixture failures of the given groups (all of them if none), offline."""
    return cluster_summaries(load(*groups), HashingEmbedder())


class NoEmbedding:
    """Stands in for the embedder where it must not be called."""

    def embed(self, texts):
        raise AssertionError("the embedder should not be called")


def assert_known_groups(embedder) -> None:
    clusters, unclustered = cluster_summaries(load(), embedder)
    by_group = {}
    for cluster in clusters:
        groups = {group_of(t) for t in cluster["trace_ids"]}
        assert len(groups) == 1, f"cluster mixes groups: {cluster['trace_ids']}"
        by_group[groups.pop()] = cluster
    assert set(by_group) == GROUPS
    assert all(len(c["trace_ids"]) == 6 for c in by_group.values())
    assert set(unclustered) == OUTLIERS


def test_failure_texts_of_different_groups_never_coincide():
    # Failures of one group may differ only in numbers, which are masked; different causes must not.
    pairs = {(failure_text(s), group_of(s.trace_id)) for s in load()}
    assert len({text for text, _ in pairs}) == len(pairs)


def test_failure_text_masks_numbers_and_keeps_the_wording():
    def text(ms: int, request: int) -> str:
        return failure_text(
            summary(
                "t1",
                failing_span_name="generate",
                error_message=f"missing field 'dose_unit' after {ms} ms",
                signature=f"request {request} failed at 2026-11-09T09:09:01Z",
            )
        )

    assert text(30, 4021) == text(45, 77)
    assert (
        text(30, 4021)
        == "generate: missing field 'dose_unit' after # ms | request # failed at #-#-#T#:#:#Z"
    )


def test_failure_text_names_the_failing_step_and_error():
    text = failure_text(load("tool")[0])
    assert "execute_tool lookup_dosage" in text and "dose_unit" in text


def test_known_groups_come_out_as_separate_clusters():
    assert_known_groups(HashingEmbedder())


@pytest.mark.skipif(not os.environ.get("RUN_SLOW"), reason="downloads the model; set RUN_SLOW=1")
def test_fastembed_separates_the_known_groups():
    assert_known_groups(FastEmbedEmbedder())


def test_every_trace_lands_in_exactly_one_place():
    clusters, unclustered = clustered()
    placed = [t for c in clusters for t in c["trace_ids"]] + unclustered
    assert sorted(placed) == sorted(s.trace_id for s in load())


def test_one_fault_causing_every_failure_is_one_cluster():
    # HDBSCAN calls a single dense group noise; the step-and-error pass turns it into a cluster.
    clusters, unclustered = clustered("ret")
    [cluster] = clusters
    assert len(cluster["trace_ids"]) == 6 and cluster["method"] == "step_error"
    assert unclustered == []


def test_one_dense_group_plus_one_offs_keeps_the_offs_unclustered():
    clusters, unclustered = clustered("ret", "odd")
    [cluster] = clusters
    assert {group_of(t) for t in cluster["trace_ids"]} == {"ret"}
    assert set(unclustered) == OUTLIERS


def test_small_run_groups_by_step_and_error_without_embedding():
    rows = [
        summary("t1", failing_span_name="retrieve", error_message="timed out after 30 ms"),
        summary("t2", failing_span_name="retrieve", error_message="timed out after 45 ms"),
        summary("t3", failing_span_name="generate", error_message="rate limited"),
    ]
    clusters, unclustered = cluster_summaries(rows, NoEmbedding())
    assert [(c["cluster_id"], c["trace_ids"], c["method"]) for c in clusters] == [
        ("c0", ["t1", "t2"], "step_error"),
        ("c1", ["t3"], "step_error"),
    ]
    assert unclustered == []  # too few traces to call anything noise


def test_normalise_error_masks_quoted_values_and_numbers():
    a = normalise_error("Missing required field 'dose_unit' after 30000 ms")
    b = normalise_error("missing required  field 'patient_id' after 12 ms")
    assert a == b


def test_empty_input_gives_nothing():
    assert cluster_summaries([], NoEmbedding()) == ([], [])


def test_result_does_not_depend_on_input_order():
    rows = load()
    shuffled = rows[:]
    random.Random(0).shuffle(shuffled)
    assert cluster_summaries(shuffled, HashingEmbedder()) == cluster_summaries(
        rows, HashingEmbedder()
    )


def test_clusters_are_numbered_by_size_and_exemplars_belong_to_them():
    clusters, _ = clustered()
    assert [c["cluster_id"] for c in clusters] == [f"c{i}" for i in range(len(clusters))]
    sizes = [len(c["trace_ids"]) for c in clusters]
    assert sizes == sorted(sizes, reverse=True)
    for cluster in clusters:
        assert 0 < len(cluster["exemplar_trace_ids"]) <= MAX_EXEMPLARS
        assert set(cluster["exemplar_trace_ids"]) <= set(cluster["trace_ids"])


def test_a_cluster_is_described_the_same_way_whichever_stage_found_it():
    clusters, _ = clustered()
    tool = next(c for c in clusters if group_of(c["trace_ids"][0]) == "tool")
    assert tool["method"] == "hdbscan"
    assert tool["signature"] == (
        "execute_tool lookup_dosage: tool call failed validation: missing required field 'x'"
    )


def test_exemplars_are_the_newest_traces_of_the_cluster():
    started = {s.trace_id: s.start_time for s in load()}
    clusters, _ = clustered()
    for cluster in clusters:
        newest = sorted(cluster["trace_ids"], key=lambda t: (started[t], t), reverse=True)
        assert cluster["exemplar_trace_ids"] == newest[:MAX_EXEMPLARS]


async def run_fixture_graph() -> dict:
    """The whole graph over the fixture failures, with a fake diagnoser answering every cluster."""
    trees = {s.trace_id: span_tree(s.trace_id) for s in load()}
    context = fake_context(FakeTraces(load(), trees), fake_diagnoser(DIAGNOSIS))
    return await build_graph().ainvoke({"target_app": "medas"}, context=context)


@pytest.mark.anyio
async def test_node_puts_plain_json_clusters_and_unclustered_into_state():
    result = await run_fixture_graph()
    json.dumps(result["clusters"])  # plain dicts: nothing for the checkpoint serializer to warn on
    assert len(result["clusters"]) == len(GROUPS) + len(OUTLIERS)
    assert set(result["unclustered"]) == OUTLIERS


def test_isolated_clusters_are_one_trace_clusters_numbered_after_the_real_ones():
    clusters, unclustered = clustered()
    isolated = isolated_clusters(load(), unclustered, first_index=len(clusters))
    assert [c["cluster_id"] for c in isolated] == ["c4", "c5"]
    assert {c["method"] for c in isolated} == {"isolated"}
    assert [c["trace_ids"] for c in isolated] == [[t] for t in unclustered]
    assert all(c["exemplar_trace_ids"] == c["trace_ids"] for c in isolated)


@pytest.mark.anyio
async def test_the_graph_diagnoses_each_isolated_failure_on_its_own():
    result = await run_fixture_graph()
    isolated = [c for c in result["clusters"] if c["method"] == "isolated"]
    assert {t for c in isolated for t in c["trace_ids"]} == OUTLIERS
    diagnosed = {d["cluster_id"] for d in result["diagnoses"]}
    assert {c["cluster_id"] for c in isolated} <= diagnosed
    assert result.get("diagnosis_failures", []) == []
