"""Checks which search engines work on this network.  Run:  python test_search.py"""
try:
    from ddgs import DDGS
except ImportError:
    from duckduckgo_search import DDGS

for backend in ["duckduckgo", "bing", "google", "brave", "mojeek", "yandex"]:
    try:
        res = DDGS(timeout=10).text("junior developer Israel", max_results=3, backend=backend) or []
        print(f"{backend:12} OK   {len(res)} results   {res[0].get('title', '')[:60] if res else ''}")
    except Exception as e:
        print(f"{backend:12} FAIL {str(e)[:70]}")
