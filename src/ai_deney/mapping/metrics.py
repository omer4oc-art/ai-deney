"""Deterministic mapping metrics for reconciliation unknown-rate tracking."""

from __future__ import annotations

from pathlib import Path

from ai_deney.reconcile.electra_vs_hotelrunner import reconcile_by_dim_daily, reconcile_by_dim_monthly


def _df_rows(df_or_rows) -> list[dict]:
    if isinstance(df_or_rows, list):
        return [dict(r) for r in df_or_rows]
    if hasattr(df_or_rows, "to_dict"):
        return [dict(r) for r in df_or_rows.to_dict("records")]
    raise TypeError("expected list[dict] or dataframe-like object")


def _unknown_rate_by_year(rows: list[dict], years: list[int]) -> dict[int, float]:
    stats: dict[int, dict[str, int]] = {}
    for year in sorted(set(int(y) for y in years)):
        stats[year] = {"total": 0, "unknown": 0}
    for row in rows:
        year = int(row.get("year", 0) or 0)
        if year not in stats:
            continue
        stats[year]["total"] += 1
        if str(row.get("reason_code") or "").strip() == "UNKNOWN":
            stats[year]["unknown"] += 1
    rates: dict[int, float] = {}
    for year in sorted(stats.keys()):
        total = int(stats[year]["total"])
        unknown = int(stats[year]["unknown"])
        rates[year] = (float(unknown) / float(total)) if total else 0.0
    return rates


def unknown_rate_improvement_by_year(
    years: list[int],
    normalized_root: Path,
    granularity: str = "monthly",
    mapping_agencies_path: Path | None = None,
    mapping_channels_path: Path | None = None,
    mapping_rules_path: Path | None = None,
) -> list[dict]:
    """
    Compare UNKNOWN share before/after canonical mapping for reconcile-by-agency.

    Baseline:
    - raw source-native dimension mode (no canonical mapping)
    Mapped:
    - canonical mapping mode (CSV + deterministic rules)
    """
    years_i = sorted(set(int(y) for y in years))
    granularity_clean = str(granularity or "monthly").strip().lower()
    if granularity_clean not in {"daily", "monthly"}:
        raise ValueError(f"unsupported granularity: {granularity}; expected one of ['daily', 'monthly']")

    recon_fn = reconcile_by_dim_monthly if granularity_clean == "monthly" else reconcile_by_dim_daily
    baseline_rows = _df_rows(
        recon_fn(
            years=years_i,
            dim="agency",
            normalized_root_electra=normalized_root,
            normalized_root_hr=normalized_root,
            mapping_agencies_path=mapping_agencies_path,
            mapping_channels_path=mapping_channels_path,
            mapping_rules_path=mapping_rules_path,
            dim_value_mode="raw",
        )
    )
    mapped_rows = _df_rows(
        recon_fn(
            years=years_i,
            dim="agency",
            normalized_root_electra=normalized_root,
            normalized_root_hr=normalized_root,
            mapping_agencies_path=mapping_agencies_path,
            mapping_channels_path=mapping_channels_path,
            mapping_rules_path=mapping_rules_path,
            dim_value_mode="canonical",
        )
    )

    baseline_rates = _unknown_rate_by_year(baseline_rows, years_i)
    mapped_rates = _unknown_rate_by_year(mapped_rows, years_i)

    out: list[dict] = []
    for year in years_i:
        baseline = float(baseline_rates.get(year, 0.0))
        mapped = float(mapped_rates.get(year, 0.0))
        improvement = ((baseline - mapped) / baseline * 100.0) if baseline > 0 else 0.0
        out.append(
            {
                "year": int(year),
                "baseline_unknown_rate": round(baseline, 4),
                "mapped_unknown_rate": round(mapped, 4),
                "improvement_pct": round(improvement, 2),
            }
        )
    return out
