"""
End-to-end demo: the agent's TraceClient against the real trace server.

Run from backend/:  uv run python scripts/demo_client.py
Add 2>/dev/null to hide the server's startup banner and logs.
"""

import asyncio
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))  # so `agent` imports when run as a script

from langchain_mcp_adapters.client import MultiServerMCPClient  # noqa: E402

from agent.mcp_client import TRACE_SERVER, TraceClient  # noqa: E402
from trace_store.models import FailedTraceQuery  # noqa: E402


def show_tree(node: dict, depth: int = 1) -> None:
    print("  " * depth + f"{node['name']}  [{node['status']}]  attrs={node['attributes']}")
    for child in node["children"]:
        show_tree(child, depth + 1)


async def main() -> None:
    start = time.perf_counter()
    async with TraceClient() as traces:  # starts trace_store.mcp_server over stdio, once
        print(f"server started + session open: {time.perf_counter() - start:.2f}s\n")

        print("== search_failed_traces (agent client, typed) ==")
        failed = await traces.search_failed_traces(FailedTraceQuery(app="medas"))
        for s in failed:
            print(f"  {s.trace_id}  failing_span={s.failing_span_name}  min_score={s.min_score}")
            print(f"    error_message: {s.error_message}")

        print("\n== same query, only traces after 09:30 UTC ==")
        since = datetime(2026, 11, 5, 9, 30, tzinfo=timezone.utc)
        later = await traces.search_failed_traces(FailedTraceQuery(app="medas", since=since))
        print("  ", [s.trace_id for s in later])

        print("\n== 3 more calls on the same session ==")
        start = time.perf_counter()
        for _ in range(3):
            await traces.search_failed_traces(FailedTraceQuery(app="medas"))
        print(f"  3 calls in {time.perf_counter() - start:.3f}s (no new server)")

    # TraceClient only exposes search_failed_traces; use a raw session for the other two tools.
    trace_id = failed[-1].trace_id
    async with MultiServerMCPClient({"traces": TRACE_SERVER}).session("traces") as session:
        tree = (await session.call_tool("get_trace_tree", {"trace_id": trace_id})).structuredContent
        print(f"\n== get_trace_tree({trace_id}) ==")
        show_tree(tree)

        span_id = tree["children"][0]["span_id"]
        args = {"trace_id": trace_id, "span_id": span_id}
        span = (await session.call_tool("get_span", args)).structuredContent
        print(f"\n== get_span({span_id}) ==")
        keys = ("name", "status", "status_message", "attributes", "children")
        print(json.dumps({k: span[k] for k in keys}, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
