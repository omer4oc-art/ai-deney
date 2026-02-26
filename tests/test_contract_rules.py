from pathlib import Path

from contract_rules import load_py_contract_rules


def test_contract_rules_loaded_from_files() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    _, tidy_forbid = load_py_contract_rules("tidy", base_dir=repo_root)
    _, strict_forbid = load_py_contract_rules("strict", base_dir=repo_root)

    assert "if not True" in tidy_forbid
    assert "never be reached" in tidy_forbid
    assert "isinstance((), tuple)" in tidy_forbid
    assert "```" in strict_forbid
    assert "TODO" in strict_forbid


def test_contract_rules_fallback_when_files_missing(tmp_path: Path) -> None:
    _, tidy_forbid = load_py_contract_rules("tidy", base_dir=tmp_path)
    _, strict_forbid = load_py_contract_rules("strict", base_dir=tmp_path)
    assert "if not True" in tidy_forbid
    assert "```" in strict_forbid
