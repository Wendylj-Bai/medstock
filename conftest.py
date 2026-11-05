"""
Safety net for ALL tests: no test may ever open the real database (data/medstock.db).

Tests must use a temporary database (pytest's tmp_path). If a test, or the app run by a
test, tries to connect to the real file, the test fails instead of changing your data.
"""

from pathlib import Path

import pytest

import db

REAL_DB = Path(db.DEFAULT_DB).resolve()


@pytest.fixture(autouse=True)
def never_touch_real_database(monkeypatch):
    real_connect = db.connect

    def guarded(path=db.DEFAULT_DB, *args, **kwargs):
        if Path(path).resolve() == REAL_DB:
            raise RuntimeError("A test tried to open the real database data/medstock.db. Use tmp_path instead.")
        return real_connect(path, *args, **kwargs)

    monkeypatch.setattr(db, "connect", guarded)


@pytest.fixture(autouse=True)
def never_call_a_real_ai_service(monkeypatch):
    """Safety net: no test may reach Gemini or Anthropic. The Streamlit test runner reads the app's secrets
    file, which can hold a real key, so client creation is blocked at two levels: the app's own factories
    (assistant.make_provider, assistant.make_client) and the SDK constructors themselves
    (google.genai.Client, anthropic.Anthropic and anthropic.AsyncAnthropic). A test that needs an answer
    passes a scripted fake client to a provider class instead."""
    import assistant

    def blocked(*_a, **_k):
        raise RuntimeError("A test tried to create a real AI client. Use a scripted fake provider instead.")

    monkeypatch.setattr(assistant, "make_provider", blocked)
    monkeypatch.setattr(assistant, "make_client", blocked)
    try:
        from google import genai
        monkeypatch.setattr(genai, "Client", blocked)
        import google.genai.client as genai_client
        monkeypatch.setattr(genai_client, "Client", blocked)
    except ImportError:
        pass
    try:
        import anthropic
        monkeypatch.setattr(anthropic, "Anthropic", blocked)
        monkeypatch.setattr(anthropic, "AsyncAnthropic", blocked)
    except ImportError:
        pass
