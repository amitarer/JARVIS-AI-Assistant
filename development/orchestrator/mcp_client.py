"""Bounded stdio JSON-RPC client for the pinned Ruflo coordination server."""

import json
import queue
import threading
import time


def decode_tool_result(response):
    value = response
    for _ in range(4):
        if not isinstance(value, dict) or not set(value).issubset({"content", "structuredContent", "isError"}):
            break
        if value.get("isError"):
            raise RuntimeError("Ruflo returned a tool error: " + str(value.get("content"))[:1000])
        if value.get("structuredContent") is not None:
            value = value["structuredContent"]
            continue
        texts = [item["text"] for item in value.get("content", []) if item.get("type") == "text"]
        if not texts:
            break
        try:
            value = json.loads("\n".join(texts))
        except ValueError:
            return {"text": "\n".join(texts)}
    return value or {}


class RufloClient:
    def __init__(self, process, log_dir, *, checkpoint=lambda: None):
        self.process = process
        self.log_dir = log_dir
        self.checkpoint = checkpoint
        self.sequence = 0
        self.inbox = queue.Queue(maxsize=256)
        self.invalid_stdout = []
        self.tools = {}
        self._threads = [threading.Thread(target=self._read, daemon=True),
                         threading.Thread(target=self._stderr, daemon=True)]
        for thread in self._threads:
            thread.start()

    def _read(self):
        for raw in self.process.stdout:
            if len(raw) > 4_000_000:
                self.invalid_stdout.append("oversized JSON-RPC message")
                continue
            line = raw.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            try:
                value = json.loads(line)
                if not isinstance(value, dict) or value.get("jsonrpc") != "2.0":
                    raise ValueError
            except ValueError:
                self.invalid_stdout.append(line[:300])
                continue
            try:
                self.inbox.put(value, timeout=1)
            except queue.Full:
                self.invalid_stdout.append("JSON-RPC inbox overflow")

    def _stderr(self):
        with (self.log_dir / "ruflo-stderr.log").open("w", encoding="utf-8") as log:
            total = 0
            for raw in self.process.stderr:
                if total < 2_000_000:
                    log.write(raw.decode("utf-8", errors="replace"))
                    log.flush()
                    total += len(raw)

    def notify(self, method, params=None):
        message = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            message["params"] = params
        self.process.send(json.dumps(message) + "\n")

    def request(self, method, params=None, timeout=60):
        self.sequence += 1
        identifier = self.sequence
        self.process.send(json.dumps({"jsonrpc": "2.0", "id": identifier, "method": method,
                                      "params": params or {}}) + "\n")
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.checkpoint()
            try:
                response = self.inbox.get(timeout=0.2)
            except queue.Empty:
                if self.process.poll() is not None:
                    raise RuntimeError(f"Ruflo exited before {method}; inspect ruflo-stderr.log")
                continue
            if response.get("id") != identifier:
                # Ruflo notifications do not resolve a request.
                continue
            if "error" in response:
                raise RuntimeError(f"MCP {method}: {response['error']}")
            return response.get("result", {})
        raise TimeoutError(f"Ruflo MCP timeout: {method}")

    def initialize(self):
        identity = self.request("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                               "clientInfo": {"name": "jarvis-development", "version": "1.0.0"}}, timeout=120)
        self.notify("notifications/initialized")
        tools = []
        cursor = None
        while True:
            page = self.request("tools/list", {"cursor": cursor} if cursor else {}, timeout=120)
            tools.extend(page.get("tools", []))
            cursor = page.get("nextCursor")
            if not cursor:
                break
        self.tools = {tool["name"]: tool for tool in tools}
        if self.invalid_stdout:
            raise RuntimeError("Ruflo emitted invalid JSON-RPC stdout")
        return {"server": identity, "tools": tools}

    def call(self, name, arguments=None):
        if name not in self.tools:
            raise RuntimeError(f"Ruflo does not advertise required tool {name}")
        response = self.request("tools/call", {"name": name, "arguments": arguments or {}})
        value = decode_tool_result(response)
        if isinstance(value, dict) and value.get("success") is False:
            raise RuntimeError(f"Ruflo {name} refused: {value.get('error')}")
        return value or {}

    def close(self):
        self.process.eof()

    def finish_io(self):
        for thread in self._threads:
            thread.join(timeout=1)
        for stream in (self.process.stdout, self.process.stderr):
            if stream is not None:
                stream.close()
