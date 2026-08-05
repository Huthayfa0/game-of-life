"""
Engine: ties together GraphStore + the LLM client + prompts.
- run_interview(): a short Q&A, then asks the model to build the initial
  graph PLUS an opening narrative and a menu of suggested next actions.
- process_action(): retrieves relevant context (RAG), asks the model to
  resolve the action, applies the diff to the graph, appends events/history,
  and returns a narrative + a fresh menu of suggested next actions.
"""
import json

import config
import llm_client as oc
import prompts
import web_search
from graph_store import GraphStore

GEN_MODEL = config.GEN_MODEL
EMBED_MODEL = config.EMBED_MODEL

# Kept deliberately short -- the model fleshes out the rest of the world
# itself (see rule 10 / the INTERVIEW_SYSTEM prompt) rather than
# interrogating the player for every detail.
INTERVIEW_QUESTIONS = [
    "In a sentence, where do you live and what's your living situation?",
    "What do you do (job/school/etc.), and how's that going?",
    "What's one goal or worry on your mind lately?",
]


def build_initial_graph(answers: dict):
    """
    Core interview logic, with no stdin/stdout of its own -- takes a
    {question: answer} dict (any subset of INTERVIEW_QUESTIONS, possibly
    empty) and returns (store, narrative, suggested_actions). Safe to call
    from any frontend (CLI, web UI, etc.).
    """
    qa_text = "\n".join(f"Q: {q}\nA: {a}" for q, a in answers.items() if a) or \
        "(no answers given -- invent a plausible ordinary life)"
    prompt = f"Interview answers:\n\n{qa_text}\n\nBuild the initial graph JSON now."

    raw = oc.generate(
        GEN_MODEL,
        prompt,
        system=prompts.INTERVIEW_SYSTEM,
        temperature=config.TEMPERATURE_INTERVIEW,
        think=config.THINK,
        timeout=config.TIMEOUT_GENERATE,
        max_tokens=config.MAX_TOKENS,
    )
    data = oc.extract_json(raw)

    store = GraphStore()
    store.world_state = data.get("world_state", {})
    for node in data.get("nodes", []):
        store.upsert_node(node)
    store.turn = 0
    store.add_event({
        "time": "Day 0",
        "actors": ["Person_Player"],
        "targets": [],
        "effects": {"note": "World initialized from intake interview."},
        "confidence": 1.0,
        "visibility": "public",
    })

    narrative = data.get("narrative", "(no opening narrative returned)")
    suggested_actions = data.get("suggested_actions", [])
    return store, narrative, suggested_actions


def run_interview():
    """
    CLI wrapper: prompts on stdin/stdout for INTERVIEW_QUESTIONS, then
    delegates to build_initial_graph(). Returns (store, narrative,
    suggested_actions).
    """
    print("\n=== World Setup ===")
    print("A few quick questions -- keep answers short, I'll fill in the rest.")
    print("(Press Enter to skip any of them.)\n")
    answers = {}
    for q in INTERVIEW_QUESTIONS:
        ans = input(f"{q}\n> ").strip()
        if ans:
            answers[q] = ans

    print("\n[Building your world...]")
    return build_initial_graph(answers)


def _get_context(store: GraphStore, action_text: str, top_k: int = None) -> str:
    """RAG step: try embedding similarity via the configured embedding model; fall back to keyword match."""
    top_k = top_k or config.RAG_TOP_K
    relevant_nodes = None
    try:
        query_vec = oc.embed(EMBED_MODEL, action_text, timeout=config.TIMEOUT_EMBED)
        scored = []
        for node in store.nodes.values():
            node_text = json.dumps(node)
            try:
                node_vec = oc.embed(EMBED_MODEL, node_text, timeout=config.TIMEOUT_EMBED)
            except oc.LLMError:
                continue
            sim = oc.cosine_similarity(query_vec, node_vec)
            scored.append((sim, node))
        scored.sort(key=lambda x: -x[0])
        relevant_nodes = [n for _, n in scored[:top_k]]
    except oc.LLMError:
        relevant_nodes = None

    if not relevant_nodes:
        relevant_nodes = store.keyword_relevant_nodes(action_text, top_k=top_k)

    # Always include the player node and anything with no match if graph is small
    if "Person_Player" in store.nodes:
        player = store.nodes["Person_Player"]
        if player not in relevant_nodes:
            relevant_nodes = [player] + relevant_nodes

    if not relevant_nodes:
        relevant_nodes = list(store.nodes.values())[:top_k]

    lines = [f"World state: {json.dumps(store.world_state)}", f"Turn: Day {store.turn}", "Relevant nodes:"]
    for n in relevant_nodes:
        lines.append(json.dumps(n))
    return "\n".join(lines)


