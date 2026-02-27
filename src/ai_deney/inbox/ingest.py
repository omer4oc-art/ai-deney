"""Inbox ingestion: copy selected files, normalize, and write run manifest."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import shutil

from ai_deney.inbox.scan import SelectedInboxFile, scan_and_select_newest
from ai_deney.inbox.validate import DEFAULT_MAX_FILE_SIZE_BYTES, validate_selected_files
from ai_deney.parsing.electra_sales import normalize_report_files as normalize_electra_report_files
from ai_deney.parsing.hotelrunner_sales import normalize_report_files as normalize_hotelrunner_report_files


@dataclass(frozen=True)
class IngestResult:
    run_id: str
    run_root: Path
    manifest_path: Path
    normalized_root: Path
    selected_files: list[SelectedInboxFile]


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _assert_within_repo(path: Path, repo_root: Path) -> None:
    try:
        path.resolve().relative_to(repo_root.resolve())
    except Exception as exc:
        raise ValueError(f"path escapes repo root: {path}") from exc


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _build_run_id(selected_files: list[SelectedInboxFile], hashes: dict[Path, str]) -> str:
    if not selected_files:
        raise ValueError("no selected files provided")

    ordered = sorted(
        selected_files,
        key=lambda s: (s.year, s.source, s.report_type, s.path.name),
    )
    max_date = max(s.report_date for s in ordered).isoformat()
    seed_parts: list[str] = []
    for item in ordered:
        seed_parts.append(
            "|".join(
                [
                    item.source,
                    item.report_type,
                    str(int(item.year)),
                    item.report_date.isoformat(),
                    item.path.name,
                    hashes[item.path],
                ]
            )
        )
    digest = hashlib.sha256("\n".join(seed_parts).encode("utf-8")).hexdigest()[:12]
    return f"inbox_{max_date}_{digest}"


def _copy_selected_file(
    selected: SelectedInboxFile,
    run_root: Path,
    repo_root: Path,
) -> Path:
    dst_dir = run_root / selected.source / selected.report_type / str(int(selected.year))
    _assert_within_repo(dst_dir, repo_root)
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / selected.path.name
    _assert_within_repo(dst, repo_root)
    shutil.copyfile(selected.path, dst)
    return dst


def _to_repo_relative(path: Path, repo_root: Path) -> str:
    _assert_within_repo(path, repo_root)
    return path.resolve().relative_to(repo_root.resolve()).as_posix()


def _normalize_from_copied_files(copied: dict[SelectedInboxFile, Path], normalized_root: Path) -> list[Path]:
    electra_summary_paths: list[Path] = []
    electra_agency_paths: list[Path] = []
    hotelrunner_paths: list[Path] = []

    for selected, copied_path in copied.items():
        if selected.source == "electra" and selected.report_type == "sales_summary":
            electra_summary_paths.append(copied_path)
        elif selected.source == "electra" and selected.report_type == "sales_by_agency":
            electra_agency_paths.append(copied_path)
        elif selected.source == "hotelrunner" and selected.report_type == "daily_sales":
            hotelrunner_paths.append(copied_path)

    out_paths: list[Path] = []
    if electra_summary_paths:
        out_paths.extend(
            normalize_electra_report_files(
                sorted(electra_summary_paths),
                report_type="sales_summary",
                output_root=normalized_root,
            )
        )
    if electra_agency_paths:
        out_paths.extend(
            normalize_electra_report_files(
                sorted(electra_agency_paths),
                report_type="sales_by_agency",
                output_root=normalized_root,
            )
        )
    if hotelrunner_paths:
        out_paths.extend(normalize_hotelrunner_report_files(sorted(hotelrunner_paths), output_root=normalized_root))

    unique: dict[str, Path] = {}
    for path in out_paths:
        unique[path.resolve().as_posix()] = path.resolve()
    return [unique[k] for k in sorted(unique.keys())]


def ingest_inbox_for_years(
    years: list[int],
    repo_root: Path | None = None,
    inbox_root: Path | None = None,
    raw_runs_root: Path | None = None,
    max_file_size_bytes: int = DEFAULT_MAX_FILE_SIZE_BYTES,
) -> IngestResult:
    """Run strict inbox ingestion and return manifest + normalized output paths."""
    repo = (repo_root or _repo_root()).resolve()
    _assert_within_repo(repo, repo)

    selected_files = scan_and_select_newest(
        years=years,
        repo_root=repo,
        inbox_root=inbox_root,
        require_complete=True,
    )
    validate_selected_files(selected_files, max_file_size_bytes=max_file_size_bytes)

    selected_sorted = sorted(
        selected_files,
        key=lambda s: (s.year, s.source, s.report_type, s.path.name),
    )
    hashes = {selected.path: _sha256_file(selected.path) for selected in selected_sorted}
    run_id = _build_run_id(selected_sorted, hashes=hashes)

    runs_root = (raw_runs_root or (repo / "data" / "raw" / "inbox_run")).resolve()
    _assert_within_repo(runs_root, repo)
    run_root = (runs_root / run_id).resolve()
    _assert_within_repo(run_root, repo)
    run_root.mkdir(parents=True, exist_ok=True)

    copied: dict[SelectedInboxFile, Path] = {}
    selected_manifest: list[dict] = []
    for selected in selected_sorted:
        copied_path = _copy_selected_file(selected=selected, run_root=run_root, repo_root=repo)
        copied[selected] = copied_path
        selected_manifest.append(
            {
                "source": selected.source,
                "report_type": selected.report_type,
                "year": int(selected.year),
                "report_date": selected.report_date.isoformat(),
                "inbox_path": _to_repo_relative(selected.path, repo),
                "copied_path": _to_repo_relative(copied_path, repo),
                "size_bytes": int(selected.size_bytes),
                "sha256": hashes[selected.path],
            }
        )

    normalized_root = (run_root / "normalized").resolve()
    _assert_within_repo(normalized_root, repo)
    normalized_root.mkdir(parents=True, exist_ok=True)
    normalized_outputs = _normalize_from_copied_files(copied=copied, normalized_root=normalized_root)

    manifest = {
        "run_id": run_id,
        "years": [int(y) for y in sorted({int(y) for y in years})],
        "selected_files": selected_manifest,
        "normalization_outputs": [_to_repo_relative(path, repo) for path in normalized_outputs],
    }
    manifest_path = (run_root / "manifest.json").resolve()
    _assert_within_repo(manifest_path, repo)
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    return IngestResult(
        run_id=run_id,
        run_root=run_root,
        manifest_path=manifest_path,
        normalized_root=normalized_root,
        selected_files=selected_sorted,
    )
