"""
Personal Life Graph Simulation - CLI entry point.

Usage:
    export OPENROUTER_API_KEY=sk-or-...
    python main.py

Uses the `openai` Python library against an OpenAI-compatible API
(OpenRouter by default -- see config.py to change provider/model).
"""
import os
import sys

import config
from engine import run_interview, process_action
from graph_store import GraphStore
import llm_client as oc
import web_search

SAVE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "saves")


def list_saves():
    if not os.path.isdir(SAVE_DIR):
        return []
    return sorted(f for f in os.listdir(SAVE_DIR) if f.endswith(".json"))


def choose_save() -> str:
    saves = list_saves()
    print("\n=== Personal Life Graph Simulation ===")
    if saves:
        print("Existing saves:")
        for i, s in enumerate(saves, 1):
            print(f"  {i}. {s}")
        print("  n. New game")
        choice = input("Choose a save number, or 'n' for new: ").strip().lower()
        if choice != "n" and choice.isdigit() and 1 <= int(choice) <= len(saves):
            return os.path.join(SAVE_DIR, saves[int(choice) - 1])
    # new game
    name = input("Name this save (e.g. my_life): ").strip() or "my_life"
    if not name.endswith(".json"):
        name += ".json"
    return os.path.join(SAVE_DIR, name)


def show_situation(narrative: str, suggested_actions: list, evidence_used: list = None):
    print(f"\n{narrative}\n")
    if evidence_used:
        print("Sources used:")
        for e in evidence_used:
            claim = e.get("claim", "").strip()
            source = e.get("source", "").strip()
            conf = e.get("confidence")
            conf_str = f" (confidence {conf})" if conf is not None else ""
            print(f"  - {claim}{conf_str}")
            if source:
                print(f"    {source}")
        print()
    if suggested_actions:
        print("What next?")
        for i, a in enumerate(suggested_actions, 1):
            print(f"  {i}. {a}")
        print("  (or just type your own action)")
    print(
        "\nOther commands: 'graph' = show full graph state, "
        "'timeline' = review your event history, "
        "'find <text>' = search your saved graph, "
        "'search <query>' = search the web, "
        "'quit' = save & exit."
    )


def handle_find(store: GraphStore, term: str):
    """Look up stored/historical info already in the save file (Level 1
    of the world model's Retrieving Missing Information rule)."""
    matches = store.find_by_name(term) or store.keyword_relevant_nodes(term, top_k=10)
    if not matches:
        print(f"\nNothing in your graph matches '{term}'.")
        return
    print(f"\nFound {len(matches)} node(s) matching '{term}':")
    for n in matches:
        rel_str = "; ".join(
            f"{r['relation']}->{store.nodes.get(r['target'], {}).get('name', r['target'])}"
            for r in n.get("relations", [])
        )
        print(f"- [{n['id']}] {n['name']} ({n['type']}) state={n.get('state')}")
        print(f"    attrs: {n.get('attributes', {})}")
        if rel_str:
            print(f"    relations: {rel_str}")


def handle_search(query: str):
    """Direct, on-demand web search (Level 3 of the same rule) -- separate
    from the automatic grounding that already runs during action
    resolution, for when the player just wants to look something up."""
    if not web_search.is_available():
        print(
            "\nWeb search isn't available: the 'ddgs' package isn't installed.\n"
            "Install it with: pip install ddgs"
        )
        return
    if not config.ENABLE_WEB_SEARCH:
        print("\nWeb search is disabled (GRAPH_RPG_ENABLE_WEB_SEARCH=false).")
        return
    print(f"\n[Searching: {query}]")
    results = web_search.search(query)
    if not results:
        print("No results (or the search failed silently -- check your connection).")
        return
    for r in results:
        print(f"\n- {r['title']}\n  {r['snippet']}\n  {r['url']}")


def resolve_input(raw: str, suggested_actions: list) -> str:
    """If raw is a valid menu number, resolve it to the matching suggested
    action text; otherwise treat raw as a free-form custom action."""
    if raw.isdigit():
        idx = int(raw)
        if 1 <= idx <= len(suggested_actions):
            return suggested_actions[idx - 1]
    return raw


def main():
    os.makedirs(SAVE_DIR, exist_ok=True)

    try:
        # quick connectivity check
        oc.generate(
            config.GEN_MODEL,
            "Reply with just: ok",
            temperature=0,
            think=config.THINK,
            timeout=config.TIMEOUT_GENERATE,
            max_tokens=config.MAX_TOKENS,
        )
    except oc.LLMError as e:
        print(f"\n[Error] {e}")
        print(
            f"Check that your API key is set (config.API_KEY / OPENROUTER_API_KEY) "
            f"and that '{config.GEN_MODEL}' is available at {config.BASE_URL}."
        )
        sys.exit(1)

    save_path = choose_save()

    if os.path.exists(save_path):
        print(f"\n[Loading {save_path}]")
        store = GraphStore.load(save_path)
        narrative = store.last_narrative or (
            "You're back. Here's where things stand:\n" + store.summary_text()
        )
        suggested_actions = store.last_suggested_actions
        evidence_used = store.last_evidence_used
    else:
        store, narrative, suggested_actions = run_interview()
        evidence_used = []
        store.last_narrative = narrative
        store.last_suggested_actions = suggested_actions
        store.last_evidence_used = evidence_used
        store.save(save_path)
        print(f"\n[Saved initial world to {save_path}]")

    print("\n=== Ready. ===")

    while True:
        show_situation(narrative, suggested_actions, evidence_used)
        raw = input("\n> ").strip()
        if not raw:
            continue
        if raw.lower() in ("quit", "exit"):
            store.save(save_path)
            print(f"[Saved to {save_path}. Bye.]")
            break
        if raw.lower() == "graph":
            print("\n" + store.summary_text())
            continue
        if raw.lower() == "timeline":
            print("\n" + store.timeline_text())
            continue
        if raw.lower().startswith("find "):
            handle_find(store, raw[len("find "):].strip())
            continue
        if raw.lower().startswith("search "):
            handle_search(raw[len("search "):].strip())
            continue

        action = resolve_input(raw, suggested_actions)

        try:
            narrative, suggested_actions, evidence_used = process_action(store, action)
        except oc.LLMError as e:
            print(f"[Model error, action not applied: {e}]")
            continue

        store.last_narrative = narrative
        store.last_suggested_actions = suggested_actions
        store.last_evidence_used = evidence_used
        store.save(save_path)
        print(f"\n--- Day {store.turn}: {action} ---")


if __name__ == "__main__":
    main()