def _gather_evidence(store: GraphStore, action_text: str) -> list:
    """
    Decides whether the action needs real-world grounding and, if so, runs
    the search(es) and returns a flat list of {"query", "title", "url",
    "snippet"} dicts. Returns [] for mundane actions, if web search is
    disabled, or if anything along the way fails -- degrading gracefully
    to "resolve without extra evidence" rather than blocking the turn.
    """
    if not config.ENABLE_WEB_SEARCH or not web_search.is_available():
        return []

    try:
        raw = oc.generate(
            GEN_MODEL,
            f"Player action: {action_text}\n\n"
            f"Relevant graph snapshot:\n{store.summary_text(max_nodes=15)}",
            system=prompts.SEARCH_QUERY_SYSTEM,
            temperature=0.2,
            think=config.THINK,
            timeout=config.TIMEOUT_GENERATE,
            max_tokens=300,
        )
        data = oc.extract_json(raw)
    except oc.LLMError:
        return []

    queries = data.get("queries", [])[: config.WEB_SEARCH_MAX_QUERIES]
    evidence = []
    for q in queries:
        for r in web_search.search(q):
            evidence.append({"query": q, **r})
    return evidence


def _format_evidence(evidence: list) -> str:
    if not evidence:
        return ""
    lines = [
        "EVIDENCE (from web search -- ground your resolution in these facts, "
        "and note in evidence_used what you relied on):"
    ]
    for e in evidence:
        lines.append(f"- [{e['query']}] {e['title']}: {e['snippet']} (source: {e['url']})")
    return "\n".join(lines)


def process_action(store: GraphStore, action_text: str):
    """
    Resolves one action, mutates store in place, and returns
    (narrative, suggested_actions, evidence_used). evidence_used is the
    list of {"claim", "source", "confidence"} dicts the model says it
    actually relied on (empty list if no evidence was gathered or none
    was used) -- see prompts.ACTION_SYSTEM's evidence_used field.
    """
    store.turn += 1
    context = _get_context(store, action_text)
    evidence = _gather_evidence(store, action_text)
    evidence_block = _format_evidence(evidence)

    prompt = (
        f"{context}\n\n"
        f"{evidence_block}\n\n"
        f"PLAYER ACTION (Day {store.turn}): {action_text}\n\n"
        f"Resolve this action now."
    )
    raw = oc.generate(
        GEN_MODEL,
        prompt,
        system=prompts.ACTION_SYSTEM,
        temperature=config.TEMPERATURE_ACTION,
        think=config.THINK,
        timeout=config.TIMEOUT_GENERATE,
        max_tokens=config.MAX_TOKENS,
    )
    data = oc.extract_json(raw)

    time_label = f"Day {store.turn}"

    evidence_used = data.get("evidence_used", [])

    event = data.get("event", {})
    event["time"] = time_label
    if evidence:
        event["evidence_searched"] = evidence
    event["evidence_used"] = evidence_used
    store.add_event(event)

    for node in data.get("node_updates", []):
        for h in node.get("history", []):
            if h.get("time") == "CURRENT_TURN":
                h["time"] = time_label
        store.upsert_node(node)

    for k, v in data.get("world_state_changes", {}).items():
        store.world_state[k] = v

    narrative = data.get("narrative", "(no narrative returned)")
    suggested_actions = data.get("suggested_actions", [])
    return narrative, suggested_actions, evidence_used
