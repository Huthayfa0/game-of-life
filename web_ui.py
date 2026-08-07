"""
Minimal web UI for the Personal Life Graph Simulation, built with Gradio.

This is an alternate frontend only -- it shares config.py, engine.py,
graph_store.py, prompts.py, llm_client.py, and web_search.py with main.py,
and reads/writes the exact same save files in saves/. The terminal version
(`python main.py`) is untouched and still works; it's the easier one for
debugging since you see raw prints and stack traces directly.

Install requirement:
    pip install gradio

Run:
    python web_ui.py
Then open the local URL it prints (usually http://127.0.0.1:7860).
"""
import html
import json
import os

import gradio as gr

from engine import INTERVIEW_QUESTIONS, build_initial_graph, process_action
from graph_store import GraphStore
import llm_client as oc
import web_search

SAVE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "saves")
os.makedirs(SAVE_DIR, exist_ok=True)


def list_saves():
    """Returns sorted *.json filenames in saves/ (just names, not full paths)."""
    return sorted(f for f in os.listdir(SAVE_DIR) if f.endswith(".json"))


def _save_path(name: str) -> str:
    """Turns a save name (possibly blank) into a full path under saves/, defaulting to 'my_life.json'."""
    name = (name or "").strip() or "my_life"
    if not name.endswith(".json"):
        name += ".json"
    return os.path.join(SAVE_DIR, name)


def _format_evidence_markdown(evidence_used: list) -> str:
    """Renders a process_action() evidence_used list as a markdown bullet list with clickable source links."""
    if not evidence_used:
        return "_No web evidence was used for this turn._"
    lines = []
    for e in evidence_used:
        claim = (e.get("claim") or "").strip()
        source = (e.get("source") or "").strip()
        conf = e.get("confidence")
        conf_str = f" (confidence {conf})" if conf is not None else ""
        line = f"- {claim}{conf_str}"
        if source:
            line += f" — [{source}]({source})"
        lines.append(line)
    return "\n".join(lines)


# ---------- callbacks ----------

def start_new(name, q1, q2, q3):
    """
    'Start new life' button callback: builds the initial graph from the 3
    intake answers, saves it, and returns the values for every output
    component (store, path, narrative, suggestions, save dropdown, evidence).
    """
    answers = {}
    for q, a in zip(INTERVIEW_QUESTIONS, [q1, q2, q3]):
        if a and a.strip():
            answers[q] = a.strip()
    try:
        store, narrative, suggested = build_initial_graph(answers)
    except oc.LLMError as e:
        return (
            None, "", f"[Error building world: {e}]",
            gr.update(choices=[], value=None, visible=False),
            gr.update(choices=list_saves()),
            _format_evidence_markdown([]),
        )

    store.last_narrative = narrative
    store.last_suggested_actions = suggested
    store.last_evidence_used = []  # no search happens during the interview step
    path = _save_path(name)
    store.save(path)
    return (
        store, path, narrative,
        gr.update(choices=suggested, value=None, visible=bool(suggested)),
        gr.update(choices=list_saves()),
        _format_evidence_markdown([]),
    )


def load_existing(filename):
    """'Load' button callback: reads a save file and returns its resume state (narrative/suggestions/evidence)."""
    if not filename:
        return (
            None, "", "Pick a save from the dropdown first.",
            gr.update(choices=[], value=None, visible=False),
            _format_evidence_markdown([]),
        )
    path = os.path.join(SAVE_DIR, filename)
    store = GraphStore.load(path)
    narrative = store.last_narrative or ("You're back. Here's where things stand:\n\n" + store.summary_text())
    suggested = store.last_suggested_actions
    return (
        store, path, narrative,
        gr.update(choices=suggested, value=None, visible=bool(suggested)),
        _format_evidence_markdown(store.last_evidence_used),
    )


def do_action(store, path, suggestion, custom_text):
    """
    'Do it' button callback: resolves whichever action was chosen (custom
    text takes priority over the selected suggestion), saves the updated
    store, and returns the new narrative/suggestions/evidence.
    """
    if store is None:
        return None, "", "Start or load a game first.", gr.update(), "", _format_evidence_markdown([])
    action = (custom_text or "").strip() or suggestion
    if not action:
        return store, path, "Pick a suggested action or type your own first.", gr.update(), "", gr.update()
    try:
        narrative, suggested, evidence_used = process_action(store, action)
    except oc.LLMError as e:
        return store, path, f"[Model error, action not applied: {e}]", gr.update(), "", gr.update()
    store.last_narrative = narrative
    store.last_suggested_actions = suggested
    store.last_evidence_used = evidence_used
    store.save(path)
    return (
        store, path, narrative,
        gr.update(choices=suggested, value=None, visible=bool(suggested)),
        "",
        _format_evidence_markdown(evidence_used),
    )


def show_graph(store):
    """Plain-text fallback view of the whole graph (same content as the CLI's 'graph' command)."""
    return store.summary_text() if store else "No game loaded yet."


def show_timeline(store):
    """Timeline tab content: the full event log in chronological order (same as the CLI's 'timeline' command)."""
    return store.timeline_text() if store else "No game loaded yet."


