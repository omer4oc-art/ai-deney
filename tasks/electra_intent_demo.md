WRITE_BLOCK: electra_intent_q1_report.md
EXPECT:
  - forbid: "```"
PROMPT:
Produce a markdown report for this question:
"get me the sales data of 2026 and 2025"
Output should include a short summary paragraph and a markdown table.
END_WRITE_BLOCK

WRITE_BLOCK: electra_intent_q2_report.md
EXPECT:
  - forbid: "```"
PROMPT:
Produce a markdown report for this question:
"get me the sales categorized by agencies for 2025"
Output should include a short summary paragraph and a markdown table.
END_WRITE_BLOCK

WRITE_BLOCK: electra_intent_q3_report.md
EXPECT:
  - forbid: "```"
PROMPT:
Produce a markdown report for this question:
"compare 2025 vs 2026 by agency"
Output should include a short comparison paragraph and a markdown table.
END_WRITE_BLOCK
