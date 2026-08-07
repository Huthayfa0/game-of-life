# Personal Life Graph Simulation

A cloud-LLM-powered life simulation built on your node-graph world model
spec (everything is a node, typed relations, world state, event history,
AI decision loop), using the `openai` Python library against OpenRouter
(or any other OpenAI-compatible API) as the backend.

Each turn, the game gives you a short narrative of what's happening plus a
menu of suggested next actions grounded in your actual graph — pick one by
number/click, or type anything else you'd rather do instead.

Two frontends, same engine and save files:
- **`main.py`** — terminal/CLI. No extra dependencies, shows raw errors
  and stack traces directly, so it's the one to use for debugging.
- **`web_ui.py`** — a minimal local web UI (buttons, text boxes, tabs)
  built with [Gradio](https://gradio.app). Same game, same `saves/`
  folder, just point-and-click instead of typing commands.

## Requirements

- The `openai` Python package: `pip install openai`
- The `ddgs` package for web search grounding (optional but recommended): `pip install ddgs`
- `gradio`, only if you want the web UI: `pip install gradio`
- An API key for your chosen provider. Defaults to OpenRouter:
  ```bash
  export OPENROUTER_API_KEY=sk-or-...
  ```
  Get a key at https://openrouter.ai/keys. Both frontends refuse to start
  with a clear error if no key is found.

## Quick start

**Terminal:**
```bash
pip install openai ddgs
export OPENROUTER_API_KEY=sk-or-...
python main.py
```

**Web UI:**
```bash
pip install openai ddgs gradio
export OPENROUTER_API_KEY=sk-or-...
python web_ui.py
```
Then open the local URL it prints (usually `http://127.0.0.1:7860`). The
**Play** tab has the save picker, the short intake questions, the
narrative, and the action buttons; **Graph** shows your world as an
interactive network diagram (drag nodes, scroll to zoom, hover for
details — see "Visual graph view" below) with a raw-text fallback and
`find`; **Timeline** lists every turn in order with its sources, so you
can review how you got here; **Web search** is the same on-demand lookup
as the CLI's `search` command. A save started in one frontend loads fine
in the other — they read and write the same JSON files in `saves/`.

**First run (either frontend):** three short questions (where you live,
what you do, what's on your mind), then the model builds your initial
world graph — a Person node for you plus a handful of connected
supporting nodes (city, job, people, goals) — and opens with a short scene
plus 3 suggested actions.

**Every turn after that (terminal):**
```
You wake up in Springfield, coffee in hand, thinking about Acme Corp.

What next?
  1. Go to work
  2. Call in sick
  3. Look for a new job
  (or just type your own action)

Other commands: 'graph' = show full graph state, 'quit' = save & exit.

> I plan to conquer China
```
Ambitious or reality-testing actions like that one trigger an automatic
web search for grounding first (China's actual population, military
scale, historical precedent for individuals attempting anything similar),
so the resolution reflects reality rather than just narrating whatever
sounds cool — see "Search & evidence grounding" below.

Typing `1`, `2`, or `3` runs that suggested action. Typing anything else
(`I go for a run instead`) runs that as a free-form custom action. The
model resolves whichever action you chose against your graph, updates it,
and gives you a fresh narrative + a fresh menu of 3 suggestions — so the
menu evolves turn to turn instead of repeating. The web UI works the same
way: click a radio option or type in the free-text box, then "Do it".

In the terminal, `graph` prints the full current graph (every node, its
attributes, and its relations) at any time. `timeline` prints every turn
in chronological order with any sources that grounded it. `find <text>`
searches just your saved graph for matching nodes (useful once the graph
gets large). `search <query>` runs an on-demand web search outside of any
action. `quit` saves and exits. The web UI has the same four as separate
tabs (**Graph**, **Timeline**, its "Find" box, and **Web search**) instead
of typed commands. Either way, your narrative and menu are saved after
every turn, so relaunching (in either frontend) resumes exactly where you
left off without another model call.

## Why the interview is short

Earlier versions asked ~8 detailed questions up front. Now it's 3, on
purpose: rather than interrogating you for every fact, the model is
instructed to invent ordinary, plausible supporting details (a coworker's
name, an approximate rent) and mark anything it invented as "estimated"
per the world model's Unknown Information rule (Known / Unknown /
Estimated, rule 10 in `prompts.py`) instead of leaving gaps. You get a
fleshed-out world from a few sentences, and can always steer or correct it
through the actions you take afterward.

## Why the graph is a real network, not a star

Early on, every node tended to connect only to `Person_Player` (a
hub-and-spoke shape) and relation verbs were generic (`related_to`,
`connected_to`). Two things fixed that, both enforced in `prompts.py`:

- **Connectivity rule**: whenever the model creates or touches a node
  other than the player, it's instructed to also connect it to *other*
  relevant nodes already in the graph — e.g. a Company connects
  `located_in` a City; a coworker connects `works_for` the Company, not
  just some vague relation to you. The result is an actual graph you can
  traverse, not just a list of things attached to you.
- **Typed relation vocabulary**: the prompt includes the full relation
  taxonomy from your spec (Political / Economic / Military / Social /
  Geographic / Dependency / Knowledge verbs) and the model is told to pick
  from the category matching the two node types involved, rather than
  defaulting to a generic verb. A Person-Company edge reaches for
  `works_for`/`owns`; a City-Country edge reaches for `located_in`; a
  Person-Person edge reaches for `friend_of`/`married_to`/`trusts`, etc.

You can sanity-check this yourself: `GraphStore.edges()` returns every
`(source, relation, target)` triple in the graph, so you can confirm nodes
are linking to each other and not just to you.

## Visual graph view (web UI)

The **Graph** tab in `web_ui.py` renders the network with
[vis.js](https://visjs.org): nodes colored by category (Political,
Economic, Military, Resources, Social, Geographic, Abstract, AI Internal —
same fixed palette every time), edges labeled with their relation verb
and arrowed in the right direction, force-directed layout so related
clusters naturally group together. Drag nodes around, scroll to zoom,
hover a node to see its full attributes and state.

It refreshes automatically after every start/load/action, and there's
also a manual "Refresh graph" button. A "Raw text view (for debugging)"
accordion underneath keeps the plain-text dump (`GraphStore.summary_text()`)
available too — same content the terminal's `graph` command shows — for
whenever the rendered view isn't what you need to inspect (e.g. checking
exact attribute values, or if something looks visually off and you want
to see the underlying data directly).