# Fixed palette so node categories are visually consistent turn to turn.
_CATEGORY_COLORS = {
    "Political":   {"background": "#5b8def", "border": "#2f5cc4"},
    "Economic":    {"background": "#3ecf8e", "border": "#1f9e6a"},
    "Military":    {"background": "#e05656", "border": "#a53a3a"},
    "Resources":   {"background": "#e0a53e", "border": "#a4761f"},
    "Social":      {"background": "#c060e0", "border": "#8b3aa5"},
    "Geographic":  {"background": "#3ecfcf", "border": "#1f9e9e"},
    "Abstract":    {"background": "#9a9a9a", "border": "#666666"},
    "AI Internal": {"background": "#e0e05e", "border": "#a4a42a"},
}


def _build_graph_document(store) -> str:
    """
    Builds a complete, standalone HTML document rendering the graph as an
    interactive force-directed network with vis.js. Returned as a full
    document (not a fragment) so it can be embedded via an <iframe
    srcdoc="..."> -- Gradio's HTML component strips <script> tags when set
    directly (browsers don't execute scripts injected via innerHTML), but
    a full document loaded into an iframe is parsed normally and its
    scripts do run.
    """
    if not store or not store.nodes:
        return (
            "<html><head><meta name='color-scheme' content='light only'>"
            "<style>html,body{background:#ffffff;}</style></head>"
            "<body style='font-family:sans-serif;padding:2rem;color:#666;background:#ffffff;'>"
            "No graph yet -- start or load a game first.</body></html>"
        )

    nodes = []
    for n in store.nodes.values():
        category = n.get("category") or n.get("type") or "Abstract"
        attrs = n.get("attributes", {})
        title_lines = [n["name"], f"{n['type']} / {category}", f"state: {n.get('state')}"]
        title_lines += [f"{k}: {v}" for k, v in attrs.items()]
        nodes.append({
            "id": n["id"],
            "label": n["name"],
            "group": category,
            "title": "\n".join(title_lines),
        })

    node_ids = set(store.nodes.keys())
    edges = []
    for src, rel, tgt in store.edges():
        if tgt not in node_ids:
            continue  # skip dangling references so vis.js doesn't choke on them
        edges.append({"from": src, "to": tgt, "label": rel or "", "arrows": "to"})

    # defense-in-depth: a node name/attribute containing a literal
    # "</script" could otherwise prematurely close the script block below
    nodes_json = json.dumps(nodes).replace("</script", "<\\/script")
    edges_json = json.dumps(edges).replace("</script", "<\\/script")
    groups_json = json.dumps({k: {"color": v} for k, v in _CATEGORY_COLORS.items()})

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="color-scheme" content="light only">
<script src="https://unpkg.com/vis-network/standalone/umd/vis-network.min.js"></script>
<style>
  /* explicit light background + text colors throughout -- without this,
     browsers/OSes with forced dark mode can invert or blacken the page
     background while vis.js's hardcoded dark label colors stay dark,
     making all text invisible against a now-black background */
  html, body {{ margin: 0; padding: 0; height: 100%; font-family: sans-serif;
                background: #ffffff; color: #222; }}
  #network {{ width: 100%; height: 100%; background: #ffffff; }}
</style>
</head>
<body>
<div id="network"></div>
<script>
  const nodes = new vis.DataSet({nodes_json});
  const edges = new vis.DataSet({edges_json});
  const container = document.getElementById('network');
  const options = {{
    nodes: {{ shape: 'dot', size: 16, font: {{ size: 14, color: '#222' }} }},
    edges: {{ font: {{ size: 10, align: 'middle', color: '#666', strokeWidth: 0 }},
              color: {{ color: '#bbb' }}, smooth: {{ type: 'dynamic' }} }},
    physics: {{ stabilization: true, barnesHut: {{ gravitationalConstant: -8000, springLength: 150 }} }},
    groups: {groups_json},
    interaction: {{ hover: true }}
  }};
  new vis.Network(container, {{ nodes: nodes, edges: edges }}, options);
</script>
</body>
</html>"""


def show_graph_visual(store) -> str:
    """Wraps the standalone graph document in an iframe so its script runs."""
    doc = _build_graph_document(store)
    escaped = html.escape(doc, quote=True)
    return (
        f'<iframe style="width:100%;height:650px;border:1px solid #ddd;'
        f'border-radius:8px;background:#ffffff;" srcdoc="{escaped}"></iframe>'
    )


def refresh_graph_views(store):
    """Refreshes both the visual network and the plain-text fallback in one click."""
    return show_graph_visual(store), show_graph(store)


def do_find(store, term):
    """'Find' button callback: same lookup as the CLI's 'find' command, formatted as a text block."""
    if store is None:
        return "No game loaded yet."
    if not term or not term.strip():
        return "Type something to search for first."
    matches = store.find_by_name(term) or store.keyword_relevant_nodes(term, top_k=10)
    if not matches:
        return f"Nothing in your graph matches '{term}'."
    blocks = []
    for n in matches:
        rel_str = "; ".join(
            f"{r['relation']}->{store.nodes.get(r['target'], {}).get('name', r['target'])}"
            for r in n.get("relations", [])
        )
        blocks.append(
            f"[{n['id']}] {n['name']} ({n['type']}) state={n.get('state')}\n"
            f"  attrs: {n.get('attributes', {})}\n"
            f"  relations: {rel_str or '(none)'}"
        )
    return "\n\n".join(blocks)


def do_web_search(query):
    """'Search' button callback: same on-demand lookup as the CLI's 'search' command."""
    if not web_search.is_available():
        return "Web search isn't available: run `pip install ddgs`."
    if not query or not query.strip():
        return "Type a query first."
    results = web_search.search(query)
    if not results:
        return "No results (or the search failed silently -- check your connection)."
    return "\n\n".join(f"{r['title']}\n{r['snippet']}\n{r['url']}" for r in results)


# ---------- layout ----------

with gr.Blocks(title="Personal Life Graph Simulation") as demo:
    store_state = gr.State(None)   # the current GraphStore object
    path_state = gr.State("")      # its save file path

    gr.Markdown("# Personal Life Graph Simulation")

    with gr.Tab("Play"):
        with gr.Row():
            with gr.Column(scale=1):
                gr.Markdown("### Continue an existing life")
                save_dropdown = gr.Dropdown(choices=list_saves(), label="Existing saves")
                load_btn = gr.Button("Load")

                gr.Markdown("### Or start a new one")
                name_box = gr.Textbox(label="Save name", placeholder="my_life")
                q1_box = gr.Textbox(label=INTERVIEW_QUESTIONS[0])
                q2_box = gr.Textbox(label=INTERVIEW_QUESTIONS[1])
                q3_box = gr.Textbox(label=INTERVIEW_QUESTIONS[2])
                start_btn = gr.Button("Start new life", variant="primary")

            with gr.Column(scale=2):
                narrative_box = gr.Textbox(label="Situation", lines=8, interactive=False)
                with gr.Accordion("Sources used this turn", open=False):
                    evidence_box = gr.Markdown(_format_evidence_markdown([]))
                suggestions = gr.Radio(choices=[], label="Suggested actions", visible=False)
                custom_action = gr.Textbox(label="Or type your own action")
                act_btn = gr.Button("Do it", variant="primary")

        start_evt = start_btn.click(
            start_new,
            [name_box, q1_box, q2_box, q3_box],
            [store_state, path_state, narrative_box, suggestions, save_dropdown, evidence_box],
        )
        load_evt = load_btn.click(
            load_existing,
            [save_dropdown],
            [store_state, path_state, narrative_box, suggestions, evidence_box],
        )
        act_evt = act_btn.click(
            do_action,
            [store_state, path_state, suggestions, custom_action],
            [store_state, path_state, narrative_box, suggestions, custom_action, evidence_box],
        )

    with gr.Tab("Graph"):
        gr.Markdown(
            "### Network view\n"
            "Nodes colored by category, edges labeled by relation. "
            "Drag to rearrange, scroll to zoom, hover a node for its attributes."
        )
        graph_btn = gr.Button("Refresh graph", variant="primary")
        graph_html = gr.HTML()

        with gr.Accordion("Raw text view (for debugging)", open=False):
            graph_box = gr.Textbox(label="", lines=25, interactive=False)

        graph_btn.click(refresh_graph_views, [store_state], [graph_html, graph_box])

        # keep the Graph tab's network view current after every start/load/action,
        # so you don't have to remember to click "Refresh graph" yourself
        start_evt.then(refresh_graph_views, [store_state], [graph_html, graph_box])
        load_evt.then(refresh_graph_views, [store_state], [graph_html, graph_box])
        act_evt.then(refresh_graph_views, [store_state], [graph_html, graph_box])

        gr.Markdown("### Find in saved graph")
        find_box = gr.Textbox(label="Search term")
        find_btn = gr.Button("Find")
        find_result = gr.Textbox(label="Matches", lines=10, interactive=False)
        find_btn.click(do_find, [store_state, find_box], [find_result])

    with gr.Tab("Timeline"):
        gr.Markdown(
            "### Event history\n"
            "Every turn, in order, with any sources that grounded it -- "
            "a way to review how you got here without reading raw JSON."
        )
        timeline_btn = gr.Button("Refresh timeline", variant="primary")
        timeline_box = gr.Textbox(label="", lines=25, interactive=False)

        timeline_btn.click(show_timeline, [store_state], [timeline_box])
        start_evt.then(show_timeline, [store_state], [timeline_box])
        load_evt.then(show_timeline, [store_state], [timeline_box])
        act_evt.then(show_timeline, [store_state], [timeline_box])

    with gr.Tab("Web search"):
        gr.Markdown("On-demand web lookup, same source used for automatic evidence grounding.")
        search_box = gr.Textbox(label="Query")
        search_btn = gr.Button("Search")
        search_result = gr.Textbox(label="Results", lines=15, interactive=False)
        search_btn.click(do_web_search, [search_box], [search_result])


if __name__ == "__main__":
    demo.launch()