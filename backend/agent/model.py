"""The chat models, reached through OpenRouter: the diagnoser's and the UI spec's."""

import os

from langchain_core.language_models import BaseChatModel
from langchain_openrouter import ChatOpenRouter

from agent.const import DEFAULT_DIAGNOSER_MODEL, DEFAULT_UI_SPEC_MODEL, REQUEST_TIMEOUT_MS


def build_model(variable: str, default: str, max_retries: int = 0) -> BaseChatModel:
    """The OpenRouter model named by the environment variable `variable`, else `default`.

    The SDK's own retry (max_retries, up to minutes of backoff) is off unless asked for: retries
    belong to the caller, which counts them against one budget per cluster in state
    (diagnose_cluster runs again after a transient error) or gives up for a fallback. A caller
    with no retry of its own (the eval's judge) asks for the SDK's.
    """
    return ChatOpenRouter(
        model=os.environ.get(variable, default),
        max_retries=max_retries,
        timeout=REQUEST_TIMEOUT_MS,
    )


def build_diagnoser_model() -> BaseChatModel:
    """Build the model named by DIAGNOSER_MODEL. Needs OPENROUTER_API_KEY, or it raises."""
    return build_model("DIAGNOSER_MODEL", DEFAULT_DIAGNOSER_MODEL)


def build_ui_spec_model() -> BaseChatModel:
    """Build the model named by UI_SPEC_MODEL, claude-haiku-5.5 by default. Needs OPENROUTER_API_KEY."""
    return build_model("UI_SPEC_MODEL", DEFAULT_UI_SPEC_MODEL)
