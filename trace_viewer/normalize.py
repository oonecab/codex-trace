"""Turn persisted items into facts suitable for a timeline, without an LLM."""
from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime

CATEGORIES = {
    "userMessage": "request", "agentMessage": "message", "reasoning": "thinking",
    "commandExecution": "command", "fileChange": "file", "webSearch": "web",
    "mcpToolCall": "tool", "collabAgentToolCall": "agent", "subAgentActivity": "agent",
    "contextCompaction": "context", "sleep": "wait", "imageView": "image",
    "imageGeneration": "image",
}
EVENT_LABELS = {"request": "用户请求", "message": "进展说明", "thinking": "思考",
          "command": "执行命令", "file": "修改文件", "web": "搜索网页", "tool": "调用工具",
          "agent": "子代理", "context": "压缩上下文", "wait": "等待", "image": "图像", "other": "其他事件"}


def text_of(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(filter(None, (text_of(v) for v in value)))
    if isinstance(value, dict):
        for key in ("text", "content", "output_text"):
            if key in value:
                return text_of(value[key])
        if value.get("type") in ("image", "input_image", "image_url"):
            return "[图像内容]"
        return json.dumps(value, ensure_ascii=False, indent=2)
    return str(value)


def timestamp_ms(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value if value > 10**11 else value * 1000)
    if not isinstance(value, str):
        return None
    try:
        return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() * 1000)
    except (ValueError, TypeError):
        return None


def compact(text: str, limit=160) -> str:
    return re.sub(r"\s+", " ", text).strip()[:limit]


