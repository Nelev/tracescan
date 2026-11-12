"""The trace browser API: read-only views of the stored traces, for the UI's Traces tab.

- `GET /v1/traces` lists the newest traces of an app, failed or not, with their lowest score
  and, for a failed one, the span its lowest score blames (names only).
- `GET /v1/traces/{trace_id}` returns one trace's span tree and its scores.

Reads go through the Postgres trace reader on TRACE_DATABASE_URL, whose transactions are
read-only. The collector stores span content as sent, so the tree is sanitized the way the MCP
server sanitizes it (trace_store/sanitize.py): attributes outside the allowlist are redacted and
status messages are truncated. Every route needs a Clerk session token (required for this router in main.py).
"""

import asyncio
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request, Response
from pydantic import AwareDatetime

from api.schemas import TOTAL_COUNT
from trace_store.const import MAX_ATTR_CHARS_TREE, MAX_LIMIT
from trace_store.models import TraceDetail, TraceId, TraceRow
from trace_store.postgres_reader import PostgresTraceReader
from trace_store.sanitize import sanitize_span

router = APIRouter(prefix="/v1")


def _reader(request: Request) -> PostgresTraceReader:
    return request.app.state.trace_reader


@router.get("/traces")
async def list_traces(
    request: Request,
    response: Response,
    app: str = "medas",
    since: AwareDatetime | None = None,
    until: AwareDatetime | None = None,
    failed_only: bool = False,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[TraceRow]:
    """One page of the list: `limit` traces after the newest `offset`. The total over all pages,
    with the same filters, is the `X-Total-Count` header, so the body stays a plain list."""
    reader = _reader(request)
    # Two independent reads, each on its own connection: run together, not one after the other.
    total, page = await asyncio.gather(
        reader.count_traces(app, since=since, until=until, failed_only=failed_only),
        reader.list_traces(
            app, since=since, until=until, failed_only=failed_only, limit=limit, offset=offset
        ),
    )
    response.headers[TOTAL_COUNT] = str(total)
    return page


@router.get("/traces/{trace_id}")
async def get_trace(request: Request, trace_id: TraceId) -> TraceDetail:
    detail = await _reader(request).get_trace_detail(trace_id)
    if detail is None:
        # Unknown, of another app, or not whole yet (no root, a missing parent).
        raise HTTPException(status_code=404, detail="trace not found")
    return detail.model_copy(update={"tree": sanitize_span(detail.tree, MAX_ATTR_CHARS_TREE)})
