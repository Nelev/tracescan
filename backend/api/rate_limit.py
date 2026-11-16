"""How often one person may start a run, and how much one app may send the collector: slowapi.

Runs are keyed on the signed-in user, the collector on the app whose token the export carries.

Starting or resuming a run is the one expensive call (a judge call per trace, the diagnoser's
calls, the UI spec calls, a trace server subprocess), so it is the only one limited, by one count
for both. `charge_run` counts it, called by the dependency that opens the run (api.runs) once the
request has been found admissible and just before anything starts: a body FastAPI refuses (`422`)
or a run that cannot be resumed (`404`, `409`) never gets that far, so it uses up nothing, and a
refused request (`429`) opens no trace session and records no run.

The collector (api.traces) has two budgets per sending app, both far above what Medas sends (its
batch exporter posts at most 512 spans every 5 s per process; its traffic generator runs 3
requests at a time), so they stop a runaway or forged sender, not normal traffic:
`charge_export` counts each export before its body is read (`COLLECTOR_REQUESTS`), and
`charge_spans` counts the spans it would store once decoded (`COLLECTOR_SPANS`). A refused export
is a `429` with `Retry-After`, nothing stored; the OTel HTTP exporter retries it after that wait,
but only within its export timeout (10 s by default), so a limit that trips in real traffic loses
spans.

The counts live in this process's memory: they reset on restart and are not shared between
workers. A shared limit needs `storage_uri` (Redis, for example).
"""

import math
import time

from fastapi import HTTPException, Request, Response
from limits import parse
from slowapi import Limiter

from auth import Principal

# Runs one person may start per window, in the `limits` notation.
RUN_LIMIT = "10/hour"
# What one app may send the collector per window: exports, and spans over all its exports.
COLLECTOR_REQUESTS = "600/minute"
COLLECTOR_SPANS = "20000/minute"
_SPANS = parse(COLLECTOR_SPANS)


def _user_key(request: Request) -> str:
    return request.state.user_id


# One instance for the process: `@limiter.limit` registers its limit on this instance at import.
# headers_enabled adds Retry-After (and X-RateLimit-*) to a 429, which the frontend reads.
# key_style="endpoint" counts by the limited function, not by URL: starting a run and resuming one
# (whose URL holds the run id) share one count, `_count_run`'s.
limiter = Limiter(key_func=_user_key, headers_enabled=True, key_style="endpoint")


@limiter.limit(RUN_LIMIT)
async def _count_run(request: Request, response: Response) -> None:
    """slowapi checks and counts when this is called; `response` takes its X-RateLimit-* headers."""


async def charge_run(request: Request, response: Response, user: Principal) -> None:
    """Count one run for `user`; raises slowapi's RateLimitExceeded (a `429` with Retry-After) once
    they have started `RUN_LIMIT` runs."""
    request.state.user_id = user.user_id
    await _count_run(request=request, response=response)


def _app_key(request: Request) -> str:
    return request.state.app


@limiter.limit(COLLECTOR_REQUESTS, key_func=_app_key)
async def _count_export(request: Request, response: Response) -> None:
    """slowapi checks and counts when this is called, per sending app."""


async def charge_export(request: Request, response: Response, app: str) -> None:
    """Count one export from `app`; slowapi's RateLimitExceeded (a `429` with Retry-After) past
    `COLLECTOR_REQUESTS`. Called before the body is read."""
    request.state.app = app
    await _count_export(request=request, response=response)


def charge_spans(app: str, spans: int) -> None:
    """Count `spans` decoded spans from `app`, all or none: a `429` with Retry-After, counting
    nothing, when they would take it past `COLLECTOR_SPANS`.

    Not a slowapi limit: slowapi checks a request once, and the export has already been counted.
    This is the `limits` strategy slowapi itself runs on, with the export's spans as its cost.
    """
    strategy, keys = limiter.limiter, ("collector_spans", app)
    if strategy.test(_SPANS, *keys, cost=spans):
        strategy.hit(_SPANS, *keys, cost=spans)
        return
    reset_at, _ = strategy.get_window_stats(_SPANS, *keys)
    raise HTTPException(
        status_code=429,
        detail=f"over {COLLECTOR_SPANS} spans for this app",
        headers={"Retry-After": str(max(1, math.ceil(reset_at - time.time())))},
    )
