"""Claude Code sessions: ~/.claude/projects/<encoded cwd>/<session id>.jsonl (read only)."""
from __future__ import annotations

import json
import os
import re
from collections import OrderedDict
from pathlib import Path

from .agent_logs import (JsonlSource, agent_item, apply_result, command_item, diff_text, edit_item,
                         list_item, read_item, read_jsonl, result_text, search_item, shrink, tool_item, web_item)
from .normalize import compact, normalize, text_of

REMINDER = re.compile(r"<system-reminder>.*?</system-reminder>", re.S)
SLASH = re.compile(r"<command-name>(.*?)</command-name>\s*(?:<command-message>.*?</command-message>)?\s*(?:<command-args>(.*?)</command-args>)?", re.S)
MODEL = re.compile(r'"model":\s*"([^"]+)"')


def user_text(content):
    """Readable text of a user message; reminders injected by the harness are not the user's words."""
    parts = []
    for b in ([{"type": "text", "text": content}] if isinstance(content, str) else content or []):
        if not isinstance(b, dict):
            continue
        if b.get("type") == "text":
            parts.append(str(b.get("text") or ""))
        elif b.get("type") == "image":
            parts.append("[图像内容]")
    text = REMINDER.sub("", "\n".join(parts)).strip()
    if text.startswith(("<local-command-", "<bash-stdout>", "<bash-stderr>")):
        return ""  # output the harness echoes back, not something the user typed
    shell = re.match(r"<bash-input>(.*?)</bash-input>", text, re.S)
    if shell:
        return "! " + shell[1].strip()
    slash = SLASH.search(text)
    if slash and text.startswith("<command-name>"):
        return ("/" + slash[1].lstrip("/") + (" " + slash[2].strip() if slash[2] and slash[2].strip() else "")).strip()
    return text


def tool_for(block, cwd):
    name, args, cid = str(block.get("name") or "tool"), block.get("input") or {}, block.get("id")
    if not isinstance(args, dict):
        args = {"input": args}
    if name in ("Bash", "PowerShell"):
        return command_item(cid, str(args.get("command") or ""), cwd)
    if name == "Read":
        return read_item(cid, str(args.get("file_path") or ""), cwd)
    if name == "Grep":
        return search_item(cid, str(args.get("pattern") or ""), str(args.get("path") or ""), cwd)
    if name == "Glob":
        return list_item(cid, "Glob " + str(args.get("pattern") or ""), str(args.get("path") or ""), cwd)
    if name == "Edit":
        return edit_item(cid, str(args.get("file_path") or ""), diff_text(args.get("old_string"), args.get("new_string")))
    if name == "MultiEdit":
        edits = [e for e in args.get("edits") or [] if isinstance(e, dict)]
        return edit_item(cid, str(args.get("file_path") or ""), "\n\n".join(diff_text(e.get("old_string"), e.get("new_string")) for e in edits))
    if name == "Write":
        return edit_item(cid, str(args.get("file_path") or ""), diff_text("", args.get("content")))
    if name == "NotebookEdit":
        return edit_item(cid, str(args.get("notebook_path") or ""), diff_text("", args.get("new_source")))
    if name == "WebSearch":
        return web_item(cid, str(args.get("query") or ""))
    if name == "WebFetch":
        return web_item(cid, str(args.get("url") or ""))
    if name in ("Task", "Agent"):
        return agent_item(cid, name, text_of(args.get("prompt") or args.get("description")))
    server = name.split("__")[1] if name.startswith("mcp__") and name.count("__") >= 2 else ""
    return tool_item(cid, name, args, server)


