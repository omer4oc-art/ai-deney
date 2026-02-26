import argparse
import ast
import json
import re
import shlex
import subprocess
import os
import py_compile
import traceback
from datetime import datetime
from pathlib import Path

from memory import memory_as_context
from run_logger import log_run
from file_tools import read_text



CODE_CONTRACT_PY = """Output ONLY valid Python code. No markdown. No prose. No triple backticks.
Requirements:
- Include docstring + type hints.
- Include input validation (raise ValueError/TypeError).
- If you are unsure about an API, do NOT guess. Prefer the simplest correct approach.
- If you cannot complete the task, output a Python file that raises RuntimeError explaining what is missing.
"""
PY_CONTRACT_MARKER = "__PY_CONTRACT__:"
_STUB_MODEL_FIXTURE = ""
_KNOWN_STUB_FIXTURES = {
    "good_py_add",
    "bad_then_good_py",
    "ast_todo_then_good",
    "dupdef_then_good",
    "tidy_weird_then_good",
}


def _live_generate(prompt: str, stream: bool = False) -> str:
    from ollama_client import generate as _ollama_generate
    return _ollama_generate(prompt, stream=stream)


def generate(prompt: str, stream: bool = False) -> str:
    # Compatibility wrapper used by existing tests that monkeypatch `batch_agent.generate`.
    return _live_generate(prompt, stream=stream)


def _stub_model_generate(fixture: str, attempt: int) -> str:
    fx = (fixture or "").strip()
    a = max(0, int(attempt or 0))
    if fx == "good_py_add":
        return "def add(a: int, b: int) -> int:\n    return a + b\n"
    if fx == "bad_then_good_py":
        if a == 0:
            return "def x(:\n    pass\n"
        return "def ok() -> int:\n    return 1\n"
    if fx == "ast_todo_then_good":
        if a == 0:
            return "def ok() -> int:\n    # TODO: cleanup\n    return 1\n"
        return "def ok() -> int:\n    return 1\n"
    if fx == "dupdef_then_good":
        if a == 0:
            return (
                "def ok() -> int:\n"
                "    return 1\n"
                "# def ok():\n"
                "#     raise RuntimeError('cannot')\n"
            )
        return "def ok() -> int:\n    return 1\n"
    if fx == "tidy_weird_then_good":
        if a == 0:
            return (
                "def ok() -> int:\n"
                "    if not True:\n"
                "        return 0\n"
                "    if not isinstance((), tuple):\n"
                "        return -1\n"
                "    x = 'never be reached'\n"
                "    return 1\n"
            )
        return "def ok() -> int:\n    return 1\n"
    raise ValueError(f"unknown --stub-model fixture: {fixture}")


def _generate_adapter(prompt: str, stream: bool = False, attempt: int = 0) -> str:
    if _STUB_MODEL_FIXTURE:
        return _stub_model_generate(_STUB_MODEL_FIXTURE, attempt)
    return generate(prompt, stream=stream)


def _run_json_agent_adapter(task: str, strict: bool, verify: bool, bullets_n: int | None):
    from agent_json import run as _run_json
    return _run_json(task, strict=strict, verify=verify, bullets_n=bullets_n)


def _run_memory_agent_adapter(task: str, context: str):
    from memory_agent import run as _run_memory
    return _run_memory(task, context=context)

def _slug(s: str, max_len: int = 60) -> str:
    s = s.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return (s[:max_len].rstrip("-")) or "task"


def _parse_task_line(line: str) -> tuple[str | None, str]:
    """
    Supports:
      - normal task line
      - FILE=path task...
      - WRITE=relpath task...
    Returns: (directive_or_none, task_text)
      directive is one of:
        - None
        - "FILE:<path>"
        - "WRITE:<relpath>"
    """
    line = line.strip()
    if not line or line.startswith("#"):
        return None, ""

    parts = shlex.split(line)
    if not parts:
        return None, ""

    head = parts[0].strip()

    def _extract_path(kind: str) -> tuple[str | None, list[str]]:
        eq_prefix = f"{kind}="
        col_prefix = f"{kind}:"
        if head.startswith(eq_prefix):
            rel = head.split("=", 1)[1].strip()
            return rel, parts[1:]
        if head == col_prefix:
            if len(parts) < 2:
                return "", []
            return parts[1].strip(), parts[2:]
        if head.startswith(col_prefix):
            rel = head.split(":", 1)[1].strip()
            return rel, parts[1:]
        return None, []

    rel, rest = _extract_path("WRITE_BLOCK")
    if rel is not None:
        if rel.endswith(":"):
            rel = rel[:-1]
        task_text = " ".join(rest).strip() or "Write the requested file."
        return f"WRITE_BLOCK:{rel}", task_text

    rel, rest = _extract_path("WRITE")
    if rel is not None:
        if rel.endswith(":"):
            rel = rel[:-1]
        task_text = " ".join(rest).strip() or "Write the requested file."
        return f"WRITE:{rel}", task_text

    rel, rest = _extract_path("WRITE_RAW")
    if rel is not None:
        if rel.endswith(":"):
            rel = rel[:-1]
        task_text = " ".join(rest).strip() or "Write raw file contents."
        return f"WRITE_RAW:{rel}", task_text

    path, rest = _extract_path("FILE")
    if path is not None:
        if path.endswith(":"):
            path = path[:-1]
        task_text = " ".join(rest).strip() or "Summarize the file."
        return f"FILE:{path}", task_text

    return None, line


def _inject_py_contract_marker(text: str, contract_name: str) -> str:
    c = (contract_name or "").strip().lower()
    if not c:
        return text
    marker = f"{PY_CONTRACT_MARKER}{c}\n"
    return marker + (text or "")


def _extract_py_contract_marker(text: str) -> tuple[str, str]:
    lines = (text or "").splitlines()
    out: list[str] = []
    contract = ""
    consumed = False
    for raw in lines:
        s = raw.strip()
        if not consumed and s.lower().startswith(PY_CONTRACT_MARKER.lower()):
            contract = s.split(":", 1)[1].strip().lower()
            consumed = True
            continue
        out.append(raw)
    cleaned = "\n".join(out).rstrip() + ("\n" if text.endswith("\n") and out else "")
    return contract, cleaned


