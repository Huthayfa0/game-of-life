"""
Personal Life Graph Simulation - CLI entry point.

Usage:
    python main.py

Requires a local Ollama server running (`ollama serve`), and the models
qwen3:4b (generation) and qwen3-rag (embeddings, optional) pulled.
"""
import os
import sys

import config
from engine import run_interview, process_action
from graph_store import GraphStore
import ollama_client as oc

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
    except oc.OllamaError as e:
        print(f"\n[Error] {e}")
        print(f"Start Ollama with `ollama serve` and make sure `{config.GEN_MODEL}` is pulled.")
        sys.exit(1)

    save_path = choose_save()

    if os.path.exists(save_path):
        print(f"\n[Loading {save_path}]")
        store = GraphStore.load(save_path)
    else:
        store = run_interview()
        store.save(save_path)
        print(f"\n[Saved initial world to {save_path}]")

    print("\n=== Ready. Type an action each turn (e.g. 'I go for a run'). ===")
    print("Commands: 'graph' = show full graph, 'quit' = save & exit.\n")

    while True:
        action = input("\nWhat do you do?\n> ").strip()
        if not action:
            continue
        if action.lower() in ("quit", "exit"):
            store.save(save_path)
            print(f"[Saved to {save_path}. Bye.]")
            break
        if action.lower() == "graph":
            print("\n" + store.summary_text())
            continue

        try:
            narration = process_action(store, action)
        except oc.OllamaError as e:
            print(f"[Model error, action not applied: {e}]")
            continue

        store.save(save_path)
        print(f"\n--- Day {store.turn} ---")
        print(narration)


if __name__ == "__main__":
    main()
