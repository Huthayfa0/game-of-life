"""
GraphStore: implements the "Everything is a Node" world model.
Handles nodes, relations, world state, events, and history.
Everything persists to a single JSON save file. Nothing is ever deleted
(rule 20: History) -- updates append to history instead of overwriting.
"""
import json
import os
import re
from datetime import datetime


def slugify_id(prefix: str, name: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", name).strip("_")
    return f"{prefix}_{slug}"


class GraphStore:
    def __init__(self):
        self.nodes: dict = {}          # id -> node dict
        self.world_state: dict = {}    # global variables
        self.events: list = []         # global event log
        self.turn: int = 0             # "Day N" counter
        self.last_narrative: str = ""            # most recent narrative shown to the player
        self.last_suggested_actions: list = []   # most recent action menu shown to the player
        self.last_evidence_used: list = []       # most recent {"claim","source","confidence"} list
        self.meta: dict = {
            "created": datetime.utcnow().isoformat(),
            "last_updated": datetime.utcnow().isoformat(),
        }

    # ---------- node operations ----------

    def upsert_node(self, node: dict):
        """
        Add a new node or merge into an existing one (by id).
        Merging: attributes are updated (overwritten per-key), relations
        are appended (deduped by relation+target), history is appended.
        """
        node_id = node["id"]
        if node_id not in self.nodes:
            node.setdefault("attributes", {})
            node.setdefault("relations", [])
            node.setdefault("history", [])
            node.setdefault("state", node.get("state", "stable"))
            self.nodes[node_id] = node
            return

        existing = self.nodes[node_id]
        existing["name"] = node.get("name", existing["name"])
        existing["type"] = node.get("type", existing["type"])
        existing["category"] = node.get("category", existing.get("category"))
        if "state" in node and node["state"]:
            existing["state"] = node["state"]

        for k, v in node.get("attributes", {}).items():
            existing.setdefault("attributes", {})[k] = v

        existing.setdefault("relations", [])
        for rel in node.get("relations", []):
            self._merge_relation(existing, rel)

        existing.setdefault("history", [])
        existing["history"].extend(node.get("history", []))

    def _merge_relation(self, node: dict, rel: dict):
        for existing_rel in node["relations"]:
            if existing_rel.get("relation") == rel.get("relation") and \
               existing_rel.get("target") == rel.get("target"):
                existing_rel.update(rel)
                return
        node["relations"].append(rel)

    def get_node(self, node_id: str) -> dict:
        return self.nodes.get(node_id)

    def find_by_name(self, name: str):
        name_lower = name.lower()
        return [n for n in self.nodes.values() if name_lower in n["name"].lower()]

    def add_event(self, event: dict):
        event.setdefault("time", f"Day {self.turn}")
        self.events.append(event)

    def append_node_history(self, node_id: str, history_entry: dict):
        if node_id in self.nodes:
            self.nodes[node_id].setdefault("history", []).append(history_entry)

    # ---------- context retrieval (simple, non-embedding fallback) ----------

    def keyword_relevant_nodes(self, text: str, top_k: int = 8):
        text_lower = text.lower()
        scored = []
        for n in self.nodes.values():
            score = 0
            if n["name"].lower() in text_lower or any(
                w in text_lower for w in n["name"].lower().split()
            ):
                score += 3
            for rel in n.get("relations", []):
                target = self.nodes.get(rel.get("target"))
                if target and target["name"].lower() in text_lower:
                    score += 1
            if score > 0:
                scored.append((score, n))
        scored.sort(key=lambda x: -x[0])
        return [n for _, n in scored[:top_k]]

    def edges(self):
        """
        Returns a flat list of (source_id, relation, target_id) for every
        relation in the graph -- useful for checking how connected the
        graph actually is (e.g. are nodes only linked to Person_Player, or
        to each other too).
        """
        result = []
        for n in self.nodes.values():
            for r in n.get("relations", []):
                result.append((n["id"], r.get("relation"), r.get("target")))
        return result

    # ---------- persistence ----------

    def to_dict(self) -> dict:
        self.meta["last_updated"] = datetime.utcnow().isoformat()
        return {
            "meta": self.meta,
            "turn": self.turn,
            "world_state": self.world_state,
            "nodes": self.nodes,
            "events": self.events,
            "last_narrative": self.last_narrative,
            "last_suggested_actions": self.last_suggested_actions,
            "last_evidence_used": self.last_evidence_used,
        }

    def save(self, path: str):
        os.makedirs(os.path.dirname(path), exist_ok=True) if os.path.dirname(path) else None
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)

    @classmethod
    def load(cls, path: str) -> "GraphStore":
        store = cls()
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        store.meta = data.get("meta", store.meta)
        store.turn = data.get("turn", 0)
        store.world_state = data.get("world_state", {})
        store.nodes = data.get("nodes", {})
        store.events = data.get("events", [])
        store.last_narrative = data.get("last_narrative", "")
        store.last_suggested_actions = data.get("last_suggested_actions", [])
        store.last_evidence_used = data.get("last_evidence_used", [])
        return store

    def summary_text(self, max_nodes: int = 40) -> str:
        """A compact plain-text summary of the whole graph, for prompting."""
        lines = [f"Turn: Day {self.turn}", f"World state: {json.dumps(self.world_state)}"]
        for n in list(self.nodes.values())[:max_nodes]:
            rel_str = "; ".join(
                f"{r['relation']}->{self.nodes.get(r['target'], {}).get('name', r['target'])}"
                for r in n.get("relations", [])
            )
            lines.append(
                f"- [{n['id']}] {n['name']} ({n['type']}/{n.get('category','')}) "
                f"state={n.get('state')} attrs={json.dumps(n.get('attributes', {}))} "
                f"relations=[{rel_str}]"
            )
        return "\n".join(lines)

    def timeline_text(self) -> str:
        """
        Formats the full event log as a readable "Day N: summary" list, in
        chronological order, with any evidence used for that turn nested
        underneath -- a way to review how you got here without reading
        raw JSON. Used by both the CLI's 'timeline' command and the web
        UI's Timeline tab.
        """
        if not self.events:
            return "No events yet."
        lines = []
        for e in self.events:
            time_label = e.get("time", "?")
            summary = e.get("summary") or (e.get("effects") or {}).get("note") or "(no summary)"
            lines.append(f"{time_label}: {summary}")
            for ev in e.get("evidence_used") or []:
                claim = (ev.get("claim") or "").strip()
                if not claim:
                    continue
                source = (ev.get("source") or "").strip()
                suffix = f" [{source}]" if source else ""
                lines.append(f"    source: {claim}{suffix}")
        return "\n".join(lines)
