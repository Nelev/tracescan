"""The budget and retry building blocks, against scripted stand-ins for one structured model call."""

import httpx
import pytest
from langchain_core.messages import AIMessage

from agent import model_guard
from agent.const import MAX_MODEL_ATTEMPTS
from agent.model_guard import Spent, backoff_delay, guarded, retryable, spent_for
from tests.fakes import FakeApiError


def answer(cost: float | None = 0.001, parsed: object = "diagnosis") -> dict:
    """What a structured call made with include_raw returns: 150 tokens."""
    raw = AIMessage(
        "",
        usage_metadata={"input_tokens": 100, "output_tokens": 50, "total_tokens": 150},
        response_metadata={} if cost is None else {"cost": cost},
    )
    return {"raw": raw, "parsed": parsed, "parsing_error": None}


def returns(result):
    async def ask():
        return result

    return ask


def raises(exc):
    async def ask():
        raise exc

    return ask


@pytest.mark.anyio
async def test_it_returns_the_answer_and_adds_up_calls_tokens_and_cost():
    spent = Spent()
    assert await guarded(returns(answer()), spent) == "diagnosis"
    await guarded(returns(answer()), spent)
    assert (spent.calls, spent.tokens, spent.cost_usd) == (2, 300, pytest.approx(0.002))


@pytest.mark.anyio
async def test_a_provider_that_reports_no_cost_costs_nothing_against_the_cost_cap():
    spent = Spent()
    await guarded(returns(answer(cost=None)), spent)
    assert spent.cost_usd == 0


@pytest.mark.anyio
async def test_a_call_that_raises_is_still_an_attempt_and_is_not_swallowed():
    spent = Spent()
    with pytest.raises(FakeApiError):
        await guarded(raises(FakeApiError(503)), spent)
    assert (spent.calls, spent.tokens) == (1, 0)


@pytest.mark.anyio
async def test_an_answer_that_does_not_fit_the_schema_raises_its_parsing_error():
    error = ValueError("does not fit")
    unparsable = {**answer(), "parsed": None, "parsing_error": error}
    spent = Spent()
    with pytest.raises(ValueError) as caught:
        await guarded(returns(unparsable), spent)
    assert caught.value is error
    assert spent.tokens == 150  # the call was paid for, so it is counted


def test_the_budget_runs_out_of_attempts_tokens_and_cost(monkeypatch):
    assert Spent(calls=MAX_MODEL_ATTEMPTS - 1).ok()
    assert not Spent(calls=MAX_MODEL_ATTEMPTS).ok()
    monkeypatch.setattr(model_guard, "MAX_CLUSTER_TOKENS", 200)
    assert not Spent(tokens=200).ok() and Spent(tokens=199).ok()
    monkeypatch.setattr(model_guard, "MAX_CLUSTER_COST_USD", 0.0015)
    assert not Spent(cost_usd=0.0015).ok() and Spent(cost_usd=0.001).ok()


def test_spent_adds_up():
    assert Spent(1, 150, 0.001) + Spent(2, 50, 0.002) == Spent(3, 200, pytest.approx(0.003))


def test_a_cluster_spent_is_the_sum_of_its_own_usage_entries():
    usage = [
        {"cluster_id": "c0", "calls": 1, "tokens": 0, "cost_usd": 0.0},
        {"cluster_id": "c1", "calls": 1, "tokens": 150, "cost_usd": 0.001},
        {"cluster_id": "c0", "calls": 2, "tokens": 300, "cost_usd": 0.002},
    ]
    assert spent_for(usage, "c0") == Spent(3, 300, 0.002)
    assert spent_for(usage, "c9") == Spent()


def test_the_wait_before_a_re_run_doubles(monkeypatch):
    monkeypatch.setattr(model_guard, "RETRY_DELAY_S", 1.0)
    assert [backoff_delay(calls) for calls in (1, 2, 3)] == [1.0, 2.0, 4.0]


@pytest.mark.parametrize(
    "exc",
    [
        FakeApiError(408),  # timeout
        FakeApiError(429),  # throttled
        FakeApiError(503),  # server error
        httpx.ConnectError("x"),  # no connection
        httpx.ReadTimeout("x"),
        TimeoutError(),
    ],
    ids=repr,
)
def test_throttling_timeouts_server_errors_and_dropped_connections_are_retryable(exc):
    assert retryable(exc)


@pytest.mark.parametrize(
    "exc",
    [
        FakeApiError(400),
        FakeApiError(401),
        RuntimeError("bug"),
    ],  # the last: a bug, not a flaky call
    ids=repr,
)
def test_client_errors_and_unknown_exceptions_are_not(exc):
    assert not retryable(exc)
