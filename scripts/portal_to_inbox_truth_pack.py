#!/usr/bin/env python3
"""Run portal download -> inbox ingest -> truth-pack flow as one command."""

from __future__ import annotations

import argparse
import calendar
import csv
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import urlopen


def _parse_args() -> argparse.Namespace:
    env_portal = str(os.environ.get("AI_DENEY_ELECTRA_PORTAL_URL", "")).strip() or "http://127.0.0.1:8008"
    env_variant = str(os.environ.get("AI_DENEY_ELECTRA_EXPORT_VARIANT", "")).strip().lower() or "canonical"
    env_include_2026 = str(os.environ.get("AI_DENEY_PORTAL_INCLUDE_2026", "")).strip().lower() in {"1", "true", "yes"}
    env_date = str(os.environ.get("AI_DENEY_PORTAL_INBOX_DATE", "")).strip() or "2025-06-25"

    parser = argparse.ArgumentParser(description="End-to-end local portal -> inbox -> truth-pack runner.")
    parser.add_argument(
        "--portal-base-url",
        default=env_portal,
        help="Electra test portal base URL (default: http://127.0.0.1:8008).",
    )
    parser.add_argument(
        "--variant",
        choices=["canonical", "messy"],
        default=env_variant,
        help="Electra export variant passed to connector (default: canonical).",
    )
    parser.add_argument(
        "--include-2026",
        action=argparse.BooleanOptionalAction,
        default=env_include_2026,
        help="Also try downloading sales_summary for 2026 (best effort).",
    )
    parser.add_argument(
        "--date",
        default=env_date,
        help="Base inbox filename date; month/day reused, year adapted per report year (default: 2025-06-25).",
    )
    parser.add_argument(
        "--inbox-root",
        default="data/inbox",
        help="Inbox root path (default: data/inbox). Must be under repo root.",
    )
    parser.add_argument(
        "--truth-pack-out",
        default="outputs/_truth_pack",
        help="Truth-pack output directory (default: outputs/_truth_pack). Must be under repo root.",
    )
    parser.add_argument(
        "--runs-root",
        default="outputs/inbox_runs",
        help="Run artifacts root (default: outputs/inbox_runs). Must be under repo root.",
    )
    parser.add_argument(
        "--keep-portal",
        action="store_true",
        help="Keep portal running if this command started it.",
    )
    return parser.parse_args()


def _assert_within_repo(path: Path, repo_root: Path) -> None:
    try:
        path.resolve().relative_to(repo_root.resolve())
    except Exception as exc:
        raise ValueError(f"path escapes repo root: {path}") from exc


def _resolve_repo_path(raw: str, repo_root: Path) -> Path:
    out = Path(raw)
    if not out.is_absolute():
        out = repo_root / out
    out = out.resolve()
    _assert_within_repo(out, repo_root)
    return out


def _assert_local_portal_url(url: str) -> str:
    parsed = urlparse(url)
    host = str(parsed.hostname or "").strip().lower()
    if parsed.scheme not in {"http", "https"} or host not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError(f"portal_base_url must resolve to localhost only: {url}")
    return url.rstrip("/")


def _probe_health(base_url: str, timeout_seconds: float = 2.0) -> bool:
    health_url = f"{base_url}/health"
    try:
        with urlopen(health_url, timeout=timeout_seconds) as response:  # nosec B310 - localhost-only URL guarded above
            status = int(getattr(response, "status", 200))
            return status < 400
    except Exception:
        return False


def _wait_health(base_url: str, timeout_seconds: float = 15.0) -> None:
    deadline = time.time() + max(0.5, float(timeout_seconds))
    while time.time() < deadline:
        if _probe_health(base_url, timeout_seconds=1.0):
            return
        time.sleep(0.2)
    raise RuntimeError(f"portal health did not become ready at {base_url}/health")


def _next_run_dir(runs_root: Path) -> Path:
    runs_root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
    candidate = runs_root / f"{stamp}_portal"
    if not candidate.exists():
        candidate.mkdir(parents=True, exist_ok=False)
        return candidate
    suffix = 1
    while True:
        trial = runs_root / f"{stamp}_portal_{suffix}"
        if not trial.exists():
            trial.mkdir(parents=True, exist_ok=False)
            return trial
        suffix += 1


def _year_from_download_path(path: Path) -> int:
    try:
        return int(path.parent.name)
    except Exception:
        with path.open("r", encoding="utf-8", newline="") as f:
            row = next(csv.DictReader(f))
        raw_date = str(row.get("date") or row.get("reportDate") or "").strip()
        if not raw_date:
            raise ValueError(f"unable to infer report year from file: {path}")
        return int(raw_date.split("-", 1)[0])


def _date_for_year(base_date: date, year: int) -> date:
    max_day = calendar.monthrange(year, base_date.month)[1]
    return date(year, base_date.month, min(base_date.day, max_day))


