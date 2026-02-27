WRITE_BLOCK: ok.py
PY_CONTRACT: tidy
EXPECT:
- must_contain: "def ok("
- forbid: "```"
PROMPT:
Write a tiny python module with exactly one function:
def ok() -> int:
    return 1
Output only python.
END_WRITE_BLOCK
