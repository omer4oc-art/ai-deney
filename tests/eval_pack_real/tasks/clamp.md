WRITE_BLOCK: clamp.py
PY_CONTRACT: tidy
EXPECT:
- must_contain: "def clamp("
- forbid: "```"
PROMPT:
Write a tiny python module with:
def clamp(x: float, lo: float, hi: float) -> float
Behavior:
- return lo if x < lo
- return hi if x > hi
- otherwise return x
Output only python.
END_WRITE_BLOCK
