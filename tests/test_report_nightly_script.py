import subprocess
from pathlib import Path


def test_report_nightly_script_writes_expected_fields(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    soak = tmp_path / "soak"
    (soak / "runs" / "iter-0001").mkdir(parents=True, exist_ok=True)
    (soak / "runs" / "iter-0002").mkdir(parents=True, exist_ok=True)
    (soak / "soak_summary.jsonl").write_text(
        '{"iteration":1,"status":"PASS","duration_seconds":2}\n'
        '{"iteration":2,"status":"FAIL","duration_seconds":3}\n',
        encoding="utf-8",
    )
    (soak / "runs" / "iter-0001" / "gate_report.json").write_text(
        '{"gate_counts":{"PY_COMPILE_FAILED":2}}',
        encoding="utf-8",
    )
    (soak / "runs" / "iter-0002" / "gate_report.json").write_text(
        '{"gate_counts":{"EXPECT_MISSING":1}}',
        encoding="utf-8",
    )

    real = tmp_path / "real"
    real.mkdir(parents=True, exist_ok=True)
    (real / "index.md").write_text("# x\n", encoding="utf-8")
    (real / "bundle.txt").write_text("b\n", encoding="utf-8")
    (real / "transcript.jsonl").write_text("{}\n", encoding="utf-8")
    (real / "gate_report.json").write_text('{"gate_counts":{}}\n', encoding="utf-8")

    out = tmp_path / "nightly_report.txt"
    p = subprocess.run(
        [
            "python3",
            "scripts/report_nightly.py",
            "--soak-dir",
            str(soak),
            "--real-outdir",
            str(real),
            "--out",
            str(out),
        ],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
    )
    assert p.returncode == 0, f"stdout={p.stdout}\nstderr={p.stderr}"
    text = out.read_text(encoding="utf-8")
    assert "iterations=2" in text
    assert "failures=1" in text
    assert "PY_COMPILE_FAILED" in text
    assert "EXPECT_MISSING" in text
    assert "real_passed=1" in text
    assert "real_index=" in text
    assert "ollama_tags=" in text
