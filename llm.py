"""One place that talks to the language model, so the agents don't care which one.

PROVIDER=gemini     (default, FREE) - Google Gemini free tier. Web search done by search.py.
PROVIDER=anthropic  (paid)          - Claude, with Anthropic's built-in web search.
"""
import json
import os
import re
import time

PROVIDER = os.getenv("PROVIDER", "gemini").lower()
# Free providers are tried in this order. Groq is the most stable free option; Gemini is the backup.
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODELS = [m.strip() for m in os.getenv(
    "GROQ_MODELS", "openai/gpt-oss-120b,llama-3.3-70b-versatile").split(",") if m.strip()]
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
        from google.genai import types
        # reads GEMINI_API_KEY; a 2-minute timeout so a stuck request can't hang the whole run
        _clients["gemini"] = genai.Client(http_options=types.HttpOptions(timeout=120_000))
    return _clients["gemini"]


# If the main model is overloaded or unavailable, the next one in the list is tried.
GEMINI_FALLBACKS = [m.strip() for m in os.getenv(
    "GEMINI_FALLBACKS", "").split(",") if m.strip()]


def _ask_gemini(system: str, prompt: str, max_tokens: int, web: bool = False) -> str:
    from google.genai import types
    tools = [types.Tool(google_search=types.GoogleSearch())] if (web and GEMINI_GROUNDING) else None
    cfg = types.GenerateContentConfig(system_instruction=system, max_output_tokens=max_tokens,
                                      tools=tools)
    models = [GEMINI_MODEL] + [m for m in GEMINI_FALLBACKS if m != GEMINI_MODEL]
    errors = []
    for model in models:
        for attempt in range(3):
            try:
                resp = _gemini().models.generate_content(model=model, contents=prompt, config=cfg)
                return resp.text or ""
            except Exception as e:
                msg = str(e)
                if any(c in msg for c in ("503", "UNAVAILABLE", "500", "INTERNAL", "504", "DEADLINE_EXCEEDED")):
                    wait = 20 * (attempt + 1)  # overloaded: wait, then retry the same model
                    print(f"   ({model} is busy [503], waiting {wait}s...)")
                    time.sleep(wait)
                    continue
                if any(c in msg for c in ("429", "RESOURCE_EXHAUSTED")):
                    print(f"   ({model}: free-tier quota hit [429], trying next model...)")
                    errors.append(f"{model}: 429")
                    break
                if any(c in msg for c in ("404", "NOT_FOUND")):
                    print(f"   ({model}: not available [404], trying next model...)")
                    errors.append(f"{model}: 404")
                    break
                raise
        else:
            errors.append(f"{model}: still busy after retries")
    raise RuntimeError("Gemini unavailable: " + "; ".join(errors))


def _ask_groq(system: str, prompt: str, max_tokens: int) -> str:
    """Groq's OpenAI-compatible API. Free tier: ~30 requests/min, ~1,000/day per model."""
    import httpx
    errors = []
    for model in GROQ_MODELS:
        for attempt in range(4):
            body = {"model": model, "max_tokens": max_tokens, "temperature": 0.3,
                    "messages": [{"role": "system", "content": system},
                                 {"role": "user", "content": prompt}]}
            if model.startswith("openai/gpt-oss"):
                body["reasoning_effort"] = "low"
            try:
                r = httpx.post("https://api.groq.com/openai/v1/chat/completions", json=body,
                               headers={"Authorization": f"Bearer {GROQ_API_KEY}"}, timeout=120)
            except httpx.HTTPError as e:
                errors.append(f"{model}: {type(e).__name__}")
                time.sleep(10)
                continue
            if r.status_code == 200:
                return r.json()["choices"][0]["message"].get("content") or ""
            if r.status_code in (429, 498, 500, 502, 503):
                # per-minute token limit or busy: Groq says how long to wait
                m = re.search(r"try again in ([\d.]+)s", r.text)
                wait = min(float(m.group(1)) + 2, 65) if m else 20 * (attempt + 1)
                if "per day" in r.text:  # daily quota for this model is used up
                    errors.append(f"{model}: daily limit")
                    break
                print(f"   ({model} busy/limited [{r.status_code}], waiting {wait:.0f}s...)")
                time.sleep(wait)
                continue
            errors.append(f"{model}: HTTP {r.status_code} {r.text[:120]}")
            break
    raise RuntimeError("Groq unavailable: " + "; ".join(errors))


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
    if GROQ_API_KEY:
        try:
            return _ask_groq(system, prompt, max_tokens)
        except RuntimeError as e:
            print(f"   ({e} - falling back to Gemini)")
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
