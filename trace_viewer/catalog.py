"""One entry point over every history source. Ids of non-Codex sources carry a prefix (`claude:`, `pi:`)."""
from __future__ import annotations


class Catalog:
    def __init__(self, sources):
        self.sources = list(sources)

    def _for(self, sid):
        for source in self.sources:
            if source.prefix and sid.startswith(source.prefix):
                return source
        for source in self.sources:
            if not source.prefix:
                return source
        raise KeyError("会话不存在。")

    def info(self):
        infos = [s.info() for s in self.sources]
        first = infos[0] if infos else {}
        return {**first, "sources": infos, "readOnly": True}

    def list_sessions(self):
        sessions, warnings = [], []
        for source in self.sources:
            try:
                rows, warning = source.list_sessions()
            except Exception as exc:  # one broken source must not hide the others
                rows, warning = [], f"{source.label}：{exc}"
            sessions.extend(rows)
            if warning:
                warnings.append(warning)
        sessions.sort(key=lambda s: s["updatedAt"] or 0, reverse=True)
        return sessions, "；".join(warnings) or None

    def load(self, sid, refresh=False):
        return self._for(sid).load(sid, refresh=refresh)

    def detail(self, sid, item_id, turn_id=None):
        return self._for(sid).detail(sid, item_id, turn_id)
