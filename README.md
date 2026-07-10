# Personal Life Graph Simulation

A local, Ollama-powered life simulation built on your node-graph world model
spec (everything is a node, typed relations, world state, event history,
AI decision loop).

## Requirements

- Ollama running locally: `ollama serve`
- Models already pulled (from your `ollama list`):
  - `qwen3:4b` — does the reasoning/generation (interview parsing, action resolution)
  - `qwen3-rag` — used for embeddings/retrieval (RAG). If it doesn't support
    `/api/embeddings`, the engine automatically falls back to keyword-based
    retrieval, so nothing breaks.
  - `phi` — not used yet, wired in as an easy swap-in if you want a faster/
    lighter model later (just change `GEN_MODEL` in `engine.py`).

No external Python packages required — everything uses the standard library.

## Configuration

All tunables live in `config.py`. Either edit the file directly, or override
at launch with environment variables:

| Setting | Env var | Default | Notes |
|---|---|---|---|
| Generation model | `GRAPH_RPG_GEN_MODEL` | `qwen3:4b` | |
| Embedding model | `GRAPH_RPG_EMBED_MODEL` | `qwen3-rag` | |
| Fallback model | `GRAPH_RPG_FALLBACK_MODEL` | `phi` | not wired in yet, available to swap |
| Thinking mode | `GRAPH_RPG_THINK` | `false` | qwen3 supports an extended reasoning pass before answering; it's off by default since it's slow and unnecessary for structured JSON output. The system prompts also explicitly forbid `<think>` blocks as a backup for Ollama versions that ignore the `think` field. |
| Generate timeout | `GRAPH_RPG_TIMEOUT_GENERATE` | `600` (10 min) | generous, since the first call after a model loads into memory can be slow on CPU |
| Embed timeout | `GRAPH_RPG_TIMEOUT_EMBED` | `120` (2 min) | per embedding call |
| Max output tokens | `GRAPH_RPG_MAX_TOKENS` | `2048` | hard cap per generation call (see "Avoiding wasted thinking tokens" below) |
| RAG top-k | `GRAPH_RPG_RAG_TOP_K` | `8` | how many nodes get pulled into context per turn |

### Avoiding wasted thinking tokens

`qwen3:4b` is a reasoning model that can default to an extended `<think>...</think>`
pass before answering, which is slow and pointless here since we only want
structured JSON. Three independent layers keep that off:

1. **`think: false`** is sent on every API call. On Ollama 0.6+ this stops
   the model from generating reasoning tokens at all — the one that
   actually saves time, not just hides output.
2. **`/no_think`** is appended to the actual prompt text. This is Qwen3's
   own trained convention for disabling its reasoning mode, so it works
   even on older Ollama builds that ignore the `think` field.
3. **`num_predict` cap** (`GRAPH_RPG_MAX_TOKENS`) hard-limits how many
   tokens a single call can produce, so even if 1 and 2 both fail for some
   reason, a call can't silently burn thousands of tokens reasoning.

As a final safety net, any `<think>...</think>` block that still leaks
into the response is stripped out before JSON parsing. If a response turns
out to be *entirely* a thinking block that got cut off by the token cap,
you'll get a clear error telling you to raise `GRAPH_RPG_MAX_TOKENS` or
check your Ollama version — rather than a cryptic JSON parse failure.

Example:
```bash
GRAPH_RPG_TIMEOUT_GENERATE=900 GRAPH_RPG_GEN_MODEL=phi python main.py
```

## Run it

```bash
python main.py
```

First run:
1. It asks you a short intake interview (where you live, living situation,
   job, finances, health, key people, current goals).
2. It sends those answers to `qwen3:4b` with the node-graph ruleset as a
   system prompt, and gets back a strict JSON graph (Person node for you,
   plus City/Company/Person/Goal nodes etc. with typed relations).
3. That graph is saved to `saves/<name>.json`.

Every subsequent run:
1. Pick your existing save (or start a new one).
2. Type an action in plain English each turn, e.g.:
   - `I apply for a new job at a tech company`
   - `I go to the gym`
   - `I call my brother to catch up`
3. The engine:
   - Pulls the most relevant nodes from your graph (RAG step — via
     `qwen3-rag` embeddings if available, otherwise keyword match)
   - Sends those + the action + the ruleset to `qwen3:4b`
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
| `config.py`       | Model names, thinking-mode toggle, timeouts, RAG top-k — all overridable via env vars |
| `ollama_client.py`| stdlib-only HTTP client for Ollama's `/api/generate` and `/api/embeddings`, plus JSON-extraction helper for messy model output |
| `graph_store.py`  | The node/relation/world-state/event data model + JSON save/load |
| `prompts.py`      | System prompts that embed your full ruleset for (a) initial graph creation, (b) per-turn action resolution |
| `engine.py`       | Orchestration: interview → initial graph; RAG retrieval → action resolution → graph diff application |
| `main.py`         | CLI: save selection, interview trigger, turn loop |

## Notes / things you may want to tune

- **Embedding cost**: the current RAG implementation re-embeds every node on
  every turn for simplicity. Fine for a personal-scale graph (dozens of
  nodes), but if your graph grows large, cache embeddings per node (store
  them alongside the node in the save file and only recompute on change).
- **Model swap**: change `GEN_MODEL` / `EMBED_MODEL` constants at the top of
  `engine.py` if you want to try `phi` for speed or a different model later.
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
