"""How often one person may start a run: slowapi, keyed on the signed-in user.

Starting or resuming a run is the one expensive call (a judge call per trace, the diagnoser's
calls, the UI spec calls, a trace server subprocess), so it is the only one limited, by one count
for both. `charge_run` counts it, called by the dependency that opens the run (api.runs) once the
request has been found admissible and just before anything starts: a body FastAPI refuses (`422`)
or a run that cannot be resumed (`404`, `409`) never gets that far, so it uses up nothing, and a
refused request (`429`) opens no trace session and records no run.

The counts live in this process's memory: they reset on restart and are not shared between
workers. A shared limit needs `storage_uri` (Redis, for example).
"""

from fastapi import Request, Response
from slowapi import Limiter

from auth import Principal

# Runs one person may start per window, in the `limits` notation.
RUN_LIMIT = "10/hour"


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
