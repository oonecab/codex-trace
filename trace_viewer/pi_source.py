"""pi agent sessions: ~/.pi/agent/sessions/--<encoded cwd>--/<timestamp>_<session id>.jsonl (read only)."""
from __future__ import annotations

import json
import os
import re
from collections import OrderedDict
from pathlib import Path

from .agent_logs import (JsonlSource, agent_item, apply_result, command_item, diff_text, edit_item, list_item, read_item,
                         read_jsonl, result_text, search_item, shrink, tool_item)
from .normalize import compact, normalize, text_of

MODEL = re.compile(r'"modelId":\s*"([^"]+)"')


def blocks_of(content):
    return [{"type": "text", "text": content}] if isinstance(content, str) else [b for b in content or [] if isinstance(b, dict)]


def user_text(content):
    parts = []
    for b in blocks_of(content):
        if b.get("type") == "text":
            parts.append(str(b.get("text") or ""))
        elif b.get("type") == "image":
            parts.append("[图像内容]")
    return "\n".join(parts).strip()


def tool_for(block, cwd):
    name, args, cid = str(block.get("name") or "tool"), block.get("arguments") or {}, block.get("id")
    if not isinstance(args, dict):
        args = {"input": args}
    low = name.lower()
    if low == "bash":
        return command_item(cid, str(args.get("command") or ""), cwd)
    if low == "read":
        return read_item(cid, str(args.get("path") or args.get("file_path") or ""), cwd)
    if low == "grep":
        return search_item(cid, str(args.get("pattern") or ""), str(args.get("path") or ""), cwd)
    if low in ("find", "ls"):
        return list_item(cid, f"{name} " + str(args.get("pattern") or args.get("path") or ""), str(args.get("path") or ""), cwd)
    if low == "edit":
        edits = [e for e in args.get("edits") or [] if isinstance(e, dict)]
        diff = "\n\n".join(diff_text(e.get("oldText"), e.get("newText")) for e in edits)
        return edit_item(cid, str(args.get("path") or ""), diff)
    if low == "write":
        return edit_item(cid, str(args.get("path") or ""), diff_text("", args.get("content")))
    if low in ("subagent", "task"):
        return agent_item(cid, name, text_of(args.get("prompt") or args.get("task")))
    return tool_item(cid, name, args)


class PiSource(JsonlSource):
    id = "pi"
    label = "pi agent"
    prefix = "pi:"

    def __init__(self, home=None):
        home = Path(home or os.environ.get("PI_CODING_AGENT_DIR") or Path.home() / ".pi" / "agent").expanduser()
        super().__init__(home / "sessions")
        self.home = home

    def info(self):
        return {**super().info(), "home": str(self.home)}

    def _scan(self, path):
        meta, prompt = {"id": "", "cwd": "", "title": "", "model": "", "createdAt": None}, ""
        with path.open(encoding="utf-8", errors="replace") as f:
            for number, line in enumerate(f):
                if number == 0:
                    try:
                        head = json.loads(line)
                    except ValueError:
                        return None
                    if not isinstance(head, dict) or head.get("type") != "session" or not head.get("id"):
                        return None
                    meta.update(id=str(head["id"]), cwd=str(head.get("cwd") or ""), createdAt=head.get("timestamp"))
                    continue
                if '"modelId"' in line:
                    found = MODEL.findall(line)
                    if found:
                        meta["model"] = found[-1]
                if not prompt and '"user"' in line:
                    try:
                        row = json.loads(line)
                    except ValueError:
                        continue
                    message = row.get("message") if isinstance(row, dict) else None
                    if isinstance(message, dict) and message.get("role") == "user":
                        prompt = user_text(message.get("content"))
        if not meta["id"]:
            return None
        meta["title"] = compact(prompt, 60)
        return meta

    def _parse(self, session):
        records, bad = read_jsonl(session["_path"])
        warnings = ["有 %d 行记录无法解析，已跳过。" % bad] if bad else []
        cwd = session["cwd"]
        # Entries form a tree (id / parentId). Show the branch that ends at the last entry.
        tree = {r["id"]: r for r in records if r.get("id")}
        leaf = next((r for r in reversed(records) if r.get("id")), None)
        chain, node, guard = [], leaf, set()
        while node and node["id"] not in guard:
            guard.add(node["id"])
            chain.append(node)
            node = tree.get(node.get("parentId"))
        active = list(reversed(chain)) if chain else []
        skipped = sum(1 for r in records if r.get("type") in ("message", "compaction") and r.get("id") not in guard)
        if skipped:
            warnings.append(f"已跳过 {skipped} 条不在当前分支上的记录。")

        entries, by_call, turns, current = [], {}, OrderedDict(), None

        def start_turn(turn_id, ts):
            turns.setdefault(turn_id, {"turn_id": turn_id, "status": "completed", "started_at": ts, "completed_at": ts})
            return turn_id

        def add(item, turn, ts, source):
            entries.append({"item": item, "turn": turn, "created": ts, "started": ts, "completed": None})
            item["sourceRecord"] = shrink(source)
            return entries[-1]

        for rec in active:
            kind, ts, rid = rec.get("type"), rec.get("timestamp"), str(rec.get("id"))
            if kind == "compaction":
                if current is None:
                    current = start_turn("start", ts)
                add({"type": "contextCompaction", "id": rid}, current, ts, {"type": "compaction", "summary": rec.get("summary")})
                continue
            if kind != "message":
                continue
            message = rec.get("message") or {}
            role = message.get("role")
            if role == "user":
                text = user_text(message.get("content"))
                if text:
                    current = start_turn(rid, ts)
                    add({"type": "userMessage", "id": rid, "content": text, "text": text}, current, ts, {"role": "user", "content": text})
            elif role == "toolResult":
                entry = by_call.get(message.get("toolCallId"))
                if entry:
                    apply_result(entry["item"], result_text(message.get("content")), bool(message.get("isError")), message.get("details"))
                    entry["completed"] = ts
                    entry["item"]["sourceResult"] = shrink({"isError": bool(message.get("isError")), "timestamp": ts})
                if current:
                    turns[current]["completed_at"] = ts
            elif role == "assistant":
                if current is None:
                    current = start_turn("start", ts)
                turns[current]["completed_at"] = ts
                for index, b in enumerate(blocks_of(message.get("content"))):
                    bt = b.get("type")
                    if bt == "text" and str(b.get("text") or "").strip():
                        phase = None
                        try:
                            phase = (json.loads(b.get("textSignature") or "{}") or {}).get("phase")
                        except (ValueError, AttributeError):
                            pass
                        final = phase == "final_answer" or (phase is None and message.get("stopReason") == "stop")
                        add({"type": "agentMessage", "id": f"{rid}-{index}", "text": b["text"], "phase": "final_answer" if final else None},
                            current, ts, {k: v for k, v in b.items() if k != "textSignature"})
                    elif bt == "thinking":
                        thought = str(b.get("thinking") or "").strip()
                        add({"type": "reasoning", "id": f"{rid}-{index}", "summary": [thought] if thought else []}, current, ts,
                            {k: v for k, v in b.items() if k != "thinkingSignature"})
                    elif bt == "toolCall":
                        entry = add(tool_for(b, cwd), current, ts, b)
                        by_call[b.get("id")] = entry
        if current:
            turns[current]["status"] = self._turn_status(session)
        events = [normalize(e["item"], turn_id=e["turn"], ordinal=n, started=e["started"], completed=e["completed"],
                            created=e["created"], source="pi-jsonl") for n, e in enumerate(entries)]
        return events, list(turns.values()), warnings
