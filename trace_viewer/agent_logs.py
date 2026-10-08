"""Helpers shared by the JSONL based sources (Claude Code, pi): file index and canonical item builders.

Other agents' records are mapped onto the same canonical items Codex produces (commandExecution, fileChange,
webSearch, mcpToolCall, collabAgentToolCall, ...), so analysis and the UI need no per-agent code. Only facts
present in the log are mapped; nothing is inferred (for example no exit code unless the log states one).
"""
from __future__ import annotations

import io
import json
import re
import threading
import time
from pathlib import Path

from .normalize import text_of, timestamp_ms
from .source_base import CachedSource

CLIP = 20000


def basename(path):
    return str(path).replace("\\", "/").rsplit("/", 1)[-1]


def project_of(cwd):
    return str(cwd or "").rstrip("/\\").replace("\\", "/").rsplit("/", 1)[-1] or "未分组"


def clip(value, limit=CLIP):
    value = str(value or "")
    return value if len(value) <= limit else value[:limit] + f"\n…（已截断，原文共 {len(value)} 个字符）"


def shrink(value, limit=4000):
    """Copy of a raw block for the 'raw record' tab, with very long strings shortened."""
    if isinstance(value, dict):
        return {k: shrink(v, limit) for k, v in value.items()}
    if isinstance(value, list):
        return [shrink(v, limit) for v in value]
    if isinstance(value, str) and len(value) > limit:
        return value[:limit] + f"…（已截断，原文共 {len(value)} 个字符）"
    return value


class ZstdUnavailable(Exception):
    """A .zstd log was found but no zstd decoder is installed."""


ZSTD_MAGIC = bytes.fromhex("28b52ffd")  # start of every zstd frame


def _last_frame_complete(zstandard, raw):
    """The stream reader silently stops at a half-written frame, so check the final frame on its own."""
    start = raw.rfind(ZSTD_MAGIC)
    if start < 0:
        return False
    decoder = zstandard.ZstdDecompressor().decompressobj()
    try:
        decoder.decompress(raw[start:])
    except zstandard.ZstdError:
        return False
    return decoder.eof


def _zstd_bytes(path):
    """Decompress a log made of many zstd frames. Returns (bytes, complete); a torn last frame keeps what was read."""
    try:
        import zstandard
    except ImportError:
        zstandard = None
    raw = Path(path).read_bytes()
    if zstandard is not None:
        reader = zstandard.ZstdDecompressor().stream_reader(io.BytesIO(raw), read_across_frames=True)
        chunks = []
        try:
            while chunk := reader.read(1 << 20):
                chunks.append(chunk)
        except zstandard.ZstdError:
            return b"".join(chunks), False  # the file is still being written
        return b"".join(chunks), _last_frame_complete(zstandard, raw)
    try:
        from compression import zstd  # Python 3.14+
    except ImportError:
        raise ZstdUnavailable("需要 zstandard 才能读取 .zstd 记录") from None
    try:
        return zstd.decompress(raw), True
    except Exception:
        return b"", False


def log_lines(path):
    """Text lines of a plain or zstd compressed JSONL log, plus whether the whole file could be read."""
    path = Path(path)
    if path.name.endswith(".zstd"):
        data, complete = _zstd_bytes(path)
        return data.decode("utf-8", errors="replace").split("\n"), complete
    return path.read_text(encoding="utf-8", errors="replace").split("\n"), True


def read_jsonl(path):
    """Parse a JSONL file leniently; returns (records, number_of_unreadable_lines)."""
    records, bad = [], 0
    for line in log_lines(path)[0]:
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except ValueError:
            bad += 1
            continue
        if isinstance(row, dict):
            records.append(row)
        else:
            bad += 1
    return records, bad


def result_text(content):
    """Text of a tool result; images stay a placeholder, never inline base64."""
    return text_of(content)


def diff_text(old, new):
    lines = [("- " + x) for x in str(old or "").split("\n")] if old else []
    lines += [("+ " + x) for x in str(new or "").split("\n")] if new else []
    return "\n".join(lines)


# ---- canonical item builders -------------------------------------------------------------------------

def command_item(call_id, command, cwd="", actions=None):
    item = {"type": "commandExecution", "id": call_id, "command": command, "status": "inProgress"}
    if cwd:
        item["cwd"] = cwd
    if actions:
        item["commandActions"] = actions
    return item


def read_item(call_id, path, cwd=""):
    return command_item(call_id, f"Read {path}", cwd, [{"type": "read", "name": basename(path), "path": path}])


def search_item(call_id, pattern, path="", cwd=""):
    action = {"type": "search", "query": pattern}
    if path:
        action["path"] = path
    return command_item(call_id, f"Grep {pattern}" + (f" {path}" if path else ""), cwd, [action])


def list_item(call_id, label, path="", cwd=""):
    action = {"type": "listFiles"}
    if path:
        action["path"] = path
    return command_item(call_id, label, cwd, [action])


