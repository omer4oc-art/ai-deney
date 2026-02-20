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
- You are not actually verifying anything. You are creating a checklist of what must be checked.
- claims_to_verify MUST include the highest-risk factual claims from your bullets.
- ALWAYS include (if present in bullets):
  1) Every numeric claim (calories, mg caffeine, grams sugar, dates, percentages).
  2) Every ingredient/sweetener/preservative claim (aspartame, HFCS, etc.).
  3) Every "contains/does not contain" claim (sugar-free, caffeine-free, etc.).
- If there are more than 3 such claims, choose the 3 most important for the user’s decision.
- claims_to_verify items must be short, specific sentences copied from (or directly matching) your bullets.
- how_to_verify must give a concrete method for each claim, in the same order, e.g.:
  - "Check the nutrition label on the can/bottle"
  - "Check Coca-Cola product nutrition page for US"
  - "Compare ingredient lists on official packaging photos"
- If your bullets contain none of the above risky claims, set claims_to_verify=["none"] and how_to_verify=["none"].
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
        claims = data.get("claims_to_verify", [])
        how = data.get("how_to_verify", [])

        if not isinstance(claims, list):
            claims = [str(claims)]
        if not isinstance(how, list):
            how = [str(how)]

        claims = [str(x).strip() for x in claims if str(x).strip()]
        how = [str(x).strip() for x in how if str(x).strip()]

        # If model forgot these fields, default to "none"
        if not claims:
            claims = ["none"]
        if not how:
            how = ["none"]

        data["claims_to_verify"] = claims[:3]
        data["how_to_verify"] = how[:3]

        # If claims != how length, pad how_to_verify
        while len(data["how_to_verify"]) < len(data["claims_to_verify"]):
            data["how_to_verify"].append("Check official packaging label or brand nutrition page.")
        data["how_to_verify"] = data["how_to_verify"][:len(data["claims_to_verify"])]

    return data

if __name__ == "__main__":
    out = run(
        "Compare Diet Coke vs Fanta Orange (regular, US). Mention sugar, calories, caffeine, and flavor.",
        strict=True,
        verify=True,
    )
    print(json.dumps(out, indent=2))
