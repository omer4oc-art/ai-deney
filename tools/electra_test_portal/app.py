"""Tiny local Electra portal for deterministic login/report-download automation tests."""

from __future__ import annotations

import csv
import io
from typing import Any

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse, Response

APP_USERNAME = "demo"
APP_PASSWORD = "demo123"
SESSION_COOKIE = "electra_portal_auth"

_SUPPORTED_REPORTS = {"sales_summary", "sales_by_agency"}
_SUPPORTED_VARIANTS = {"canonical", "messy"}

app = FastAPI(title="Electra Test Portal", version="0.1.0")


def _parse_years(raw_years: list[str] | None, raw_csv_years: str | None) -> list[int]:
    out: set[int] = set()
    for item in raw_years or []:
        text = str(item or "").strip()
        if not text:
            continue
        out.add(int(text))
    if raw_csv_years:
        for token in str(raw_csv_years).split(","):
            text = token.strip()
            if not text:
                continue
            out.add(int(text))
    years = sorted(out)
    if not years:
        raise ValueError("at least one year is required")
    return years


def _summary_rows(year: int) -> list[dict[str, str]]:
    return [
        {
            "date": f"{year}-01-01",
            "gross_sales": "100.00",
            "net_sales": "90.00",
            "currency": "USD",
        },
        {
            "date": f"{year}-01-02",
            "gross_sales": "120.00",
            "net_sales": "108.00",
            "currency": "USD",
        },
    ]


def _agency_rows(year: int) -> list[dict[str, str]]:
    return [
        {
            "date": f"{year}-01-01",
            "agency_id": "AG001",
            "agency_name": "Atlas Partners",
            "gross_sales": "80.00",
            "net_sales": "72.00",
            "currency": "USD",
        },
        {
            "date": f"{year}-01-01",
            "agency_id": "DIRECT",
            "agency_name": "Direct Channel",
            "gross_sales": "20.00",
            "net_sales": "18.00",
            "currency": "USD",
        },
    ]


def _render_csv(report_type: str, years: list[int], variant: str) -> str:
    rows: list[dict[str, str]] = []
    for year in years:
        if report_type == "sales_summary":
            rows.extend(_summary_rows(year))
        elif report_type == "sales_by_agency":
            rows.extend(_agency_rows(year))
        else:
            raise ValueError(f"unsupported report_type: {report_type}")

    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\n")

    if report_type == "sales_summary":
        if variant == "messy":
            writer.writerow(["reportDate", "grossRevenue", "net", "curr", "ignored_extra"])
            for row in rows:
                writer.writerow([row["date"], row["gross_sales"], row["net_sales"], row["currency"], "x"])
        else:
            writer.writerow(["date", "gross_sales", "net_sales", "currency"])
            for row in rows:
                writer.writerow([row["date"], row["gross_sales"], row["net_sales"], row["currency"]])

    elif report_type == "sales_by_agency":
        if variant == "messy":
            writer.writerow(["dateValue", "agentId", "agency", "gross", "netRevenue", "currencyCode", "extra_col"])
            for row in rows:
                writer.writerow(
                    [
                        row["date"],
                        row["agency_id"],
                        row["agency_name"],
                        row["gross_sales"],
                        row["net_sales"],
                        row["currency"],
                        "x",
                    ]
                )
        else:
            writer.writerow(["date", "agency_id", "agency_name", "gross_sales", "net_sales", "currency"])
            for row in rows:
                writer.writerow(
                    [
                        row["date"],
                        row["agency_id"],
                        row["agency_name"],
                        row["gross_sales"],
                        row["net_sales"],
                        row["currency"],
                    ]
                )

    return output.getvalue()


def _is_authed(request: Request) -> bool:
    return request.cookies.get(SESSION_COOKIE) == "1"


def _login_page(error: str = "") -> str:
    msg = f"<p style='color:#b00'>{error}</p>" if error else ""
    return (
        "<!doctype html><html><body>"
        "<h1>Electra Test Portal Login</h1>"
        f"{msg}"
        "<form method='post' action='/login'>"
        "<label>Username <input name='username' /></label><br />"
        "<label>Password <input type='password' name='password' /></label><br />"
        "<button type='submit' id='login-submit'>Login</button>"
        "</form>"
        "</body></html>"
    )


def _reports_page() -> str:
    return (
        "<!doctype html><html><body>"
        "<h1>Electra Reports</h1>"
        "<form method='post' action='/reports/download'>"
        "<label>Report <select name='report_type'>"
        "<option value='sales_summary'>sales_summary</option>"
        "<option value='sales_by_agency'>sales_by_agency</option>"
        "</select></label><br />"
        "<label>Years (comma separated) <input name='years' value='2025' /></label><br />"
        "<label>Variant <select name='variant'>"
        "<option value='canonical'>canonical</option>"
        "<option value='messy'>messy</option>"
        "</select></label><br />"
        "<button type='submit' id='download-submit'>Download CSV</button>"
        "</form>"
        "</body></html>"
    )


@app.get("/health")
def health() -> dict[str, Any]:
    return {"ok": True, "service": "electra_test_portal"}


@app.get("/login", response_class=HTMLResponse)
def login_get() -> str:
    return _login_page()


@app.post("/login")
def login_post(username: str = Form(...), password: str = Form(...)) -> Response:
    if username != APP_USERNAME or password != APP_PASSWORD:
        return HTMLResponse(_login_page(error="Invalid credentials"), status_code=401)

    resp = RedirectResponse(url="/reports", status_code=303)
    resp.set_cookie(SESSION_COOKIE, "1", httponly=True, samesite="lax")
    return resp


@app.get("/reports", response_class=HTMLResponse)
def reports_get(request: Request) -> Response:
    if not _is_authed(request):
        return RedirectResponse(url="/login", status_code=303)
    return HTMLResponse(_reports_page())


@app.post("/reports/download")
def reports_download(
    request: Request,
    report_type: str = Form(...),
    years: str = Form(""),
    variant: str = Form("canonical"),
) -> Response:
    if not _is_authed(request):
        return PlainTextResponse("unauthorized", status_code=401)

    report_type = str(report_type).strip()
    if report_type not in _SUPPORTED_REPORTS:
        return PlainTextResponse(f"unsupported report_type: {report_type}", status_code=400)

    variant = str(variant).strip().lower() or "canonical"
    if variant not in _SUPPORTED_VARIANTS:
        return PlainTextResponse(f"unsupported variant: {variant}", status_code=400)

    try:
        years_list = _parse_years(raw_years=None, raw_csv_years=years)
    except Exception as exc:
        return PlainTextResponse(f"invalid years: {exc}", status_code=400)

    csv_text = _render_csv(report_type=report_type, years=years_list, variant=variant)
    year_span = f"{min(years_list)}-{max(years_list)}"
    filename = f"electra_{report_type}_{year_span}.csv"
    headers = {"Content-Disposition": f"attachment; filename={filename}"}
    return Response(content=csv_text, media_type="text/csv", headers=headers)
