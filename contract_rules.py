from pathlib import Path


_DEFAULTS = {
    "tidy": {
        "must_contain": [],
        "forbid": [
            "if not True",
            "never be reached",
            "isinstance((), tuple)",
        ],
    },
    "strict": {
        "must_contain": [],
        "forbid": [
            "```",
            "TODO",
        ],
    },
}


def _strip_quotes(value: str) -> str:
    v = value.strip()
    if len(v) >= 2 and ((v[0] == '"' and v[-1] == '"') or (v[0] == "'" and v[-1] == "'")):
        return v[1:-1]
    return v


def load_py_contract_rules(contract_name: str, base_dir: Path | None = None) -> tuple[list[str], list[str]]:
    name = (contract_name or "").strip().lower()
    if name not in _DEFAULTS:
        return [], []

    defaults = _DEFAULTS[name]
    must_contain = list(defaults["must_contain"])
    forbid = list(defaults["forbid"])

    root = base_dir if base_dir is not None else Path(__file__).resolve().parent
    rules_path = root / "contracts" / f"py_{name}_rules.txt"
    if not rules_path.exists():
        return must_contain, forbid

    loaded_must: list[str] = []
    loaded_forbid: list[str] = []
    for raw in rules_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip().lower()
        value = _strip_quotes(value.strip())
        if not value:
            continue
        if key == "must_contain":
            loaded_must.append(value)
        elif key == "forbid":
            loaded_forbid.append(value)

    if loaded_must:
        must_contain = loaded_must
    if loaded_forbid:
        forbid = loaded_forbid
    return must_contain, forbid
