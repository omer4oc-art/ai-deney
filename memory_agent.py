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
    # Guard: if memory context is empty, do NOT answer with outside facts
    if not context.strip() or context.strip() == "No saved memory yet.":
        return {
            "title": "Not in memory",
            "bullets": [
                "Your memory does not include information about this topic.",
                "Run without --use-memory to get a normal model answer.",
                "Example: python agent.py \"What is the difference between Diet Coke and Fanta?\"",
                "Use --use-memory only for topics you have saved into memory (like week1 setup).",
                "If you want, you can manually save a correct note to memory for reuse later."
            ],
            "memory_to_save": ""
        }

    prompt = f"""{SYSTEM}

You MUST follow these rules:
- Use ONLY the Memory context facts. Do NOT invent facts.
- If the memory does not contain enough info, say so.
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

    # Enforce exactly 5 non-empty bullets (without adding facts)
    data["bullets"] = _ensure_five_nonempty(data.get("bullets", []))

    # Enforce memory_to_save default
    if "memory_to_save" not in data or data["memory_to_save"] is None:
        data["memory_to_save"] = ""

    return data