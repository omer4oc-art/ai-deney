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

def run(task: str, context: str = "") -> dict:
    prompt = f"""{SYSTEM}

Memory context (may help, do not invent facts beyond it):
{context}

Task: {task}

Return JSON with this exact schema:
{{
  "title": "string",
  "bullets": ["string", "string", "string", "string", "string"],
  "memory_to_save": "string"
}}

Rules for memory_to_save:
- If there is nothing worth saving, set it to an empty string.
- If there is something worth saving, make it one short sentence (max ~20 words).
"""
    text = generate(prompt, stream=False).strip()
    if not text:
        raise RuntimeError("Model returned empty output. Is `ollama serve` running?")
    json_text = _extract_json(text)
    if not json_text:
        print("RAW MODEL OUTPUT (not JSON):\n", text)
        raise RuntimeError("Could not find JSON in model output.")
    return json.loads(json_text)
