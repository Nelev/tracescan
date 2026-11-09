"""The diagnoser's chat model, reached through OpenRouter."""

import os

from langchain_core.language_models import BaseChatModel
from langchain_openrouter import ChatOpenRouter

from agent.const import DEFAULT_DIAGNOSER_MODEL


def build_diagnoser_model() -> BaseChatModel:
    """Build the model named by DIAGNOSER_MODEL. Needs OPENROUTER_API_KEY, or it raises."""
    return ChatOpenRouter(model=os.environ.get("DIAGNOSER_MODEL", DEFAULT_DIAGNOSER_MODEL))