def _load_tasks(path: str, tasks_format: str = "blocks") -> list[tuple[str | None, str]]:
    text = read_text(path, max_chars=300_000)
    lines = text.splitlines()
    tasks: list[tuple[str | None, str]] = []
    current_py_contract = ""
    fmt = (tasks_format or "blocks").strip().lower()
    if fmt not in {"blocks", "lines"}:
        raise ValueError(f"unsupported tasks format: {tasks_format}")
    if fmt == "lines":
        for raw in lines:
            s = raw.strip()
            if s.upper().startswith("WRITE_BLOCK") or s.upper() == "END_WRITE_BLOCK":
                raise ValueError("WRITE_BLOCK not supported in --tasks-format=lines")
    i = 0
    while i < len(lines):
        raw = lines[i]
        m_contract = re.match(r"^\s*PY_CONTRACT\s*:\s*([A-Za-z0-9_-]+)\s*$", raw.strip(), flags=re.IGNORECASE)
        if m_contract:
            val = m_contract.group(1).strip().lower()
            if val in {"strict", "tidy"}:
                current_py_contract = val
            i += 1
            continue

        directive, task = _parse_task_line(raw)
        if not task:
            i += 1
            continue

        if isinstance(directive, str) and directive.startswith("WRITE_BLOCK:"):
            rel = directive.split(":", 1)[1]
            buf = []
            i += 1
            while i < len(lines) and lines[i].strip() != "END_WRITE_BLOCK":
                buf.append(lines[i])
                i += 1
            if i < len(lines) and lines[i].strip() == "END_WRITE_BLOCK":
                i += 1
            body = "\n".join(buf).rstrip() + "\n"
            if current_py_contract in {"strict", "tidy"} and rel.lower().endswith(".py"):
                body = _inject_py_contract_marker(body, current_py_contract)
                current_py_contract = ""
            tasks.append((f"WRITE_BLOCK:{rel}", body))
            continue

        if isinstance(directive, str) and directive.startswith("WRITE_RAW:"):
            rel = directive.split(":", 1)[1]
            buf = []
            i += 1
            while i < len(lines) and lines[i].strip() != "END_WRITE_RAW":
                buf.append(lines[i])
                i += 1
            if i < len(lines) and lines[i].strip() == "END_WRITE_RAW":
                i += 1
            body = "\n".join(buf).rstrip() + "\n"
            if current_py_contract in {"strict", "tidy"} and rel.lower().endswith(".py"):
                body = _inject_py_contract_marker(body, current_py_contract)
                current_py_contract = ""
            tasks.append((f"WRITE_RAW:{rel}", body))
            continue

        if isinstance(directive, str) and directive.startswith("WRITE:"):
            rel = directive.split(":", 1)[1]
            if current_py_contract in {"strict", "tidy"} and rel.lower().endswith(".py"):
                task = _inject_py_contract_marker(task, current_py_contract)
                current_py_contract = ""

        tasks.append((directive, task))
        i += 1
    return tasks
def _render_md(title: str, bullets: list[str]) -> str:
    title = (title or "").strip()
    lines = []
    if title:
        lines.append(f"# {title}")
        lines.append("")
    for b in bullets or []:
        b = str(b).strip()
        if b:
            lines.append(f"- {b}")
    return "\n".join(lines).strip() + "\n"


def _extract_from_md(md_text: str) -> tuple[str, list[str]]:
    title = ""
    bullets: list[str] = []
    for line in md_text.splitlines():
        line = line.rstrip()
        if not title and line.startswith("#"):
            title = line.lstrip("#").strip()
        if line.startswith("- "):
            b = line[2:].strip()
            if b:
                bullets.append(b)
    return title, bullets



def _flush_index(outdir: Path, index_lines: list[str]) -> None:
    try:
        index_path = outdir / "index.md"
        index_path.write_text("\n".join(index_lines).strip() + "\n", encoding="utf-8")
    except Exception:
        # never let index writing crash the batch
        pass

def _open_in_vscode(path: Path) -> None:
    try:
        subprocess.run(["code", str(path)], check=False)
    except Exception:
        pass


def _find_latest_next_tasks() -> str:
    root = Path("outputs")
    if not root.exists():
        return ""
    batches = sorted(root.glob("batch-*"), key=lambda p: p.name, reverse=True)
    for b in batches:
        cand = b / "next_tasks.txt"
        if cand.exists():
            return str(cand)
    return ""


def _write_generated_file(outdir: Path, rel_path: str, content: str) -> Path:
    rel = rel_path.strip().lstrip("/").replace("..", "_")
    gen_root = outdir / "generated"
    target = gen_root / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content.rstrip() + "\n", encoding="utf-8")
    return target


# ----------------------------
# Topic guard (heuristic)
# ----------------------------
STOPWORDS = {
    "the","a","an","and","or","to","of","in","on","for","with","is","are","was","were",
    "be","as","at","by","from","this","that","it","its","your","you","we","our","i",
    "explain","summarize","rewrite","provide","include","add","make","give","why","how",
    "simple","terms","bullets","bullet","points","point","paragraph","use","uses","usage",
    "compare","difference","differences","between","about"
}
DRIFT_WORDS = {
    "ingredient","ingredients","nutrition","nutritional","calorie","calories","sugar",
    "caffeine","aspartame","hfcs","corn syrup","allergen","allergens","preservative",
    "label","packaging","mg","grams","serving"
}
def _keywords(text: str) -> set[str]:
    text = text.lower()
    words = re.findall(r"[a-z0-9]+", text)
    return {w for w in words if len(w) >= 3 and w not in STOPWORDS}

def topic_guard(task_text: str, output_title: str, output_bullets: list[str]) -> tuple[bool, str]:
    task_keys = _keywords(task_text)
    out_text = (output_title or "") + " " + " ".join(output_bullets or [])
    out_text_l = out_text.lower()
    out_keys = _keywords(out_text)

    if not task_keys:
        return False, "no task keywords"

    overlap = task_keys.intersection(out_keys)
    overlap_ratio = len(overlap) / max(1, len(task_keys))
    drift_hits = [w for w in DRIFT_WORDS if w in out_text_l]

    too_low_overlap = overlap_ratio < 0.15 and len(overlap) <= 1
    has_drift = len(drift_hits) >= 2

    if too_low_overlap and has_drift:
        return True, f"low keyword overlap ({len(overlap)}/{len(task_keys)}); drift: {', '.join(drift_hits[:6])}"
    return False, f"ok overlap ({len(overlap)}/{len(task_keys)})"




