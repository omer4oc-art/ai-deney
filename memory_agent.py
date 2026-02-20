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

def _split_bullet(b: str):
    # Split without adding new facts: first try semicolons, then commas
    parts = [p.strip() for p in b.split(";") if p.strip()]
    if len(parts) >= 2:
        return parts
    parts = [p.strip() for p in b.split(",") if p.strip()]
    if len(parts) >= 2:
        return parts
    return [b.strip()]

def _ensure_five_nonempty(bullets):
    bullets = [b.strip() for b in bullets if isinstance(b, str) and b.strip()]

    # If fewer than 5, split existing bullets into smaller ones
    while len(bullets) < 5 and bullets:
        i = max(range(len(bullets)), key=lambda idx: len(bullets[idx]))
        longest = bullets.pop(i)
        pieces = _split_bullet(longest)
        bullets.insert(i, pieces[0])
        for extra in pieces[1:]:
            bullets.append(extra)

        # If splitting didn't increase count, stop to avoid looping
        if len(pieces) == 1:
            break

    # If still fewer than 5, pad with a neutral, non-invented note
    while len(bullets) < 5:
        bullets.append("Memory context did not include additional details.")

    return bullets[:5]

def run(task: str, context: str = "") -> dict:
    prompt = f"""{SYSTEM}

You MUST follow these rules:
- Use ONLY the Memory context facts. Do NOT invent facts.
- If the memory does not contain enough info, say so in the bullets.
- Output exactly 5 bullets, no more, no less.
- Each bullet should include BOTH: (a) the item, and (b) what it is for (purpose).
- If the task asks about "what we installed", cover ALL major installs mentioned in memory across the 5 bullets (combine items if needed).
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

    # Enforce exactly 5 meaningful bullets without inventing new facts
    data["bullets"] = _ensure_five_nonempty(data.get("bullets", []))

    # Enforce memory_to_save default
    if ("memory_to_save" not in data) or (data["memory_to_save"] is None):
        data["memory_to_save"] = ""
    return data
