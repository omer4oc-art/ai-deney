import json
import requests

OLLAMA_URL = "http://127.0.0.1:11434/api/generate"
DEFAULT_MODEL = "llama3.1:8b"

def generate(prompt: str, model: str = DEFAULT_MODEL, stream: bool = True, timeout: int = 300) -> str:
    payload = {"model": model, "prompt": prompt, "stream": stream}

    if not stream:
        r = requests.post(OLLAMA_URL, json=payload, timeout=timeout)
        r.raise_for_status()
        return r.json()["response"].strip()

    out = []
    with requests.post(OLLAMA_URL, json=payload, stream=True, timeout=timeout) as r:
        r.raise_for_status()
        for line in r.iter_lines(decode_unicode=True):
            if not line:
                continue
            data = json.loads(line)
            out.append(data.get("response", ""))
            if data.get("done"):
                break
    return "".join(out).strip()

def healthcheck() -> bool:
    try:
        r = requests.head("http://127.0.0.1:11434/", timeout=5)
        return r.status_code == 200
    except Exception:
        return False
