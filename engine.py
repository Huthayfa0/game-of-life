"""
Engine: ties together GraphStore + the LLM client + prompts.
- run_interview(): builds the initial graph from Q&A
- process_action(): retrieves relevant context (RAG), asks the model to
  resolve the action, applies the diff to the graph, appends events/history
"""
import json

import config
import llm_client as oc
import prompts
from graph_store import GraphStore

GEN_MODEL = config.GEN_MODEL
EMBED_MODEL = config.EMBED_MODEL

INTERVIEW_QUESTIONS = [
    "Where do you live (city/country)?",
    "Describe your current living situation (housing, who you live with).",
    "What's your job / main occupation right now?",
    "Roughly, how are things financially right now?",
    "How's your health / energy level lately?",
    "Who are the important people in your life right now, and your relationship to them?",
    "What are 1-3 things you're currently trying to achieve or working toward?",
    "Anything else about your current situation worth capturing?",
]


def run_interview() -> GraphStore:
    print("\n=== World Setup: tell me about your current life ===")
    print("(Press Enter to skip a question if it doesn't apply.)\n")
    answers = {}
    for q in INTERVIEW_QUESTIONS:
        ans = input(f"{q}\n> ").strip()
        if ans:
            answers[q] = ans

    qa_text = "\n".join(f"Q: {q}\nA: {a}" for q, a in answers.items())
    prompt = f"Interview answers:\n\n{qa_text}\n\nBuild the initial graph JSON now."

    print("\n[Building your initial world graph...]")
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
    return store


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


def process_action(store: GraphStore, action_text: str) -> str:
    """Returns narration text; mutates store in place."""
    store.turn += 1
    context = _get_context(store, action_text)

    prompt = (
        f"{context}\n\n"
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

    event = data.get("event", {})
    event["time"] = time_label
    store.add_event(event)

    for node in data.get("node_updates", []):
        for h in node.get("history", []):
            if h.get("time") == "CURRENT_TURN":
                h["time"] = time_label
        store.upsert_node(node)

    for k, v in data.get("world_state_changes", {}).items():
        store.world_state[k] = v

    return data.get("narration", "(no narration returned)")
