WRITE_BLOCK: safe_div.py
PY_CONTRACT: tidy
EXPECT:
- must_contain: "def safe_div("
- forbid: "```"
PROMPT:
Write a tiny python module with:
def safe_div(a: float, b: float) -> float | None
Behavior:
- if b == 0 return None
- otherwise return a / b
Output only python.
END_WRITE_BLOCK