Implementation note: the network needs an internet connection *in your
browser* to load vis.js from a CDN (`unpkg.com`) — it's not bundled, to
keep this "simplest way possible" rather than adding a JS build step. If
you're offline or the CDN is blocked, the visual panel will just show a
blank iframe; the raw text view still works regardless, which is exactly
why it's kept rather than replaced.

## Search & evidence grounding

This follows the world model's "Retrieving Missing Information" rule
(search the graph → infer → search the internet → fall back to the
model's own knowledge):

1. **Stored data (the save file itself)** is always the first source —
   every action already pulls the most relevant nodes from your graph via
   RAG (`engine._get_context`) before resolution. You can also query it
   directly any time with `find <text>`.
2. **Automatic web grounding**: before resolving an action, a small,
   cheap model call (`prompts.SEARCH_QUERY_SYSTEM`) decides whether the
   action plausibly depends on real-world facts the model might not
   reliably know — population/military/economic figures, historical
   precedent, real institutions, current events. Mundane actions ("I go to
   the gym") return no queries and cost nothing extra. Ambitious or
   reality-testing ones ("I plan to conquer China", "I try to buy
   Twitter") get 1-3 targeted search queries, run via DuckDuckGo
   (`web_search.py`, no API key needed), and the results are fed into the
   action-resolution prompt as an EVIDENCE block. The model is instructed
   to resolve the action realistically against that evidence rather than
   narrating a fictional success — so "conquer China" comes back as the
   real-world absurdity it is, grounded in actual population/military
   figures, not a fantasy outcome.
3. **On-demand web search**: type `search <query>` any time to look
   something up directly, outside of any action.
4. **Provenance, visible in both frontends**: when evidence was used, it's
   recorded on the turn's event (`evidence_searched` = what was searched
   and found, `evidence_used` = what the model says it actually relied on,
   with a confidence value) so your save file keeps a record of what
   grounded each decision, per the spec's "Internet Rules" (source,
   confidence, retrieved-when). It's not just buried in the save file
   either — the terminal prints a "Sources used:" list right under the
   narrative whenever evidence was used, and the web UI has a "Sources
   used this turn" accordion in the same spot. Both persist through
   save/load (`GraphStore.last_evidence_used`), so reloading a save shows
   the same sources you last saw, not a blank slate.

Web search degrades gracefully everywhere: if `ddgs` isn't installed, if
`GRAPH_RPG_ENABLE_WEB_SEARCH=false`, or if a search fails for any reason
(network issue, rate limit), the game just proceeds without that evidence
instead of erroring out.

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
| Web search on/off | `GRAPH_RPG_ENABLE_WEB_SEARCH` | `true` | disable to skip all web grounding (automatic + `search` command) |
| Web search results | `GRAPH_RPG_WEB_SEARCH_MAX_RESULTS` | `4` | results fetched per query |
| Web search timeout | `GRAPH_RPG_WEB_SEARCH_TIMEOUT` | `15` (seconds) | per search call |
| Web search max queries | `GRAPH_RPG_WEB_SEARCH_MAX_QUERIES` | `3` | cap on queries generated per action turn |

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

## File map

### `config.py`
All settings in one place: backend URL/API key, which models to use for
generation and embeddings, the thinking-mode toggle, timeouts, the output
token cap, and how many graph nodes get pulled into context per turn (RAG
top-k). Everything here can be overridden by an environment variable
without editing the file — see the table above. Raises a clear error at
import time if no API key is configured anywhere.

### `llm_client.py`
The only file that talks to the network. Wraps the official `openai`
Python library's `chat.completions.create()` (for generation) and
`embeddings.create()` (for RAG retrieval) against whatever `BASE_URL` is
configured. Also owns:
- **Thinking suppression**: the `/no_think` prompt injection, the
  `extra_body` reasoning-disable flags, and the retry-without-extra-body
  fallback if a backend rejects them.
- **`strip_think()`**: regex-strips any `<think>...</think>` block that
  leaks into a response anyway, whether or not it was closed properly.
- **`extract_json()`**: pulls a JSON object out of a raw model response
  even if it's wrapped in markdown fences or has stray text around it —
  models don't always follow "respond with only JSON" perfectly.
- **`LLMError`**: a single exception type the rest of the app catches, so
  callers don't need to know which underlying `openai` exception fired.

### `graph_store.py`
The data model for the world. A `GraphStore` holds:
- `nodes` — dict of node id → node dict (id, name, type, category,
  attributes, relations, state, history)
- `world_state` — global variables that aren't tied to any one node
- `events` — the full event log (turn number, actors, targets, effects)
- `turn` — the current "Day N" counter
- `last_narrative` / `last_suggested_actions` / `last_evidence_used` —
  what the player last saw, so reloading a save resumes instantly (same
  narrative, same menu, same sources) without another model call

Key methods: `upsert_node()` (add a node, or merge into an existing one —
merging updates attributes, appends relations, and appends history rather
than overwriting, so nothing is ever lost); `edges()` (flat list of every
`(source, relation, target)` triple, useful for checking how connected the
graph actually is); `keyword_relevant_nodes()` (fallback retrieval if
embeddings aren't available); `save()` / `load()` (JSON persistence);
`summary_text()` (a compact plain-text dump of the whole graph, used both
by the `graph` command and as fallback context if a save predates the
narrative/suggestion fields); `timeline_text()` (the full event log as a
chronological "Day N: summary" list, with any evidence used nested
underneath each entry — used by the `timeline` command and the web UI's
Timeline tab).

### `web_search.py`
DuckDuckGo search via the `ddgs` package (no API key needed). Exposes
`search(query)` → list of `{title, url, snippet}`, and `is_available()`.
Degrades to returning `[]` — never raises — if `ddgs` isn't installed, web
search is disabled in config, or the search call itself fails for any
reason, so a search hiccup never blocks a turn.

### `prompts.py`
Everything the model is told, in one place. Contains:
- `RULESET` — your full node-graph spec (node types, the relation
  taxonomy, world/local state, the AI decision loop, the Unknown
  Information rule), plus the connectivity rule and relation-vocabulary
  guidance that keeps the graph from turning into a star shape.
- `NO_THINK_INSTRUCTION` — the explicit "don't show reasoning" text
  reinforcing the API-level thinking suppression.
- `SEARCH_QUERY_SYSTEM` — system prompt for a small, cheap call that
  decides whether an action needs web-search grounding and, if so, what
  to search for.
- `INTERVIEW_SYSTEM` — system prompt for turning a few short answers into
  an initial graph, an opening narrative, and 3 suggested first actions.
- `ACTION_SYSTEM` — system prompt for resolving one player action into a
  graph diff (event, node/attribute/relation changes, world state
  changes), a narrative of what happened, which evidence (if any) it
  relied on, and a fresh 3-suggestion menu.

### `engine.py`
Orchestration layer connecting the graph, the prompts, and the LLM client.
- `build_initial_graph(answers)` — the core interview logic: takes a
  `{question: answer}` dict (any subset, possibly empty), sends it to
  `INTERVIEW_SYSTEM`, and returns `(store, narrative, suggested_actions)`.
  Does no stdin/stdout of its own, so any frontend can call it directly.
- `run_interview()` — the CLI-specific wrapper: prompts on stdin/stdout for
  `INTERVIEW_QUESTIONS`, then delegates to `build_initial_graph()`. Used
  by `main.py`; `web_ui.py` calls `build_initial_graph()` directly with
  answers from its text boxes instead.
- `_get_context(store, action_text)` — the RAG step: embeds the action text
  and every node, ranks nodes by cosine similarity, and returns the top-k
  most relevant ones as context (falling back to keyword matching if
  embeddings aren't available). Always includes the player node.
- `_gather_evidence(store, action_text)` — asks `SEARCH_QUERY_SYSTEM`
  whether the action needs web grounding, runs any resulting queries
  through `web_search.search()`, and returns the results (or `[]` for
  mundane actions, or if search is unavailable/disabled/fails).
- `process_action(store, action_text)` — builds the prompt from graph
  context + any evidence, sends it to `ACTION_SYSTEM`, applies the
  returned diff to the graph (new event, node upserts, world state
  changes, evidence provenance on the event), and returns
  `(narrative, suggested_actions, evidence_used)`.

### `main.py`
The CLI. Picks or creates a save file, runs the connectivity check and
interview if needed, then loops: show the current narrative, any sources
used to ground it, and the numbered action menu; read one line of input;
resolve it to an action (a menu number → that suggestion's text, anything
else → itself as a custom action); run it through `process_action`; save;
repeat. Also handles `graph` (dump full graph), `timeline` (dump event
history), `find <text>` (search the saved graph), `search <query>`
(on-demand web search), and `quit`.

### `web_ui.py`
The point-and-click alternative to `main.py`, built with
[Gradio](https://gradio.app). Purely a frontend — it imports the exact
same `build_initial_graph()`, `process_action()`, `GraphStore`,
`web_search`, and `INTERVIEW_QUESTIONS` that `main.py` uses, and reads/
writes the same `saves/*.json` files, so nothing about the simulation
itself is duplicated. Four tabs: **Play** (save picker, the 3 intake
questions, narrative box, a "Sources used this turn" accordion,
suggested-action radio buttons, free-text action box), **Graph**
(interactive vis.js network + a "find" box + the raw-text fallback),
**Timeline** (chronological event log via `GraphStore.timeline_text()`),
and **Web search** (on-demand lookup). Only run this one if you have
`gradio` installed; `main.py` has no such requirement and remains the
simpler, more transparent option when something needs debugging.

`_format_evidence_markdown(evidence_used)` turns the list from
`process_action()`'s third return value into a small bullet list (claim,
confidence, a clickable source link) or a "no evidence" placeholder if
empty; `start_new`, `load_existing`, and `do_action` all feed it into the
Sources accordion, and it round-trips through save/load via
`GraphStore.last_evidence_used` just like the narrative and suggestions do.

Graph rendering specifics: `_build_graph_document(store)` builds a
complete standalone HTML document (nodes/edges as vis.js `DataSet`s,
colored by `_CATEGORY_COLORS`, dangling edge targets filtered out, a
defensive `</script` replacement against a node name breaking out of the
script block). `show_graph_visual(store)` HTML-escapes that document and
wraps it in `<iframe srcdoc="...">` — necessary because Gradio's `gr.HTML`
strips `<script>` tags when set directly (browsers don't execute scripts
injected via `innerHTML`), but a full document loaded into an iframe is
parsed normally and its scripts do run. `refresh_graph_views(store)`
returns both the visual and the text fallback together, and is wired to
fire automatically after every start/load/action, not just the manual
refresh button — `show_timeline(store)` for the Timeline tab is wired the
same way.

## Notes / things you may want to tune

- **Cost**: every action turn makes one generation call, plus (if the
  action seems to need real-world grounding) one small search-decision
  call and a handful of free DuckDuckGo lookups, plus one embedding call
  per graph node (for RAG retrieval) if `EMBED_MODEL` supports it.
  Free-tier models avoid direct cost; paid models will accrue per-token
  charges — keep an eye on usage if your graph grows large.
- **Web search reliability**: DuckDuckGo via `ddgs` needs no API key,
  which is convenient but also means it can be rate-limited or blocked
  more easily than a paid search API. It fails silently (the game just
  proceeds without that evidence) rather than blocking your turn, so
  reality-grounding is best-effort, not guaranteed. For heavier use,
  swapping `web_search.py`'s implementation for a paid API (Tavily,
  Serper, Bing) would be a straightforward change — it only needs to keep
  returning the same `{title, url, snippet}` shape.
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
  act) but it's out of scope for this version.

## Suggested next steps

Roughly in order of "smallest effort, biggest payoff" first:

1. **Multiple concurrent lives in the web UI.** Right now switching saves
   means reloading the page state; a proper save browser (thumbnail/list
   of all saves with last-played date, pulled from `meta.last_updated`)
   would make managing several playthroughs less clunky.
2. **Cache embeddings.** Called out above already — becomes worth doing
   once a save has enough nodes that every turn's RAG step visibly slows
   down.
3. **NPCs with their own goals.** The spec's multi-actor/knowledge-graph
   sections (#21, #22) are the biggest structural change on this list —
   worth it if you want people in your life to independently pursue their
   own goals and occasionally surprise you, rather than only reacting to
   your actions.

