"""The eval on Medas: its fault switches turned on one at a time, then one triage run over all.

Run from backend/:  uv run --env-file .env python -m eval.medas_run [--only tool_schema,...]
                        [--control] [--medas ../../medas] [--backend http://localhost:8010]

For each fault in the answer key (eval/medas_ground_truth.py) and each of its input sets, it
runs Medas's traffic generator (`dataset/traffic/send_traffic.py`, in the Medas checkout) as a
child process with only that fault's switch set, then the control sets with no switch: one
window of traffic in which every fault competes with the others and with healthy requests, so
the look-alike pairs share it too. `--only` sends just the faults named, with no controls;
`--control` sends the controls alone, where anything found is a false alarm.

Each trace is matched to the child process whose run holds its start, and labelled with
`kind_of`: the fault, if it fired on that request, else healthy. A trace that matches no child
(Medas used by someone else meanwhile) or a child with another number of traces than questions
stops the run: the answer key must cover every trace in the window. Then the triage graph runs
over the window as in eval/run.py, with no checkpointer, so it stops at the review pause and
writes nothing, and the result goes to out/eval/<timestamp>.json with `answer_key` "medas", for
eval.judge and eval.metrics.

Needs TraceScan's backend running (Medas sends its traces to its collector, so Medas's .env
must point OTEL_EXPORTER_OTLP_TRACES_ENDPOINT at it), Medas's database up and indexed, and
here TRACE_DATABASE_URL and OPENROUTER_API_KEY. Billable on both sides: one Medas agent run per
question, one trace judge call per trace, one diagnoser call per cluster.
"""

import argparse
import asyncio
import json
import os
import urllib.request
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agent.embeddings import FastEmbedEmbedder
from agent.mcp_client import TraceClient
from agent.model import build_diagnoser_model, build_trace_judge_model
from eval.medas_ground_truth import CONTROL_SETS, FAULTS, InputSet, kind_of
from eval.metrics import OUT_DIR
from eval.run import triage_window
from scripts.seed_traces import APP
from trace_store.const import MAX_LIMIT
from trace_store.models import SpanNode, TraceQuery, TraceSummary
from trace_store.postgres_reader import PostgresTraceReader, read_only_engine

ANSWER_KEY = "medas"
# The Medas checkout, next to this one by default.
DEFAULT_MEDAS = Path(__file__).resolve().parents[3] / "medas"
DEFAULT_BACKEND = "http://localhost:8010"
# What the child process keeps of this one's environment: enough to find and run uv. Nothing
# else, so none of TraceScan's settings (its keys, its database) reaches Medas, which reads its
# own .env, and no switch is on unless this module sets it.
CHILD_ENV = ("PATH", "HOME", "LANG", "TERM", "XDG_CACHE_HOME", "UV_CACHE_DIR")
# The traffic generator's first line names the switches that are on.
FAULTS_LINE = "Faults on: "


@dataclass(frozen=True)
class Send:
    """One run of Medas's traffic generator: an input set, with one fault's switch or none."""

    fault: str | None  # None: a control, no switch on
    input_set: InputSet

    @property
    def questions(self) -> int:
        return len(self.input_set.ids) * self.input_set.repeat

    @property
    def environment(self) -> dict[str, str]:
        return FAULTS[self.fault].switch if self.fault else {}

    def describe(self) -> str:
        ids = ",".join(self.input_set.ids)
        return f"{self.fault or 'control'} {ids} x{self.input_set.repeat}"


@dataclass(frozen=True)
class Sent:
    send: Send
    started: datetime
    ended: datetime

    def holds(self, moment: datetime) -> bool:
        return self.started <= moment < self.ended

    def record(self, traces: int) -> dict[str, Any]:
        return {
            "fault": self.send.fault,
            "ids": list(self.send.input_set.ids),
            "repeat": self.send.input_set.repeat,
            "started": self.started.isoformat(),
            "ended": self.ended.isoformat(),
            "traces": traces,
        }


class TrafficMismatch(Exception):
    """The window's traces are not the ones the runner sent."""


Sender = Callable[[Send], Awaitable[str]]


def plan(only: Sequence[str] | None = None, control: bool = False) -> list[Send]:
    """What the run sends, in order: every fault's input sets, then the controls; with `only`,
    those faults' sets and no controls; with `control`, the controls alone."""
    controls = [Send(None, input_set) for input_set in CONTROL_SETS]
    if control:
        return controls
    faults = list(only) if only else list(FAULTS)
    sends = [Send(fault, input_set) for fault in faults for input_set in FAULTS[fault].input_sets]
    return sends if only else sends + controls


