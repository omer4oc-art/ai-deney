WRITE_BLOCK: electra_mock_sales_summary.py
EXPECT:
  - must_contain: "def add("
  - must_contain: "return a + b"
  - forbid: "```"
PROMPT:
Create a Python script that:
1) uses ai_deney.connectors.electra_mock.ElectraMockConnector
2) fetches sales_summary for 2025 and 2026
3) normalizes to data/normalized
4) writes markdown summary with headers:
   - # Electra Sales Summary
   - Year 2025
   - Year 2026
Output only python.
END_WRITE_BLOCK

WRITE_BLOCK: electra_mock_sales_by_agency.py
EXPECT:
  - must_contain: "def add("
  - must_contain: "return a + b"
  - forbid: "```"
PROMPT:
Create a Python script that:
1) fetches sales_by_agency for 2025 and 2026 from ElectraMockConnector
2) computes grouped totals by agency
3) writes a markdown table with section header:
   - # Sales By Agencies
Include rows for 2025 and 2026.
Output only python.
END_WRITE_BLOCK

WRITE_RAW: electra_mock_expected_headers.md
# Electra Sales Summary
- Year 2025
- Year 2026

# Sales By Agencies
- Agency totals for 2025
- Agency totals for 2026
END_WRITE_RAW

