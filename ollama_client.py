import json
import requests
from typing import Optional

OLLAMA_HOST = "http://127.0.0.1:11434"
OLLAMA_URL = f"{OLLAMA_HOST}/api/generate"
DEFAULT_MODEL = "llama3.1:8b"

class OllamaNotRunning(RuntimeError):
    pass

def healthcheck(timeout: int = 2) -> bool:
    try:
        r = requests.head(f"{OLLAMA_HOST}/", timeout=timeout)
        return r.status_code == 200
    except Exception:
        return False

def _raise_friendly_ollama_error() -> None:
    raise OllamaNotRunning(
        "Ollama is not running.\n"
        "Start it with:  ollama serve\n"
        "Then try again.\n"
        f"(Expected server at {OLLAMA_HOST})"
    )

def generate(prompt: str, model: str = DEFAULT_MODEL, stream: bool = False, timeout: int = 300) -> str:
    """
    Returns the model response as a string.
    If stream=True, we still assemble chunks and return the full text.
    (Use generate_live() if you want live printing.)
    """
    if not healthcheck():
        _raise_friendly_ollama_error()

    payload = {"model": model, "prompt": prompt, "stream": stream}

    # Non-stream: one JSON response
    if not stream:
        r = requests.post(OLLAMA_URL, json=payload, timeout=timeout)
        r.raise_for_status()
        return r.json().get("response", "").strip()

    # Stream: newline-delimited JSON chunks
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

def generate_live(prompt: str, model: str = DEFAULT_MODEL, timeout: int = 300) -> None:
    """
    Streams tokens as they arrive and prints them immediately (typing effect).
    """
    if not healthcheck():
        _raise_friendly_ollama_error()

    payload = {"model": model, "prompt": prompt, "stream": True}
    with requests.post(OLLAMA_URL, json=payload, stream=True, timeout=timeout) as r:
        r.raise_for_status()
        for line in r.iter_lines(decode_unicode=True):
            if not line:
                continue
            data = json.loads(line)
            chunk = data.get("response", "")
            if chunk:
                print(chunk, end="", flush=True)
            if data.get("done"):
                print()
                break
