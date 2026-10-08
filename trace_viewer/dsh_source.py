"""DeepSeek Harness sessions: ~/.dsh/sessions/--<encoded cwd>--/<session>/session[.vN].jsonl[.zstd] (read only).

The CLI, web and desktop front ends share this store. Logs are append-only: many small zstd frames, so reading
them needs the optional `zstandard` package (or Python 3.14+). Without it the sessions are not listed and the page
says what to install; nothing else is affected.
"""
from __future__ import annotations

import json
import os
import re
import sys
from collections import OrderedDict
from pathlib import Path

from .agent_logs import (JsonlSource, ZstdUnavailable, agent_item, apply_result, command_item, diff_text, edit_item,
                         list_item, log_lines, read_item, search_item, shrink, tool_item, web_item)
from .normalize import compact, normalize, text_of

NAME = re.compile(r"^session(?:\.v(\d+))?\.jsonl(\.zstd)?$")
SKIP = ('-chunks"', '"type":"assistant/chunk"')  # streaming fragments; complete messages follow
INSTALL_HINT = "发现 DeepSeek Harness 的 zstd 压缩会话（%d 个文件），需要先给运行本服务的 Python 安装解压库：\"%s\" -m pip install zstandard（Python 3.14 以上自带，无需安装）。"


def args_of(call):
    raw = call.get("arguments")
    if isinstance(raw, dict):
        return raw
    try:
        parsed = json.loads(raw) if isinstance(raw, str) and raw.strip() else {}
    except ValueError:
        return {"input": raw}
    return parsed if isinstance(parsed, dict) else {"input": parsed}


def tool_for(call, cwd):
    name, args, cid = str(call.get("name") or "tool"), args_of(call), call.get("id") or call.get("callId")
    path = str(args.get("file_path") or args.get("path") or "")
    if name in ("pwsh", "bash"):
        return command_item(cid, str(args.get("command") or ""), cwd)
    if name == "read":
        return read_item(cid, path, cwd)
    if name == "grep":
        return search_item(cid, str(args.get("pattern") or ""), str(args.get("path") or ""), cwd)
    if name == "glob":
        return list_item(cid, "glob " + str(args.get("pattern") or ""), str(args.get("path") or ""), cwd)
    if name == "edit":
        return edit_item(cid, path, diff_text(args.get("old_string"), args.get("new_string")))
    if name == "write":
        return edit_item(cid, path, diff_text("", args.get("content")))
    if name == "str_replace_editor":
        action = args.get("command")
        if action == "view":
            return read_item(cid, path, cwd)
        if action == "create":
            return edit_item(cid, path, diff_text("", args.get("file_text")))
        return edit_item(cid, path, diff_text(args.get("old_str"), args.get("new_str")))
    if name == "web_search":
        return web_item(cid, str(args.get("query") or ""))
    if name == "read_image":
        return {"type": "imageView", "id": cid, "path": path, "status": "inProgress"}
    if name == "spawn_teammate":
        return agent_item(cid, name, text_of(args.get("prompt") or args.get("description")))
    return tool_item(cid, name, args)


