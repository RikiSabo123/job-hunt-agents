"""One place that talks to the language model, so the agents don't care which one.

PROVIDER=gemini     (default, FREE) - Google Gemini free tier. Web search done by search.py.
PROVIDER=anthropic  (paid)          - Claude, with Anthropic's built-in web search.
"""
import json
import os
import re
import time

PROVIDER = os.getenv("PROVIDER", "gemini").lower()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
# true = Gemini searches Google by itself (works even when your network blocks search engines)
GEMINI_GROUNDING = os.getenv("GEMINI_GROUNDING", "false").lower() == "true"
WORKER_MODEL = os.getenv("WORKER_MODEL", "claude-sonnet-5-5")
BOSS_MODEL = os.getenv("BOSS_MODEL", "claude-opus-5-5")

WEB_SEARCH_TOOL = {"type": "web_search_20250305", "name": "web_search", "max_uses": 8}

_clients = {}


def client():
    """Anthropic client (used by the paid mode and the LLM manager)."""
    if "anthropic" not in _clients:
        from anthropic import Anthropic
        _clients["anthropic"] = Anthropic()  # reads ANTHROPIC_API_KEY
    return _clients["anthropic"]


def _gemini():
    if "gemini" not in _clients:
        from google import genai
        _clients["gemini"] = genai.Client()  # reads GEMINI_API_KEY
    return _clients["gemini"]


def _ask_gemini(system: str, prompt: str, max_tokens: int, web: bool = False) -> str:
    from google.genai import types
    tools = [types.Tool(google_search=types.GoogleSearch())] if (web and GEMINI_GROUNDING) else None
    cfg = types.GenerateContentConfig(system_instruction=system, max_output_tokens=max_tokens,
                                      tools=tools)
    for attempt in range(5):
        try:
            resp = _gemini().models.generate_content(model=GEMINI_MODEL, contents=prompt, config=cfg)
            return resp.text or ""
        except Exception as e:
            # Free tier = low per-minute limits. Wait and retry instead of crashing.
            if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                wait = 20 * (attempt + 1)
                print(f"   (free-tier limit hit, waiting {wait}s...)")
                time.sleep(wait)
                continue
            raise
    raise RuntimeError("Gemini free-tier limit: try again later (daily quota may be used up).")


def _ask_anthropic(system: str, prompt: str, web: bool, max_tokens: int) -> str:
    messages = [{"role": "user", "content": prompt}]
    kwargs = dict(model=WORKER_MODEL, max_tokens=max_tokens, system=system)
    if web:
        kwargs["tools"] = [WEB_SEARCH_TOOL]
    resp = client().messages.create(messages=messages, **kwargs)
    while resp.stop_reason == "pause_turn":  # long web-search turns may pause
        messages = messages + [{"role": "assistant", "content": resp.content}]
        resp = client().messages.create(messages=messages, **kwargs)
    return "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")


def ask(system: str, prompt: str, *, web: bool = False, max_tokens: int = 8000) -> str:
    """`web=True` only matters for Anthropic; in free mode the worker passes search results itself."""
    if PROVIDER == "anthropic":
        return _ask_anthropic(system, prompt, web, max_tokens)
    return _ask_gemini(system, prompt, max_tokens, web)


def extract_json(text: str):
    """Pull the first JSON object/array out of a model answer."""
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    candidate = fenced.group(1) if fenced else text
    for opener, closer in (("{", "}"), ("[", "]")):
        start, end = candidate.find(opener), candidate.rfind(closer)
        if start != -1 and end > start:
            try:
                return json.loads(candidate[start:end + 1])
            except json.JSONDecodeError:
                continue
    raise ValueError(f"Agent did not return valid JSON:\n{text[:500]}")


def ask_json(system: str, prompt: str, **kw):
    text = ask(system, prompt + "\n\nReturn ONLY valid JSON inside a ```json code block.", **kw)
    return extract_json(text)
