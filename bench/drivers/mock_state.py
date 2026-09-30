"""The mock provider's script state: queues, cursors, redacted logging.

DEFAULT_REPLY is the suite's scripted model response — single source for
every scenario that needs the mock turn text.
"""
from __future__ import annotations

import json
import os
import threading
import time

DEFAULT_REPLY = "The benchmark acknowledges this message. All systems nominal."


def default_script(reply: str = DEFAULT_REPLY) -> dict:
    """The default single-response script."""
    return {"responses": [{"text": reply}]}


def sse_chunk(obj) -> bytes:
    """One SSE data chunk."""
    return ("data: " + json.dumps(obj) + "\n\n").encode()


def user_message_text(body: dict) -> str:
    """The concatenated user-message text of a request body.

    Chat-completions bodies carry ``messages``; Responses-API bodies
    carry ``input`` items with input_text parts — both are read so the
    queue ``match`` keys work for either wire protocol."""
    parts = []
    for message in body.get("messages", []):
        if message.get("role") != "user":
            continue
        content = message.get("content")
        if isinstance(content, str):
            parts.append(content)
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("text"):
                    parts.append(part["text"])
    for item in body.get("input") or []:
        if not isinstance(item, dict) or item.get("role") != "user":
            continue
        content = item.get("content")
        if isinstance(content, str):
            parts.append(content)
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("text"):
                    parts.append(part["text"])
    return chr(10).join(parts)


class MockState:
    """The loaded script plus per-queue response cursors."""

    def __init__(self, script_path: str):
        self.script_path = script_path
        self.lock = threading.Lock()
        self.cursors: dict = {}
        self.reload()

    def reload(self) -> None:
        """(Re)load the script file."""
        with open(self.script_path) as f:
            script = json.load(f)
        self.responses = script.get("responses", [{"text": "ok"}])
        self.queues = script.get("queues", [])
        self.log_path = self.script_path + ".requests.jsonl"
        self._mtime = self._mtime_of()

    def _mtime_of(self):
        try:
            return os.path.getmtime(self.script_path)
        except OSError:
            return None

    def pick(self, body: dict) -> tuple[str, list, int]:
        """(queue_name, responses, cursor_index) for this request.

        The script file is live: run_suite rewrites it per phase (the
        kernel benchmarks install their toolCall queues after launch),
        so a changed mtime reloads before serving."""
        mtime = self._mtime_of()
        if mtime is not None and mtime != self._mtime:
            self.reload()
            self._mtime = mtime
        model = body.get("model", "")
        user_text = user_message_text(body)
        for q in self.queues:
            if q.get("matchModels") and model in q["matchModels"]:
                name = q["name"]
                break
            if q.get("match") and all(m in user_text for m in q["match"]):
                name = q["name"]
                break
        else:
            name = "default"
        responses = next((q["responses"] for q in self.queues if q["name"] == name), None) or self.responses
        key = name
        with self.lock:
            i = self.cursors.get(key, 0)
            self.cursors[key] = (i + 1) % len(responses) if len(responses) > 1 else 0
        return name, responses, i

    def log(self, path: str, body: dict, queue: str) -> None:
        """Record a redacted request summary (no content)."""
        try:
            items = body.get("messages") or body.get("input") or []
            roles = [
                {"role": m.get("role"), "len": len(json.dumps(m.get("content", "")))}
                for m in items
            ]
            with open(self.log_path, "a") as f:
                f.write(json.dumps({"ts": time.time(), "path": path, "model": body.get("model"),
                                    "queue": queue, "stream": body.get("stream"), "messages": roles}) + "\n")
        except Exception:
            pass
