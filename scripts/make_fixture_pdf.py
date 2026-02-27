#!/usr/bin/env python3
"""Generate deterministic Electra sample PDF fixture."""

from __future__ import annotations

from pathlib import Path


TABLE_LINES = [
    "date|gross_sales|net_sales|currency",
    "2025-12-31|1000.00|900.00|USD",
    "2026-12-31|1300.00|1170.00|USD",
]


def _pdf_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def build_pdf_bytes(lines: list[str]) -> bytes:
    """Build a minimal single-page PDF with deterministic text content."""
    content_parts = [
        "BT",
        "/F1 12 Tf",
        "50 770 Td",
        "(Electra Sales Summary Sample) Tj",
        "0 -20 Td",
    ]
    for idx, line in enumerate(lines):
        if idx > 0:
            content_parts.append("0 -16 Td")
        content_parts.append(f"({_pdf_escape(line)}) Tj")
    content_parts.append("ET")
    content = "\n".join(content_parts) + "\n"
    content_bytes = content.encode("latin-1")

    objects = [
        "1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n",
        "2 0 obj\n<< /Type /Pages /Count 1 /Kids [3 0 R] >>\nendobj\n",
        (
            "3 0 obj\n"
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792]\n"
            "/Resources << /Font << /F1 5 0 R >> >>\n"
            "/Contents 4 0 R >>\n"
            "endobj\n"
        ),
        f"4 0 obj\n<< /Length {len(content_bytes)} >>\nstream\n{content}endstream\nendobj\n",
        "5 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n",
    ]

    out = bytearray()
    out.extend(b"%PDF-1.4\n")
    offsets = [0]
    for obj in objects:
        offsets.append(len(out))
        out.extend(obj.encode("latin-1"))

    xref_offset = len(out)
    out.extend(f"xref\n0 {len(offsets)}\n".encode("latin-1"))
    out.extend(b"0000000000 65535 f \n")
    for off in offsets[1:]:
        out.extend(f"{off:010d} 00000 n \n".encode("latin-1"))
    out.extend(
        (
            "trailer\n"
            f"<< /Size {len(offsets)} /Root 1 0 R >>\n"
            "startxref\n"
            f"{xref_offset}\n"
            "%%EOF\n"
        ).encode("latin-1")
    )
    return bytes(out)


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    out_path = repo_root / "fixtures" / "electra" / "sales_summary_sample.pdf"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(build_pdf_bytes(TABLE_LINES))
    print(out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