def faults_on(output: str) -> set[str]:
    """The switches the traffic generator said were on, from its output."""
    for line in output.splitlines():
        if line.startswith(FAULTS_LINE):
            named = line.removeprefix(FAULTS_LINE).strip()
            return set() if named == "none" else {name.strip() for name in named.split(",")}
    raise TrafficMismatch("the traffic generator did not say which faults were on")


async def send_all(sends: Sequence[Send], sender: Sender) -> list[Sent]:
    """Run every send one after another, timing each. Stops when a child ran with other
    switches on than the send asked for."""
    done = []
    for send in sends:
        started = datetime.now(UTC)
        output = await sender(send)
        ended = datetime.now(UTC)
        expected = {send.fault} if send.fault else set()
        if (on := faults_on(output)) != expected:
            raise TrafficMismatch(f"asked for {sorted(expected)}, Medas ran with {sorted(on)}")
        done.append(Sent(send, started, ended))
    return done


def assign(summaries: Sequence[TraceSummary], sent: Sequence[Sent]) -> dict[str, Sent]:
    """Each trace's send: the one whose run holds the trace's start. Raises TrafficMismatch for
    a trace no send holds, or a send with another number of traces than questions."""
    assigned: dict[str, Sent] = {}
    strays = []
    for summary in summaries:
        owner = next((s for s in sent if s.holds(summary.start_time)), None)
        if owner is None:
            strays.append(summary.trace_id)
        else:
            assigned[summary.trace_id] = owner
    if strays:
        raise TrafficMismatch(f"traces no send made, in the window: {', '.join(sorted(strays))}")
    for each in sent:
        got = sum(owner is each for owner in assigned.values())
        if got != each.send.questions:
            raise TrafficMismatch(
                f"{each.send.describe()}: {got} traces for {each.send.questions} questions"
            )
    return assigned


async def label(
    assigned: dict[str, Sent], tree_of: Callable[[str], Awaitable[SpanNode | None]]
) -> dict[str, str]:
    """The answer key of the window: each trace's kind (`kind_of`), read off its tree."""
    kinds = {}
    for trace_id, sent in assigned.items():
        tree = await tree_of(trace_id)
        if tree is None:
            raise TrafficMismatch(f"trace {trace_id} is not whole")
        kinds[trace_id] = kind_of(sent.send.fault, tree)
    return kinds


def child_environment(send: Send) -> dict[str, str]:
    kept = {name: os.environ[name] for name in CHILD_ENV if name in os.environ}
    return kept | send.environment


def _echoed(line: str) -> bool:
    """The generator's lines worth showing: the switches, and one per question (id, kind,
    outcome, seconds; it never prints an answer)."""
    return line.startswith(FAULTS_LINE) or (line[:1] in "NEA" and line[1:3].isdigit())


def subprocess_sender(medas_api: Path) -> Sender:
    """A sender that runs Medas's traffic generator in `medas_api`."""

    async def send(each: Send) -> str:
        print(f"-- {each.describe()}")
        child = await asyncio.create_subprocess_exec(
            "uv", "run", "python", "-m", "dataset.traffic.send_traffic",
            "--ids", ",".join(each.input_set.ids),
            "--repeat", str(each.input_set.repeat),
            cwd=medas_api,
            env=child_environment(each),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )  # fmt: skip
        out, _ = await child.communicate()
        output = out.decode(errors="replace")
        for line in filter(_echoed, output.splitlines()):
            print(f"   {line}")
        if child.returncode != 0:
            raise TrafficMismatch(f"the traffic generator exited with {child.returncode}")
        return output

    return send


def check_medas(medas: Path) -> Path:
    """The Medas API folder, after checking that its .env turns no switch on by itself."""
    medas_api = medas / "medas-api"
    if not (medas_api / "faults.py").is_file():
        raise SystemExit(f"{medas_api} is not a Medas checkout with fault switches")
    env_file = medas_api / ".env"
    lines = env_file.read_text().splitlines() if env_file.is_file() else []
    if any(line.strip().startswith("FAULT_") for line in lines):
        raise SystemExit(f"{env_file} sets a FAULT_ switch: remove it, the runner sets them")
    return medas_api


def check_backend(backend: str) -> None:
    try:
        with urllib.request.urlopen(f"{backend}/health", timeout=5) as response:  # noqa: S310
            if response.status == 200:
                return
    except OSError:
        pass
    raise SystemExit(f"TraceScan's backend does not answer at {backend}: Medas's traces go there")