class ClaudeCodeSource(JsonlSource):
    id = "claude"
    label = "Claude Code"
    prefix = "claude:"

    def __init__(self, home=None):
        home = Path(home or os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude").expanduser()
        super().__init__(home / "projects")
        self.home = home

    def info(self):
        return {**super().info(), "home": str(self.home)}

    def _scan(self, path):
        meta = {"id": path.stem, "cwd": "", "title": "", "model": "", "createdAt": None}
        prompt = ""
        with path.open(encoding="utf-8", errors="replace") as f:
            for line in f:
                if '"ai-title"' in line:
                    row = _loads(line)
                    if row and row.get("type") == "ai-title" and row.get("aiTitle"):
                        meta["title"] = str(row["aiTitle"])
                    continue
                if not meta["cwd"] or not prompt or not meta["createdAt"]:
                    row = _loads(line)
                    if row and row.get("type") in ("user", "assistant"):
                        meta["cwd"] = meta["cwd"] or str(row.get("cwd") or "")
                        meta["createdAt"] = meta["createdAt"] or row.get("timestamp")
                        if not prompt and row["type"] == "user" and not row.get("isMeta") and not row.get("isSidechain"):
                            prompt = user_text((row.get("message") or {}).get("content"))
                if '"model"' in line and '"assistant"' in line:
                    found = MODEL.findall(line)
                    if found:
                        meta["model"] = found[-1]
        if not meta["cwd"] and not meta["title"] and not prompt:
            return None
        meta["title"] = meta["title"] or compact(prompt, 60)
        return meta

    def _parse(self, session):
        path = session["_path"]
        records, bad = read_jsonl(path)
        warnings = ["有 %d 行记录无法解析，已跳过。" % bad] if bad else []
        cwd = session["cwd"]
        entries, by_call, turns, seen, sidechain = [], {}, OrderedDict(), set(), 0
        current = None

        def start_turn(turn_id, ts):
            turns.setdefault(turn_id, {"turn_id": turn_id, "status": "completed", "started_at": ts, "completed_at": ts})
            return turn_id

        def add(item, turn, ts, record, source=None):
            entries.append({"item": item, "turn": turn, "created": ts, "started": ts, "completed": None})
            item["sourceRecord"] = shrink(source if source is not None else record)
            return entries[-1]

        for rec in records:
            kind = rec.get("type")
            if kind not in ("user", "assistant"):
                continue
            uid = rec.get("uuid")
            if uid in seen:
                continue
            seen.add(uid)
            if rec.get("isSidechain"):
                sidechain += 1
                continue
            message, ts = rec.get("message") or {}, rec.get("timestamp")
            content = message.get("content")
            blocks = [{"type": "text", "text": content}] if isinstance(content, str) else [b for b in content or [] if isinstance(b, dict)]
            if kind == "user":
                for b in blocks:
                    if b.get("type") != "tool_result":
                        continue
                    entry = by_call.get(b.get("tool_use_id"))
                    if entry:
                        apply_result(entry["item"], result_text(b.get("content")), bool(b.get("is_error")))
                        entry["completed"] = ts
                        entry["item"]["sourceResult"] = shrink({"isError": bool(b.get("is_error")), "timestamp": ts})
                    if current:
                        turns[current]["completed_at"] = ts
                if rec.get("isMeta"):
                    continue
                text = user_text([b for b in blocks if b.get("type") != "tool_result"])
                if text:
                    current = start_turn(str(rec.get("promptId") or uid), ts)
                    add({"type": "userMessage", "id": str(uid), "content": text, "text": text}, current, ts, rec, {"role": "user", "content": text})
                continue
            if current is None:
                current = start_turn("start", ts)
            turns[current]["completed_at"] = ts
            for index, b in enumerate(blocks):
                bt = b.get("type")
                if bt == "text" and str(b.get("text") or "").strip():
                    final = message.get("stop_reason") == "end_turn"
                    add({"type": "agentMessage", "id": f"{uid}-{index}", "text": b["text"], "phase": "final_answer" if final else None}, current, ts, rec, b)
                elif bt == "thinking":
                    thought = str(b.get("thinking") or "").strip()
                    add({"type": "reasoning", "id": f"{uid}-{index}", "summary": [thought] if thought else []}, current, ts, rec,
                        {k: v for k, v in b.items() if k != "signature"})
                elif bt == "tool_use":
                    item = tool_for(b, cwd)
                    entry = add(item, current, ts, rec, b)
                    by_call[b.get("id")] = entry
        if sidechain:
            warnings.append(f"已跳过 {sidechain} 条子代理内部记录。")
        if current:
            turns[current]["status"] = self._turn_status(session)
        events = []
        for ordinal, e in enumerate(entries):
            events.append(normalize(e["item"], turn_id=e["turn"], ordinal=ordinal, started=e["started"], completed=e["completed"],
                                    created=e["created"], source="claude-jsonl"))
        return events, list(turns.values()), warnings


def _loads(line):
    try:
        row = json.loads(line)
    except ValueError:
        return None
    return row if isinstance(row, dict) else None
