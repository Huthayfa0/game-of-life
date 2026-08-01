"""
LLM client built on the official `openai` Python library (chat.completions +
embeddings) against any OpenAI-compatible API. Defaults to OpenRouter, but
the backend is fully swappable via config.BASE_URL / config.API_KEY (e.g.
OpenAI directly, or a self-hosted OpenAI-compatible server).

Install requirement:
    pip install openai
"""
import re

try:
    from openai import (
        OpenAI,
        APIError,
        APIConnectionError,
        APITimeoutError,
        BadRequestError,
    )
except ImportError as e:
    raise ImportError(
        "The 'openai' package is required. Install it with:\n"
        "    pip install openai"
    ) from e

import config

_THINK_TAG_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_OPEN_THINK_TAG_RE = re.compile(r"<think>.*", re.DOTALL | re.IGNORECASE)  # unclosed (got cut off)

_client = None


class LLMError(Exception):
    pass


def get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=config.API_KEY, base_url=config.BASE_URL)
    return _client


def strip_think(text: str) -> str:
    """
    Remove any <think>...</think> reasoning block that slipped into the
    output text, whether or not it was properly closed. Belt-and-suspenders
    for backends/models that don't fully honor the no-thinking directives.
    """
    text = _THINK_TAG_RE.sub("", text)
    text = _OPEN_THINK_TAG_RE.sub("", text)
    return text.strip()


def generate(model, prompt, system=None, temperature=0.4, think=False, timeout=600, max_tokens=None):
    """
    Single-shot chat completion. Returns response text with any thinking
    block stripped out.

    Mechanisms that suppress "thinking" to avoid burning thousands of
    tokens on reasoning before the real answer:
      1. A literal "/no_think" directive appended to the prompt -- some
         model families (e.g. Qwen3) respond to this directly regardless
         of backend/endpoint.
      2. extra_body={"reasoning": {"exclude": True}, "think": False} passed
         alongside the standard OpenAI params -- "reasoning.exclude" is
         OpenRouter's native switch for hiding/suppressing reasoning
         tokens; "think" covers other providers with a similar flag.
         Harmlessly ignored by backends/models that don't support either.
      3. An optional max_tokens cap as a hard ceiling, so even if 1 and 2
         are both ignored, a call can't run away generating reasoning.
    Any thinking block that still leaks through is stripped before the
    text is returned.
    """
    effective_prompt = prompt if think else f"{prompt}\n\n/no_think"

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": effective_prompt})

    client = get_client()
    kwargs = dict(
        model=model,
        messages=messages,
        temperature=temperature,
        timeout=timeout,
    )
    if max_tokens:
        kwargs["max_tokens"] = max_tokens

    extra_body = {"think": think} if not think else {}
    if not think:
        extra_body["reasoning"] = {"exclude": True}

    try:
        response = client.chat.completions.create(extra_body=extra_body, **kwargs)
    except TypeError:
        # installed openai version too old to accept extra_body kwarg at all
        response = client.chat.completions.create(**kwargs)
    except BadRequestError:
        # backend rejected one of the unrecognized fields outright -- retry
        # without them rather than failing the whole call over a cosmetic flag
        try:
            response = client.chat.completions.create(**kwargs)
        except (APIError, APIConnectionError, APITimeoutError) as e2:
            raise LLMError(
                f"Request to {config.BASE_URL} failed: {e2}\n"
                f"Check that the API key is valid and '{model}' is available on this backend."
            )
    except (APIConnectionError, APITimeoutError) as e:
        raise LLMError(
            f"Could not reach {config.BASE_URL}: {e}\n"
            f"Check your network connection and that BASE_URL is correct."
        )
    except APIError as e:
        raise LLMError(f"Request to {config.BASE_URL} failed: {e}")

    text = response.choices[0].message.content or ""

    if not think:
        stripped = strip_think(text)
        if not stripped and text.strip():
            raise LLMError(
                "Model output was entirely a thinking block that got cut off "
                "before reaching an answer (likely hit the token cap while "
                "still 'thinking' despite think=false). Try raising "
                "GRAPH_RPG_MAX_TOKENS in config.py, or double-check whether "
                "this backend/model supports disabling reasoning."
            )
        text = stripped
    return text


def embed(model, text, timeout=120):
    """
    Returns an embedding vector for text using the given model.
    Raises LLMError if the model/backend doesn't support embeddings.
    """
    client = get_client()
    try:
        response = client.embeddings.create(model=model, input=text, timeout=timeout)
    except (APIConnectionError, APITimeoutError) as e:
        raise LLMError(f"Could not reach {config.BASE_URL} for embeddings: {e}")
    except APIError as e:
        raise LLMError(f"Embedding request failed for model '{model}': {e}")
    if not response.data:
        raise LLMError(f"Model '{model}' returned no embedding.")
    return response.data[0].embedding


def cosine_similarity(a: list, b: list) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
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
    import json

    text = strip_think(text).strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

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
    raise LLMError(f"Could not parse JSON from model output:\n{text[:500]}")
