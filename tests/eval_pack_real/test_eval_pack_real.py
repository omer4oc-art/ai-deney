import os
import re
import sys
import subprocess
from pathlib import Path
from urllib import request
import json

import pytest


def _ollama_reachable(timeout: float = 0.8) -> bool:
    url = "http://127.0.0.1:11434/api/tags"
    try:
        with request.urlopen(url, timeout=timeout) as resp:
            if getattr(resp, "status", None) != 200:
                return False
            body = resp.read().decode("utf-8", errors="ignore")
            if not body.strip():
                return False
            data = json.loads(body)
            models = data.get("models", [])
            return isinstance(models, list) and len(models) > 0
    except Exception:
        return False


def _target_from_task(task_file: Path) -> str:
    txt = task_file.read_text(encoding="utf-8")
    m = re.search(r"^\s*WRITE_BLOCK\s*:\s*([^\s]+)\s*$", txt, flags=re.MULTILINE)
    assert m, f"missing WRITE_BLOCK line in {task_file}"
    return m.group(1).strip()


def _task_files() -> list[Path]:
    root = Path(__file__).resolve().parent / "tasks"
    return sorted([p for p in root.glob("*.md") if p.is_file()])


@pytest.mark.parametrize("task_file", _task_files(), ids=lambda p: p.stem)
def test_real_tasks_run_with_repair_bundle_and_transcript(tmp_path: Path, task_file: Path) -> None:
    if not _ollama_reachable():
        pytest.skip("ollama not reachable")

    repo_root = Path(__file__).resolve().parents[2]
    outdir = tmp_path / f"real_{task_file.stem}"
    env = dict(os.environ)
    env["AI_DENEY_PYTEST_ARGS"] = "-k test_ast_quality_gate_text_rejects_top_level_print_and_pass_only"
    p = subprocess.run(
        [
            sys.executable,
            "batch_agent.py",
            "--chat",
            "--tasks-format",
            "blocks",
            "--repair-retries",
            "1",
            "--bundle",
            "--record-transcript",
            "--outdir",
            str(outdir),
            str(task_file),
        ],
        cwd=str(repo_root),
        env=env,
        capture_output=True,
        text=True,
    )
    assert p.returncode == 0, f"stdout={p.stdout}\nstderr={p.stderr}"

    rel_target = _target_from_task(task_file)
    generated = outdir / "generated" / rel_target
    assert generated.exists(), f"missing generated file: {generated}"
    c = subprocess.run([sys.executable, "-m", "py_compile", str(generated)], capture_output=True, text=True)
    assert c.returncode == 0, f"stdout={c.stdout}\nstderr={c.stderr}"
    assert (outdir / "index.md").exists()
    assert (outdir / "bundle.txt").exists()
    assert (outdir / "transcript.jsonl").exists()