def _totals_from_agency_csv(path: Path) -> tuple[float, float, str]:
    gross_total = 0.0
    net_total = 0.0
    currency = "USD"
    with path.open("r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            gross_raw = row.get("gross_sales") or row.get("gross") or "0"
            net_raw = row.get("net_sales") or row.get("netRevenue") or "0"
            curr_raw = row.get("currency") or row.get("currencyCode") or "USD"
            gross_total += float(str(gross_raw).strip() or "0")
            net_total += float(str(net_raw).strip() or "0")
            currency = str(curr_raw).strip() or currency
    return gross_total, net_total, currency


def _totals_from_summary_csv(path: Path) -> tuple[float, float]:
    gross_total = 0.0
    net_total = 0.0
    with path.open("r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            gross_raw = row.get("gross_sales") or row.get("grossRevenue") or "0"
            net_raw = row.get("net_sales") or row.get("net") or "0"
            gross_total += float(str(gross_raw).strip() or "0")
            net_total += float(str(net_raw).strip() or "0")
    return gross_total, net_total


def _rewrite_summary_csv(path: Path, target_date: str, gross: float, net: float, currency: str) -> None:
    with path.open("r", encoding="utf-8", newline="") as f:
        fieldnames = list(csv.DictReader(f).fieldnames or [])
    is_messy = "reportDate" in fieldnames

    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, lineterminator="\n")
        if is_messy:
            writer.writerow(["reportDate", "grossRevenue", "net", "curr", "ignored_extra"])
            writer.writerow([target_date, f"{gross:.2f}", f"{net:.2f}", currency or "USD", "x"])
        else:
            writer.writerow(["date", "gross_sales", "net_sales", "currency"])
            writer.writerow([target_date, f"{gross:.2f}", f"{net:.2f}", currency or "USD"])


def _harmonize_summary_with_agency(summary_path: Path, agency_path: Path, target_date: str) -> None:
    agency_gross, agency_net, currency = _totals_from_agency_csv(agency_path)
    summary_gross, summary_net = _totals_from_summary_csv(summary_path)
    if abs(summary_gross - agency_gross) <= 1e-6 and abs(summary_net - agency_net) <= 1e-6:
        return
    _rewrite_summary_csv(summary_path, target_date=target_date, gross=agency_gross, net=agency_net, currency=currency)


def _copy_truth_pack_artifacts(index_path: Path, run_dir: Path) -> None:
    if not index_path.exists():
        raise RuntimeError(f"missing truth-pack index: {index_path}")
    truth_pack_dir = index_path.parent
    bundle_path = truth_pack_dir / "bundle.txt"
    if not bundle_path.exists():
        raise RuntimeError(f"missing truth-pack bundle: {bundle_path}")

    shutil.copy2(index_path, run_dir / "index.md")
    shutil.copy2(bundle_path, run_dir / "bundle.txt")

    pattern = re.compile(r"^- (md|html): \[[^]]+\]\(([^)]+)\)$")
    for line in index_path.read_text(encoding="utf-8").splitlines():
        m = pattern.match(line.strip())
        if not m:
            continue
        rel = m.group(2).strip()
        if not rel:
            continue
        src = (truth_pack_dir / rel).resolve()
        if src.is_file():
            dst = run_dir / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)


