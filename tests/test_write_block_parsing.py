from pathlib import Path
import pytest
import batch_agent as b


def test_write_block_is_single_task() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    tasks_dir = repo_root / "tests" / "_tmp_tasks"
    tasks_dir.mkdir(parents=True, exist_ok=True)

    t = tasks_dir / "tasks_write_block_parsing_test.txt"
    t.write_text(
        "WRITE_BLOCK=src/ai_deney/x.py\n"
        "EXPECT:\n"
        "- must_contain: def x\n"
        "PROMPT:\n"
        "say hi\n"
        "END_WRITE_BLOCK\n",
        encoding="utf-8",
    )

    tasks = b._load_tasks(str(t))
    assert len(tasks) == 1
    d, body = tasks[0]
    assert d == "WRITE_BLOCK:src/ai_deney/x.py"
    assert "EXPECT:" in body
    assert "PROMPT:" in body
    assert "say hi" in body


def test_parse_expect_prompt_block_and_expectations_gate_text() -> None:
    block = (
        "EXPECT:\n"
        "- must_contain: \"def example\"\n"
        "- forbid: TODO\n"
        "PROMPT:\n"
        "Write function example.\n"
    )
    must, forbid, prompt, py_contract = b._parse_expect_prompt_block(block)
    assert must == ['"def example"']
    assert forbid == ["TODO"]
    assert "Write function example." in prompt
    assert py_contract == ""

    ok, msg = b._expectations_gate_text("def example() -> int:\n    return 1\n", must, forbid)
    assert ok, msg

    ok2, msg2 = b._expectations_gate_text("def example() -> int:\n    # TODO\n    return 1\n", must, forbid)
    assert not ok2
    assert "forbidden" in msg2


def test_write_block_colon_header_is_single_task() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    tasks_dir = repo_root / "tests" / "_tmp_tasks"
    tasks_dir.mkdir(parents=True, exist_ok=True)

    t = tasks_dir / "tasks_write_block_colon_parsing_test.txt"
    t.write_text(
        "WRITE_BLOCK: outputs/_smoke_agent_quality/smoke_module.py\n"
        "EXPECT:\n"
        "- must_contain: def add(\n"
        "PROMPT:\n"
        "Write add function.\n"
        "END_WRITE_BLOCK\n",
        encoding="utf-8",
    )

    tasks = b._load_tasks(str(t))
    assert len(tasks) == 1
    d, body = tasks[0]
    assert d == "WRITE_BLOCK:outputs/_smoke_agent_quality/smoke_module.py"
    assert "EXPECT:" in body
    assert "PROMPT:" in body


def test_py_contract_strict_applies_to_next_python_write_block() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    tasks_dir = repo_root / "tests" / "_tmp_tasks"
    tasks_dir.mkdir(parents=True, exist_ok=True)

    t = tasks_dir / "tasks_py_contract_strict_parse.txt"
    t.write_text(
        "PY_CONTRACT: strict\n"
        "WRITE_BLOCK: outputs/_smoke_agent_quality/contract_parse.py\n"
        "PROMPT:\n"
        "Write ok() -> int returning 1.\n"
        "END_WRITE_BLOCK\n",
        encoding="utf-8",
    )

    tasks = b._load_tasks(str(t))
    assert len(tasks) == 1
    d, body = tasks[0]
    assert d == "WRITE_BLOCK:outputs/_smoke_agent_quality/contract_parse.py"
    must, forbid, prompt, py_contract = b._parse_expect_prompt_block(body)
    assert must == []
    assert forbid == []
    assert "Write ok() -> int returning 1." in prompt
    assert py_contract == "strict"


def test_py_contract_strict_inside_write_block_body() -> None:
    block = (
        "PY_CONTRACT: strict\n"
        "EXPECT:\n"
        "- must_contain: def ok\n"
        "PROMPT:\n"
        "Write ok() -> int.\n"
    )
    must, forbid, prompt, py_contract = b._parse_expect_prompt_block(block)
    assert py_contract == "strict"
    assert must == ["def ok"]
    assert "Write ok() -> int." in prompt


def test_tasks_format_blocks_collapses_write_block() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    tasks_dir = repo_root / "tests" / "_tmp_tasks"
    tasks_dir.mkdir(parents=True, exist_ok=True)
    t = tasks_dir / "tasks_blocks_mode_parse.txt"
    t.write_text(
        "WRITE_BLOCK: outputs/_smoke_agent_quality/blocks_mode.py\n"
        "PROMPT:\n"
        "Write ok() -> int.\n"
        "END_WRITE_BLOCK\n",
        encoding="utf-8",
    )
    tasks = b._load_tasks(str(t), tasks_format="blocks")
    assert len(tasks) == 1
    assert tasks[0][0] == "WRITE_BLOCK:outputs/_smoke_agent_quality/blocks_mode.py"


def test_tasks_format_lines_rejects_write_block() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    tasks_dir = repo_root / "tests" / "_tmp_tasks"
    tasks_dir.mkdir(parents=True, exist_ok=True)
    t = tasks_dir / "tasks_lines_mode_reject.txt"
    t.write_text(
        "WRITE_BLOCK: outputs/_smoke_agent_quality/lines_mode.py\n"
        "PROMPT:\n"
        "Write ok() -> int.\n"
        "END_WRITE_BLOCK\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="WRITE_BLOCK not supported"):
        b._load_tasks(str(t), tasks_format="lines")
