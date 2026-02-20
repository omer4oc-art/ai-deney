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

def run(task: str, context: str) -> dict:
    # If there’s no memory context, refuse instead of guessing.
    if not context.strip():
        return {
            "title": "No relevant memory found",
            "bullets": [
                "Memory context is empty for this query.",
                "Run without --use-memory to get a general answer.",
                "Or add a memory note if you want this remembered.",
                "Tip: use --memory-query week1 for setup questions.",
                "No valid answer can be generated from memory alone."
            ],
            "memory_to_save": ""
        }

    prompt = f"""{SYSTEM}

You MUST follow these rules:
- Use ONLY the Memory context facts. Do NOT invent facts.
- If memory lacks info, say so.
- Output exactly 5 bullets.
- Do not repeat the same item in multiple bullets.
- memory_to_save MUST be empty string unless Task explicitly says: "save this to memory:".

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
    json_text = _extract_json(text)
    if not json_text:
        raise RuntimeError("Could not find JSON in model output.")
    data = json.loads(json_text)

    data["title"] = str(data.get("title", "")).strip() or "Memory result"
    data["bullets"] = _ensure_five_nonempty(data.get("bullets", []))
    if "memory_to_save" not in data or data["memory_to_save"] is None:
        data["memory_to_save"] = ""
    return data