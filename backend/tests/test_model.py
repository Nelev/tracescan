"""The chat models are built from the environment, with a default each."""

from langchain_core.language_models import BaseChatModel
from langchain_openrouter import ChatOpenRouter

from agent.const import DEFAULT_DIAGNOSER_MODEL, DEFAULT_TRACE_JUDGE_MODEL, DEFAULT_UI_SPEC_MODEL
from agent.model import build_diagnoser_model, build_trace_judge_model, build_ui_spec_model


def built(model: BaseChatModel) -> ChatOpenRouter:
    assert isinstance(model, ChatOpenRouter)
    return model


def test_each_model_has_its_own_default(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.delenv("DIAGNOSER_MODEL", raising=False)
    monkeypatch.delenv("UI_SPEC_MODEL", raising=False)
    assert built(build_diagnoser_model()).model_name == DEFAULT_DIAGNOSER_MODEL
    assert (
        built(build_ui_spec_model()).model_name
        == DEFAULT_UI_SPEC_MODEL
        == "anthropic/claude-haiku-5.5"
    )


def test_the_environment_overrides_each_model_alone(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.delenv("DIAGNOSER_MODEL", raising=False)
    monkeypatch.setenv("UI_SPEC_MODEL", "mistralai/mistral-small-3.2-24b-instruct")
    assert built(build_ui_spec_model()).model_name == "mistralai/mistral-small-3.2-24b-instruct"
    assert built(build_diagnoser_model()).model_name == DEFAULT_DIAGNOSER_MODEL


def test_the_trace_judge_has_its_own_cheap_default_and_variable(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.delenv("TRACE_JUDGE_MODEL", raising=False)
    monkeypatch.setenv("JUDGE_MODEL", "openai/gpt-6.1-sol")  # the eval's grader, not this one
    assert built(build_trace_judge_model()).model_name == DEFAULT_TRACE_JUDGE_MODEL
    assert DEFAULT_TRACE_JUDGE_MODEL != DEFAULT_DIAGNOSER_MODEL
    monkeypatch.setenv("TRACE_JUDGE_MODEL", "mistralai/mistral-small-3.2-24b-instruct")
    assert built(build_trace_judge_model()).model_name == "mistralai/mistral-small-3.2-24b-instruct"
    assert built(build_trace_judge_model()).max_retries == 0
