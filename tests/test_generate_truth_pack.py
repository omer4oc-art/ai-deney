import json
import shutil
import subprocess
import sys
from pathlib import Path


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _electra_summary_csv(date_value: str = "2025-01-01") -> str:
    return (
        "date,gross_sales,net_sales,currency\n"
        f"{date_value},100.00,90.00,USD\n"
    )


def _electra_agency_csv(date_value: str = "2025-01-01") -> str:
    return (
        "date,agency_id,agency_name,gross_sales,net_sales,currency\n"
        f"{date_value},AG001,Atlas Partners,100.00,90.00,USD\n"
    )


def _hotelrunner_csv(date_value: str = "2025-01-01") -> str:
    return (
        "date,booking_id,channel,gross_sales,net_sales,currency\n"
        f"{date_value},HR1,Booking.com,100.00,90.00,USD\n"
    )


def _hotelrunner_agency_dim_csv(date_value: str = "2025-01-01") -> str:
    return (
        "date,booking_id,agency_id,agency_name,gross_sales,net_sales,currency\n"
        f"{date_value},HR1,AG001,Atlas Partners,100.00,90.00,USD\n"
    )


def _manifest_path_from_stdout(stdout: str) -> Path | None:
    for line in stdout.splitlines():
        if line.startswith("INBOX: manifest="):
            raw = line.split("=", 1)[1].strip()
            if raw:
                return Path(raw)
    return None


def test_generate_truth_pack_script_creates_index_and_bundle() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    outdir = repo_root / "tests" / "_tmp_tasks" / "truth_pack" / "out"
    shutil.rmtree(outdir.parent, ignore_errors=True)
    outdir.parent.mkdir(parents=True, exist_ok=True)
    p = subprocess.run(
        [sys.executable, "scripts/generate_truth_pack.py", "--outdir", str(outdir)],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
    )
    assert p.returncode == 0, f"stdout={p.stdout}\nstderr={p.stderr}"
    index_path = outdir / "index.md"
    bundle_path = outdir / "bundle.txt"
    assert index_path.exists()
    assert bundle_path.exists()

    index_text = index_path.read_text(encoding="utf-8")
    assert "# Hotel Truth Pack v1" in index_text
    assert "Q1" in index_text
    assert ".md" in index_text
    assert ".html" in index_text
    assert "compare electra vs hotelrunner for 2025" in index_text
    assert "electra vs hotelrunner monthly reconciliation for 2025" in index_text
    assert "electra vs hotelrunner monthly reconciliation for 2026" in index_text
    assert "where do electra and hotelrunner differ by agency in 2025" in index_text
    assert "monthly reconciliation by agency 2026 electra hotelrunner" in index_text
    assert "any anomalies by agency in 2026" in index_text
    assert "mapping health report 2025" in index_text
    assert "which agencies are unmapped in 2026" in index_text
    assert "agency drift electra vs hotelrunner 2025" in index_text
    assert "mapping explain agency 2025" in index_text
    assert "mapping explain agency 2026" in index_text
    assert "mapping unknown rate improvement 2025" in index_text
    assert "mapping unknown rate improvement 2026" in index_text

    bundle_text = bundle_path.read_text(encoding="utf-8")
    assert "===== FILE: index.md =====" in bundle_text
    assert "Data freshness / source: Source: Electra mock fixtures; Generated: deterministic run." in bundle_text
    assert "Data freshness / source: Source: Electra + HotelRunner mock fixtures; Generated: deterministic run." in bundle_text
    assert (
        "Data freshness / source: Source: Electra + HotelRunner mock fixtures + mapping config; Generated: deterministic run."
        in bundle_text
    )


def test_generate_truth_pack_use_inbox_falls_back_when_empty() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    tmp_root = repo_root / "tests" / "_tmp_tasks" / "truth_pack" / "inbox_empty"
    outdir = tmp_root / "out"
    inbox_root = tmp_root / "inbox"

    shutil.rmtree(tmp_root, ignore_errors=True)
    (inbox_root / "electra").mkdir(parents=True, exist_ok=True)
    (inbox_root / "hotelrunner").mkdir(parents=True, exist_ok=True)

    p = subprocess.run(
        [
            sys.executable,
            "scripts/generate_truth_pack.py",
            "--outdir",
            str(outdir),
            "--use-inbox",
            "1",
            "--inbox-root",
            str(inbox_root),
        ],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
    )
    assert p.returncode == 0, f"stdout={p.stdout}\nstderr={p.stderr}"
    assert "INBOX: falling back to deterministic fixtures" in p.stdout
    assert (outdir / "index.md").exists()
    assert (outdir / "bundle.txt").exists()
    index_text = (outdir / "index.md").read_text(encoding="utf-8")
    assert "SOURCE: fixtures (inbox fallback)" in index_text
    assert "## Skipped Questions" not in index_text
    assert "missing years:" not in index_text