def safe_raw(value):
    """Opaque reasoning and embedded binary media are not a readable transcript."""
    if isinstance(value, dict):
        if str(value.get("type", "")).lower() == "reasoning":
            value = {**value, "content": "[仅展示公开思考摘要]"}
            if "raw_content" in value:
                value["raw_content"] = "[仅展示公开思考摘要]"
        return {k: ("[未展示加密内容]" if k in ("encrypted_content", "encryptedContent") else
                    "[二进制内容已省略]" if k in ("data", "blob") and isinstance(v, str) and len(v) > 4096 else
                    safe_raw(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [safe_raw(v) for v in value]
    return value


def canonical_item(item: dict) -> dict:
    """Map the PascalCase rollout representation to the history DB representation."""
    item = dict(item)
    kind = str(item.get("type") or "unknown")
    item["type"] = kind
    if kind[:1].isupper():
        item["type"] = kind[:1].lower() + kind[1:]
    if kind == "Extension":
        item["type"] = item.get("kind", "other")
        if "search" in item["type"].lower():
            item["type"] = "webSearch"
    aliases = {"aggregated_output": "aggregatedOutput", "exit_code": "exitCode",
               "parsed_cmd": "commandActions", "process_id": "processId", "summary_text": "summary",
               "raw_content": "content", "duration_ms": "durationMs", "receiver_thread_ids": "receiverThreadIds",
               "sender_thread_id": "senderThreadId", "agent_thread_id": "agentThreadId", "agent_path": "agentPath"}
    for old, new in aliases.items():
        if old in item and new not in item:
            item[new] = item[old]
    duration = item.get("duration")
    if isinstance(duration, dict) and "durationMs" not in item:
        item["durationMs"] = int(duration.get("secs", 0) * 1000 + duration.get("nanos", 0) / 10**6)
    if isinstance(item.get("command"), list):
        item["commandArgv"] = item["command"]
        item["command"] = " ".join(item["command"])
    if item["type"] == "agentMessage" and "text" not in item:
        item["text"] = text_of(item.get("content"))
    return item


# Each handler turns one canonical item into the readable parts of an event. A new item type
# (for example from another agent's log) only needs a handler registered with @handles(...).
HANDLERS = {}


def handles(*types):
    def register(fn):
        for t in types:
            HANDLERS[t] = fn
        return fn
    return register


@handles("userMessage")
def _user_message(item, label):
    body = text_of(item.get("content"))
    # A user prompt may contain app context followed by the actual message.
    body = re.sub(r"<(environment_context|external_codex_apps_open_page)>.*?</\1>", "", body, flags=re.S).strip() or body
    reply = re.fullmatch(r"<send_user_message_question_reply>\s*(.*?)\s*</send_user_message_question_reply>", body, flags=re.S)
    if reply:
        try:
            answers = json.loads(reply[1])
            if isinstance(answers, list) and all(isinstance(a, dict) for a in answers):
                body = "\n\n".join(f"{a.get('question', '')}\n选择：{text_of(a.get('answer'))}" for a in answers)
        except ValueError:
            pass
    return {"title": compact(body), "body": body}


@handles("agentMessage")
def _agent_message(item, label):
    body = text_of(item.get("text"))
    final = item.get("phase") in ("final", "final_answer")
    return {"label": "最终答复" if final else "进展说明", "title": compact(body), "body": body}


@handles("reasoning")
def _reasoning(item, label):
    body = text_of(item.get("summary"))
    return {"title": compact(body) if body.strip() else "思考 · 没有可展示的摘要", "body": body}


@handles("commandExecution")
def _command(item, label):
    input_text = text_of(item.get("command"))
    output = text_of(item.get("aggregatedOutput"))
    actions = item.get("commandActions") or []
    names = [str(x.get("name") or x.get("path") or "") for x in actions if isinstance(x, dict)]
    names = [n.replace("\\", "/").rsplit("/", 1)[-1] for n in names if n]
    kinds = {x.get("type") for x in actions if isinstance(x, dict)}
    parts = {"input": input_text, "output": output}
    if kinds and kinds <= {"read"}:
        parts.update(label="读取文件", title="读取 " + "、".join(dict.fromkeys(names)) if names else "读取文件")
    elif kinds and kinds <= {"search"}:
        parts.update(label="搜索代码", title=compact(input_text))
    elif kinds and kinds <= {"listFiles"}:
        parts.update(label="列出文件", title=compact(input_text))
    else:
        # Show the script, not the ubiquitous PowerShell executable prefix.
        shown = re.sub(r'^.*?(?:-Command\s+| -lc\s+)', '', input_text, count=1, flags=re.I)
        parts["title"] = compact(shown.strip('"\'')) or label
    return parts


@handles("fileChange")
def _file_change(item, label):
    changes = item.get("changes") or []
    files = [str(x.get("path", "")) for x in changes if isinstance(x, dict) and x.get("path")]
    title = "修改 " + "、".join(p.replace("\\", "/").rsplit("/", 1)[-1] for p in files[:3])
    if len(files) > 3:
        title += f" 等 {len(files)} 个文件"
    diff = "\n\n".join(f"{x.get('path', '')}\n{text_of(x.get('diff'))}" for x in changes if isinstance(x, dict))
    return {"title": title, "input": diff, "output": text_of(item.get("resultText")), "body": "\n".join(files), "files": files}


@handles("webSearch")
def _web_search(item, label):
    action = item.get("action") or {}
    query = text_of(item.get("query")) or text_of(action.get("query")) or text_of(action)
    return {"title": compact(query) or "搜索网页", "input": query, "output": text_of(item.get("results"))}


@handles("mcpToolCall")
def _tool_call(item, label):
    return {"title": str(item.get("tool") or item.get("name") or label), "body": str(item.get("server") or ""),
            "input": json.dumps(item.get("arguments") or {}, ensure_ascii=False, indent=2),
            "output": text_of(item.get("result")) or text_of(item.get("error"))}


@handles("collabAgentToolCall")
def _collab_agent(item, label):
    return {"title": str(item.get("tool") or "协调子代理"), "agents": list(item.get("receiverThreadIds") or []),
            "input": text_of(item.get("prompt")), "output": text_of(item.get("agentsStates"))}


@handles("subAgentActivity")
def _sub_agent(item, label):
    agent = item.get("agentThreadId")
    return {"title": str(item.get("kind") or "子代理活动"), "agents": [agent] if agent else [],
            "body": str(item.get("agentPath") or "")}


@handles("contextCompaction")
def _compaction(item, label):
    return {"title": "整理上下文，继续工作", "body": "记录表明发生了上下文压缩。"}


@handles("imageView")
def _image_view(item, label):
    return {"title": "查看图像", "body": str(item.get("path") or "")}


def _fallback(item, typ, category):
    """Unknown types stay visible: show the type name and any text the record carries."""
    return {"title": typ if category == "other" else EVENT_LABELS[category],
            "body": text_of(item.get("text") or item.get("message"))}


def normalize(item: dict, *, turn_id: str, ordinal: int, started=None, completed=None, created=None, source="sqlite") -> dict:
    item = canonical_item(item)
    typ = item.get("type", "unknown")
    category = CATEGORIES.get(typ, "other")
    label = EVENT_LABELS[category]
    handler = HANDLERS.get(typ)
    parts = handler(item, label) if handler else _fallback(item, typ, category)
    label = parts.get("label", label)
    title, body = parts.get("title", label), parts.get("body", "")
    input_text, output = parts.get("input", ""), parts.get("output", "")
    files, agents = parts.get("files", []), parts.get("agents", [])
    status = str(item.get("status") or "completed")
    code = item.get("exitCode")
    error = status.lower() in {"failed", "error", "declined", "cancelled", "canceled", "interrupted"} or (code is not None and code != 0) or bool(item.get("error"))
    if isinstance(item.get("result"), dict) and item["result"].get("isError"):
        error = True
    start = timestamp_ms(started)
    end = timestamp_ms(completed)
    duration = item.get("durationMs")
    if duration is None and start is not None and end is not None:
        duration = max(0, end - start)
    preview = (output or input_text or body) if typ == "mcpToolCall" else (body or output or input_text)
    return {"id": str(item.get("id", f"item-{ordinal}")), "turnId": str(turn_id), "ordinal": ordinal,
            "type": typ, "category": category, "label": label, "title": title or label,
            "preview": preview[:700], "status": status, "error": error,
            "exitCode": code, "startedAt": start, "completedAt": end,
            "timestamp": start or timestamp_ms(created) or end, "durationMs": duration,
            "answerPhase": "final" if item.get("phase") == "final_answer" else item.get("phase"), "files": files, "agents": agents, "source": source,
            "hasReadableText": bool(body or input_text or output),
            "_detail": {"body": body, "input": input_text, "output": output, "raw": safe_raw(item)}}


def public_event(event: dict) -> dict:
    return {k: v for k, v in event.items() if not k.startswith("_")}


def statistics(events: list[dict]) -> dict:
    counts = Counter(e["category"] for e in events)
    return {"events": len(events), "categories": dict(counts),
            "toolCalls": sum(e["type"] in {"commandExecution", "fileChange", "webSearch", "mcpToolCall", "collabAgentToolCall", "imageView", "imageGeneration", "sleep"} for e in events),
            "errors": sum(e["error"] for e in events),
            "files": len({f for e in events for f in e["files"]}),
            "thinkingWithoutText": sum(e["category"] == "thinking" and not e["hasReadableText"] for e in events)}
