"""LLM access, through one of two backends (LLM_BACKEND):

api (default)  any OpenAI-compatible chat-completions API.
               Needs LLM_API_KEY and LLM_BASE_URL.
cli            a command-line AI agent already signed in on this machine, so no API
               key is needed (local runs only). LLM_CLI_COMMAND is the command line;
               "{model}" in it is replaced by the model, and the prompt goes to stdin.

Both use LLM_SCREEN_MODEL (cheap model, always used for screening) and LLM_MODEL
(stronger model, optionally used for CV tailoring).
"""
from __future__ import annotations

import json
import re
import shlex
import subprocess
import tempfile
import time

from .common import env, log

CLI_TIMEOUT = 600  # seconds per call


class Fatal(Exception):
    """An error that retrying cannot fix."""


class LLM:
    def __init__(self):
        self.backend = env("LLM_BACKEND", "api").lower()
        self.screen_model = env("LLM_SCREEN_MODEL", required=True)
        self.model = env("LLM_MODEL", self.screen_model)
        if self.backend == "api":
            from openai import OpenAI
            self.client = OpenAI(api_key=env("LLM_API_KEY", required=True), base_url=env("LLM_BASE_URL"))
        elif self.backend == "cli":
            self.cli_command = env("LLM_CLI_COMMAND", required=True)
            self.workdir = tempfile.mkdtemp(prefix="job-shortlist-")  # neutral cwd: no project files
        else:
            raise SystemExit(f"LLM_BACKEND must be 'api' or 'cli', got {self.backend!r}")

    def model_for(self, choice: str) -> str:
        """Map a config choice ("cheap" or "strong") to a model ID."""
        if choice not in ("cheap", "strong"):
            raise SystemExit(f"models.tailoring must be 'cheap' or 'strong', got {choice!r}")
        return self.screen_model if choice == "cheap" else self.model

    def _api(self, system: str, user: str, model: str, max_tokens: int) -> str:
        from openai import AuthenticationError, BadRequestError, NotFoundError, PermissionDeniedError
        try:
            # No temperature: some current models reject it, and the defaults are fine here.
            resp = self.client.chat.completions.create(
                model=model,
                max_tokens=max_tokens,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            )
        except (BadRequestError, AuthenticationError, PermissionDeniedError, NotFoundError) as e:
            raise Fatal(f"LLM request rejected: {e}") from None
        return resp.choices[0].message.content or ""

    def _cli(self, system: str, user: str, model: str, max_tokens: int) -> str:
        args = [a.replace("{model}", model) for a in shlex.split(self.cli_command)]
        prompt = f"{system}\n\n{user}\n\nRespond with the JSON object only, no other text."
        try:
            proc = subprocess.run(args, input=prompt, capture_output=True, text=True,
                                  timeout=CLI_TIMEOUT, cwd=self.workdir)
        except FileNotFoundError:
            raise Fatal(f"LLM_CLI_COMMAND not found: {args[0]}") from None
        if proc.returncode != 0:
            raise RuntimeError(f"agent exited with code {proc.returncode}: {(proc.stderr or proc.stdout).strip()[:300]}")
        return proc.stdout

    def json(self, system: str, user: str, *, model: str = None, max_tokens: int = 4000) -> dict:
        complete = self._api if self.backend == "api" else self._cli
        last_err = None
        for attempt in range(4):
            try:
                return parse_json(complete(system, user, model or self.model, max_tokens))
            except Fatal as e:
                raise RuntimeError(f"{e} (not retried)") from None
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
