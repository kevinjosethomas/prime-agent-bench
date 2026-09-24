#!/usr/bin/env python3
"""Deterministic offline mock provider for the benchmark suite.

Serves OpenAI chat-completions (SSE), OpenAI /v1/models, and Anthropic
/v1/messages (SSE) from one JSON script, so all five products run with
identical scripted model responses and zero network inference.

Script format (mock_provider.py-compatible):
  {"responses": [{"text": "..."} | {"toolCall": {...}}, ...],
   "queues": [{"name","match","matchModels","responses"}]}

Requests are logged to <script>.requests.jsonl with content REDACTED
(role/length summaries only). Not part of any product.
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def user_message_text(body: dict) -> str:
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
    def __init__(self, script_path: str):
        self.script_path = script_path
        self.lock = threading.Lock()
        self.cursors: dict = {}
        self.reload()

    def reload(self):
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

    def log(self, path: str, body: dict, queue: str):
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


STATE: MockState = None


def sse_chunk(obj) -> bytes:
    return (json.dumps(obj) + "\n\n").encode()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _cors(self):
        self.send_header("access-control-allow-origin", "*")

    def do_GET(self):
        if self.path.endswith("/models"):
            body = json.dumps({
                "object": "list",
                "data": [{"id": "mock-1", "object": "model", "created": 1789584000, "owned_by": "bench"}],
            }).encode()
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(body)))
            self._cors()
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(404)
        self.send_header("content-length", "0")
        self.end_headers()

    def do_POST(self):
        length = int(self.headers.get("content-length", 0))
        raw = self.rfile.read(length)
        try:
            body = json.loads(raw)
        except Exception:
            body = {}
        queue, responses, idx = STATE.pick(body)
        resp = responses[min(idx, len(responses) - 1)]
        STATE.log(self.path, body, queue)
        delay = float(resp.get("delayMs", 0)) / 1000.0
        if delay:
            time.sleep(delay)
        if "error" in resp:
            payload = json.dumps({"error": {"message": resp["error"], "type": "bench_error"}}).encode()
            self.send_response(resp.get("status", 400))
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        if self.path.endswith("/chat/completions"):
            self._chat_completions(body, resp)
        elif self.path.endswith("/messages"):
            self._anthropic_messages(body, resp)
        else:
            self.send_response(404)
            self.send_header("content-length", "0")
            self.end_headers()

    # -- OpenAI chat completions ------------------------------------------
    def _chat_completions(self, body, resp):
        model = body.get("model", "mock-1")
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.send_header("cache-control", "no-cache")
        self._cors()
        self.end_headers()
        cid = "chatcmpl-bench"
        def delta(obj):
            return sse_chunk({"id": cid, "object": "chat.completion.chunk", "created": 1789584000,
                              "model": model, "choices": [{"index": 0, "delta": obj, "finish_reason": None}]})
        self.wfile.write(delta({"role": "assistant", "content": ""}))
        if "text" in resp:
            text = resp["text"]
            for i in range(0, len(text), 96):
                self.wfile.write(delta({"content": text[i:i+96]}))
                self.wfile.flush()
        if "toolCall" in resp:
            tc = resp["toolCall"]
            self.wfile.write(delta({"tool_calls": [{
                "index": 0, "id": "call_bench_1", "type": "function",
                "function": {"name": tc["name"], "arguments": json.dumps(tc["arguments"])}}]}))
        finish = "tool_calls" if "toolCall" in resp else "stop"
        self.wfile.write(sse_chunk({"id": cid, "object": "chat.completion.chunk", "created": 1789584000,
                                    "model": model, "choices": [{"index": 0, "delta": {}, "finish_reason": finish}]}))
        if body.get("stream_options", {}).get("include_usage") or body.get("stream") is False:
            pass
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()

    # -- Anthropic messages ------------------------------------------------
    def _anthropic_messages(self, body, resp):
        model = body.get("model", "mock-1")
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.send_header("cache-control", "no-cache")
        self._cors()
        self.end_headers()
        def ev(name, data):
            self.wfile.write(f"event: {name}\ndata: {json.dumps(data)}\n\n".encode())
            self.wfile.flush()
        ev("message_start", {"type": "message_start", "message": {"id": "msg_bench", "type": "message",
            "role": "assistant", "model": model, "content": [], "stop_reason": None, "usage": {"input_tokens": 10, "output_tokens": 0}}})
        text = resp.get("text", "")
        tc = resp.get("toolCall")
        blocks = ([{"type": "text", "index": 0}] if text else []) + (
            [{"type": "tool_use", "index": 1, "id": "toolu_bench_1", "name": tc["name"], "input": {}}] if tc else [])
        for b in blocks:
            ev("content_block_start", {"type": "content_block_start", "index": b["index"],
                "content_block": {"type": b["type"], **({"text": ""} if b["type"] == "text" else
                {"id": b["id"], "name": b["name"], "input": {}})}})
            if b["type"] == "text":
                for i in range(0, len(text), 96):
                    ev("content_block_delta", {"type": "content_block_delta", "index": 0,
                        "delta": {"type": "text_delta", "text": text[i:i+96]}})
            else:
                args = json.dumps(tc["arguments"])
                ev("content_block_delta", {"type": "content_block_delta", "index": 1,
                    "delta": {"type": "input_json_delta", "partial_json": args}})
            ev("content_block_stop", {"type": "content_block_stop", "index": b["index"]})
        ev("message_delta", {"type": "message_delta",
            "delta": {"stop_reason": "tool_use" if tc else "end_turn", "stop_sequence": None},
            "usage": {"output_tokens": max(1, len(text) // 4)}})
        ev("message_stop", {"type": "message_stop"})


def main():
    script = sys.argv[1]
    global STATE
    STATE = MockState(script)
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(server.server_address[1], flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