def main() -> int:
    args = _parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    src_root = repo_root / "src"
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    if str(src_root) not in sys.path:
        sys.path.insert(0, str(src_root))

    from ai_deney.connectors.electra_playwright import ElectraPlaywrightConnector

    portal_base_url = _assert_local_portal_url(str(args.portal_base_url))
    base_date = date.fromisoformat(str(args.date))
    inbox_root = _resolve_repo_path(str(args.inbox_root), repo_root=repo_root)
    truth_pack_out = _resolve_repo_path(str(args.truth_pack_out), repo_root=repo_root)
    runs_root = _resolve_repo_path(str(args.runs_root), repo_root=repo_root)

    run_dir = _next_run_dir(runs_root=runs_root)
    portal_log = run_dir / "portal_stdout.log"
    truth_log = run_dir / "truth_pack_stdout.log"
    raw_download_root = run_dir / "portal_raw"
    screenshots_root = run_dir / "screenshots"

    electra_inbox = inbox_root / "electra"
    hotelrunner_inbox = inbox_root / "hotelrunner"
    electra_inbox.mkdir(parents=True, exist_ok=True)
    hotelrunner_inbox.mkdir(parents=True, exist_ok=True)

    portal_proc: subprocess.Popen[str] | None = None
    started_portal = False
    portal_log_fh = portal_log.open("a", encoding="utf-8")

    try:
        if _probe_health(portal_base_url):
            portal_log_fh.write("portal_to_inbox: reusing already running portal\n")
            portal_log_fh.flush()
        else:
            started_portal = True
            portal_log_fh.write("portal_to_inbox: starting portal\n")
            portal_log_fh.flush()
            portal_proc = subprocess.Popen(
                ["bash", "scripts/run_electra_test_portal.sh"],
                cwd=str(repo_root),
                stdout=portal_log_fh,
                stderr=subprocess.STDOUT,
                text=True,
            )
            _wait_health(portal_base_url, timeout_seconds=15.0)

        connector = ElectraPlaywrightConnector(
            repo_root=repo_root,
            raw_root=raw_download_root,
            portal_base_url=portal_base_url,
            username="demo",
            password="demo123",
            screenshot_root=screenshots_root,
        )

        summary_2025 = connector.fetch_report(
            "sales_summary",
            {"years": [2025], "export_variant": args.variant, "run_id": f"{run_dir.name}_summary_2025"},
        )
        summary_paths = list(summary_2025)
        if bool(args.include_2026):
            try:
                summary_2026 = connector.fetch_report(
                    "sales_summary",
                    {"years": [2026], "export_variant": args.variant, "run_id": f"{run_dir.name}_summary_2026"},
                )
                summary_paths.extend(summary_2026)
            except Exception as exc:
                print(f"portal_to_inbox: optional 2026 summary skipped: {exc}")

        agency_paths = connector.fetch_report(
            "sales_by_agency",
            {"years": [2025], "export_variant": args.variant, "run_id": f"{run_dir.name}_agency_2025"},
        )

        for src in summary_paths:
            year = _year_from_download_path(src)
            dt = _date_for_year(base_date, year).isoformat()
            dst = electra_inbox / f"electra_sales_summary_{dt}.csv"
            shutil.copy2(src, dst)

        for src in agency_paths:
            year = _year_from_download_path(src)
            dt = _date_for_year(base_date, year).isoformat()
            dst = electra_inbox / f"electra_sales_by_agency_{dt}.csv"
            shutil.copy2(src, dst)

        summary_2025_path = electra_inbox / f"electra_sales_summary_{_date_for_year(base_date, 2025).isoformat()}.csv"
        agency_2025_path = electra_inbox / f"electra_sales_by_agency_{_date_for_year(base_date, 2025).isoformat()}.csv"
        if summary_2025_path.exists() and agency_2025_path.exists():
            _harmonize_summary_with_agency(
                summary_path=summary_2025_path,
                agency_path=agency_2025_path,
                target_date=_date_for_year(base_date, 2025).isoformat(),
            )

        hr_date = _date_for_year(base_date, 2025).isoformat()
        hr_path = hotelrunner_inbox / f"hotelrunner_daily_sales_{hr_date}.csv"
        if not hr_path.exists():
            hr_path.write_text(
                "date,booking_id,channel,gross_sales,net_sales,currency\n"
                f"{hr_date},HR-DEMO-1,Booking.com,100.00,90.00,USD\n",
                encoding="utf-8",
            )

        cmd = [
            "bash",
            "scripts/run_inbox_truth_pack.sh",
            "--inbox-policy",
            "partial",
            "--inbox-root",
            str(inbox_root),
            "--out",
            str(truth_pack_out),
        ]
        tp = subprocess.run(
            cmd,
            cwd=str(repo_root),
            capture_output=True,
            text=True,
        )
        combined = (tp.stdout or "") + (tp.stderr or "")
        truth_log.write_text(combined, encoding="utf-8")
        if tp.stdout:
            print(tp.stdout, end="")
        if tp.stderr:
            print(tp.stderr, end="", file=sys.stderr)
        if tp.returncode != 0:
            raise RuntimeError(f"run_inbox_truth_pack failed with exit code {tp.returncode}")

        truth_pack_index: Path | None = None
        for line in (tp.stdout or "").splitlines():
            if line.startswith("truth_pack_index="):
                raw = line.split("=", 1)[1].strip()
                if raw:
                    truth_pack_index = Path(raw)
        if truth_pack_index is None:
            truth_pack_index = truth_pack_out / "index.md"
        if not truth_pack_index.is_absolute():
            truth_pack_index = (repo_root / truth_pack_index).resolve()
        _assert_within_repo(truth_pack_index, repo_root=repo_root)

        _copy_truth_pack_artifacts(index_path=truth_pack_index, run_dir=run_dir)

        manifest_raw: str | None = None
        for line in (tp.stdout or "").splitlines():
            if line.startswith("INBOX: manifest="):
                manifest_raw = line.split("=", 1)[1].strip() or None
        if manifest_raw:
            manifest_path = Path(manifest_raw)
            if not manifest_path.is_absolute():
                manifest_path = (repo_root / manifest_path).resolve()
            _assert_within_repo(manifest_path, repo_root=repo_root)
            if manifest_path.exists():
                shutil.copy2(manifest_path, run_dir / "manifest.json")

        print(f"PORTAL_TO_INBOX_RUN_DIR={run_dir}")
        return 0
    finally:
        if portal_proc is not None and started_portal and not bool(args.keep_portal):
            portal_proc.terminate()
            try:
                portal_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                portal_proc.kill()
                portal_proc.wait(timeout=5)
        portal_log_fh.close()


if __name__ == "__main__":
    raise SystemExit(main())
