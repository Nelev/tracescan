"""The diagnoser's chat model, reached through OpenRouter."""

import os

from langchain_core.language_models import BaseChatModel
from langchain_openrouter import ChatOpenRouter

from agent.const import DEFAULT_DIAGNOSER_MODEL, REQUEST_TIMEOUT_MS


def build_diagnoser_model() -> BaseChatModel:
    """Build the model named by DIAGNOSER_MODEL. Needs OPENROUTER_API_KEY, or it raises.

    The SDK's own retry (max_retries, default 2, up to minutes of backoff) is off: retries belong
    to the graph (diagnose_cluster runs again after a transient error), which counts them against
    one budget per cluster in state.
    """
    return ChatOpenRouter(
        model=os.environ.get("DIAGNOSER_MODEL", DEFAULT_DIAGNOSER_MODEL),
        max_retries=0,
        timeout=REQUEST_TIMEOUT_MS,
    )
