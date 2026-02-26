import subprocess
import sys
from pathlib import Path

import batch_agent as b


def test_bundle_batch_script_includes_index_outputs_and_generated_in_order(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    script = repo_root / "scripts" / "bundle_batch.sh"

    batch_dir = tmp_path / "outputs" / "batch-20260225-120000"
    batch_dir.mkdir(parents=True, exist_ok=True)
    (batch_dir / "generated").mkdir(parents=True, exist_ok=True)

    index = (
        "# Batch run: batch-20260225-120000\n\n"
        "- tasks file: `tests/_tmp_tasks/demo_tasks.md`\n"
        "- mode: `chat`\n\n"
        "## 1. task one\n"
        "- gate-summary: `attempt 0: PY_COMPILE_FAILED; final: PASS`\n"
        "- output: `001-one.md`\n\n"
        "## 2. task two\n"
        "- output: `002-two.json`\n"
    )
    (batch_dir / "index.md").write_text(index, encoding="utf-8")
    (batch_dir / "001-one.md").write_text("# One\n\n- alpha\n", encoding="utf-8")
    (batch_dir / "002-two.json").write_text('{"title":"Two"}\n', encoding="utf-8")
    (batch_dir / "generated" / "a.py").write_text("def a() -> int:\n    return 1\n", encoding="utf-8")
    (batch_dir / "generated" / "b.txt").write_text("hello\n", encoding="utf-8")

    p = subprocess.run(
        ["bash", str(script), str(batch_dir)],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
    )
    assert p.returncode == 0, f"bundle script failed: stdout={p.stdout}\nstderr={p.stderr}"

    bundle = batch_dir / "bundle.txt"
    assert bundle.exists()
    txt = bundle.read_text(encoding="utf-8")
    assert "BATCH_BUNDLE v1" in txt
    assert "tasks_file=tests/_tmp_tasks/demo_tasks.md" in txt
    assert "mode=chat" in txt
    assert "number_of_tasks=2" in txt
    assert "number_of_generated_files=2" in txt
    assert "===== FILE: index.md" in txt
    assert "# One" in txt
    assert '{"title":"Two"}' in txt
    assert "def a() -> int:" in txt
    assert "GATE_SUMMARY: attempt 0: PY_COMPILE_FAILED; final: PASS" in txt
    assert "===== FILE: generated/b.txt" in txt

    pos_index = txt.index("===== FILE: index.md")
    pos_one = txt.index("===== FILE: 001-one.md")
    pos_two = txt.index("===== FILE: 002-two.json")
    pos_gen_a = txt.index("===== FILE: generated/a.py")
    assert pos_index < pos_one < pos_two < pos_gen_a


def test_bundle_batch_script_latest_mode(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    script = repo_root / "scripts" / "bundle_batch.sh"

    outputs = tmp_path / "outputs"
    b1 = outputs / "batch-20260225-100000"
    b2 = outputs / "batch-20260225-110000"
    b1.mkdir(parents=True, exist_ok=True)
    b2.mkdir(parents=True, exist_ok=True)
    (b1 / "index.md").write_text("# old\n", encoding="utf-8")
    (b2 / "index.md").write_text("# latest\n", encoding="utf-8")

    p = subprocess.run(
        ["bash", str(script), "--latest"],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
    )
    assert p.returncode == 0, f"bundle latest failed: stdout={p.stdout}\nstderr={p.stderr}"
    assert (b2 / "bundle.txt").exists()


def test_batch_agent_bundle_flag_writes_bundle(tmp_path: Path, monkeypatch) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    tasks_dir = repo_root / "tests" / "_tmp_tasks" / "bundle_flag"
    tasks_dir.mkdir(parents=True, exist_ok=True)
    tasks_path = tasks_dir / "tasks_bundle_flag.txt"
    tasks_path.write_text(
        "WRITE_BLOCK: outputs/_smoke_agent_quality/bundle_flag.py\n"
        "PROMPT:\n"
        "Write def ok() -> int: return 1\n"
        "END_WRITE_BLOCK\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        b,
        "generate",
        lambda prompt, stream=False: "def ok() -> int:\n    return 1\n",
    )
    monkeypatch.setattr(b, "_maybe_run_pytest", lambda project_root: (True, "pytest skipped (stubbed)"))

    outdir = tmp_path / "out_bundle_flag"
    monkeypatch.setattr(
        sys,
        "argv",
        ["batch_agent.py", str(tasks_path), "--outdir", str(outdir), "--bundle"],
    )
    b.main()

    bundle = outdir / "bundle.txt"
    assert bundle.exists()


def test_bundle_includes_gate_summary_for_wrote_generated_file(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    script = repo_root / "scripts" / "bundle_batch.sh"

    batch_dir = tmp_path / "outputs" / "batch-20260225-130000"
    gen_dir = batch_dir / "generated"
    gen_dir.mkdir(parents=True, exist_ok=True)
    (gen_dir / "ok.py").write_text("def ok() -> int:\n    return 1\n", encoding="utf-8")

    (batch_dir / "index.md").write_text(
        "# Batch run: batch-20260225-130000\n\n"
        "- tasks file: `tests/_tmp_tasks/one.md`\n"
        "- mode: `chat`\n\n"
        "## 1. WRITE_BLOCK=generated/ok.py\n"
        "- gate-summary: `attempt 0: AST_TODO_FOUND; final: PASS`\n"
        "- wrote: `generated/ok.py`\n",
        encoding="utf-8",
    )

    p = subprocess.run(
        ["bash", str(script), str(batch_dir)],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
    )
    assert p.returncode == 0, f"bundle script failed: stdout={p.stdout}\nstderr={p.stderr}"

    bundle = batch_dir / "bundle.txt"
    assert bundle.exists()
    txt = bundle.read_text(encoding="utf-8")
    assert "number_of_tasks=1" in txt
    assert "number_of_generated_files=1" in txt

    idx_summary = txt.index("GATE_SUMMARY: attempt 0: AST_TODO_FOUND; final: PASS")
    idx_file = txt.index("===== FILE: generated/ok.py")
    assert idx_summary < idx_file
