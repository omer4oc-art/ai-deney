import os
from pathlib import Path


def test_inbox_watcher_script_exists_and_is_executable() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    watcher = repo_root / "scripts" / "inbox_watch_once.sh"
    assert watcher.exists()
    assert os.access(watcher, os.X_OK)
