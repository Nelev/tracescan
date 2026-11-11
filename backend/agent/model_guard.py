"""Budget and retry building blocks for the diagnoser's model call.

The budget lives in graph state. Every diagnose_cluster run appends one usage entry to
`model_usage`, and a cluster's spend is the sum of its entries (`spent_for`). The router puts the
cluster's entries in the `Send` payload, so the node can check the budget before and after its
run (`Spent.ok`). `guarded` makes one structured call (`include_raw=True`: the raw message carries
tokens and cost) and adds it to a `Spent`; whether to run again is the graph's decision.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import httpx

from agent.const import (
    MAX_CLUSTER_COST_USD,
    MAX_CLUSTER_TOKENS,
    MAX_MODEL_ATTEMPTS,
    RETRY_DELAY_S,
)


@dataclass
class Spent:
    calls: int = 0  # every attempt, including ones that raised
    tokens: int = 0
    cost_usd: float = 0.0  # stays 0 when the provider reports none, so only the token cap applies

    def __add__(self, other: "Spent") -> "Spent":
        return Spent(
            self.calls + other.calls, self.tokens + other.tokens, self.cost_usd + other.cost_usd
        )

    def ok(self) -> bool:
        """Whether another call is allowed."""
        return (
            self.calls < MAX_MODEL_ATTEMPTS
            and self.tokens < MAX_CLUSTER_TOKENS
            and self.cost_usd < MAX_CLUSTER_COST_USD
        )


def spent_by_cluster(usage: list[dict]) -> dict[str, Spent]:
    """Every cluster's spend so far, in one pass over the `model_usage` entries."""
    totals: dict[str, Spent] = {}
    for entry in usage:
        spent = Spent(entry["calls"], entry["tokens"], entry["cost_usd"])
        totals[entry["cluster_id"]] = totals.get(entry["cluster_id"], Spent()) + spent
    return totals


def spent_for(usage: list[dict], cluster_id: str) -> Spent:
    """What a cluster has spent so far: the sum of its `model_usage` entries."""
    total = Spent()
    for entry in usage:
        if entry["cluster_id"] == cluster_id:
            total += Spent(entry["calls"], entry["tokens"], entry["cost_usd"])
    return total


def retryable(exc: Exception) -> bool:
    """Throttling, timeouts, server errors and dropped connections. The SDK's errors carry a status."""
    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        return status in (408, 429) or status >= 500
    return isinstance(exc, httpx.TransportError | TimeoutError | ConnectionError)


def backoff_delay(calls: int) -> float:
    """Seconds to wait before the next call, given the calls made so far: doubles each time."""
    return RETRY_DELAY_S * 2 ** (calls - 1)


async def guarded(ask: Callable[[], Awaitable[Any]], spent: Spent):
    """Make one call and add it to `spent`; returns the parsed answer or raises.

    `ask` makes one structured call with `include_raw=True`, so it yields a dict with `raw`,
    `parsed` and `parsing_error`. LangChain types that call as `dict | BaseModel`, hence `Any`.
    """
    spent.calls += 1  # counted first: an attempt that raises is still an attempt
    out = await ask()
    raw = out["raw"]
    spent.tokens += (raw.usage_metadata or {}).get("total_tokens", 0)
    spent.cost_usd += raw.response_metadata.get("cost", 0.0)
    if out["parsed"] is None:
        raise out["parsing_error"]
    return out["parsed"]
