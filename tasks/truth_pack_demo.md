WRITE_RAW: truth_pack_demo_readme.md
# Truth Pack Demo

This batch demonstrates deterministic, offline Electra truth-pack generation.

Run command:

python3 scripts/generate_truth_pack.py --outdir outputs/_truth_pack

Expected outputs under `outputs/_truth_pack`:

- index.md
- bundle.txt
- markdown report files
- html report files
END_WRITE_RAW

WRITE_RAW: truth_pack_questions.md
# Curated Truth Pack Questions

1. get me the sales data of 2025
2. get me the sales data of 2026
3. get me the sales data of 2026 and 2025
4. get me the sales categorized by agencies for 2025
5. get me the sales categorized by agencies for 2026
6. compare 2025 vs 2026 by agency
7. sales by month for 2025
8. sales by month for 2026
9. top agencies in 2026
10. share of direct vs agencies in 2025
END_WRITE_RAW

WRITE_RAW: truth_pack_expected_report_headers.md
# Expected Report Headers

- Sales Summary
- Sales By Agency
- Sales By Month
- Top Agencies
- Direct vs Agency Share
END_WRITE_RAW
