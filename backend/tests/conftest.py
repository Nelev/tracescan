import pytest

from agent.mcp_client import TraceClient


@pytest.fixture
async def traces():
    """One open session to the real trace server."""
    async with TraceClient() as client:
        yield client
