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
        bullets.append("Memory context did not include additional details.")
    return bullets[:5]

def run(task: str, context: str = "") -> dict:
    prompt = f"""{SYSTEM}

You MUST follow these rules:
- Use ONLY the Memory context facts. Do NOT invent facts.
- If memory does not contain enough info, say so.
- Output exactly 5 bullets, no more, no less.
- Do not repeat the same item in multiple bullets.
- memory_to_save MUST be an empty string unless the Task explicitly says "save this to memory:".

Memory context:
{context}

Task: {task}

Return JSON with this exact schema:
{{
  "title": "string",
  "bullets": ["string","string","string","string","string"],
  "memory_to_save": "string"
}}
"""
    text = generate(prompt, stream=False).strip()
    if not text:
        raise RuntimeError("Model returned empty output. Is `ollama serve` running?")

    json_text = _extract_json(text)
    if not json_text:
        print("RAW MODEL OUTPUT (not JSON):\n", text)
        raise RuntimeError("Could not find JSON in model output.")

    data = json.loads(json_text)
    data["bullets"] = _ensure_five_nonempty(data.get("bullets", []))

    if "memory_to_save" not in data or data["memory_to_save"] is None:
        data["memory_to_save"] = ""

    return data
