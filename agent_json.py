import json
from ollama_client import generate

SYSTEM = "Return ONLY valid JSON. No extra text. No markdown."

def run(task: str) -> dict:
    prompt = f"""{SYSTEM}

Task: {task}

Return JSON with this exact schema:
{{
  "title": "string",
  "bullets": ["string", "string", "string", "string", "string"]
}}
"""
    text = generate(prompt, stream=False)
    return json.loads(text)

if __name__ == "__main__":
    data = run("Summarize what we installed today and why in 5 bullets.")
    print(json.dumps(data, indent=2))