class DeepSeekHarnessSource(JsonlSource):
    id = "dsh"
    label = "DeepSeek Harness"
    prefix = "dsh:"

    def __init__(self, home=None):
        home = Path(home or os.environ.get("DSH_HOME") or Path.home() / ".dsh").expanduser()
        super().__init__(home / "sessions")
        self.home = home
        self._compressed = 0
        self._missing_zstd = False

    def info(self):
        return {**super().info(), "home": str(self.home)}

    def _files(self):
        """One log per session folder: the highest format generation (`session.v4.jsonl` over `session.jsonl`)."""
        if not self.root or not self.root.is_dir():
            return []
        found, compressed = [], 0
        for folder in self.root.glob("*/*"):
            best = None
            try:
                if not folder.is_dir():
                    continue
                for f in folder.iterdir():
                    m = NAME.match(f.name)
                    if m and f.is_file():
                        key = (int(m[1] or 0), bool(m[2]))
                        if best is None or key > best[0]:
                            best = (key, f)
                if best:
                    real = best[1].resolve()
                    if real.is_relative_to(self.root):
                        found.append(real)
                        compressed += real.name.endswith(".zstd")
            except OSError:
                continue
        self._compressed = compressed
        return found

    def _scan(self, path):
        try:
            lines, _ = log_lines(path)
        except ZstdUnavailable:
            self._missing_zstd = True
            return None
        meta = {"id": "", "cwd": "", "title": "", "model": "", "createdAt": None}
        label, asked = "", False
        for number, line in enumerate(lines):
            if number == 0:
                try:
                    head = json.loads(line)
                except ValueError:
                    return None
                if not isinstance(head, dict) or head.get("type") != "session" or not head.get("id"):
                    return None
                meta.update(id=str(head["id"]), cwd=str(head.get("cwd") or ""), createdAt=head.get("createdAt"))
                continue
            asked = asked or '"user/message"' in line[:40]
            if not any(k in line for k in ('"session/title"', '"request/header"', '"model/selection"', '"subagent/descriptor"')):
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            data = row.get("data") or {}
            kind = row.get("type")
            if kind == "session/title" and data.get("title"):
                meta["title"] = str(data["title"])
            elif kind == "request/header":
                meta["model"] = str(((data.get("header") or {}).get("config") or {}).get("model") or meta["model"])
            elif kind == "model/selection":
                meta["model"] = str(data.get("model") or meta["model"])
            elif kind == "subagent/descriptor" and data.get("label"):
                label = str(data["label"])
        if not meta["id"] or not asked:
            return None  # a header with no user message has nothing to show
        meta["title"] = ("子代理：" + compact(label, 60)) if label else compact(meta["title"], 60)
        return meta

    def list_sessions(self):
        sessions, warning = super().list_sessions()
        if self._missing_zstd:
            warning = INSTALL_HINT % (self._compressed, sys.executable)
        return sessions, warning

    def _parse(self, session):
        lines, complete = log_lines(session["_path"])
        warnings = [] if complete else ["记录末尾尚未写完，已读取到最后一个完整的数据块。"]
        cwd, bad = session["cwd"], 0
        entries, by_call, turns, current, members = [], {}, OrderedDict(), None, {}

        def turn_for(number, ts):
            nonlocal current
            current = "turn-%s" % number if number is not None else "start"
            turns.setdefault(current, {"turn_id": current, "status": "unknown", "started_at": ts, "completed_at": None})
            return current

        def add(item, turn, ts, source):
            entries.append({"item": item, "turn": turn, "created": ts, "started": ts, "completed": None})
            item["sourceRecord"] = shrink(source)
            return entries[-1]

        for line in lines[1:]:
            line = line.strip()
            if not line or any(k in line[:48] for k in SKIP):
                continue
            try:
                row = json.loads(line)
            except ValueError:
                bad += 1
                continue
            kind, ts, data = row.get("type"), row.get("time"), row.get("data") or {}
            if kind == "turn/start":
                turn_for(data.get("turn"), ts)
            elif kind == "turn/end":
                turn = turn_for(data.get("turn"), ts)
                outcome = (data.get("reason") or {}).get("kind")
                turns[turn].update(completed_at=ts, status={"completed": "completed", "aborted": "interrupted", "error": "failed"}.get(outcome, "unknown"))
                if outcome == "error":
                    turns[turn]["error_json"] = json.dumps((data.get("reason") or {}).get("error"), ensure_ascii=False)
            elif kind == "user/message":
                if (data.get("source") or {}).get("kind", "user") != "user":
                    continue  # approval notices, injected context, team and skill messages are not the user's request
                message = data
                text = "\n".join(str(b.get("text") or "") for b in message.get("content") or [] if isinstance(b, dict) and b.get("type") == "text").strip()
                if text:
                    turn = current or turn_for(data.get("turn"), ts)
                    add({"type": "userMessage", "id": str(message.get("id") or row.get("seq")), "content": text, "text": text}, turn, ts,
                        {"role": "user", "content": text})
            elif kind == "assistant/message":
                message = data.get("message") or {}
                turn = turn_for(data.get("turn"), ts) if current is None else current
                blocks = [b for b in message.get("content") or [] if isinstance(b, dict)]
                has_calls = any(b.get("type") == "tool-call" for b in blocks)
                for index, b in enumerate(blocks):
                    bt, base = b.get("type"), "%s-%s" % (data.get("step") if data.get("step") is not None else row.get("seq"), index)
                    if bt == "reasoning":
                        thought = str(b.get("text") or "").strip()
                        add({"type": "reasoning", "id": "r" + base, "summary": [thought] if thought else []}, turn, ts, b)
                    elif bt == "text" and str(b.get("text") or "").strip():
                        add({"type": "agentMessage", "id": "m" + base, "text": b["text"], "phase": None if has_calls else "final_answer"}, turn, ts, b)
                    elif bt == "tool-call":
                        entry = add(tool_for(b, cwd), turn, ts, b)
                        by_call[b.get("id")] = entry
                        if b.get("name") == "spawn_teammate":
                            members[args_of(b).get("name")] = entry
            elif kind == "tool/result":
                message = data.get("message") or {}
                entry = by_call.get(message.get("toolCallId"))
                if entry:
                    text = "\n".join(str(b.get("text") or "") if b.get("type") == "text" else "[图像内容]" for b in message.get("content") or [] if isinstance(b, dict))
                    apply_result(entry["item"], text, bool(message.get("isError")))
                    entry["completed"] = ts
                    entry["item"]["sourceResult"] = shrink({"isError": bool(message.get("isError")), "timestamp": ts})
            elif kind == "team/member":
                member = data.get("member") or {}
                entry = members.get(member.get("name"))
                if entry and member.get("id") and member["id"] not in entry["item"]["receiverThreadIds"]:
                    entry["item"]["receiverThreadIds"].append(self.prefix + member["id"])
        if bad:
            warnings.append("有 %d 行记录无法解析，已跳过。" % bad)
        # A turn without `turn/end` is running only while the file is still being written; otherwise its outcome is unknown.
        if current and turns[current]["status"] == "unknown" and self._turn_status(session) == "inProgress":
            turns[current]["status"] = "inProgress"
        events = [normalize(e["item"], turn_id=e["turn"], ordinal=n, started=e["started"], completed=e["completed"],
                            created=e["created"], source="dsh-jsonl") for n, e in enumerate(entries)]
        return events, list(turns.values()), warnings