def test_generate_truth_pack_inbox_partial_uses_available_year_and_writes_manifest() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    tmp_root = repo_root / "tests" / "_tmp_tasks" / "truth_pack" / "inbox_partial"
    outdir = tmp_root / "out"
    inbox_root = tmp_root / "inbox"

    shutil.rmtree(tmp_root, ignore_errors=True)
    (inbox_root / "electra").mkdir(parents=True, exist_ok=True)
    (inbox_root / "hotelrunner").mkdir(parents=True, exist_ok=True)

    _write(inbox_root / "electra" / "electra_sales_summary_2025-01-31.csv", _electra_summary_csv("2025-01-31"))
    _write(inbox_root / "electra" / "electra_sales_by_agency_2025-01-31.csv", _electra_agency_csv("2025-01-31"))
    _write(
        inbox_root / "hotelrunner" / "hotelrunner_daily_sales_2025-01-31.csv",
        _hotelrunner_agency_dim_csv("2025-01-31"),
    )
    _write(inbox_root / "electra" / "electra_sales_summary_2026-01-31.csv", _electra_summary_csv("2026-01-31"))
    _write(
        inbox_root / "hotelrunner" / "hotelrunner_daily_sales_2026-01-31.csv",
        _hotelrunner_agency_dim_csv("2026-01-31"),
    )

    p = subprocess.run(
        [
            sys.executable,
            "scripts/generate_truth_pack.py",
            "--outdir",
            str(outdir),
            "--use-inbox",
            "1",
            "--inbox-root",
            str(inbox_root),
            "--inbox-policy",
            "partial",
        ],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
    )
    assert p.returncode == 0, f"stdout={p.stdout}\nstderr={p.stderr}"
    assert "INBOX: using run_id=" in p.stdout
    assert "INBOX: partial policy skipped years with missing inbox files: 2026" in p.stdout
    assert "INBOX: partial policy skipped" in p.stdout

    manifest_path = _manifest_path_from_stdout(p.stdout)
    assert manifest_path is not None
    assert manifest_path.exists()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["years"] == [2025]
    assert len(manifest["selected_files"]) == 3

    index_text = (outdir / "index.md").read_text(encoding="utf-8")
    assert "SOURCE: inbox; ingested years: [2025]; skipped years: [2026]" in index_text
    assert "## Skipped Questions" in index_text
    assert "missing years:" not in index_text
    report_mds = [path.name for path in outdir.glob("*.md") if path.name != "index.md"]
    assert report_mds
    assert all("2026" not in name for name in report_mds)


def test_generate_truth_pack_inbox_strict_falls_back_when_incomplete() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    tmp_root = repo_root / "tests" / "_tmp_tasks" / "truth_pack" / "inbox_strict_incomplete"
    outdir = tmp_root / "out"
    inbox_root = tmp_root / "inbox"

    shutil.rmtree(tmp_root, ignore_errors=True)
    (inbox_root / "electra").mkdir(parents=True, exist_ok=True)
    (inbox_root / "hotelrunner").mkdir(parents=True, exist_ok=True)

    _write(inbox_root / "electra" / "electra_sales_summary_2025-01-31.csv", _electra_summary_csv("2025-01-31"))
    _write(inbox_root / "electra" / "electra_sales_by_agency_2025-01-31.csv", _electra_agency_csv("2025-01-31"))
    _write(inbox_root / "hotelrunner" / "hotelrunner_daily_sales_2025-01-31.csv", _hotelrunner_csv("2025-01-31"))
    _write(inbox_root / "electra" / "electra_sales_summary_2026-01-31.csv", _electra_summary_csv("2026-01-31"))

    p = subprocess.run(
        [
            sys.executable,
            "scripts/generate_truth_pack.py",
            "--outdir",
            str(outdir),
            "--use-inbox",
            "1",
            "--inbox-root",
            str(inbox_root),
            "--inbox-policy",
            "strict",
        ],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
    )
    assert p.returncode == 0, f"stdout={p.stdout}\nstderr={p.stderr}"
    assert "INBOX: falling back to deterministic fixtures" in p.stdout
    assert "INBOX: manifest=" not in p.stdout

    index_text = (outdir / "index.md").read_text(encoding="utf-8")
    assert "SOURCE: fixtures (inbox fallback)" in index_text
    assert "## Skipped Questions" not in index_text
    assert "missing years:" not in index_text
    assert (outdir / "02_get_me_the_sales_data_of_2026.md").exists()
