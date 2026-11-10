"""The chat models are built from the environment, with a default each."""

from agent.const import DEFAULT_DIAGNOSER_MODEL, DEFAULT_UI_SPEC_MODEL
from agent.model import build_diagnoser_model, build_ui_spec_model


def test_each_model_has_its_own_default(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.delenv("DIAGNOSER_MODEL", raising=False)
    monkeypatch.delenv("UI_SPEC_MODEL", raising=False)
    assert build_diagnoser_model().model_name == DEFAULT_DIAGNOSER_MODEL
    assert build_ui_spec_model().model_name == DEFAULT_UI_SPEC_MODEL == "anthropic/claude-haiku-5.5"


def test_the_environment_overrides_each_model_alone(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.delenv("DIAGNOSER_MODEL", raising=False)
    monkeypatch.setenv("UI_SPEC_MODEL", "mistralai/mistral-small-3.2-24b-instruct")
    assert build_ui_spec_model().model_name == "mistralai/mistral-small-3.2-24b-instruct"
    assert build_diagnoser_model().model_name == DEFAULT_DIAGNOSER_MODEL
