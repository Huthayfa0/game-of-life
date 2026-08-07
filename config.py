"""
Central configuration. Edit these values directly, or override at launch
via environment variables, e.g.:

    OPENROUTER_API_KEY=sk-... python main.py
    GRAPH_RPG_GEN_MODEL=openai/gpt-4o-mini python main.py
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


# ---- Backend (any OpenAI-compatible API) ----
# Defaults to OpenRouter. Point this at OpenAI directly, or any other
# OpenAI-compatible provider, by overriding the env vars below.
BASE_URL = os.environ.get("GRAPH_RPG_BASE_URL", "https://openrouter.ai/api/v1")
API_KEY = (
    os.environ.get("GRAPH_RPG_API_KEY")
    or os.environ.get("OPENROUTER_API_KEY")
    or os.environ.get("OPENAI_API_KEY")
)
if not API_KEY:
    raise RuntimeError(
        "No API key found. Set the OPENROUTER_API_KEY environment variable "
        "(or OPENAI_API_KEY / GRAPH_RPG_API_KEY), e.g.:\n"
        "    export OPENROUTER_API_KEY=sk-or-...\n"
        "Get a key at https://openrouter.ai/keys"
    )

# ---- Models ----
# Pick any model id your BASE_URL provider serves. Defaults below assume
# OpenRouter; swap these if you point BASE_URL elsewhere.
GEN_MODEL = os.environ.get("GRAPH_RPG_GEN_MODEL", "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free")
EMBED_MODEL = os.environ.get("GRAPH_RPG_EMBED_MODEL", "openai/text-embedding-3-small")

# ---- Thinking mode ----
# Some models (reasoning models) can emit an extended chain-of-thought pass
# before answering. It's slow and unnecessary here since we only want
# strict JSON out. THINK=False both asks the API to suppress it (where
# supported) and instructs the model directly in the system prompt not to
# show reasoning, as a belt-and-suspenders approach for models/providers
# that don't support an explicit "no thinking" API flag.
THINK = _env_bool("GRAPH_RPG_THINK", False)

# ---- Timeouts (seconds) ----
# Generous by default since some hosted models (especially free-tier /
# large MoE models) can be slow or queued.
TIMEOUT_GENERATE = _env_int("GRAPH_RPG_TIMEOUT_GENERATE", 600)   # 10 min
TIMEOUT_EMBED = _env_int("GRAPH_RPG_TIMEOUT_EMBED", 120)         # 2 min per embedding call

# ---- Output length cap ----
# Extra safety net against runaway "thinking" (on top of THINK=False and
# the /no_think prompt directive): hard-caps how many tokens the model can
# generate per call. 32768 is comfortably more than a JSON graph update
# needs, but stops a misbehaving model from burning thousands of tokens
# on reasoning it wasn't supposed to produce at all.
MAX_TOKENS = _env_int("GRAPH_RPG_MAX_TOKENS", 32768)

# ---- Generation temperature ----
TEMPERATURE_INTERVIEW = 0.4
TEMPERATURE_ACTION = 0.5

# ---- RAG ----
RAG_TOP_K = _env_int("GRAPH_RPG_RAG_TOP_K", 8)

# ---- Web search grounding ----
# Grounds action resolution in real-world facts (population/military/
# economic figures, historical precedent, current events, real entities)
# via DuckDuckGo, per the world model's "Retrieving Missing Information"
# rule: search the graph first, then infer, then search the internet, and
# only fall back to the model's own knowledge if neither applies.
ENABLE_WEB_SEARCH = _env_bool("GRAPH_RPG_ENABLE_WEB_SEARCH", True)
WEB_SEARCH_MAX_RESULTS = _env_int("GRAPH_RPG_WEB_SEARCH_MAX_RESULTS", 4)
WEB_SEARCH_TIMEOUT = _env_int("GRAPH_RPG_WEB_SEARCH_TIMEOUT", 15)
WEB_SEARCH_MAX_QUERIES = _env_int("GRAPH_RPG_WEB_SEARCH_MAX_QUERIES", 3)