def _parse_expect_prompt_block(block_text: str) -> tuple[list[str], list[str], str, str]:
    """
    Parse EXPECT:/PROMPT: sections from a WRITE_BLOCK body.

    Format:
      EXPECT:
      - must_contain: <text>
      - forbid: <text>
      PROMPT:
      <multiline prompt>
      END_WRITE_BLOCK (handled by _load_tasks)

    Returns: (must_contain, forbid, prompt, py_contract)
    If EXPECT:/PROMPT: not present, returns ([], [], original_text).
    """
    text = (block_text or "").replace("\r\n", "\n").replace("\r", "\n")
    marker_contract, text = _extract_py_contract_marker(text)
    py_contract = marker_contract

    if "EXPECT:" not in text:
        return [], [], text, py_contract

    lines = text.splitlines()
    must: list[str] = []
    forbid: list[str] = []
    prompt_lines: list[str] = []
    mode = None  # None | "expect" | "prompt"

    def norm_item(raw: str) -> str:
        x = raw.strip()
        if x.startswith("- "):
            x = x[2:].strip()
        return x

    for raw in lines:
        line = raw.strip()
        if line == "EXPECT:":
            mode = "expect"
            continue
        if line == "PROMPT:":
            mode = "prompt"
            continue
        if line.lower().startswith("py_contract:"):
            v = line.split(":", 1)[1].strip().lower()
            if v in {"strict", "tidy"}:
                py_contract = v
            continue

        if mode == "expect":
            item = norm_item(raw)
            low = item.lower()
            if low.startswith("must_contain:"):
                val = item.split(":", 1)[1].strip()
                if val:
                    must.append(val)
            elif low.startswith("forbid:"):
                val = item.split(":", 1)[1].strip()
                if val:
                    forbid.append(val)
            else:
                continue
        elif mode == "prompt":
            prompt_lines.append(raw)

    prompt = "\n".join(prompt_lines).rstrip() + ("\n" if prompt_lines else "")
    if not prompt:
        return must, forbid, text, py_contract
    return must, forbid, prompt, py_contract


def _normalize_expectation_value(raw: str) -> str:
    v = (raw or "").strip()
    if len(v) >= 2 and ((v[0] == "'" and v[-1] == "'") or (v[0] == '"' and v[-1] == '"')):
        return v[1:-1]
    return v


def _expectations_gate_text(text: str, must_contain: list[str], forbid: list[str]) -> tuple[bool, str]:
    """
    Simple per-task expectations: substring must_contain / forbid.
    Returns (ok, message).
    """
    txt = text or ""
    must_clean = [_normalize_expectation_value(m) for m in (must_contain or []) if str(m).strip()]
    forbid_clean = [_normalize_expectation_value(f) for f in (forbid or []) if str(f).strip()]

    missing = [m for m in must_clean if m not in txt]
    present_forbid = [f for f in forbid_clean if f in txt]

    if missing:
        return False, "missing required substrings: " + ", ".join(repr(x) for x in missing)
    if present_forbid:
        return False, "found forbidden substrings: " + ", ".join(repr(x) for x in present_forbid)
    return True, "expectations ok"


def _expectation_failures(text: str, must_contain: list[str], forbid: list[str]) -> list[str]:
    txt = text or ""
    must_clean = [_normalize_expectation_value(m) for m in (must_contain or []) if str(m).strip()]
    forbid_clean = [_normalize_expectation_value(f) for f in (forbid or []) if str(f).strip()]
    failures: list[str] = []

    for m in must_clean:
        if m not in txt:
            failures.append(f"EXPECT_MISSING|{repr(m)}")
    for f in forbid_clean:
        if f in txt:
            failures.append(f"EXPECT_FORBID_HIT|{repr(f)}")
    return failures


def _expectations_gate(py_path: Path, must_contain: list[str], forbid: list[str]) -> tuple[bool, str]:
    try:
        txt = py_path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return False, f"could not read file: {e}"
    return _expectations_gate_text(txt, must_contain, forbid)


def _lint_python_file(py_path: Path) -> tuple[bool, str]:
    """Return (ok, message)."""
    try:
        py_compile.compile(str(py_path), doraise=True)
        return True, "py_compile ok"
    except Exception as e:
        return False, str(e)


def _lint_python_source(source: str) -> tuple[bool, str]:
    try:
        compile(source, "<generated>", "exec")
        return True, "compile ok"
    except Exception as e:
        return False, str(e)


def _lint_python_source_with_traceback(source: str) -> tuple[bool, str]:
    try:
        compile(source, "<generated>", "exec")
        return True, "compile ok"
    except Exception:
        tb = traceback.format_exc().strip()
        if tb:
            return False, tb
        return False, "compile error"


def _ast_quality_gate_text(text: str) -> tuple[bool, str]:
    try:
        tree = ast.parse(text)
    except Exception as e:
        return False, f"AST_PARSE_FAILED|{e}"

    issues: list[str] = []
    if re.search(r"\bTODO\b", text, flags=re.IGNORECASE):
        issues.append("AST_TODO_FOUND")

    top_level_def_or_class_names: set[str] = set()
    saw_def_or_class = False
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            top_level_def_or_class_names.add(node.name)

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            saw_def_or_class = True
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if len(node.body) == 1 and isinstance(node.body[0], ast.Pass):
                issues.append(f"AST_PASS_ONLY_FUNCTION|{node.name}")

    if not saw_def_or_class:
        issues.append("AST_NO_DEFS_OR_CLASSES")

    # Block commented-out duplicate top-level defs/classes (e.g. "# def ok(...)" when def ok exists).
    if top_level_def_or_class_names:
        pat_def = re.compile(r"^\s*#\s*def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(")
        pat_cls = re.compile(r"^\s*#\s*class\s+([A-Za-z_][A-Za-z0-9_]*)\s*[:\(]")
        for raw_line in text.splitlines():
            m_def = pat_def.match(raw_line)
            if m_def:
                name = m_def.group(1)
                if name in top_level_def_or_class_names:
                    issues.append(f"AST_COMMENTED_OUT_DUPLICATE_DEF|{name}")
                continue
            m_cls = pat_cls.match(raw_line)
            if m_cls:
                name = m_cls.group(1)
                if name in top_level_def_or_class_names:
                    issues.append(f"AST_COMMENTED_OUT_DUPLICATE_DEF|{name}")

    if issues:
        uniq = sorted(set(issues))
        return False, "\n".join(uniq)
    return True, "ast quality ok"


def _ast_quality_gate(py_path: Path) -> tuple[bool, str]:
    try:
        text = py_path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return False, f"could not read file: {e}"
    return _ast_quality_gate_text(text)


def _run_python_file_gates(py_path: Path) -> tuple[bool, str]:
    try:
        text = py_path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return False, f"PY_READ_FAILED|{e}"
    ok, failures = _evaluate_python_quality_text(
        text=text,
        must_contain=[],
        forbid=[],
        extra_gate=_ast_quality_gate_text,
    )
    if not ok:
        return False, "\n".join(failures)
    return True, "python gates ok"


def _evaluate_python_quality_text(
    text: str,
    must_contain: list[str],
    forbid: list[str],
    extra_gate=None,
) -> tuple[bool, list[str]]:
    failures: list[str] = []

    ok, compile_msg = _lint_python_source_with_traceback(text)
    if not ok:
        failures.append(f"PY_COMPILE_FAILED|{compile_msg}")
        return False, failures

    expect_failures = _expectation_failures(text, must_contain, forbid)
    if expect_failures:
        failures.extend(expect_failures)
        return False, failures

    if callable(extra_gate):
        ok_extra, msg_extra = extra_gate(text)
        if not ok_extra:
            for line in (msg_extra or "").splitlines():
                s = line.strip()
                if s:
                    failures.append(s)
            if not failures:
                failures.append("PY_QUALITY_FAILED|unknown")
            return False, failures

    return True, []


