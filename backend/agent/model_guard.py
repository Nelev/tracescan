"""Budget and retry building blocks for the model calls of the diagnoser and the trace judge.

Each node keeps one `Spent` for its item (a cluster, a trace) over all its calls, checks it with
`Spent.ok` against the item's `Budget` before asking again, and appends it to graph state as one
usage entry: `model_usage` keyed by `cluster_id`, `judge_usage` keyed by `trace_id` (`spent_by`
sums them per item). `guarded` makes one structured call (`include_raw=True`: the raw message
carries tokens and cost) and adds it to a `Spent`.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import httpx
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage
from pydantic import BaseModel

from agent.const import (
    MAX_CLUSTER_COST_USD,
    MAX_CLUSTER_TOKENS,
    MAX_MODEL_ATTEMPTS,
    MAX_TRACE_COST_USD,
    MAX_TRACE_TOKENS,
    RETRY_DELAY_S,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Budget:
    """How much one item (a cluster, a trace) may spend: calls, tokens and cost."""

    calls: int
    tokens: int
    cost_usd: float


# Functions, not constants: the limits are read when checked, so tests can patch them.
def cluster_budget() -> Budget:
    return Budget(MAX_MODEL_ATTEMPTS, MAX_CLUSTER_TOKENS, MAX_CLUSTER_COST_USD)


def trace_budget() -> Budget:
    return Budget(MAX_MODEL_ATTEMPTS, MAX_TRACE_TOKENS, MAX_TRACE_COST_USD)


@dataclass
class Spent:
    calls: int = 0  # every attempt, including ones that raised
    tokens: int = 0
    cost_usd: float = 0.0  # stays 0 when the provider reports none, so only the token cap applies

    def __add__(self, other: "Spent") -> "Spent":
        return Spent(
            self.calls + other.calls, self.tokens + other.tokens, self.cost_usd + other.cost_usd
        )

    def ok(self, budget: Budget) -> bool:
        """Whether another call is allowed within `budget`."""
        return (
            self.calls < budget.calls
            and self.tokens < budget.tokens
            and self.cost_usd < budget.cost_usd
        )


def _spent(entry: dict) -> Spent:
    return Spent(entry["calls"], entry["tokens"], entry["cost_usd"])


def spent_by(usage: list[dict], key: str = "cluster_id") -> dict[str, Spent]:
    """Every item's spend so far, in one pass over its usage entries, by `key`."""
    totals: dict[str, Spent] = {}
    for entry in usage:
        totals[entry[key]] = totals.get(entry[key], Spent()) + _spent(entry)
    return totals


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


def retrying[**P, R](
    call: Callable[P, Awaitable[R]], spent: Spent, budget: Budget, label: str
) -> Callable[P, Awaitable[R]]:
    """`call`, retried after a doubling wait on a transient error while `spent` is within `budget`.

    One call at a time, so an answer already given is never asked for again. Any other error, or
    one with no budget left, is raised. `label` names the item in the log; no message is logged.
    """

    async def call_retrying(*args: P.args, **kwargs: P.kwargs) -> R:
        while True:
            try:
                return await call(*args, **kwargs)
            except Exception as exc:
                if not (retryable(exc) and spent.ok(budget)):
                    raise
                logger.warning("%s: %s, retrying", label, type(exc).__name__)
                await asyncio.sleep(backoff_delay(spent.calls))

    return call_retrying


def structured_asker[M: BaseModel](
    model: BaseChatModel, schema: type[M], spent: Spent
) -> Callable[[list[BaseMessage]], Awaitable[M]]:
    """One guarded structured call per use: messages in, a validated `schema` out.

    json_schema, not the default function_calling: that forces a tool_choice, which some models
    (Claude through OpenRouter) reject with a 400. include_raw keeps the raw message, which carries
    the tokens and cost that `guarded` adds up. Streaming is off because nobody reads tokens:
    without it, a v3 event stream routes the call through LangChain's token-streaming path; this
    keeps any injected model on the same path as ainvoke.
    """
    structured = model.model_copy(update={"disable_streaming": True}).with_structured_output(
        schema, method="json_schema", include_raw=True
    )

    async def ask(messages: list[BaseMessage]) -> M:
        return schema.model_validate(await guarded(lambda: structured.ainvoke(messages), spent))

    return ask
