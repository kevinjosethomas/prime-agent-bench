"""The mock provider's script state: queues, cursors, redacted logging.

DEFAULT_REPLY is the suite's scripted model response — single source for
every scenario that needs the mock turn text.
"""
from __future__ import annotations

import json
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
    """The concatenated user-message text of a request body."""
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

    def pick(self, body: dict) -> tuple[str, list, int]:
        """(queue_name, responses, cursor_index) for this request."""
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
            roles = [
                {"role": m.get("role"), "len": len(json.dumps(m.get("content", "")))}
                for m in body.get("messages", [])
            ]
            with open(self.log_path, "a") as f:
                f.write(json.dumps({"ts": time.time(), "path": path, "model": body.get("model"),
                                    "queue": queue, "stream": body.get("stream"), "messages": roles}) + "\n")
        except Exception:
            pass
