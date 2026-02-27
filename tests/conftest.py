import os
import pytest

@pytest.fixture(autouse=True)
def _force_deterministic_connectors(monkeypatch):
    # Never allow unit tests to depend on a running portal/browser.
    monkeypatch.setenv("AI_DENEY_ELECTRA_CONNECTOR", "mock")
    monkeypatch.delenv("AI_DENEY_ELECTRA_PORTAL_URL", raising=False)
    monkeypatch.delenv("AI_DENEY_ELECTRA_PORTAL_USERNAME", raising=False)
    monkeypatch.delenv("AI_DENEY_ELECTRA_PORTAL_PASSWORD", raising=False)
    monkeypatch.delenv("AI_DENEY_ELECTRA_EXPORT_VARIANT", raising=False)
