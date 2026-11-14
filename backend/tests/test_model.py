"""The chat models are built from the environment, with a default each."""

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_openrouter import ChatOpenRouter

from agent.const import DEFAULT_DIAGNOSER_MODEL, DEFAULT_TRACE_JUDGE_MODEL, DEFAULT_UI_SPEC_MODEL
from agent.model import build_diagnoser_model, build_trace_judge_model, build_ui_spec_model

MODELS = [
    (build_diagnoser_model, "DIAGNOSER_MODEL", DEFAULT_DIAGNOSER_MODEL),
    (build_trace_judge_model, "TRACE_JUDGE_MODEL", DEFAULT_TRACE_JUDGE_MODEL),
    (build_ui_spec_model, "UI_SPEC_MODEL", DEFAULT_UI_SPEC_MODEL),
]
OTHER = "mistralai/mistral-small-3.2-24b-instruct"


def built(model: BaseChatModel) -> ChatOpenRouter:
    assert isinstance(model, ChatOpenRouter)
    return model


@pytest.mark.parametrize(("build", "variable", "default"), MODELS, ids=[v for _, v, _ in MODELS])
def test_each_model_has_its_own_default_and_variable(monkeypatch, build, variable, default):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    for _, name, _ in MODELS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("JUDGE_MODEL", "openai/gpt-6.1-sol")  # the eval's grader, read by none
    assert built(build()).model_name == default
    assert built(build()).max_retries == 0  # retries belong to the caller

    monkeypatch.setenv(variable, OTHER)
    assert built(build()).model_name == OTHER
    for other_build, _, other_default in MODELS:  # the variable sets its own model alone
        if other_build is not build:
            assert built(other_build()).model_name == other_default