def _failure_codes(failures: list[str]) -> list[str]:
    out: list[str] = []
    for f in failures or []:
        s = str(f).strip()
        if not s:
            continue
        code = s.split("|", 1)[0].strip()
        if code and code not in out:
            out.append(code)
    return out


def _merge_unique(items: list[str], extra: list[str]) -> list[str]:
    out: list[str] = []
    for x in (items or []) + (extra or []):
        s = str(x).strip()
        if s and s not in out:
            out.append(s)
    return out


def _contract_forbid(contract_name: str) -> list[str]:
    c = (contract_name or "").strip().lower()
    if c == "strict":
        return ["```"]
    if c == "tidy":
        return ["if not True", "never be reached", "isinstance((), tuple)"]
    return []


def _generate_python_with_repair(
    user_prompt: str,
    rel_path: str,
    must_contain: list[str],
    forbid: list[str],
    max_repairs: int,
    initial_text: str = "",
    extra_gate=None,
) -> tuple[str, bool, str, int, str]:
    """
    Generate python and auto-repair on quality failures.
    Returns (final_text, ok, last_message, model_calls, gate_summary).
    """
    prompt = (user_prompt or "").strip()
    retries = max(0, int(max_repairs or 0))
    model_calls = 0
    last_text = ""
    last_failures: list[str] = []
    summary_parts: list[str] = []

    if initial_text:
        candidate = _strip_code_fences(initial_text)
        ok, failures = _evaluate_python_quality_text(
            text=candidate,
            must_contain=must_contain,
            forbid=forbid,
            extra_gate=extra_gate,
        )
        if ok:
            return candidate, True, "QUALITY_OK", model_calls, "attempt 0: PASS; final: PASS"
        last_text = candidate
        last_failures = failures
        c = _failure_codes(failures)
        summary_parts.append(f"attempt 0: {','.join(c) if c else 'UNKNOWN_FAILURE'}")
    else:
        full_prompt = CODE_CONTRACT_PY + "\n\n" + prompt
        candidate = _strip_code_fences(_generate_adapter(full_prompt, stream=False, attempt=0))
        model_calls += 1
        ok, failures = _evaluate_python_quality_text(
            text=candidate,
            must_contain=must_contain,
            forbid=forbid,
            extra_gate=extra_gate,
        )
        if ok:
            return candidate, True, "QUALITY_OK", model_calls, "attempt 0: PASS; final: PASS"
        last_text = candidate
        last_failures = failures
        c = _failure_codes(failures)
        summary_parts.append(f"attempt 0: {','.join(c) if c else 'UNKNOWN_FAILURE'}")

    for repair_ix in range(1, retries + 1):
        failure_block = "\n".join(last_failures) if last_failures else "UNKNOWN_FAILURE"
        repair_prompt = (
            f"{CODE_CONTRACT_PY}\n\n"
            f"Original prompt:\n{prompt}\n\n"
            f"Target file path: {rel_path}\n"
            "Previous output failed quality gates.\n"
            "Failure reasons (machine-readable):\n"
            f"{failure_block}\n\n"
            "Return ONLY valid Python code. No markdown fences. No commentary.\n\n"
            "Previous output:\n"
            f"{last_text}"
        )
        candidate = _strip_code_fences(_generate_adapter(repair_prompt, stream=False, attempt=repair_ix))
        model_calls += 1
        ok, failures = _evaluate_python_quality_text(
            text=candidate,
            must_contain=must_contain,
            forbid=forbid,
            extra_gate=extra_gate,
        )
        if ok:
            summary_parts.append("final: PASS")
            return candidate, True, "QUALITY_OK", model_calls, "; ".join(summary_parts)
        last_text = candidate
        last_failures = failures
        c = _failure_codes(failures)
        summary_parts.append(f"attempt {repair_ix}: {','.join(c) if c else 'UNKNOWN_FAILURE'}")

    final_msg = "REPAIR_EXHAUSTED\n" + "\n".join(last_failures or ["UNKNOWN_FAILURE"])
    summary_parts.append("final: FAIL_AFTER_RETRIES")
    return last_text, False, final_msg, model_calls, "; ".join(summary_parts)


def _strip_code_fences(text: str) -> str:
    """
    Remove common markdown code fences from model output.
    Handles:
      ```python
      ...
      ```
    and ``` ... ```
    """
    s = text.strip()
    s = re.sub(r"^\s*```[a-zA-Z0-9_-]*\s*\n", "", s)
    s = re.sub(r"\n\s*```\s*$", "", s)
    return s.strip() + "\n"


def _maybe_run_pytest(project_root: Path) -> tuple[bool, str]:
    """
    Runs pytest if tests/ exists and pytest is installed.
    Returns (ok, message). If skipped, ok=True with a skip message.
    """
    tests_dir = project_root / "tests"
    if not tests_dir.exists():
        return True, "pytest skipped (no tests/ folder)"

    env = dict(**__import__("os").environ)
    src_dir = project_root / "src"
    if src_dir.exists():
        env["PYTHONPATH"] = str(src_dir) + (":" + env.get("PYTHONPATH", "") if env.get("PYTHONPATH") else "")

    try:
        venv_pytest = project_root / ".venv" / "bin" / "pytest"
        if venv_pytest.exists() and os.access(str(venv_pytest), os.X_OK):
            cmd = [str(venv_pytest), "-q"]
        else:
            cmd = ["pytest", "-q"]
        extra = env.get("AI_DENEY_PYTEST_ARGS", "").strip()
        if extra:
            try:
                cmd.extend(shlex.split(extra))
            except Exception:
                pass

        r = subprocess.run(cmd, cwd=str(project_root), env=env, capture_output=True, text=True)
        if r.returncode == 0:
            return True, "pytest ok"
        out = (r.stdout + "\n" + r.stderr).strip()
        tail = "\n".join(out.splitlines()[-25:])
        return False, "pytest failed:\n" + tail
    except FileNotFoundError:
        return True, "pytest skipped (pytest not installed)"
    except Exception as e:
        return False, f"pytest error: {e}"


def _run_bundle_script(batch_dir: Path) -> tuple[bool, str]:
    script = Path("scripts/bundle_batch.sh")
    if not script.exists():
        return False, "bundle requested but missing script: scripts/bundle_batch.sh"
    if not os.access(str(script), os.X_OK):
        return False, "bundle requested but script is not executable: scripts/bundle_batch.sh"

    try:
        r = subprocess.run([str(script), str(batch_dir)], capture_output=True, text=True)
    except Exception as e:
        return False, f"bundle failed to execute: {e}"

    if r.returncode != 0:
        out = (r.stdout + "\n" + r.stderr).strip()
        tail = "\n".join(out.splitlines()[-25:])
        return False, f"bundle script failed:\n{tail}"
    return True, "bundle ok"


