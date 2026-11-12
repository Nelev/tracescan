"""Progress events for a graph run, safe to send to a client.

With `astream_events(..., version="v3")` the raw stream carries full state (`values`) and every
node's input and result (`tasks`), which can hold clinical span data. `ProgressTransformer` boils
the `tasks` channel down to an allowlist: node, task id, cluster id, ok flag and counts. Consumers
read it only through `progress_events`, never by iterating the raw stream.
"""

from collections import Counter
from collections.abc import AsyncIterator

from langgraph.stream import AsyncGraphRunStream, ProtocolEvent, StreamChannel, StreamTransformer

from agent.schemas import ProgressEvent

CHANNEL = "progress"

# Nodes fanned out once per item (score_trace: once per trace, up to MAX_JUDGED_TRACES), so their
# branches do not each report (each progress event costs the API a UI-spec call). Instead a
# `node_progress` event says how many are done each time another 1/PROGRESS_STEPS of them is (the
# last step is left out: the node after them starting says it). The total is the number of start
# events: LangGraph emits the start of every task of a step before any of them runs.
COUNTED_NODES = frozenset({"score_trace"})
PROGRESS_STEPS = 4

# Result keys whose length is reported. Only lengths leave the graph, never the values.
COUNTED_KEYS = (
    "traces",
    "failed_traces",
    "clusters",
    "unclustered",
    "diagnoses",
    "diagnosis_failures",
    "proposals",
    "actions_log",
)


class ProgressTransformer(StreamTransformer):
    required_stream_modes = ("tasks",)

    def __init__(self, scope: tuple[str, ...] = ()) -> None:
        super().__init__(scope)
        self._channel: StreamChannel[ProgressEvent] = StreamChannel(CHANNEL)
        # A result payload has no input, so the cluster id is kept from the matching start.
        self._cluster_ids: dict[str, str] = {}
        # Per counted node: how many of its branches started, and how many are done.
        self._started: Counter[str] = Counter()
        self._done: Counter[str] = Counter()

    def init(self) -> dict:
        return {CHANNEL: self._channel}

    def process(self, event: ProtocolEvent) -> bool:
        params = event["params"]
        # Nested graphs have their own namespace; only this graph's own nodes are reported.
        if event["method"] != "tasks" or tuple(params["namespace"]) != self.scope:
            return True
        data = params["data"]
        # Same discriminator as LangGraph's own lifecycle transformer: only results carry `result`.
        finished = "result" in data
        if data["name"] in COUNTED_NODES:
            if finished:
                self._count_done(data["name"])
            else:
                self._started[data["name"]] += 1
            return True
        progress: ProgressEvent = {"node": data["name"], "task_id": data["id"]}
        if finished:
            self._finish(progress, data)
        else:
            self._start(progress, data)
        self._channel.push(progress)
        return True

    def _count_done(self, node: str) -> None:
        """Count one finished branch of `node`; report each step but the last."""
        self._done[node] += 1
        done, total = self._done[node], self._started[node]
        if done < total and (done - 1) * PROGRESS_STEPS // total < done * PROGRESS_STEPS // total:
            self._channel.push(
                {"event": "node_progress", "node": node, "counts": {"done": done, "total": total}}
            )

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
