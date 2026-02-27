from pathlib import Path
import shutil
from urllib.error import URLError

import pytest

from ai_deney.connectors.electra_playwright import ElectraPlaywrightConnector


def test_probe_health_failure_raises_friendly_message(monkeypatch: pytest.MonkeyPatch) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    work_root = repo_root / "tests" / "_tmp_tasks" / "electra_playwright_connector"
    shutil.rmtree(work_root, ignore_errors=True)
    work_root.mkdir(parents=True, exist_ok=True)
    connector = ElectraPlaywrightConnector(
        repo_root=repo_root,
        raw_root=work_root / "raw",
        screenshot_root=work_root / "screenshots",
        portal_base_url="http://127.0.0.1:65530",
    )

    def _raise_url_error(*args, **kwargs):
        raise URLError("connection refused")

    monkeypatch.setattr("ai_deney.connectors.electra_playwright.urlopen", _raise_url_error)

    with pytest.raises(RuntimeError) as exc_info:
        connector._probe_portal_health()

    msg = str(exc_info.value)
    assert "Electra Test Portal not reachable at http://127.0.0.1:65530" in msg
    assert "bash scripts/run_electra_test_portal.sh" in msg
    assert "connection refused" in msg
