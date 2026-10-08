"""Shared plumbing for every history source: caching, per-session parse locks and result assembly.

A source only has to say how to list sessions (`list_sessions`), find one (`_session`) and turn it into
normalized events plus turns (`_parse`). Everything downstream (analysis, fingerprint, detail lookup) is common.
"""
from __future__ import annotations

import hashlib
import threading
import time
from collections import OrderedDict

from .analysis import build_analysis
from .normalize import public_event, statistics, timestamp_ms


class StoreError(Exception):
    pass


def fingerprint(result):
    """Cheap change token for the UI: event identity, status and payload sizes, never full content."""
    digest = hashlib.sha1()
    for e in result["events"]:
        d = e["_detail"]
        digest.update(repr((e["turnId"], e["id"], e["ordinal"], e["status"], e["exitCode"], e["completedAt"], e["durationMs"],
                            len(d["body"]), len(d["input"]), len(d["output"]))).encode("utf-8"))
    for t in result["turns"]:
        digest.update(repr((t["id"], t["status"], t["completedAt"], t["durationMs"])).encode("utf-8"))
    digest.update(repr((result["session"]["title"], result["session"]["updatedAt"], result["analysis"]["version"])).encode("utf-8"))
    return digest.hexdigest()


def assemble(session, sid, events, turns, warnings):
    """Build the API result. `turns` use the history-database shape: turn_id, status, started_at, ..."""
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
    result["fingerprint"] = fingerprint(result)
    return result


class CachedSource:
    """Subclasses provide `list_sessions`, `_session` and `_parse`; ids may carry a source prefix."""

    id = "codex"
    label = "Codex"
    prefix = ""

    def __init__(self):
        self._lock = threading.RLock()
        self._parse_locks = {}
        self._cache = OrderedDict()

    def owns(self, sid):
        return sid.startswith(self.prefix) if self.prefix else True

    def info(self):  # pragma: no cover - overridden
        return {"id": self.id, "label": self.label}

    def list_sessions(self):  # pragma: no cover - overridden
        raise NotImplementedError

    def _session(self, sid):  # pragma: no cover - overridden
        raise NotImplementedError

    def _parse(self, session):  # pragma: no cover - overridden
        """Return (events, turns, warnings) for one session dict."""
        raise NotImplementedError

    def _cached(self, sid, max_age=2):
        with self._lock:
            cached = self._cache.get(sid)
            if cached and (max_age is None or time.monotonic() - cached[0] < max_age):
                return cached[1]
        return None

    def load(self, sid, refresh=False):
        if not refresh and (hit := self._cached(sid)):
            return hit
        with self._lock:
            parse_lock = self._parse_locks.setdefault(sid, threading.Lock())
        with parse_lock:
            # Another request may have finished parsing while this one waited.
            if not refresh and (hit := self._cached(sid)):
                return hit
            session = self._session(sid)
            if not session:
                raise KeyError("会话不存在。")
            events, turns, warnings = self._parse(session)
            result = assemble(session, sid, events, turns, warnings)
            with self._lock:
                self._cache[sid] = (time.monotonic(), result)
                self._cache.move_to_end(sid)
                while len(self._cache) > 3:
                    evicted, _ = self._cache.popitem(last=False)
                    self._parse_locks.pop(evicted, None)
            return result

    def detail(self, sid, item_id, turn_id=None):
        def find(result):
            return next((e for e in result["events"] if e["id"] == item_id and (turn_id is None or e["turnId"] == turn_id)), None)

        event = find(self._cached(sid, max_age=None) or self.load(sid))
        if event is None:
            # The cached copy may predate this event; look again before giving up.
            event = find(self.load(sid, refresh=True))
        if event is None:
            raise KeyError("事件不存在，可能需要刷新。")
        return {**public_event(event), **event["_detail"]}
