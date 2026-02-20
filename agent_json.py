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

def _has_risky_claims(bullets) -> bool:
    joined = " ".join([str(b) for b in bullets]).lower()

    risky_words = [
        "caffeine", "aspartame", "acesulfame", "sucralose",
        "hfcs", "high fructose", "corn syrup",
        "sugar", "sweetener", "ingredient", "preservative",
        "sodium benzoate", "potassium sorbate",
        "calorie", "kcal", "grams", " mg", "contains", "does not contain",
        "sugar-free", "caffeine-free"
    ]
    if any(w in joined for w in risky_words):
        return True

    if any(ch.isdigit() for ch in joined) and any(u in joined for u in [" mg", "g ", "grams", "calorie", "kcal", "%"]):
        return True

    return False

def run(task: str, strict: bool = False, verify: bool = False) -> dict:
    strict_rules = ""
    if strict:
        strict_rules = """
Strict rules:
- Do NOT guess facts (numbers, ingredients, dates, mg caffeine, calories, grams sugar).
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
Verify rules (STRICT):
- ONLY create claims_to_verify for risky factual claims (nutrition, ingredients, contains/does-not-contain, caffeine/sugar/calories).
- If the bullets contain no such risky factual claims, set:
  claims_to_verify=["none"] and how_to_verify=["none"].
- If there are more than 3 risky claims, choose the 3 most important.
- how_to_verify must be concrete: "nutrition label", "official product nutrition page", "ingredient list on packaging".
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
        if not _has_risky_claims(data["bullets"]):
            data["claims_to_verify"] = ["none"]
            data["how_to_verify"] = ["none"]
            return data

        claims = data.get("claims_to_verify", [])
        how = data.get("how_to_verify", [])

        if not isinstance(claims, list):
            claims = [str(claims)]
        if not isinstance(how, list):
            how = [str(how)]

        claims = [str(x).strip() for x in claims if str(x).strip()]
        how = [str(x).strip() for x in how if str(x).strip()]

        if not claims:
            claims = ["none"]
        if not how:
            how = ["none"]

        data["claims_to_verify"] = claims[:3]
        data["how_to_verify"] = how[:3]

        while len(data["how_to_verify"]) < len(data["claims_to_verify"]):
            data["how_to_verify"].append("Check official packaging label or brand nutrition page.")
        data["how_to_verify"] = data["how_to_verify"][:len(data["claims_to_verify"])]

    return data
