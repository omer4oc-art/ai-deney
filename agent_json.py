import json
import re
from ollama_client import generate

SYSTEM = "Return ONLY valid JSON. No extra text. No markdown."

SETUP_CONTEXT = """Today on this Mac mini we:
- installed Xcode Command Line Tools (xcode-select --install)
- installed Homebrew and added it to PATH via ~/.zprofile
- installed git, python, node, wget via Homebrew
- installed Visual Studio Code via Homebrew cask
- installed Ollama and downloaded llama3.1:8b
- created a project folder ~/ai-deney/week1 and a Python venv .venv using Python 3.14.3
- wrote Python scripts ollama_client.py and local_llm_test.py to call Ollama over http://127.0.0.1:11434
"""

def _extract_json(text: str) -> str:
    text = text.strip()
    if text.startswith("{") and text.endswith("}"):
        return text
    m = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if m:
        return m.group(0).strip()
    return ""

def run(task: str) -> dict:
    prompt = f"""{SYSTEM}

Context:
{SETUP_CONTEXT}

Task: {task}

Return JSON with this exact schema:
{{
  "title": "string",
  "bullets": ["string", "string", "string", "string", "string"]
}}
"""
    text = generate(prompt, stream=False).strip()

    if not text:
        raise RuntimeError("Model returned empty output. Is `ollama serve` running?")

    json_text = _extract_json(text)
    if not json_text:
        print("RAW MODEL OUTPUT (not JSON):")
        print(text)
        raise RuntimeError("Could not find a JSON object in the model output.")

    try:
        return json.loads(json_text)
    except json.JSONDecodeError as e:
        print("RAW JSON CANDIDATE (failed to parse):")
        print(json_text)
        raise

if __name__ == "__main__":
    data = run("Summarize what we installed today and why in 5 bullets.")
    print(json.dumps(data, indent=2))
