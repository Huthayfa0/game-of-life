"""
Central configuration. Edit these values directly, or override at launch
via environment variables, e.g.:

    GRAPH_RPG_GEN_MODEL=phi python main.py
    GRAPH_RPG_THINK=true python main.py
"""
import os


def _env_bool(name: str, default: bool) -> bool:
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


def _env_int(name: str, default: int) -> int:
    val = os.environ.get(name)
    if val is None:
        return default
    try:
        return int(val)
    except ValueError:
        return default


# ---- Models ----
GEN_MODEL = os.environ.get("GRAPH_RPG_GEN_MODEL", "qwen3:4b")
EMBED_MODEL = os.environ.get("GRAPH_RPG_EMBED_MODEL", "qwen3-rag")
FALLBACK_MODEL = os.environ.get("GRAPH_RPG_FALLBACK_MODEL", "phi")  # unused by default, available as a swap-in

# ---- Thinking mode ----
# qwen3 models support an extended "thinking"/chain-of-thought pass before
# answering. It's slow and not needed here since we only want strict JSON
# out. THINK=False sends {"think": false} to Ollama (supported on Ollama
# 0.6+ for qwen3-family models) AND the system prompts explicitly forbid
# reasoning output, as a belt-and-suspenders approach for older Ollama
# versions that ignore the "think" field.
THINK = _env_bool("GRAPH_RPG_THINK", False)

# ---- Timeouts (seconds) ----
# Local CPU inference, especially for the first request after a model
# loads into memory, can be slow -- these are generous on purpose.
TIMEOUT_GENERATE = _env_int("GRAPH_RPG_TIMEOUT_GENERATE", 6000)   # 10 min
TIMEOUT_EMBED = _env_int("GRAPH_RPG_TIMEOUT_EMBED", 1200)         # 2 min per embedding call

# ---- Output length cap ----
# Third safety net against runaway "thinking" (on top of think=False and
# the /no_think prompt directive): hard-caps how many tokens the model can
# generate per call. 2048 is comfortably more than a JSON graph update
# needs, but stops a misbehaving model from burning thousands of tokens
# on reasoning it wasn't supposed to produce at all.
MAX_TOKENS = _env_int("GRAPH_RPG_MAX_TOKENS", 2048)

# ---- Generation temperature ----
TEMPERATURE_INTERVIEW = 0.4
TEMPERATURE_ACTION = 0.5

# ---- RAG ----
RAG_TOP_K = _env_int("GRAPH_RPG_RAG_TOP_K", 8)
