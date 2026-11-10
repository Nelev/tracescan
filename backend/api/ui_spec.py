"""The UI spec of a streamed message, written by the small model.

One call per message (`compose_ui`): the model gets `{"event", "data"}` as JSON, with the prompt in
`ui_prompt.md`, and replies with a spec. The reply is parsed as JSON and passed on as it is: the
backend knows nothing of the components or the spec's shape, and the frontend checks it before it
draws anything. A call that fails or is too slow, or a reply that is not a JSON object, gives None:
the message then has no spec, and the page shows it as it is.

The model sees what the message carries. Progress and lifecycle messages hold ids and counts only; a
`proposal` holds the diagnoser's prose, which can be clinical text, and the model copies its values
into the page with nothing checking the copy. Spend is not counted yet.
"""

import asyncio
import json
import logging
from pathlib import Path

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.utils.json import parse_json_markdown

from agent.const import MAX_UI_CALLS_PER_RUN, UI_CALL_TIMEOUT_S

logger = logging.getLogger(__name__)

# The catalog in words, written by the frontend (`npm run export:ui-prompt`): plain text to the
# backend, which still knows nothing of json-render.
_HERE = Path(__file__).parent
CATALOG = (_HERE / "ui_catalog.md").read_text().strip()
PROMPT = (_HERE / "ui_prompt.md").read_text().replace("{{catalog}}", CATALOG)


class UiSpecs:
    """The UI spec calls of one run: at most `MAX_UI_CALLS_PER_RUN`, then every message gets None."""

    def __init__(self, model: BaseChatModel) -> None:
        self._model = model
        self._calls = 0

    async def compose(self, event: str, data: dict) -> dict | None:
        if self._calls >= MAX_UI_CALLS_PER_RUN:
            return None
        self._calls += 1
        return await compose_ui(self._model, event, data)


async def compose_ui(model: BaseChatModel, event: str, data: dict) -> dict | None:
    """The spec the model writes for one message, or None. Never raises."""
    messages = [SystemMessage(PROMPT), HumanMessage(json.dumps({"event": event, "data": data}))]
    try:
        reply = await asyncio.wait_for(model.ainvoke(messages), UI_CALL_TIMEOUT_S)
        spec = parse_json_markdown(reply.text)
    except ValueError:  # includes LangChain's parse error; the reply itself is not logged
        logger.warning("ui spec of %s: the reply is not JSON", event)
        return None
    except Exception as exc:
        # Type name only: the message could carry the proposal's text.
        logger.warning("ui spec of %s: the model call failed: %s", event, type(exc).__name__)
        return None
    if not isinstance(spec, dict):
        logger.warning("ui spec of %s: the reply is not a JSON object", event)
        return None
    return spec
