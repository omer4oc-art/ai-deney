import json
import re
from ollama_client import generate

SYSTEM = "Return ONLY valid JSON. No extra text. No markdown."

def _extract_json(text: str) -> str:
    text = text.strip()
    if text.startswith("{") and text.endswith("}"):
        return text
    m = re.search(r"\{.*\}", text, flags=re.DOTALL)
    return m.group(0).strip() if m else ""

def _ensure_five_nonempty(bullets):
    bullets = [b.strip() for b in bullets if isinstance(b, str) and b.strip()]
    while len(bullets) < 5:
        bullets.append("Not enough detail provided.")
    return bullets[:5]

def run(task: str, strict: bool = False, verify: bool = False) -> dict:
    strict_rules = ""
    if strict:
        strict_rules = """
Strict rules:
- Do NOT guess facts (numbers, ingredients, dates, mg caffeine, calories).
- If unsure, say "unknown/varies by variant" rather than inventing.
- Prefer general, correct statements over specific, uncertain ones.
"""

    if verify:
        schema = """{
  "title": "string",
  "bullets": ["string","string","string","string","string"],
  "claims_to_verify": ["string","string","string"],
  "how_to_verify": ["string","string","string"]
}"""
        verify_rules = """
Verify rules:
- claims_to_verify: list up to 3 factual claims in your bullets that could be wrong or vary by region/variant.
- how_to_verify: for each claim, give a concrete way to check (e.g., "nutrition label", "brand website nutrition page", "USDA/FDA database", "photo of can label").
- If your answer is fully general and not fact-specific, you can put "none" as the single item in claims_to_verify and how_to_verify.
"""
    else:
        schema = """{
  "title": "string",
  "bullets": ["string","string","string","string","string"]
}"""
        verify_rules = ""

    prompt = f"""{SYSTEM}

Task: {task}
{strict_rules}

Return JSON with this exact schema:
{schema}

Rules:
- Output exactly 5 bullets.
- No extra keys beyond the schema.
{verify_rules}
"""
    text = generate(prompt, stream=False).strip()
    if not text:
        raise RuntimeError("Model returned empty output. Is `ollama serve` running?")

    json_text = _extract_json(text)
    if not json_text:
        print("RAW MODEL OUTPUT (not JSON):\n", text)
        raise RuntimeError("Could not find JSON in model output.")

    data = json.loads(json_text)
    data["title"] = str(data.get("title", "")).strip() or "Result"
    data["bullets"] = _ensure_five_nonempty(data.get("bullets", []))

    if verify:
        # Ensure fields exist and are lists
        claims = data.get("claims_to_verify", [])
        how = data.get("how_to_verify", [])
        if not isinstance(claims, list):
            claims = [str(claims)]
        if not isinstance(how, list):
            how = [str(how)]
        data["claims_to_verify"] = [str(x).strip() for x in claims if str(x).strip()][:3] or ["none"]
        data["how_to_verify"] = [str(x).strip() for x in how if str(x).strip()][:3] or ["none"]

    return data

if __name__ == "__main__":
    out = run("Compare Diet Coke vs Fanta Orange (regular, US). Mention sugar, calories, caffeine, and flavor.", strict=True, verify=True)
    print(json.dumps(out, indent=2))