def edit_item(call_id, path, diff):
    return {"type": "fileChange", "id": call_id, "changes": [{"path": path, "diff": clip(diff)}], "status": "inProgress"}


def web_item(call_id, query):
    return {"type": "webSearch", "id": call_id, "query": query, "status": "inProgress"}


def agent_item(call_id, tool, prompt):
    return {"type": "collabAgentToolCall", "id": call_id, "tool": tool, "prompt": prompt, "receiverThreadIds": [], "status": "inProgress"}


def tool_item(call_id, tool, arguments, server=""):
    item = {"type": "mcpToolCall", "id": call_id, "tool": tool, "arguments": arguments, "status": "inProgress"}
    if server:
        item["server"] = server
    return item


EXIT_CODE = re.compile(r"^Exit code (\d+)")


def apply_result(item, text, is_error, details=None):
    """Attach a tool result to its call. Only what the log states is recorded."""
    kind = item["type"]
    item["status"] = "failed" if is_error else "completed"
    if kind == "commandExecution":
        item["aggregatedOutput"] = clip(text)
        match = EXIT_CODE.match(text or "")
        if match:
            item["exitCode"] = int(match[1])
    elif kind == "fileChange":
        shown = (details or {}).get("diff") if isinstance(details, dict) else None
        if shown:
            item["changes"][0]["diff"] = clip(shown)
        if text:
            item["resultText"] = clip(text)
    elif kind == "webSearch":
        item["results"] = clip(text)
    elif kind == "collabAgentToolCall":
        item["agentsStates"] = clip(text)
    else:
        item["result"] = {"isError": bool(is_error), "content": clip(text)}


# ---- session file index ---------------------------------------------------------------------------

class JsonlSource(CachedSource):
    """A directory of one-file-per-session JSONL logs. Subclasses implement `_scan` and `_parse`."""

    pattern = "*/*.jsonl"

    def __init__(self, root):
        super().__init__()
        self.root = Path(root).expanduser().resolve() if root else None
        self._meta = {}          # path -> (mtime_ns, size, scanned metadata or None)
        self._index = (0.0, {})  # (monotonic time, id -> session)
        self._index_lock = threading.Lock()

    def info(self):
        return {"id": self.id, "label": self.label, "home": str(self.root) if self.root else None,
                "available": bool(self.root and self.root.is_dir())}

    def _scan(self, path):  # pragma: no cover - overridden
        """Return session metadata (id, title, cwd, model, createdAt) or None to skip the file."""
        raise NotImplementedError

    def _files(self):
        if not self.root or not self.root.is_dir():
            return []
        found = []
        for path in self.root.glob(self.pattern):
            try:
                real = path.resolve()
                if real.is_file() and real.is_relative_to(self.root):  # never follow a link out of the log folder
                    found.append(real)
            except OSError:
                continue
        return found

    def _build_index(self):
        sessions, seen = {}, set()
        for path in self._files():
            try:
                stat = path.stat()
            except OSError:
                continue
            seen.add(path)
            cached = self._meta.get(path)
            if cached and cached[0] == stat.st_mtime_ns and cached[1] == stat.st_size:
                meta = cached[2]
            else:
                try:
                    meta = self._scan(path)
                except OSError:
                    meta = None
                self._meta[path] = (stat.st_mtime_ns, stat.st_size, meta)
            if not meta:
                continue
            cwd = meta.get("cwd") or ""
            sessions[self.prefix + meta["id"]] = {
                "id": self.prefix + meta["id"], "title": meta.get("title") or f"{self.label} 会话 {meta['id'][:8]}",
                "cwd": cwd, "project": project_of(cwd), "model": meta.get("model") or "",
                "updatedAt": int(stat.st_mtime * 1000), "createdAt": timestamp_ms(meta.get("createdAt")),
                "archived": False, "originator": self.label, "source": self.id, "sourceLabel": self.label,
                "historyMode": None, "tokensUsed": None, "agentPath": None, "_path": str(path)}
        for gone in set(self._meta) - seen:
            del self._meta[gone]
        return sessions

    def _sessions(self, force=False):
        with self._index_lock:
            now = time.monotonic()
            if force or now - self._index[0] > 3:
                self._index = (now, self._build_index())
            return self._index[1]

    def list_sessions(self):
        sessions = sorted(self._sessions().values(), key=lambda s: s["updatedAt"] or 0, reverse=True)
        return sessions, None

    def _session(self, sid):
        return self._sessions().get(sid) or self._sessions(force=True).get(sid)

    def _turn_status(self, session, now=None):
        """Logs carry no turn status. The latest turn counts as running only while the file is still being written."""
        recent = ((now or time.time()) * 1000 - (session["updatedAt"] or 0)) < 60_000
        return "inProgress" if recent else "completed"
