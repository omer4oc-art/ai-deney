import batch_agent as b


def test_ast_quality_gate_text_rejects_top_level_print_and_pass_only() -> None:
    bad = (
        "def f() -> None:\n"
        "    pass\n"
        "# TODO: implement\n"
    )
    ok, msg = b._ast_quality_gate_text(bad)
    assert not ok
    assert "AST_PASS_ONLY_FUNCTION|f" in msg
    assert "AST_TODO_FOUND" in msg


def test_generate_python_with_repair_succeeds_on_second_try(monkeypatch) -> None:
    calls = {"n": 0}

    def fake_generate(prompt: str, stream: bool = False) -> str:
        calls["n"] += 1
        if calls["n"] == 1:
            return "def broken(:\n    pass\n"
        return "def fixed() -> int:\n    return 1\n"

    monkeypatch.setattr(b, "generate", fake_generate)
    text, ok, msg, model_calls, gate_summary = b._generate_python_with_repair(
        user_prompt="Write function fixed",
        rel_path="src/fixed.py",
        must_contain=["def fixed"],
        forbid=["TODO"],
        max_repairs=2,
        extra_gate=b._ast_quality_gate_text,
    )
    assert ok, msg
    assert "def fixed" in text
    assert calls["n"] == 2
    assert model_calls == 2
    assert "attempt 0:" in gate_summary
    assert "final: PASS" in gate_summary


def test_generate_python_with_repair_triggers_on_expect_failure(monkeypatch) -> None:
    calls = {"n": 0}

    def fake_generate(prompt: str, stream: bool = False) -> str:
        calls["n"] += 1
        if calls["n"] == 1:
            return "def add(a: int, b: int) -> int:\n    return a - b\n"
        return "def add(a: int, b: int) -> int:\n    return a + b\n"

    monkeypatch.setattr(b, "generate", fake_generate)
    text, ok, msg, model_calls, gate_summary = b._generate_python_with_repair(
        user_prompt="Write add function",
        rel_path="src/add.py",
        must_contain=["return a + b"],
        forbid=["```"],
        max_repairs=2,
        extra_gate=b._ast_quality_gate_text,
    )
    assert ok, msg
    assert "return a + b" in text
    assert calls["n"] == 2
    assert model_calls == 2
    assert "EXPECT_MISSING" in gate_summary