def _parse_gate_summary_attempts(gate_summary: str) -> list[dict]:
    attempts: list[dict] = []
    s = (gate_summary or "").strip()
    if not s:
        return attempts
    parts = [p.strip() for p in s.split(";") if p.strip()]
    for p in parts:
        m = re.match(r"^attempt\s+(\d+)\s*:\s*(.+)$", p, flags=re.IGNORECASE)
        if not m:
            continue
        n = int(m.group(1))
        raw_codes = [x.strip() for x in m.group(2).split(",") if x.strip()]
        known_codes = [c for c in raw_codes if c and c != "PASS" and c != "UNKNOWN_FAILURE"]
        status = "PASS" if not known_codes else "FAIL"
        attempts.append({
            "attempt": n,
            "status": status,
            "gate_failures": known_codes,
        })
    return attempts


def _write_gate_report(path: Path, report: dict) -> None:
    try:
        path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    except Exception:
        pass
def main():
    global _STUB_MODEL_FIXTURE
    parser = argparse.ArgumentParser(description="Batch runner for your local agent.")
    parser.add_argument("tasks_file", nargs="?", default="", help="Tasks file. Optional if --run-latest-next.")
    parser.add_argument("--run-latest-next", action="store_true", help="Use newest outputs/batch-*/next_tasks.txt.")

    parser.add_argument("--chat", action="store_true", help="Plain text mode.")
    parser.add_argument("--use-memory", action="store_true", help="Force memory mode.")
    parser.add_argument("--router", action="store_true", help="Router mode (uses memory only if --memory-query matches).")

    parser.add_argument("--memory-query", default="", help="Filter memory context by keyword.")
    parser.add_argument("--memory-limit", type=int, default=10, help="How many memory items to include.")
    parser.add_argument("--strict", action="store_true", help="Don't guess facts (JSON modes).")
    parser.add_argument("--verify", action="store_true", help="Add claims_to_verify/how_to_verify (JSON modes).")
    parser.add_argument("--bullets", type=int, default=0, help="Force bullet count (0 = model decides).")

    parser.add_argument("--outdir", default="", help="Output directory. Default outputs/batch-<timestamp>/")
    parser.add_argument("--format", choices=["json", "md"], default="md", help="Output format for JSON/memory/chat task outputs (not task-file parsing).")
    parser.add_argument("--tasks-format", choices=["lines", "blocks"], default="blocks", help="How to parse tasks file input.")
    parser.add_argument("--stub-model", default="", help="Deterministic local fixture model (disables live model calls).")

    parser.add_argument("--review", action="store_true", help="Generate review.md.")
    parser.add_argument("--review-bullets", type=int, default=7, help="Bullets per section in review.")
    parser.add_argument("--next-tasks", action="store_true", help="Generate next_tasks.txt (requires --review).")
    parser.add_argument("--next-tasks-n", type=int, default=8, help="How many lines for next_tasks.txt.")
    parser.add_argument("--topic-guard", action="store_true", help="Flag likely off-topic outputs.")
    parser.add_argument("--repair-retries", type=int, default=0, help="Auto-repair retries for generated Python files (0=disabled).")
    parser.add_argument("--bundle", action="store_true", help="Write bundle.txt using scripts/bundle_batch.sh after successful batch.")
    parser.add_argument("--open", action="store_true", help="Open index/review/next_tasks in VS Code.")
    args = parser.parse_args()
    _STUB_MODEL_FIXTURE = (args.stub_model or "").strip()
    if _STUB_MODEL_FIXTURE and _STUB_MODEL_FIXTURE not in _KNOWN_STUB_FIXTURES:
        print(f"unknown --stub-model fixture: {_STUB_MODEL_FIXTURE}")
        raise SystemExit(1)

    if args.run_latest_next and not args.tasks_file:
        latest = _find_latest_next_tasks()
        if not latest:
            print("No next_tasks.txt found. Run a batch with --review --next-tasks first.")
            return
        args.tasks_file = latest
        print(f"Using latest next tasks file: {args.tasks_file}")

    if not args.tasks_file:
        print("Please provide a tasks_file, or use --run-latest-next.")
        return

    bullets_n = args.bullets if args.bullets and args.bullets > 0 else None

    if args.outdir:
        outdir = Path(args.outdir)
    else:
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        outdir = Path(f"outputs/batch-{ts}")
    outdir.mkdir(parents=True, exist_ok=True)
    started_at = datetime.now().isoformat()

    try:
        tasks = _load_tasks(args.tasks_file, tasks_format=args.tasks_format)
    except ValueError as e:
        print(str(e))
        raise SystemExit(1)
    if not tasks:
        print("No tasks found.")
        return

    q = args.memory_query.strip() or None
    ctx = memory_as_context(query=q, limit=args.memory_limit)

    index_lines = [f"# Batch run: {outdir.name}", ""]
    index_lines.append(f"- tasks file: `{args.tasks_file}`")
    index_lines.append(f"- mode: `{'chat' if args.chat else ('router' if args.router else ('memory' if args.use_memory else 'json'))}`")
    index_lines.append(f"- strict: `{args.strict}` | verify: `{args.verify}` | bullets: `{bullets_n if bullets_n is not None else 'variable'}`")
    index_lines.append("")

    produced_files: list[tuple[str, Path]] = []
    gate_report = {
        "batch_id": outdir.name,
        "outdir": str(outdir),
        "tasks_file": args.tasks_file,
        "mode": "chat" if args.chat else ("router" if args.router else ("memory" if args.use_memory else "json")),
        "started_at": started_at,
        "finished_at": "",
        "tasks": [],
        "gate_counts": {},
    }

    def _report_task(task_index: int, directive: str, target: str, final_status: str, gate_summary: str = "") -> None:
        attempts = _parse_gate_summary_attempts(gate_summary)
        for a in attempts:
            for code in a.get("gate_failures", []) or []:
                gate_report["gate_counts"][code] = int(gate_report["gate_counts"].get(code, 0)) + 1
        gate_report["tasks"].append({
            "task_index": task_index,
            "directive": directive,
            "target": target,
            "final_status": final_status,
            "attempts": attempts,
        })

    try:
        for i, (directive, task) in enumerate(tasks, start=1):
            base = f"{i:03d}-{_slug(task)}"

            # Decide mode
            if args.chat:
                mode = "chat"
            elif args.use_memory:
                mode = "memory"
            elif args.router:
                mode = "router->memory" if (args.memory_query.strip() and ctx.strip()) else "router->json"
            else:
                mode = "json"

            # Handle WRITE tasks first: write + continue (no JSON run)
            if isinstance(directive, str) and directive.startswith("WRITE_RAW:"):
                rel = directive.split(":", 1)[1]
                label = f"WRITE_RAW={rel}"
                try:
                    py_contract, raw_content = _extract_py_contract_marker(task)
                    content = raw_content
                    contract_forbid = _contract_forbid(py_contract) if rel.lower().endswith(".py") else []

                    gen_path = _write_generated_file(outdir, rel, content)
                    gate_summary = ""
                    if gen_path.suffix == ".py":
                        ok, msg = _run_python_file_gates(gen_path)
                        if not ok:
                            codes0 = _failure_codes((msg or "").splitlines())
                            gate_summary = f"attempt 0: {','.join(codes0) if codes0 else 'UNKNOWN_FAILURE'}; final: FAIL_AFTER_RETRIES"
                            if args.repair_retries > 0:
                                repaired, ok_repair, repair_msg, _calls, gate_summary = _generate_python_with_repair(
                                    user_prompt=f"Repair this Python file for target path {rel}.",
                                    rel_path=rel,
                                    must_contain=[],
                                    forbid=contract_forbid,
                                    max_repairs=args.repair_retries,
                                    initial_text=content,
                                    extra_gate=_ast_quality_gate_text,
                                )
                                if ok_repair:
                                    content = repaired
                                    gen_path = _write_generated_file(outdir, rel, content)
                                    ok, msg = _run_python_file_gates(gen_path)
                                else:
                                    msg = repair_msg

                            if not ok:
                                err_path = outdir / f"{base}.py_compile.error.txt"
                                err_path.write_text(msg + "\n", encoding="utf-8")
                                index_lines.append(f"## {i}. {label}")
                                if gate_summary:
                                    index_lines.append(f"- gate-summary: `{gate_summary}`")
                                index_lines.append(f"- ERROR: `{err_path.name}`")
                                index_lines.append("")
                                _report_task(i, "WRITE_RAW", rel, "FAIL", gate_summary)
                                log_run({"mode": "batch->error", "task": label, "title": "py_compile failed", "saved_to": str(err_path)})
                                _flush_index(outdir, index_lines)
                                raise SystemExit(1)

                    index_lines.append(f"## {i}. {label}")
                    if gate_summary:
                        index_lines.append(f"- gate-summary: `{gate_summary}`")
                    index_lines.append(f"- wrote: `generated/{rel}`")
                    index_lines.append("")
                    _report_task(i, "WRITE_RAW", rel, "PASS", gate_summary)
                    produced_files.append((label, gen_path))
                    log_run({"mode": "batch->write_raw", "task": label, "title": f"wrote {rel}", "saved_to": str(gen_path)})
                except SystemExit:
                    raise
                except Exception as e:
                    err_path = outdir / f"{base}.error.txt"
                    err_path.write_text(str(e) + "\n", encoding="utf-8")
                    index_lines.append(f"## {i}. {label}")
                    index_lines.append(f"- ERROR: `{err_path.name}`")
                    index_lines.append("")
                    _report_task(i, "WRITE_RAW", rel, "FAIL", "")
                    log_run({"mode": "batch->error", "task": label, "title": "write_raw error", "saved_to": str(err_path)})
                    raise SystemExit(1)
                continue

            if isinstance(directive, str) and directive.startswith("WRITE_BLOCK:"):
                rel = directive.split(":", 1)[1]
                label = f"WRITE_BLOCK={rel}"
                try:
                    must_contains, forbids, parsed_prompt, py_contract = _parse_expect_prompt_block(task)
                    actual_prompt = (parsed_prompt or task).strip()
                    gate_summary = ""
                    if rel.lower().endswith(".py"):
                        forbids = _merge_unique(forbids, _contract_forbid(py_contract))

                    if rel.lower().endswith(".py"):
                        text, ok_repair, repair_msg, _calls, gate_summary = _generate_python_with_repair(
                            user_prompt=actual_prompt,
                            rel_path=rel,
                            must_contain=must_contains,
                            forbid=forbids,
                            max_repairs=args.repair_retries,
                            extra_gate=_ast_quality_gate_text,
                        )
                        if not ok_repair:
                            err_path = outdir / f"{base}.semantic.error.txt"
                            err_msg = "SEMANTIC GATE FAILED\n" + repair_msg + "\n\nGenerated Text:\n" + text
                            err_path.write_text(err_msg, encoding="utf-8")
                            index_lines.append(f"## {i}. {label}")
                            if gate_summary:
                                index_lines.append(f"- gate-summary: `{gate_summary}`")
                            index_lines.append(f"- ERROR: `{err_path.name}` (semantic gate)")
                            index_lines.append("")
                            _report_task(i, "WRITE_BLOCK", rel, "FAIL", gate_summary)
                            log_run({"mode": "batch->error", "task": label, "title": "semantic gate failed", "saved_to": str(err_path)})
                            _flush_index(outdir, index_lines)
                            raise SystemExit(1)
                    else:
                        text = _generate_adapter(actual_prompt, stream=False, attempt=0)
                        ok_expect, msg_expect = _expectations_gate_text(text, must_contains, forbids)
                        if not ok_expect:
                            err_path = outdir / f"{base}.semantic.error.txt"
                            err_msg = "SEMANTIC GATE FAILED\n" + msg_expect + "\n\nGenerated Text:\n" + text
                            err_path.write_text(err_msg, encoding="utf-8")
                            index_lines.append(f"## {i}. {label}")
                            index_lines.append(f"- ERROR: `{err_path.name}` (semantic gate)")
                            index_lines.append("")
                            _report_task(i, "WRITE_BLOCK", rel, "FAIL", "")
                            log_run({"mode": "batch->error", "task": label, "title": "semantic gate failed", "saved_to": str(err_path)})
                            _flush_index(outdir, index_lines)
                            raise SystemExit(1)

                    gen_path = _write_generated_file(outdir, rel, text)
                    if gen_path.suffix == ".py":
                        ok, msg = _run_python_file_gates(gen_path)
                        if not ok:
                            err_path = outdir / f"{base}.py_compile.error.txt"
                            err_path.write_text(msg + "\n", encoding="utf-8")
                            index_lines.append(f"## {i}. {label}")
                            index_lines.append(f"- ERROR: `{err_path.name}`")
                            index_lines.append("")
                            _report_task(i, "WRITE_BLOCK", rel, "FAIL", gate_summary if rel.lower().endswith(".py") else "")
                            log_run({"mode": "batch->error", "task": label, "title": "py_compile failed", "saved_to": str(err_path)})
                            _flush_index(outdir, index_lines)
                            raise SystemExit(1)

                    index_lines.append(f"## {i}. {label}")
                    if rel.lower().endswith(".py") and gate_summary:
                        index_lines.append(f"- gate-summary: `{gate_summary}`")
                    index_lines.append(f"- wrote: `generated/{rel}`")
                    index_lines.append("")
                    _report_task(i, "WRITE_BLOCK", rel, "PASS", gate_summary if rel.lower().endswith(".py") else "")
                    produced_files.append((label, gen_path))
                    log_run({"mode": "batch->write_block", "task": label, "title": f"wrote {rel}", "saved_to": str(gen_path)})
                except SystemExit:
                    raise
                except Exception as e:
                    err_path = outdir / f"{base}.error.txt"
                    err_path.write_text(str(e) + "\n", encoding="utf-8")
                    index_lines.append(f"## {i}. {label}")
                    index_lines.append(f"- ERROR: `{err_path.name}`")
                    index_lines.append("")
                    _report_task(i, "WRITE_BLOCK", rel, "FAIL", "")
                    log_run({"mode": "batch->error", "task": label, "title": "write_block error", "saved_to": str(err_path)})
                    raise SystemExit(1)
                continue

            if isinstance(directive, str) and directive.startswith("WRITE:"):
                rel = directive.split(":", 1)[1]
                py_contract, write_task = _extract_py_contract_marker(task)
                label = f"{write_task} (WRITE={rel})"
                try:
                    gate_summary = ""
                    if rel.lower().endswith(".py"):
                        contract_forbid = _contract_forbid(py_contract)
                        text, ok_repair, repair_msg, _calls, gate_summary = _generate_python_with_repair(
                            user_prompt=write_task,
                            rel_path=rel,
                            must_contain=[],
                            forbid=contract_forbid,
                            max_repairs=args.repair_retries,
                            extra_gate=_ast_quality_gate_text,
                        )
                        if not ok_repair:
                            err_path = outdir / f"{base}.semantic.error.txt"
                            err_msg = "SEMANTIC GATE FAILED\n" + repair_msg + "\n\nGenerated Text:\n" + text
                            err_path.write_text(err_msg, encoding="utf-8")
                            index_lines.append(f"## {i}. {label}")
                            if gate_summary:
                                index_lines.append(f"- gate-summary: `{gate_summary}`")
                            index_lines.append(f"- ERROR: `{err_path.name}` (semantic gate)")
                            index_lines.append("")
                            _report_task(i, "WRITE", rel, "FAIL", gate_summary)
                            log_run({"mode": "batch->error", "task": label, "title": "semantic gate failed", "saved_to": str(err_path)})
                            _flush_index(outdir, index_lines)
                            raise SystemExit(1)
                    else:
                        text = _generate_adapter(write_task, stream=False, attempt=0)

                    gen_path = _write_generated_file(outdir, rel, text)
                    if gen_path.suffix == ".py":
                        ok, msg = _run_python_file_gates(gen_path)
                        if not ok:
                            err_path = outdir / f"{base}.py_compile.error.txt"
                            err_path.write_text(msg + "\n", encoding="utf-8")
                            index_lines.append(f"## {i}. {label}")
                            index_lines.append(f"- ERROR: `{err_path.name}`")
                            index_lines.append("")
                            _report_task(i, "WRITE", rel, "FAIL", gate_summary if rel.lower().endswith(".py") else "")
                            log_run({"mode": "batch->error", "task": label, "title": "py_compile failed", "saved_to": str(err_path)})
                            _flush_index(outdir, index_lines)
                            raise SystemExit(1)

                    index_lines.append(f"## {i}. {label}")
                    if rel.lower().endswith(".py") and gate_summary:
                        index_lines.append(f"- gate-summary: `{gate_summary}`")
                    index_lines.append(f"- wrote: `generated/{rel}`")
                    index_lines.append("")
                    _report_task(i, "WRITE", rel, "PASS", gate_summary if rel.lower().endswith(".py") else "")
                    produced_files.append((label, gen_path))
                    log_run({"mode": "batch->write", "task": label, "title": f"wrote {rel}", "saved_to": str(gen_path)})
                except SystemExit:
                    raise
                except Exception as e:
                    err_path = outdir / f"{base}.error.txt"
                    err_path.write_text(str(e) + "\n", encoding="utf-8")
                    index_lines.append(f"## {i}. {label}")
                    index_lines.append(f"- ERROR: `{err_path.name}`")
                    index_lines.append("")
                    _report_task(i, "WRITE", rel, "FAIL", "")
                    log_run({"mode": "batch->error", "task": label, "title": "write error", "saved_to": str(err_path)})
                    raise SystemExit(1)
                continue

    # Build task, injecting file content if FILE=...
            full_task = task
            label = task
            if isinstance(directive, str) and directive.startswith("FILE:"):
                path = directive.split(":", 1)[1]
                label = f"{task} (FILE={path})"
                try:
                    file_text = read_text(path)
                    full_task = task + "\n\n[FILE CONTENT]\n" + file_text
                except FileNotFoundError as e:
                    err_path = outdir / f"{base}.error.txt"
                    err_path.write_text(str(e) + "\n", encoding="utf-8")
                    index_lines.append(f"## {i}. {label}")
                    index_lines.append(f"- ERROR: `{err_path.name}` (missing file)")
                    index_lines.append("")
                    _report_task(i, "FILE", path, "FAIL", "")
                    log_run({"mode": "batch->error", "task": label, "title": "missing file", "saved_to": str(err_path)})
                    continue
    
            try:
                if mode == "chat":
                    text = _generate_adapter(full_task, stream=False, attempt=0)
                    saved_path = outdir / f"{base}.txt"
                    saved_path.write_text(text.strip() + "\n", encoding="utf-8")
                    index_lines.append(f"## {i}. {label}")
                    index_lines.append(f"- output: `{saved_path.name}`")
                    index_lines.append("")
                    _report_task(i, directive.split(":", 1)[0] if isinstance(directive, str) else "TASK", str(saved_path.name), "PASS", "")
                    produced_files.append((label, saved_path))
                    log_run({"mode": "batch->chat", "task": label, "title": text[:60], "saved_to": str(saved_path)})
                    continue
    
                if mode.endswith("memory"):
                    data = _run_memory_agent_adapter(full_task, context=ctx)
                    printable = {k: v for k, v in data.items() if k != "memory_to_save"}
                else:
                    printable = _run_json_agent_adapter(full_task, strict=args.strict, verify=args.verify, bullets_n=bullets_n)
    
                if args.format == "md":
                    saved_path = outdir / f"{base}.md"
                    md = _render_md(str(printable.get("title", "")).strip(), printable.get("bullets", []))
                    saved_path.write_text(md, encoding="utf-8")
                else:
                    saved_path = outdir / f"{base}.json"
                    saved_path.write_text(json.dumps(printable, indent=2) + "\n", encoding="utf-8")
    
                index_lines.append(f"## {i}. {label}")
                index_lines.append(f"- output: `{saved_path.name}`")
                index_lines.append("")
                _report_task(i, directive.split(":", 1)[0] if isinstance(directive, str) else "TASK", str(saved_path.name), "PASS", "")
                produced_files.append((label, saved_path))
    
                if args.topic_guard:
                    title = str(printable.get("title", "")).strip()
                    bullets = printable.get("bullets", [])
                    if not isinstance(bullets, list):
                        bullets = []
                    bullets = [str(b).strip() for b in bullets if str(b).strip()]
                    off, reason = topic_guard(label, title, bullets)
                    if off:
                        warn_path = outdir / f"{base}.warning.txt"
                        warn_path.write_text(f"OFF-TOPIC WARNING\nTask: {label}\nReason: {reason}\nOutput: {saved_path.name}\n", encoding="utf-8")
                        index_lines.append(f"- ⚠️ OFF-TOPIC: `{warn_path.name}` ({reason})")
                        index_lines.append("")
                        log_run({"mode": "batch->topic_guard", "task": label, "title": "off-topic", "saved_to": str(warn_path)})
    
                log_run({
                    "mode": f"batch->{mode}",
                    "task": label,
                    "title": printable.get("title", "Result"),
                    "strict": bool(args.strict),
                    "verify": bool(args.verify),
                    "memory_query": args.memory_query.strip(),
                    "saved_to": str(saved_path),
                })
    
            except Exception as e:
                err_path = outdir / f"{base}.error.txt"
                err_path.write_text(str(e) + "\n", encoding="utf-8")
                index_lines.append(f"## {i}. {label}")
                index_lines.append(f"- ERROR: `{err_path.name}`")
                index_lines.append("")
                _report_task(i, directive.split(":", 1)[0] if isinstance(directive, str) else "TASK", label, "FAIL", "")
                log_run({"mode": "batch->error", "task": label, "title": "error", "saved_to": str(err_path)})
    finally:
        gate_report["finished_at"] = datetime.now().isoformat()
        _write_gate_report(outdir / "gate_report.json", gate_report)

    index_path = outdir / "index.md"
    index_path.write_text("\n".join(index_lines).strip() + "\n", encoding="utf-8")

    # END-OF-BATCH PYTEST GATE
    ok_py, msg_py = _maybe_run_pytest(Path("."))
    if not ok_py:
        err_path = outdir / "pytest.error.txt"
        err_path.write_text("PYTEST FAILED\n" + msg_py + "\n", encoding="utf-8")
        index_lines.append(f"- ERROR: `{err_path.name}`")
        index_lines.append("")
        log_run({"mode": "batch->error", "task": f"pytest gate for {outdir.name}", "title": "pytest failed", "saved_to": str(err_path)})
        index_path.write_text("\n".join(index_lines).strip() + "\n", encoding="utf-8")
        raise SystemExit(1)
    else:
        log_run({"mode": "batch->pytest", "task": f"pytest gate for {outdir.name}", "title": msg_py, "saved_to": str(outdir)})

    review_path = None
    next_tasks_path = None

    if args.review:
        digests = []
        for label, path in produced_files:
            try:
                if path.suffix == ".json":
                    obj = json.loads(path.read_text(encoding="utf-8"))
                    title = str(obj.get("title", "")).strip()
                    bullets = obj.get("bullets", [])
                    if not isinstance(bullets, list):
                        bullets = []
                    bullets = [str(b).strip() for b in bullets if str(b).strip()]
                elif path.suffix == ".md":
                    title, bullets = _extract_from_md(path.read_text(encoding="utf-8"))
                else:
                    title = label
                    bullets = [path.read_text(encoding="utf-8").strip()]
                digests.append({"task": label, "title": title, "bullets": bullets[:8]})
            except Exception:
                digests.append({"task": label, "title": "", "bullets": ["(could not parse output)"]})

        if not digests:
            review_text = f"# Batch Run Review: {outdir.name}\n\nNo runnable outputs were produced (all tasks failed or wrote empty files).\n"
        else:
            review_prompt = f"""Write a markdown review of this batch run.

Use ONLY the digest below. Do NOT invent facts.
Do NOT mention CLI flags. Do NOT output fake paths like /path/to/...

Format:
# Batch Run Review: {outdir.name}

## Key takeaways
- Max {args.review_bullets} bullets

## Action items
- Max {args.review_bullets} bullets (each should be a runnable tasks_file line)

## Risks / things to verify
- If none, write: None.

## Suggested next batch tasks
- Output up to {args.review_bullets} runnable task lines (no numbering, no bullets).
- Only use FILE= if that exact filename appears in the digest.

Digest:
{json.dumps(digests, indent=2)}
"""
            review_text = _generate_adapter(review_prompt, stream=False, attempt=0).strip() + "\n"

        review_path = outdir / "review.md"
        review_path.write_text(review_text, encoding="utf-8")
        log_run({"mode": "batch->review", "task": f"review for {outdir.name}", "title": "batch review", "saved_to": str(review_path)})

        if args.next_tasks and digests:
            next_prompt = f"""Create the NEXT batch tasks file.

Rules:
- Output plain text ONLY.
- One runnable task per line.
- No numbering, no bullets, no headers.
- Do NOT invent syntaxes like TEXT=.
- FILE= is ONLY for reading existing files and MUST be at the start of the line.
- Never output /path/to/... or FILE=/home/... placeholders.
- Default to variable-length bullets unless an exact count clearly helps.

Review text:
{review_text}

Digest:
{json.dumps(digests, indent=2)}
"""
            nxt = _generate_adapter(next_prompt, stream=False, attempt=0).strip()
            lines = []
            for line in nxt.splitlines():
                line = line.strip()
                if not line:
                    continue
                if line.lower().startswith("here are"):
                    continue
                if "TEXT=" in line:
                    continue
                if line.startswith("FILE=/") or line.startswith("FILE=~") or "/path/to/" in line:
                    continue
                line = re.sub(r"^[-*]\s+", "", line)
                line = re.sub(r"^\d+\.\s+", "", line)
                line = re.sub(r"^task:\s*", "", line, flags=re.IGNORECASE)
                line = re.sub(r"^rewrite task:\s*", "", line, flags=re.IGNORECASE)
                line = re.sub(r"^rewrite:\s*", "", line, flags=re.IGNORECASE)
                if line:
                    lines.append(line)
                if len(lines) >= args.next_tasks_n:
                    break

            next_tasks_path = outdir / "next_tasks.txt"
            next_tasks_path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
            log_run({"mode": "batch->next_tasks", "task": f"next tasks for {outdir.name}", "title": "next_tasks", "saved_to": str(next_tasks_path)})

    print(f"Batch complete. Outputs saved to: {outdir}")
    print(f"Index: {index_path}")
    if review_path:
        print(f"Review: {review_path}")
    if next_tasks_path:
        print(f"Next tasks: {next_tasks_path}")

    if args.open:
        _open_in_vscode(index_path)
        if review_path:
            _open_in_vscode(review_path)
        if next_tasks_path:
            _open_in_vscode(next_tasks_path)

    # Note: bundling currently runs on successful completion only.
    if args.bundle:
        ok_bundle, msg_bundle = _run_bundle_script(outdir)
        if not ok_bundle:
            print(msg_bundle)
            raise SystemExit(1)


if __name__ == "__main__":
    main()
