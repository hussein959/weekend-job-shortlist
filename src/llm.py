"""Thin wrapper around any OpenAI-compatible chat-completions API.

Configure with LLM_API_KEY, LLM_BASE_URL, LLM_SCREEN_MODEL (cheap model, always used
for screening) and LLM_MODEL (stronger model, optionally used for CV tailoring).
"""
from __future__ import annotations

import json
import re
import time

from openai import OpenAI

from .common import env, log


class LLM:
    def __init__(self):
        self.client = OpenAI(api_key=env("LLM_API_KEY", required=True), base_url=env("LLM_BASE_URL"))
        self.screen_model = env("LLM_SCREEN_MODEL", required=True)
        self.model = env("LLM_MODEL", self.screen_model)

    def model_for(self, choice: str) -> str:
        """Map a config choice ("cheap" or "strong") to a model ID."""
        if choice not in ("cheap", "strong"):
            raise SystemExit(f"models.tailoring must be 'cheap' or 'strong', got {choice!r}")
        return self.screen_model if choice == "cheap" else self.model

    def json(self, system: str, user: str, *, model: str = None, max_tokens: int = 4000) -> dict:
        last_err = None
        for attempt in range(4):
            try:
                resp = self.client.chat.completions.create(
                    model=model or self.model,
                    max_tokens=max_tokens,
                    temperature=0.2,
                    messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                )
                return parse_json(resp.choices[0].message.content or "")
            except Exception as e:
                last_err = e
                wait = 5 * 2 ** attempt
                log.warning("LLM call failed (%s); retrying in %ss", e, wait)
                time.sleep(wait)
        raise RuntimeError(f"LLM call failed after retries: {last_err}")


def parse_json(text: str) -> dict:
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("No JSON object in model output")
    return json.loads(text[start : end + 1])
