"""
Minimal Ollama client using only the Python standard library.
Talks to a local Ollama server (default http://localhost:11434).
"""
import json
import math
import re
import urllib.request
import urllib.error

OLLAMA_HOST = "http://localhost:11434"

_THINK_TAG_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_OPEN_THINK_TAG_RE = re.compile(r"<think>.*", re.DOTALL | re.IGNORECASE)  # unclosed tag (got cut off)


class OllamaError(Exception):
    pass


def _post(path: str, payload: dict, timeout: int = 600) -> dict:
    url = f"{OLLAMA_HOST}{path}"
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body)
    except urllib.error.URLError as e:
        raise OllamaError(
            f"Could not reach Ollama at {OLLAMA_HOST}{path}. "
            f"Is 'ollama serve' running? ({e})"
        )


def strip_think(text: str) -> str:
    """
    Remove any <think>...</think> reasoning block that slipped into the
    output text, whether or not it was properly closed. Belt-and-suspenders
    for cases where "think": false isn't honored by an older Ollama build.
    """
    text = _THINK_TAG_RE.sub("", text)
    text = _OPEN_THINK_TAG_RE.sub("", text)
    return text.strip()


def generate(model, prompt, system=None, temperature=0.4, think=False, timeout=600, max_tokens=None):
    """
    Single-shot generation. Returns raw text response with any thinking
    block stripped out.

    Mechanisms that suppress "thinking" to avoid burning thousands of
    tokens on reasoning before the real answer:
      1. The "think" API field (works on Ollama 0.6+ for reasoning models
         like qwen3 -- when honored, the model doesn't generate reasoning
         tokens at all, so this is the one that actually saves time/tokens).
      2. A literal "/no_think" directive appended to the prompt, which is
         Qwen3's own trained convention for disabling its reasoning mode
         regardless of Ollama version or which endpoint is used.
      3. An optional num_predict cap (max_tokens) as a hard ceiling, so
         even if 1 and 2 are both ignored, the call can't run away.
    Any thinking block that still leaks through is stripped from the
    response text before it's returned.
    """
    effective_prompt = prompt if think else f"{prompt}\n\n/no_think"
    options = {"temperature": temperature}
    if max_tokens:
        options["num_predict"] = max_tokens
    payload = {
        "model": model,
        "prompt": effective_prompt,
        "stream": False,
        "think": think,
        "options": options,
    }
    if system:
        payload["system"] = system
    result = _post("/api/generate", payload, timeout=timeout)
    if "error" in result:
        raise OllamaError(result["error"])
    text = result.get("response", "")
    if not think:
        stripped = strip_think(text)
        if not stripped and text.strip():
            raise OllamaError(
                "Model output was entirely a thinking block that got cut off "
                "before reaching an answer (likely hit the token cap while "
                "still 'thinking' despite think=false). Try raising "
                "GRAPH_RPG_MAX_TOKENS in config.py, or double-check your "
                "Ollama version supports the 'think' API field."
            )
        text = stripped
    return text


def embed(model, text, timeout=120):
    """
    Returns an embedding vector for text using the given model.
    Raises OllamaError if the model doesn't support embeddings.
    """
    result = _post("/api/embeddings", {"model": model, "prompt": text}, timeout=timeout)
    if "error" in result:
        raise OllamaError(result["error"])
    vec = result.get("embedding")
    if not vec:
        raise OllamaError(f"Model '{model}' returned no embedding.")
    return vec


def cosine_similarity(a: list, b: list) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def extract_json(text: str):
    """
    LLMs often wrap JSON in markdown fences, add preamble/postamble text,
    or (for reasoning models) leave a stray thinking block. This strips
    thinking blocks first, then pulls out the first valid top-level JSON
    object or array it can find.
    """
    text = strip_think(text).strip()
    # strip markdown fences
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()

    # Try direct parse first
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Fallback: find the widest {...} or [...] block via bracket matching
    for open_ch, close_ch in (("{", "}"), ("[", "]")):
        start = text.find(open_ch)
        if start == -1:
            continue
        depth = 0
        for i in range(start, len(text)):
            if text[i] == open_ch:
                depth += 1
            elif text[i] == close_ch:
                depth -= 1
                if depth == 0:
                    candidate = text[start:i + 1]
                    try:
                        return json.loads(candidate)
                    except json.JSONDecodeError:
                        break
    raise OllamaError(f"Could not parse JSON from model output:\n{text[:500]}")
