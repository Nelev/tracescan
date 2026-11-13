"""How often one person may start a run: slowapi, keyed on the signed-in user.

Starting or resuming a run is the one expensive call (a judge call per trace, the diagnoser's
calls, the UI spec calls, a trace server subprocess), so it is the only one limited, by one count
for both. The limit sits on a dependency, `limit_runs`, not on the route: slowapi's decorator
checks when the decorated function is called, and FastAPI calls a route only after every
dependency, `_open_run` included, has run, so a limit on the route would refuse a run that had
already started. A route decorator's dependencies
run after the router's session check and before the route's own parameters, so a refused request
opens no trace session and records no run.

The counts live in this process's memory: they reset on restart and are not shared between
workers. A shared limit needs `storage_uri` (Redis, for example).
"""

from typing import Annotated

from fastapi import Depends, Request, Response
from slowapi import Limiter

from auth import CurrentUser

# Runs one person may start per window, in the `limits` notation.
RUN_LIMIT = "10/hour"


def _remember_user(request: Request, user: CurrentUser) -> None:
    """Put the user id on the request for `_user_key`: slowapi checks before `limit_runs` runs."""
    request.state.user_id = user.user_id


def _user_key(request: Request) -> str:
    return request.state.user_id


# One instance for the process: `@limiter.limit` registers its limit on this instance at import.
# headers_enabled adds Retry-After (and X-RateLimit-*) to a 429, which the frontend reads.
# key_style="endpoint" counts by the limited function, not by URL: starting a run and resuming one
# (whose URL holds the run id) share one count, `limit_runs`'s.
limiter = Limiter(key_func=_user_key, headers_enabled=True, key_style="endpoint")


@limiter.limit(RUN_LIMIT)
async def limit_runs(
    request: Request,
    response: Response,  # slowapi writes the X-RateLimit-* headers of an allowed call here
    _: Annotated[None, Depends(_remember_user)],
) -> None:
    """Refuse the call with a 429 when the signed-in user has started `RUN_LIMIT` runs."""
