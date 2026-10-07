"""Thin wrapper around Groq's chat API that always returns parsed JSON.

Groq's free tier allows about 8,000 tokens per minute per model, so callers keep
prompts small; the SDK retries 429s with back-off (max_retries below).
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field

from ai import settings


class LLMError(RuntimeError):
    pass


@dataclass
class LLMResult:
    data: dict
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    seconds: float = 0.0
    raw: str = field(default="", repr=False)


def _client():
    from groq import Groq  # imported lazily so tests can run without the SDK

    key = settings.get("GROQ_API_KEY")
    if not key:
        raise LLMError("GROQ_API_KEY is not set (Streamlit secrets or environment)")
    return Groq(api_key=key, max_retries=5, timeout=90)


def parse_json(text: str) -> dict:
    """Parse a JSON object, tolerating code fences or text around it."""
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.S)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, flags=re.S)
        if m:
            return json.loads(m.group(0))
        raise


def chat_json(model: str, system: str, user: str, *, max_tokens: int = 2000, effort: str = "low",
              temperature: float = 0.2, client=None) -> LLMResult:
    client = client or _client()
    t0 = time.time()
    last_err: Exception | None = None
    for attempt in range(2):
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                temperature=temperature,
                max_completion_tokens=max_tokens,
                response_format={"type": "json_object"},
                extra_body={"reasoning_effort": effort, "include_reasoning": False},
            )
            text = resp.choices[0].message.content or ""
            data = parse_json(text)
            usage = getattr(resp, "usage", None)
            return LLMResult(data=data, model=model, raw=text, seconds=time.time() - t0,
                             prompt_tokens=getattr(usage, "prompt_tokens", 0) or 0,
                             completion_tokens=getattr(usage, "completion_tokens", 0) or 0)
        except (json.JSONDecodeError, ValueError) as exc:
            last_err = exc  # malformed JSON: ask once more
        except Exception as exc:  # API errors (rate limit after retries, bad request, ...)
            if "json_validate_failed" in str(exc) and attempt == 0:
                last_err = exc       # Groq rejected malformed JSON: try once more
                continue
            raise LLMError(f"{model}: {exc}") from exc
    raise LLMError(f"{model}: could not parse JSON ({last_err})")
