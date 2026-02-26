import sys
from pathlib import Path

import pytest

import batch_agent as b


@pytest.mark.parametrize("extra_args", [[], ["--chat"]])
def test_write_block_executes_as_single_task_in_all_modes(tmp_path: Path, monkeypatch, extra_args: list[str]) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    tasks_dir = repo_root / "tests" / "_tmp_tasks" / "write_block_modes"
    tasks_dir.mkdir(parents=True, exist_ok=True)

    tasks_path = tasks_dir / "write_block_chat.md"
    tasks_path.write_text(
        "WRITE_BLOCK: outputs/_smoke_agent_quality/smoke_module.py\n"
        "EXPECT:\n"
        "- must_contain: \"def add(\"\n"
        "- must_contain: \"return a + b\"\n"
        "- forbid: \"```\"\n"
        "PROMPT:\n"
        "Write a small python module with add(a: int, b: int) -> int returning a + b. Output only python.\n"
        "END_WRITE_BLOCK\n",
        encoding="utf-8",
    )

    parsed = b._load_tasks(str(tasks_path))
    assert len(parsed) == 1
    assert parsed[0][0] == "WRITE_BLOCK:outputs/_smoke_agent_quality/smoke_module.py"

    monkeypatch.setattr(
        b,
        "generate",
        lambda prompt, stream=False: "def add(a: int, b: int) -> int:\n    return a + b\n",
    )
    monkeypatch.setattr(b, "_maybe_run_pytest", lambda project_root: (True, "pytest skipped (stubbed)"))

    outdir = tmp_path / ("out_chat" if extra_args else "out_default")
    argv = ["batch_agent.py", str(tasks_path), "--outdir", str(outdir), *extra_args]
    monkeypatch.setattr(sys, "argv", argv)

    b.main()

    gen_path = outdir / "generated" / "outputs" / "_smoke_agent_quality" / "smoke_module.py"
    assert gen_path.exists(), f"expected generated file missing: {gen_path}"
    txt = gen_path.read_text(encoding="utf-8")
    assert "def add(" in txt
    assert "return a + b" in txt

    index_path = outdir / "index.md"
    idx = index_path.read_text(encoding="utf-8")
    assert "## 1. WRITE_BLOCK=outputs/_smoke_agent_quality/smoke_module.py" in idx
    assert "## 2." not in idx