async def answer(
    sent: Sequence[Sent], trace_database_url: str
) -> tuple[dict[str, str], list[dict[str, Any]]]:
    """The window's answer key (trace id to kind) and the record of each send, read from the
    stored traces."""
    engine = read_only_engine(trace_database_url)
    try:
        reader = PostgresTraceReader(engine)
        summaries = await reader.search_traces(
            TraceQuery(app=APP, since=sent[0].started, until=sent[-1].ended, limit=MAX_LIMIT)
        )
        assigned = assign(summaries, sent)
        kinds = await label(assigned, reader.get_trace_tree)
    finally:
        await engine.dispose()
    return kinds, [s.record(sum(owner is s for owner in assigned.values())) for s in sent]


def sent_from(records: Sequence[dict[str, Any]]) -> list[Sent]:
    """The sends of a results file, as `Sent.record` wrote them."""
    return [
        Sent(
            Send(r["fault"], InputSet(ids=tuple(r["ids"]), repeat=r["repeat"])),
            datetime.fromisoformat(r["started"]),
            datetime.fromisoformat(r["ended"]),
        )
        for r in records
    ]


async def run(sends: Sequence[Send], sender: Sender, trace_database_url: str) -> dict[str, Any]:
    sent = await send_all(sends, sender)
    since, until = sent[0].started, sent[-1].ended
    kinds, records = await answer(sent, trace_database_url)
    print(f"{len(kinds)} traces sent; triaging the window")
    async with TraceClient(trace_database_url) as traces:
        model, judge = build_diagnoser_model(), build_trace_judge_model()
        found = await triage_window(since, until, kinds, traces, FastEmbedEmbedder(), model, judge)
    return {
        "answer_key": ANSWER_KEY,
        "model": getattr(model, "model_name", "unknown"),
        "judge_model": getattr(judge, "model_name", "unknown"),
        "since": since.isoformat(),
        "until": until.isoformat(),
        "control": all(s.fault is None for s in sends),
        "sent": records,
    } | found


def main() -> None:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--only", help="comma-separated faults to send, with no controls")
    parser.add_argument("--control", action="store_true", help="send the controls alone")
    parser.add_argument("--medas", type=Path, default=DEFAULT_MEDAS, help="the Medas checkout")
    parser.add_argument("--backend", default=DEFAULT_BACKEND, help="TraceScan's backend")
    parser.add_argument(
        "--relabel",
        type=Path,
        help="label a results file's traces again from the stored trees (after FIRED changed); "
        "sends nothing, triages nothing, and drops the file's grades",
    )
    args = parser.parse_args()
    only = [name.strip() for name in args.only.split(",")] if args.only else None
    if only and (unknown := set(only) - set(FAULTS)):
        parser.error(f"unknown faults: {', '.join(sorted(unknown))}")
    if only and args.control:
        parser.error("--only and --control do not go together")
    trace_database_url = os.environ.get("TRACE_DATABASE_URL")
    if not trace_database_url:
        parser.error("set TRACE_DATABASE_URL")
    if args.relabel:
        relabel(args.relabel, trace_database_url)
        return
    medas_api = check_medas(args.medas)
    check_backend(args.backend)

    sends = plan(only, args.control)
    print(f"{len(sends)} sends, {sum(s.questions for s in sends)} questions")
    result = asyncio.run(run(sends, subprocess_sender(medas_api), trace_database_url))
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}.json"
    path.write_text(json.dumps(result, indent=2))
    print(
        f"{len(result['failing_spans'])} failed traces, {len(result['clusters'])} clusters, "
        f"{len(result['diagnoses'])} diagnoses in {result['seconds']}s: {path}"
    )


def relabel(path: Path, trace_database_url: str) -> None:
    result = json.loads(path.read_text())
    kinds, _ = asyncio.run(answer(sent_from(result["sent"]), trace_database_url))
    changed = {
        t: (result["kinds"][t], kind) for t, kind in kinds.items() if kind != result["kinds"][t]
    }
    result["kinds"] = kinds
    # The grades were given against the old majority kinds: grade again with eval.judge.
    for stale in ("verdicts", "judge", "human"):
        result.pop(stale, None)
    path.write_text(json.dumps(result, indent=2))
    for trace_id, (old, new) in changed.items():
        print(f"{trace_id}: {old} -> {new}")
    print(f"{len(changed)} traces labelled again: {path}")


if __name__ == "__main__":
    main()
