"""Progress events for a graph run, safe to send to a client.

With `astream_events(..., version="v3")` the raw stream carries full state (`values`) and every
node's input and result (`tasks`), which can hold clinical span data. `ProgressTransformer` boils
the `tasks` channel down to an allowlist: node, task id, cluster id, ok flag and counts. Consumers
read it only through `progress_events`, never by iterating the raw stream.
"""

from collections.abc import AsyncIterator
from typing import Literal, TypedDict

from langgraph.stream import AsyncGraphRunStream, ProtocolEvent, StreamChannel, StreamTransformer

CHANNEL = "progress"

# Nodes that run once per trace: up to MAX_JUDGED_TRACES of them, so they report nothing of their
# own (each progress event costs the API a UI-spec call); join_scores after them reports the count.
SILENT_NODES = frozenset({"score_trace"})

# Result keys whose length is reported. Only lengths leave the graph, never the values.
COUNTED_KEYS = (
    "traces",
    "failed_traces",
    "clusters",
    "unclustered",
    "diagnoses",
    "diagnosis_failures",
    "reproductions",
    "proposals",
    "actions_log",
)


class ProgressEvent(TypedDict, total=False):
    # node_paused: the node called interrupt() and waits for a resume (human_review).
    event: Literal["node_started", "node_finished", "node_failed", "node_paused"]
    node: str
    task_id: str
    # Set on the branches of the diagnose fan-out, so the client can tell parallel tasks apart.
    cluster_id: str
    # False when a node finished but recorded a failure (a cluster whose diagnosis failed).
    ok: bool
    counts: dict[str, int]


class ProgressTransformer(StreamTransformer):
    required_stream_modes = ("tasks",)

    def __init__(self, scope: tuple[str, ...] = ()) -> None:
        super().__init__(scope)
        self._channel: StreamChannel[ProgressEvent] = StreamChannel(CHANNEL)
        # A result payload has no input, so the cluster id is kept from the matching start.
        self._cluster_ids: dict[str, str] = {}

    def init(self) -> dict:
        return {CHANNEL: self._channel}

    def process(self, event: ProtocolEvent) -> bool:
        params = event["params"]
        # Nested graphs have their own namespace; only this graph's own nodes are reported.
        if event["method"] != "tasks" or tuple(params["namespace"]) != self.scope:
            return True
        data = params["data"]
        if data["name"] in SILENT_NODES:
            return True
        progress: ProgressEvent = {"node": data["name"], "task_id": data["id"]}
        # Same discriminator as LangGraph's own lifecycle transformer: only results carry `result`.
        if "result" in data:
            self._finish(progress, data)
        else:
            self._start(progress, data)
        self._channel.push(progress)
        return True

    def _start(self, progress: ProgressEvent, data: dict) -> None:
        progress["event"] = "node_started"
        cluster_id = _cluster_id(data.get("input"))
        if cluster_id is not None:
            self._cluster_ids[data["id"]] = cluster_id
            progress["cluster_id"] = cluster_id

    def _finish(self, progress: ProgressEvent, data: dict) -> None:
        writes = data["result"] or {}
        progress["counts"] = {key: len(writes[key]) for key in COUNTED_KEYS if key in writes}
        # The error text is dropped on purpose: it could carry span contents.
        failed = bool(data.get("error"))
        if failed:
            progress["event"] = "node_failed"
        else:
            progress["event"] = "node_paused" if data.get("interrupts") else "node_finished"
        if (cluster_id := self._cluster_ids.pop(data["id"], None)) is not None:
            progress["cluster_id"] = cluster_id
        if not failed and progress["counts"].get("diagnosis_failures"):
            progress["ok"] = False


def progress_events(stream: AsyncGraphRunStream) -> AsyncIterator[ProgressEvent]:
    """The run's progress events, the only part of a v3 stream that is safe to forward."""
    return stream.extensions[CHANNEL]


def _cluster_id(task_input: object) -> str | None:
    """The id of the cluster a diagnose branch works on, if this task is one."""
    if not isinstance(task_input, dict):
        return None
    cluster = task_input.get("cluster")
    if isinstance(cluster, dict) and isinstance(cluster.get("cluster_id"), str):
        return cluster["cluster_id"]
    return None
