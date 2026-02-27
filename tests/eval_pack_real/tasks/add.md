WRITE_BLOCK: add.py
PY_CONTRACT: tidy
EXPECT:
- must_contain: "def add("
- forbid: "```"
PROMPT:
Write a tiny python module with:
def add(a: int, b: int) -> int:
    return a + b
Output only python.
END_WRITE_BLOCK
