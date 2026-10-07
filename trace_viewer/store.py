"""Read Codex's local stores. No writes, migrations, or model calls."""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from collections import OrderedDict
from contextlib import closing
from pathlib import Path

from .normalize import canonical_item, normalize, public_event, statistics, text_of, timestamp_ms
from .analysis import build_analysis


class StoreError(Exception):
    pass


class HistoryStore:
    def __init__(self, home=None):
        self.home = Path(home or os.environ.get("CODEX_HOME") or Path.home() / ".codex").expanduser().resolve()
        self.state = self._database("state_")
        self.history = self._database("thread_history_")
        self._lock = threading.RLock()
        self._cache = OrderedDict()
        self._index = None

    def _database(self, prefix):
        paths = list(self.home.glob(prefix + "*.sqlite"))
        return max(paths, key=lambda p: int(p.stem.rsplit("_", 1)[1]) if p.stem.rsplit("_", 1)[1].isdigit() else -1, default=None)

    def connect(self, path):
        if path is None:
            raise StoreError("没有找到对应的 Codex 数据库。")
        con = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=3)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA query_only=ON")
        return con

    def info(self):
        return {"home": str(self.home), "stateDatabase": self.state.name if self.state else None,
                "historyDatabase": self.history.name if self.history else None, "readOnly": True}

    def _rollout_index(self):
        now = time.monotonic()
        if self._index and now - self._index[0] < 10:
            return self._index[1]
        result = []
        for folder in ("sessions", "archived_sessions"):
            for path in (self.home / folder).rglob("rollout-*.jsonl"):
                try:
                    with path.open(encoding="utf-8") as f:
                        first = json.loads(f.readline())
                    if not isinstance(first, dict) or not isinstance(first.get("payload"), dict):
                        continue
                    meta = first["payload"]
                    if first.get("type") != "session_meta" or not meta.get("id"):
                        continue
                    result.append({"id": meta["id"], "title": "会话 " + meta["id"][:8], "name": None,
                                   "cwd": meta.get("cwd", ""), "model": meta.get("model", ""),
                                   "updated_at": path.stat().st_mtime, "created_at": meta.get("timestamp"),
                                   "rollout_path": str(path), "archived": folder == "archived_sessions",
                                   "originator": meta.get("originator", ""), "history_mode": meta.get("history_mode", "legacy")})
                except (OSError, ValueError):
                    continue
        self._index = (now, result)
        return result

    def list_sessions(self):
        warning = None
        try:
            if not self.state:
                raise StoreError("使用 rollout 文件索引。")
            with closing(self.connect(self.state)) as con:
                cols = {r[1] for r in con.execute("PRAGMA table_info(threads)")}
                wanted = [c for c in ("id", "title", "name", "cwd", "model", "updated_at", "created_at", "archived", "rollout_path", "originator", "history_mode", "tokens_used", "agent_path") if c in cols]
                rows = [dict(r) for r in con.execute("SELECT " + ",".join(wanted) + " FROM threads ORDER BY updated_at DESC")]
        except (sqlite3.Error, StoreError) as exc:
            warning = str(exc)
            rows = self._rollout_index()
        sessions = []
        for r in rows:
            path = str(r.get("cwd") or "")
            if path.startswith("\\\\?\\"):
                path = path[4:]
            sessions.append({"id": r["id"], "title": r.get("name") or r.get("title") or "未命名会话",
                             "cwd": path, "project": path.rstrip("/\\").replace("\\", "/").rsplit("/", 1)[-1] or "未分组",
                             "model": r.get("model") or "", "updatedAt": timestamp_ms(r.get("updated_at")),
                             "createdAt": timestamp_ms(r.get("created_at")), "archived": bool(r.get("archived")),
                             "originator": r.get("originator") or "Codex", "historyMode": r.get("history_mode"),
                             "tokensUsed": r.get("tokens_used"), "agentPath": r.get("agent_path"),
                             "_rollout": r.get("rollout_path")})
        sessions.sort(key=lambda s: s["updatedAt"] or 0, reverse=True)
        return sessions, warning

    def _session(self, sid):
        sessions, _ = self.list_sessions()
        return next((s for s in sessions if s["id"] == sid), None)

    def load(self, sid, refresh=False):
        with self._lock:
            cached = self._cache.get(sid)
            if cached and not refresh and time.monotonic() - cached[0] < 2:
                return cached[1]
            session = self._session(sid)
            if not session:
                raise KeyError("会话不存在。")
            warnings, events, turns = [], [], []
            if self.history:
                try:
                    with closing(self.connect(self.history)) as con:
                        turns = [dict(r) for r in con.execute("SELECT * FROM thread_turns WHERE thread_id=? ORDER BY rollout_ordinal", (sid,))]
                        rows = con.execute("SELECT * FROM thread_items WHERE thread_id=? ORDER BY rollout_ordinal", (sid,))
                        for raw_row in rows:
                            r = dict(raw_row)
                            try:
                                item = json.loads(r["item_json"])
                                if not isinstance(item, dict):
                                    raise ValueError("item is not an object")
                            except (ValueError, TypeError):
                                warnings.append("一个损坏的历史条目无法解析。")
                                continue
                            events.append(normalize(item, turn_id=r["turn_id"], ordinal=r["rollout_ordinal"],
                                                    started=r.get("started_at_ms"), completed=r.get("completed_at_ms"), created=r.get("created_at_ms")))
                except sqlite3.Error as exc:
                    warnings.append("结构化历史暂不可读，将尝试原始记录：" + str(exc))
                    events, turns = [], []
            if not events:
                events, turns, extra = self._read_rollout(session.get("_rollout"))
                warnings.extend(extra)
            turn_map = {str(t["turn_id"]): {"id": str(t["turn_id"]), "status": t.get("status", "unknown"),
                        "startedAt": timestamp_ms(t.get("started_at")), "completedAt": timestamp_ms(t.get("completed_at")),
                        "durationMs": t.get("duration_ms"), "error": t.get("error_json")} for t in turns}
            for e in events:
                if e["turnId"] not in turn_map:
                    turn_map[e["turnId"]] = {"id": e["turnId"], "status": "unknown", "startedAt": e["timestamp"], "completedAt": None, "durationMs": None}
            result = {"session": {k: v for k, v in session.items() if not k.startswith("_")},
                      "turns": list(turn_map.values()), "events": events, "stats": statistics(events),
                      "warnings": list(dict.fromkeys(warnings)), "loadedAt": int(time.time() * 1000)}
            result["analysis"] = build_analysis(events, result["turns"], session_id=sid, cwd=session["cwd"])
            self._cache[sid] = (time.monotonic(), result)
            self._cache.move_to_end(sid)
            while len(self._cache) > 3:
                self._cache.popitem(last=False)
            return result

    def detail(self, sid, item_id, turn_id=None):
        result = self.load(sid)
        event = next((e for e in result["events"] if e["id"] == item_id and (turn_id is None or e["turnId"] == turn_id)), None)
        if event is None:
            raise KeyError("事件不存在，可能需要刷新。")
        return {**public_event(event), **event["_detail"]}

    def _read_rollout(self, value):
        if not value:
            return [], [], ["这个会话没有可读取的本地执行记录。"]
        path = Path(value).resolve()
        if not path.is_relative_to(self.home):
            return [], [], ["记录路径位于选定的 Codex 数据目录之外，未读取。"]
        try:
            with path.open(encoding="utf-8") as f:
                lines = list(f)
        except OSError:
            return [], [], ["原始记录不存在或暂时无法读取。"]
        rows, warnings = [], []
        for i, line in enumerate(lines):
            try:
                row = json.loads(line)
                if not isinstance(row, dict) or not isinstance(row.get("payload", {}), dict):
                    raise ValueError("invalid event structure")
                rows.append((i, row))
            except ValueError:
                warnings.append("跳过尚未写完或损坏的 JSONL 行。")
        modern = any(r.get("type") == "event_msg" and r.get("payload", {}).get("type") == "item_completed" for _, r in rows)
        events, turns, pending, seen = [], OrderedDict(), {}, set()
        tid = "legacy"
        for ordinal, row in rows:
            p = row.get("payload", {})
            when = row.get("timestamp")
            typ = p.get("type")
            if row.get("type") == "turn_context":
                tid = p.get("turn_id", tid)
            if row.get("type") == "event_msg" and typ == "task_started":
                tid = p.get("turn_id", tid)
                turns[tid] = {"turn_id": tid, "started_at": p.get("started_at") or when, "status": "inProgress"}
            if row.get("type") == "event_msg" and typ in ("task_complete", "task_completed", "turn_aborted"):
                active = p.get("turn_id", tid)
                turns.setdefault(active, {"turn_id": active}).update(status="interrupted" if typ == "turn_aborted" else "completed", completed_at=when)
            item = None
            start, end = None, None
            if modern:
                if row.get("type") != "event_msg" or typ != "item_completed":
                    continue
                tid = p.get("turn_id", tid)
                if not isinstance(p.get("item"), dict):
                    warnings.append("一个执行条目的结构损坏，已跳过。")
                    continue
                item = canonical_item(p["item"])
                start, end = p.get("started_at_ms"), p.get("completed_at_ms")
            elif row.get("type") == "response_item":
                if typ == "message" and p.get("role") in ("user", "assistant"):
                    item = {"type": "userMessage" if p["role"] == "user" else "agentMessage", "id": p.get("id") or f"row-{ordinal}", "content": p.get("content"), "text": text_of(p.get("content")), "phase": p.get("phase")}
                elif typ == "reasoning":
                    item = {"type": "reasoning", "id": p.get("id") or f"row-{ordinal}", "summary": p.get("summary", []), "content": []}
                elif typ in ("function_call", "custom_tool_call"):
                    call_id = p.get("call_id") or p.get("id") or f"row-{ordinal}"
                    if (tid, call_id) in seen:
                        continue
                    name = p.get("name", "tool")
                    args = p.get("arguments") or p.get("input") or ""
                    try:
                        parsed = json.loads(args) if isinstance(args, str) else args
                    except ValueError:
                        parsed = {"input": args}
                    if not isinstance(parsed, dict):
                        parsed = {"input": parsed}
                    if name.split(".")[-1] in ("exec_command", "shell", "shell_command"):
                        item = {"type": "commandExecution", "id": call_id, "command": parsed.get("cmd") or parsed.get("command") or args, "status": "inProgress"}
                    else:
                        item = {"type": "mcpToolCall", "id": call_id, "tool": name, "arguments": parsed, "status": "inProgress"}
                    pending[(tid, call_id)] = (len(events), item, tid, ordinal, when)
                elif typ in ("function_call_output", "custom_tool_call_output"):
                    key = (tid, p.get("call_id"))
                    # Results may arrive after another turn_context; call IDs still identify the pending call.
                    if key not in pending:
                        key = next((k for k in pending if k[1] == p.get("call_id")), key)
                    match = pending.pop(key, None)
                    if match:
                        idx, previous, old_tid, old_ord, old_time = match
                        previous["aggregatedOutput" if previous["type"] == "commandExecution" else "result"] = p.get("output", "")
                        previous["status"] = "completed"
                        events[idx] = normalize(previous, turn_id=old_tid, ordinal=old_ord, started=old_time, completed=when, source="rollout")
                    continue
            if item:
                item.setdefault("id", f"row-{ordinal}")
                key = (tid, item["id"])
                if key in seen:
                    continue
                seen.add(key)
                events.append(normalize(item, turn_id=tid, ordinal=ordinal, started=start, completed=end, created=when, source="rollout"))
        return events, list(turns.values()), warnings
