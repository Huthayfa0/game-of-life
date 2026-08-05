"""
Lightweight web search, used to ground action resolution in real-world
facts -- population figures, military strength, historical precedent,
current events, real institutions -- per the world model's "Retrieving
Missing Information" rule (search the graph -> infer -> search the
internet -> fall back to the model's own knowledge).

Uses DuckDuckGo via the `ddgs` package, which needs no API key.

Install requirement:
    pip install ddgs
"""
import config

try:
    from ddgs import DDGS
except ImportError:
    DDGS = None


def is_available() -> bool:
    return DDGS is not None


def search(query: str, max_results: int = None, timeout: int = None) -> list:
    """
    Returns a list of {"title", "url", "snippet"} dicts for the query.

    Returns [] rather than raising if search is disabled, the `ddgs`
    package isn't installed, or the search itself fails for any reason
    (network issue, rate limit, etc.) -- a failed or skipped search should
    degrade to "resolve the action without extra evidence", not crash the
    game.
    """
    if not config.ENABLE_WEB_SEARCH or DDGS is None:
        return []

    max_results = max_results or config.WEB_SEARCH_MAX_RESULTS
    timeout = timeout or config.WEB_SEARCH_TIMEOUT

    try:
        with DDGS(timeout=timeout) as ddgs:
            raw_results = list(ddgs.text(query, max_results=max_results))
    except Exception:
        return []

    results = []
    for r in raw_results:
        snippet = (r.get("body") or "")[:400]  # keep save files/prompts from bloating
        results.append({
            "title": r.get("title", ""),
            "url": r.get("href") or r.get("url", ""),
            "snippet": snippet,
        })
    return results
