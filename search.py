"""Free web search (no API key). Tries several search engines and uses the first that works.

If your network blocks some engines, set SEARCH_BACKENDS in .env, e.g.:
    SEARCH_BACKENDS=bing,google
"""
import os
import time

try:
    from ddgs import DDGS
except ImportError:  # older package name
    from duckduckgo_search import DDGS

BACKENDS = [b.strip() for b in os.getenv(
    "SEARCH_BACKENDS", "duckduckgo,bing,google,brave,mojeek,yandex").split(",") if b.strip()]

_working = None  # remembered after the first success, so later searches are fast


def _search_one(query: str, per_query: int) -> list[dict]:
    global _working
    order = [_working] + [b for b in BACKENDS if b != _working] if _working else BACKENDS
    errors = []
    for backend in order:
        try:
            results = DDGS(timeout=10).text(query, max_results=per_query, backend=backend) or []
            if results:
                if _working != backend:
                    print(f"   (search engine in use: {backend})")
                _working = backend
                return results
            errors.append(f"{backend}: no results")
        except Exception as e:
            errors.append(f"{backend}: {str(e)[:80]}")
    print(f"   (all search engines failed for '{query}': {' | '.join(errors)})")
    return []


def web_search(queries: list[str], per_query: int = 8) -> str:
    """Run several searches and return the results as plain text for an agent to read."""
    seen, lines = set(), []
    for q in queries:
        for r in _search_one(q, per_query):
            url = r.get("href") or r.get("url")
            if not url or url in seen:
                continue
            seen.add(url)
            lines.append(f"- {r.get('title', '')}\n  {url}\n  {r.get('body', '')}")
        time.sleep(1)  # be polite, avoid getting blocked
    return "\n".join(lines) or "(no results)"
