import pytest

from agent import model_guard
from agent.mcp_client import TraceClient


@pytest.fixture(autouse=True)
def no_retry_wait(monkeypatch):
    """No test waits out a retry delay."""
    monkeypatch.setattr(model_guard, "RETRY_DELAY_S", 0)


@pytest.fixture
async def traces():
    """One open session to the real trace server."""
    async with TraceClient() as client:
        yield client
