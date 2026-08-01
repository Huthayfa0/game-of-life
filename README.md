# Personal Life Graph Simulation

A cloud-LLM-powered life simulation built on your node-graph world model
spec (everything is a node, typed relations, world state, event history,
AI decision loop), using the `openai` Python library against OpenRouter
(or any other OpenAI-compatible API) as the backend.

## Requirements

- The `openai` Python package: `pip install openai`
- An API key for your chosen provider. Defaults to OpenRouter:
  ```bash
  export OPENROUTER_API_KEY=sk-or-...
  ```
  Get a key at https://openrouter.ai/keys. The app will refuse to start
  with a clear error if no key is found.

## Configuration

All tunables live in `config.py`. Either edit the file directly, or override
at launch with environment variables:

| Setting | Env var | Default | Notes |
|---|---|---|---|
| Backend URL | `GRAPH_RPG_BASE_URL` | `https://openrouter.ai/api/v1` | Point this at `https://api.openai.com/v1` or any other OpenAI-compatible endpoint to switch providers. |
| API key | `GRAPH_RPG_API_KEY` | — | Falls back to `OPENROUTER_API_KEY` or `OPENAI_API_KEY` if set. Required — startup fails with a clear message if none is found. |
| Generation model | `GRAPH_RPG_GEN_MODEL` | `nvidia/nemotron-3-ultra-550b-a55b:free` | Any model id your BASE_URL provider serves. |
| Embedding model | `GRAPH_RPG_EMBED_MODEL` | `openai/text-embedding-3-small` | Used for RAG retrieval. If unavailable, the engine automatically falls back to keyword-based retrieval, so nothing breaks. |
| Thinking mode | `GRAPH_RPG_THINK` | `false` | Some models emit an extended reasoning pass before answering; off by default since it's slow and unnecessary for structured JSON output. |
| Generate timeout | `GRAPH_RPG_TIMEOUT_GENERATE` | `600` (10 min) | generous, since some hosted/free-tier models can be slow or queued |
| Embed timeout | `GRAPH_RPG_TIMEOUT_EMBED` | `120` (2 min) | per embedding call |
| Max output tokens | `GRAPH_RPG_MAX_TOKENS` | `2048` | hard cap per generation call (see "Avoiding wasted thinking tokens" below) |
| RAG top-k | `GRAPH_RPG_RAG_TOP_K` | `8` | how many nodes get pulled into context per turn |

### Avoiding wasted thinking tokens

Reasoning models can default to an extended `<think>...</think>` pass
before answering, which is slow and pointless here since we only want
structured JSON. Three independent layers keep that off:

1. **`/no_think`** is appended to the actual prompt text. Some model
   families (e.g. Qwen3) respond to this directive directly, independent
   of backend — the most portable of the three.
2. **`extra_body={"reasoning": {"exclude": True}, "think": False}`** is
   sent alongside the standard OpenAI params on every call.
   `reasoning.exclude` is OpenRouter's native switch for suppressing
   reasoning tokens; `think` covers other providers with a similar flag.
   Fields a backend doesn't recognize are just ignored, and if one
   hard-rejects an unknown field, the client automatically retries once
   without it.
3. **`max_tokens` cap** (`GRAPH_RPG_MAX_TOKENS`) hard-limits how many
   tokens a single call can produce, so even if 1 and 2 both fail for some
   reason, a call can't silently burn thousands of tokens reasoning.

As a final safety net, any `<think>...</think>` block that still leaks
into the response is stripped out before JSON parsing. If a response turns
out to be *entirely* a thinking block that got cut off by the token cap,
you'll get a clear error telling you to raise `GRAPH_RPG_MAX_TOKENS` or
check whether your backend/model supports disabling reasoning — rather
than a cryptic JSON parse failure.

Example:
```bash
GRAPH_RPG_TIMEOUT_GENERATE=900 GRAPH_RPG_GEN_MODEL=openai/gpt-4o-mini python main.py
```

## Run it

```bash
export OPENROUTER_API_KEY=sk-or-...
python main.py
```

First run:
1. It asks you a short intake interview (where you live, living situation,
   job, finances, health, key people, current goals).
2. It sends those answers to the configured model with the node-graph
   ruleset as a system prompt, and gets back a strict JSON graph (Person
   node for you, plus City/Company/Person/Goal nodes etc. with typed
   relations).
3. That graph is saved to `saves/<name>.json`.

Every subsequent run:
1. Pick your existing save (or start a new one).
2. Type an action in plain English each turn, e.g.:
   - `I apply for a new job at a tech company`
   - `I go to the gym`
   - `I call my brother to catch up`
3. The engine:
   - Pulls the most relevant nodes from your graph (RAG step — via the
     configured embedding model if available, otherwise keyword match)
   - Sends those + the action + the ruleset to the generation model
   - Gets back a JSON diff: new event, node/attribute/relation updates,
     world state changes, and a short narration
   - Applies the diff to the graph (nothing is deleted — updates append to
     history, per rule 20) and re-saves the file
   - Prints the narration to you

Type `graph` at any time to print the full current graph state.
Type `quit` to save and exit.

## File map

| File              | Responsibility |
|-------------------|----------------|
| `config.py`       | Backend URL/key, model names, thinking-mode toggle, timeouts, RAG top-k — all overridable via env vars |
| `llm_client.py`   | `openai`-library-based client for chat completions + embeddings against any OpenAI-compatible backend, plus JSON-extraction helper for messy model output |
| `graph_store.py`  | The node/relation/world-state/event data model + JSON save/load |
| `prompts.py`      | System prompts that embed your full ruleset for (a) initial graph creation, (b) per-turn action resolution |
| `engine.py`       | Orchestration: interview → initial graph; RAG retrieval → action resolution → graph diff application |
| `main.py`         | CLI: save selection, interview trigger, turn loop |

## Notes / things you may want to tune

- **Cost**: every action turn makes one generation call, plus one
  embedding call per graph node (for RAG retrieval) if `EMBED_MODEL`
  supports it. Free-tier models avoid direct cost; paid models will accrue
  per-token charges — keep an eye on usage if your graph grows large.
- **Embedding cost/latency**: the current RAG implementation re-embeds
  every node on every turn for simplicity. Fine for a personal-scale graph
  (dozens of nodes), but if your graph grows large, cache embeddings per
  node (store them alongside the node in the save file and only recompute
  on change).
- **Model choice**: any model id your BASE_URL provider serves works —
  change `GRAPH_RPG_GEN_MODEL` / `GRAPH_RPG_EMBED_MODEL` to try something
  faster, cheaper, or higher quality.
- **Validation strictness**: right now the action resolver is intentionally
  lenient (rule: "let them attempt it, reflect realistic consequences")
  rather than hard-blocking actions like the wargame version's Action
  Validation section (#18). If you want hard validation (e.g. can't "buy a
  house" with $0), that logic can be added as a pre-check in `engine.py`
  before calling the model.
- **Multiple actors**: this build assumes a single Person_Player node. The
  original spec supports many autonomous actors with their own goals/
  knowledge graphs (#21, #22) — that's a natural next step if you want NPCs
  in your life (e.g. simulate how a friend or coworker might independently
  act) but it's out of scope for this first version.
