"""The call to the small model for the UI spec of a streamed message (api.ui_spec)."""

import asyncio
import json
import logging

import pytest
from langchain_core.language_models.fake_chat_models import FakeListChatModel

from api import ui_spec
from api.ui_spec import CATALOG, PROMPT, compose_ui
from tests.fakes import SPEC, scripted

PHI = "patient John Doe"  # stands in for text that must never reach a log

EVENT = "proposal"
DATA = {"cluster_id": "c0", "title": "retrieve returned nothing", "body": "## Summary"}


class FailingModel(FakeListChatModel):
    async def ainvoke(self, *args, **kwargs):
        raise RuntimeError(f"provider says: {PHI}")


class SlowModel(FakeListChatModel):
    async def ainvoke(self, *args, **kwargs):
        await asyncio.sleep(5)


@pytest.mark.anyio
async def test_a_spec_inside_code_fences_is_read():
    assert await compose_ui(scripted("```json\n" + json.dumps(SPEC) + "\n```"), EVENT, DATA) == SPEC


@pytest.mark.anyio
async def test_the_spec_is_not_checked_here():
    odd = {"anything": ["the", "frontend", "checks"]}  # the backend knows nothing of components
    assert await compose_ui(scripted(json.dumps(odd)), EVENT, DATA) == odd


@pytest.mark.anyio
async def test_the_model_is_asked_about_this_message_only():
    model = scripted(json.dumps(SPEC))
    await compose_ui(model, EVENT, DATA)
    assert len(model.seen) == 1
    system, human = model.seen[0]
    assert system.content == PROMPT
    assert json.loads(human.content) == {"event": EVENT, "data": DATA}


@pytest.mark.anyio
@pytest.mark.parametrize("reply", ["not json at all", "[1, 2]", '"a string"', "42"])
async def test_a_reply_that_is_not_a_json_object_gives_none(reply, caplog):
    caplog.set_level(logging.WARNING)
    model = scripted(reply)
    assert await compose_ui(model, EVENT, DATA) is None
    assert len(model.seen) == 1  # not asked again
    assert "not JSON" in caplog.text or "not a JSON object" in caplog.text


@pytest.mark.anyio
async def test_a_failing_call_gives_none_and_logs_no_text(caplog):
    caplog.set_level(logging.DEBUG)
    assert await compose_ui(FailingModel(responses=["x"]), EVENT, DATA) is None
    assert "RuntimeError" in caplog.text and PHI not in caplog.text


@pytest.mark.anyio
async def test_a_slow_call_gives_none_without_waiting(monkeypatch):
    monkeypatch.setattr(ui_spec, "UI_CALL_TIMEOUT_S", 0.05)
    assert await compose_ui(SlowModel(responses=["x"]), EVENT, DATA) is None


def test_the_prompt_carries_the_catalog_the_frontend_wrote():
    assert CATALOG in PROMPT and "{{" not in PROMPT
    assert any(line.startswith("| `") for line in CATALOG.splitlines())  # a row per component
