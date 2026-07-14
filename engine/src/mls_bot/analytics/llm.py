"""Thin Anthropic Messages-API client over httpx.

Deliberately dependency-light: ``httpx`` is already a project dependency, so
this avoids pulling the full ``anthropic`` SDK. The whole module degrades to a
no-op when ``ANTHROPIC_API_KEY`` is absent — every public function returns
``None`` / ``False`` so callers can fall back to deterministic behaviour
without special-casing the "no key" path.

Usage::

    from mls_bot.analytics.llm import llm_available, call_json
    if llm_available():
        result = call_json(system="...", user="...", max_tokens=1500)
"""
from __future__ import annotations

import json
import os
import re
from typing import Any, Optional

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass


_API_URL = "https://api.anthropic.com/v1/messages"
_API_VERSION = "2023-06-01"

# Cheapest current Claude model — good enough for structured extraction from
# MLS remarks. Override per-call via the ``model`` arg.
DEFAULT_MODEL = "claude-haiku-4-5-20251001"


def api_key() -> Optional[str]:
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    return key or None


def llm_available() -> bool:
    """True when an Anthropic API key is configured."""
    return api_key() is not None


def call_messages(*, system: str, user: str,
                  max_tokens: int = 1500,
                  model: str = DEFAULT_MODEL,
                  temperature: Optional[float] = 0.0,
                  timeout: float = 40.0) -> Optional[str]:
    """Call the Anthropic Messages API, returning the raw text response.

    ``system`` may be empty ("") for a user-only prompt — the parameter is
    then omitted from the request. ``temperature=None`` omits the parameter
    so the model runs at its API default (the blind-valuer's certified
    posture). Both existing behaviors (non-empty system, temperature 0.0)
    are unchanged.

    Returns ``None`` when no API key is set or the request fails — callers
    must treat ``None`` as "LLM unavailable, use the deterministic path"."""
    key = api_key()
    if not key:
        return None
    import httpx

    headers = {
        "x-api-key": key,
        "anthropic-version": _API_VERSION,
        "content-type": "application/json",
    }
    body = {
        "model": model,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "messages": [{"role": "user", "content": user}],
    }
    if system:
        body["system"] = system
    # Some newer models (e.g. claude-opus-4-8) deprecate the `temperature`
    # parameter and 400 if it is sent. Omit it for those so the call succeeds
    # instead of silently degrading the hygiene pass to a no-op. None = caller
    # asked for the API-default temperature (omit the parameter entirely).
    if temperature is None or "opus-4-8" in model:
        body.pop("temperature", None)
    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(_API_URL, headers=headers, json=body)
            resp.raise_for_status()
            data = resp.json()
    except Exception:
        return None
    # Messages API returns content as a list of blocks; concatenate text blocks.
    try:
        blocks = data.get("content", [])
        text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
        return text or None
    except Exception:
        return None


_JSON_FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def _extract_json(text: str) -> Optional[Any]:
    """Pull a JSON object/array out of a model response, fenced or bare."""
    if not text:
        return None
    # Prefer a fenced block if present.
    m = _JSON_FENCE.search(text)
    candidate = m.group(1) if m else text
    candidate = candidate.strip()
    # Trim to the outermost {...} or [...] if there's leading/trailing prose.
    for opener, closer in (("{", "}"), ("[", "]")):
        start = candidate.find(opener)
        end = candidate.rfind(closer)
        if start != -1 and end != -1 and end > start:
            snippet = candidate[start:end + 1]
            try:
                return json.loads(snippet)
            except json.JSONDecodeError:
                continue
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        return None


def call_json(*, system: str, user: str,
              max_tokens: int = 1500,
              model: str = DEFAULT_MODEL,
              temperature: float = 0.0) -> Optional[Any]:
    """Call the API and parse a JSON object/array from the response.

    Returns ``None`` when the LLM is unavailable or the response can't be
    parsed as JSON."""
    text = call_messages(system=system, user=user, max_tokens=max_tokens,
                         model=model, temperature=temperature)
    if text is None:
        return None
    return _extract_json(text)


__all__ = ["llm_available", "api_key", "call_messages", "call_json", "DEFAULT_MODEL"]
