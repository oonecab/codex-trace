"""Deterministic cards, relationships and graph. No model, I/O or command execution."""
from __future__ import annotations

import hashlib
import json
import ntpath
import posixpath
import re
import shlex
from collections import Counter, OrderedDict

VERSION = "rules-1"
PHASES = {"inspect": "读取与检索", "change": "文件修改", "verify": "测试与检查",
          "execute": "命令执行", "tools": "工具操作", "delegate": "子代理协作",
          "context": "上下文整理", "wait": "等待", "statement": "说明与摘要", "other": "其他记录"}
LABELS = {"read": "读取文件", "search": "搜索", "list": "列出文件", "edit": "修改文件",
          "test": "运行测试", "check": "语法检查", "build": "构建命令", "command": "执行命令",
          "web": "网页检索", "tool": "调用工具", "agent": "子代理活动", "image": "查看图像",
          "context": "整理上下文", "wait": "等待", "message": "进展说明", "final": "最终答复",
          "thinking": "公开摘要", "request": "用户请求", "other": "其他事件"}
PHASE_FOR = {"read": "inspect", "search": "inspect", "list": "inspect", "web": "inspect", "image": "inspect",
             "edit": "change", "test": "verify", "check": "verify", "build": "verify", "command": "execute",
             "tool": "tools", "agent": "delegate", "context": "context", "wait": "wait",
             "message": "statement", "final": "statement", "thinking": "statement", "request": "statement"}
ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def uid(kind, *parts):
    value = json.dumps(parts, ensure_ascii=False, separators=(",", ":"))
    return kind + ":" + hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]


def clip(value, size=110):
    return re.sub(r"\s+", " ", str(value or "")).strip()[:size]


def path_key(value, cwd=""):
    """Lexical identity only; never inspect the referenced filesystem."""
    value = str(value or "").strip()
    if not value or re.search(r"[\r\n*$?%`(){}]", value) or value.startswith("~") or re.match(r"\w+://", value):
        return None
    cwd = str(cwd or "")
    if value.startswith("\\\\?\\"):
        value = value[4:]
    if cwd.startswith("\\\\?\\"):
        cwd = cwd[4:]
    windows = bool(re.match(r"^[a-zA-Z]:", value) or value.startswith("\\\\") or re.match(r"^[a-zA-Z]:", cwd) or "\\" in cwd)
    module = ntpath if windows else posixpath
    if windows and module.splitdrive(value)[0] and not module.isabs(value):
        return None  # C:relative depends on per-drive shell state, not the logged cwd.
    if windows and value.startswith(("\\", "/")) and not module.splitdrive(value)[0]:
        drive = module.splitdrive(cwd)[0]
        if not drive:
            return None
        value = drive + value
    if not module.isabs(value):
        if not cwd or not module.isabs(cwd):
            return None
        value = module.join(cwd, value)
    value = module.normpath(value)
    return value.replace("\\", "/").casefold() if windows else value


def evidence(field, quote, rule):
    return {"field": field, "quote": str(quote)[:240], "rule": rule}


def _tokens(line):
    try:
        return [t[1:-1] if len(t) > 1 and t[0] == t[-1] and t[0] in "\"'" else t
                for t in shlex.split(line, posix=False)]
    except ValueError:
        return []


def _statements(script):
    # Quoted scripts/examples are not executable statements. Here-strings commonly
    # contain whole source files, including strings such as "pytest".
    script = re.sub(r"(?ms)@(['\"]).*?^\s*\1@", "__HERE_STRING__", script)
    lines, chars, quote = [], [], None
    for char in script:
        if char in "\"'":
            quote = None if quote == char else char if quote is None else quote
        if char in "\n;|" and quote is None:
            lines.append("".join(chars).strip()); chars = []
        else:
            chars.append(char)
    lines.append("".join(chars).strip())
    return [line.lstrip("& ") for line in lines if line and not line.startswith("#")]


def _script(raw, fallback):
    actions = raw.get("commandActions") or []
    commands = [a.get("command") for a in actions if isinstance(a, dict) and isinstance(a.get("command"), str)]
    if commands:
        return "\n".join(dict.fromkeys(commands)), "commandActions.command"
    value = fallback
    # Only unwrap an actual shell executable at the start, not '-Command' inside data.
    match = re.match(r"^\s*(?:\"[^\"]*(?:pwsh|powershell)(?:\.exe)?\"|[^\s]*(?:pwsh|powershell)(?:\.exe)?)\s+(?:-\w+\s+)*?-Command\s+([\s\S]+)$", value, re.I)
    if not match:
        match = re.match(r"^\s*(?:\"[^\"]*(?:bash|sh)\"|(?:/[^\s]+/)?(?:bash|sh))\s+-[lc]+\s+([\s\S]+)$", value)
    if match:
        value = match[1]
        if len(value) > 1 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
    return value, "command"


def command_info(event):
    detail = event["_detail"]
    raw = detail["raw"]
    script, source_field = _script(raw, detail["input"])
    operations, refs, reasons, tests, display = [], [], [], [], []
    changes_directory = False
    actions = [a for a in (raw.get("commandActions") or []) if isinstance(a, dict)]
    for action in actions:
        op = {"read": "read", "search": "search", "listFiles": "list"}.get(action.get("type"))
        if op:
            operations.append(op)
            reasons.append(evidence("commandActions.type", action["type"], "记录中的命令分类"))
        if action.get("path"):
            refs.append((str(action["path"]), "reads" if op == "read" else "targets", "commandActions.path"))
    for line in _statements(script):
        tokens = _tokens(line)
        if not tokens:
            continue
        executable = tokens[0].replace("\\", "/").rsplit("/", 1)[-1].lower().removesuffix(".exe")
        args = tokens[1:]
        if executable in {"cd", "chdir", "set-location", "push-location", "pop-location", "pushd", "popd"}:
            changes_directory = True
        op, runner = None, None
        if executable in {"get-content", "cat", "head", "tail", "type"}:
            op = "read"
            # Literal arguments only. Variables, glob patterns and computed paths stay unlinked.
            if executable == "get-content":
                m = re.search(r"(?i)-(?:literalpath|path)\s+((?:'[^']*'|\"[^\"]*\"|[^\s,]+)(?:\s*,\s*(?:'[^']*'|\"[^\"]*\"|[^\s,]+))*)", line)
                if m:
                    for token in re.findall(r"'([^']*)'|\"([^\"]*)\"|([^\s,]+)", m[1]):
                        refs.append((next((x for x in token if x), ""), "reads", source_field))
            else:
                refs.extend((a, "reads", source_field) for a in args if not a.startswith("-") and not a.isdigit())
        elif executable in {"rg", "grep", "select-string", "findstr"}:
            op = "list" if executable == "rg" and "--files" in args else "search"
        elif executable in {"ls", "dir", "get-childitem"}:
            op = "list"
        elif executable in {"pytest", "py.test"}:
            op, runner = "test", "pytest"
        elif re.fullmatch(r"python(?:\d+(?:\.\d+)*)?|py", executable):
            if len(args) >= 2 and args[0] == "-m" and args[1] in {"pytest", "unittest"}:
                op, runner = "test", args[1]
            elif len(args) >= 2 and args[:2] == ["-m", "compileall"]:
                op = "check"
        elif executable == "node" and any(a in {"--check", "-c"} for a in args):
            op = "check"
        elif executable in {"npm", "pnpm", "yarn", "bun"}:
            if (args and args[0] == "test") or (len(args) >= 2 and args[:2] == ["run", "test"]):
                op, runner = "test", executable + " test"
            elif len(args) >= 2 and args[:2] == ["run", "build"]:
                op = "build"
        elif executable in {"cargo", "go", "dotnet"} and args and args[0] == "test":
            op, runner = "test", executable + " test"
        if op == "test" and any(a in {"--help", "-h", "--collect-only", "--co"} for a in args):
            op, runner = "command", None
        if executable != "__here_string__":
            display.append(" ".join([executable, *args]))
        if op:
            operations.append(op)
            reasons.append(evidence(source_field, line, "按命令入口识别用途"))
        if runner:
            tests.append({"runner": runner, "argv": tokens, "command": line})
    operations = list(dict.fromkeys(operations)) or ["command"]
    if changes_directory:
        refs = [ref for ref in refs if ntpath.isabs(ref[0]) or posixpath.isabs(ref[0])]
    kind = next((k for k in ("test", "check", "build", "read", "search", "list") if k in operations), "command")
    return {"kind": kind, "operations": operations, "files": refs, "evidence": reasons,
            "tests": tests, "repeatSafe": not changes_directory, "display": clip(" ; ".join(display) or script)}


def test_reports(output):
    """Recognize terminal summaries, never treat an exit code as a test count."""
    text = ANSI.sub("", output or "").replace("\r\n", "\n")
    reports = []
    for m in re.finditer(r"(?m)^Ran (\d+) tests? in [\d.]+s\s*\n\s*\n?(OK(?: \([^\n]*\))?|FAILED(?: \([^\n]*\))?)\s*$", text):
        verdict = m[2]
        reports.append({"framework": "unittest", "total": int(m[1]), "status": "passed" if verdict.startswith("OK") else "failed",
                        "label": f"输出报告 {m[1]} 项测试：{verdict}", "quote": m[0].strip()[:240]})
    for m in re.finditer(r"(?m)^(?:=+\s*)?((?:\d+ (?:passed|failed|skipped|errors?|xfailed|xpassed|deselected)(?:,\s*|\s+))+)(?:in\s+[\d.]+s[^\n]*)?(?:\s*=+)?\s*$", text):
        counts = {name: int(n) for n, name in re.findall(r"(\d+) (passed|failed|skipped|errors?|xfailed|xpassed|deselected)", m[1])}
        if not any(k in counts for k in ("passed", "failed", "error", "errors")):
            continue
        failed = any(counts.get(k, 0) for k in ("failed", "error", "errors"))
        total = sum(v for k, v in counts.items() if k != "deselected")
        reports.append({"framework": "pytest", "total": total, "status": "failed" if failed else "passed",
                        "label": "输出报告 " + "、".join(f"{counts[k]} 项{label}" for k, label in (("passed", "通过"), ("failed", "失败"), ("error", "错误"), ("errors", "错误"), ("skipped", "跳过")) if k in counts), "quote": m[0].strip()[:240]})
    return reports


def _statement_hint(text):
    patterns = [("计划措辞", r"^(?:我(?:会|将|计划)|接下来|计划|准备|I(?:'ll| will)|Next\b)"),
                ("推测措辞", r"^(?:可能|怀疑|推测|假设|我(?:怀疑|推测)|I suspect|Perhaps\b|Hypothesis\b)"),
                ("结果措辞", r"^(?:已(?:完成|确认|验证)|测试通过|验证通过|确认|I (?:confirmed|verified)|Tests? passed)")]
    for label, pattern in patterns:
        if re.search(pattern, text.strip(), re.I):
            return label
    return "原文陈述"


def extract_card(event, session_id, cwd):
    d = event["_detail"]
    raw = d["raw"]
    kind = {"file": "edit", "tool": "tool", "agent": "agent", "web": "web", "context": "context", "wait": "wait", "image": "image", "message": "final" if event["phase"] == "final" else "message", "thinking": "thinking", "request": "request"}.get(event["category"], "other")
    operations, refs = [kind], []
    reasons = [evidence("type", event["type"], "记录中的事件类型")]
    tests, reports, repeat_safe = [], [], True
    title = event["title"]
    if event["category"] == "command":
        info = command_info(event)
        kind, operations, refs, tests = info["kind"], info["operations"], info["files"], info["tests"]
        repeat_safe = info["repeatSafe"]
        reasons.extend(info["evidence"])
        title = info["display"]
        if tests:
            reports = test_reports(d["output"])
            title = "运行 " + "、".join(dict.fromkeys(t["runner"] for t in tests)) + " 测试"
        elif kind == "check":
            title = "检查代码语法 · " + title
    if kind == "edit":
        relation = "writes" if raw.get("status") in {"completed", "applied"} and not event["error"] else "write_attempt"
        refs = [(p, relation, "changes.path") for p in event["files"]]
    file_refs = []
    base = str(raw.get("cwd") or cwd or "")
    for path, relation, field in refs:
        key = path_key(path, base)
        if key and not any(r["key"] == key and r["relation"] == relation for r in file_refs):
            file_refs.append({"key": key, "path": path, "relation": relation, "evidence": evidence(field, path, "记录中的字面路径；按工作目录解析")})
    if kind == "read" and file_refs:
        title = "读取 " + "、".join(r["path"].replace("\\", "/").rsplit("/", 1)[-1] for r in file_refs[:3])
        if len(file_refs) > 3:
            title += f" 等 {len(file_refs)} 个文件"
    statement = kind in {"thinking", "message", "final", "request"}
    has_result = bool(d["output"] or event["exitCode"] is not None or (event["category"] in {"command", "file", "tool", "agent", "web"} and raw.get("status")))
    report_failed = any(r["status"] == "failed" for r in reports)
    report_passed = bool(reports) and not report_failed
    attention = bool(event["error"] or report_failed)
    if reports:
        result_label = "；".join(r["label"] for r in reports[-2:])
    elif event["exitCode"] is not None:
        result_label = f"命令退出 {event['exitCode']}"
    elif event["status"] == "inProgress":
        result_label = "记录状态：执行中"
    elif event["error"]:
        result_label = "记录含异常"
    else:
        result_label = "已记录返回内容" if d["output"] else "记录状态：" + str(raw.get("status") or "未记录")
    if reports and event["exitCode"] not in (None, 0):
        result_label += f"；整条命令退出 {event['exitCode']}"
    tests_key = uid("test-command", path_key(base, base), [t["argv"] for t in tests]) if tests and repeat_safe and path_key(base, base) else None
    return {"id": uid("card", session_id, event["turnId"], event["id"]), "eventId": event["id"], "turnId": event["turnId"], "ordinal": event["ordinal"],
            "kind": kind, "label": LABELS[kind], "phase": PHASE_FOR.get(kind, "other"), "operations": operations,
            "title": clip(title, 170), "preview": event["preview"][:350], "timestamp": event["timestamp"], "durationMs": event["durationMs"],
            "sourceKind": "statement" if statement else "record", "statementHint": _statement_hint(d["body"]) if statement else None,
            "isOperation": not statement, "readable": event["hasReadableText"], "attention": attention,
            "files": file_refs, "agents": event["agents"], "evidence": reasons,
            "testCommands": [{"runner": t["runner"], "command": t["command"]} for t in tests], "testReports": reports,
            "testOutcome": "failed" if report_failed else "passed" if report_passed else "unreported",
            "hasResult": has_result, "resultLabel": result_label, "exitCode": event["exitCode"], "_testKey": tests_key}


def build_analysis(events, turns, *, session_id="", cwd=""):
    """L1 rule cards -> L2 explicit relationships -> L3 graph + turn summaries."""
    cards = [extract_card(e, session_id, cwd) for e in events]
    by_turn = OrderedDict((t["id"], []) for t in turns)
    for c in cards:
        by_turn.setdefault(c["turnId"], []).append(c)
    nodes, edges, seen_nodes = [], [], set()

    def node(id_, type_, label, **fields):
        if id_ not in seen_nodes:
            nodes.append({"id": id_, "type": type_, "label": label, **fields}); seen_nodes.add(id_)
        return id_

    def edge(src, dst, kind, label, basis="record", **fields):
        edges.append({"id": uid("edge", src, dst, kind), "source": src, "target": dst, "kind": kind, "label": label, "basis": basis, **fields})

    session_node = node(uid("session", session_id), "session", "当前会话", sessionId=session_id)
    summaries = []
    for turn_id, turn_cards in by_turn.items():
        turn_cards.sort(key=lambda c: c["ordinal"])
        turn_node = node(uid("turn", session_id, turn_id), "turn", "对话轮次", turnId=turn_id)
        edge(session_node, turn_node, "contains", "包含轮次")
        operations = [c for c in turn_cards if c["isOperation"]]
        previous, stages, test_groups = None, [], OrderedDict()
        for card in turn_cards:
            cid = node(card["id"], "statement" if not card["isOperation"] else "action", card["title"], cardId=card["id"], turnId=turn_id)
            edge(turn_node, cid, "contains", "本轮记录", turnId=turn_id)
            if card["hasResult"]:
                rid = node(uid("result", cid), "result", card["resultLabel"], cardId=cid, turnId=turn_id, attention=card["attention"])
                edge(cid, rid, "returns", "条目记录的返回", turnId=turn_id, evidence=[evidence("aggregatedOutput / result / status / exitCode", card["resultLabel"], "同一持久化事件中的返回字段")])
            for ref in card["files"]:
                fid = node(uid("file", ref["key"]), "file", ref["path"].replace("\\", "/").rsplit("/", 1)[-1], path=ref["path"], canonicalPath=ref["key"])
                edge(cid, fid, ref["relation"], {"reads": "读取", "writes": "已完成的修改记录", "write_attempt": "修改目标（未确认完成）", "targets": "命令目标"}[ref["relation"]], turnId=turn_id, evidence=[ref["evidence"]])
            for aid in dict.fromkeys(card["agents"]):
                anid = node(uid("agent", aid), "agent", "子代理 " + aid[:8], sessionId=aid)
                edge(cid, anid, "agent_reference", "记录中的代理 ID", turnId=turn_id)
            if not card["isOperation"]:
                continue
            if previous:
                edge(previous["id"], cid, "sequence", "记录顺序", "order", turnId=turn_id)
            previous = card
            if not stages or stages[-1]["phase"] != card["phase"]:
                stages.append({"id": uid("stage", cid, card["phase"]), "phase": card["phase"], "label": PHASES[card["phase"]], "cardIds": []})
            stages[-1]["cardIds"].append(cid)
            if card["_testKey"]:
                group = test_groups.setdefault(card["_testKey"], [])
                if group:
                    before = group[-1]
                    edits = [c for c in operations if before["ordinal"] < c["ordinal"] < card["ordinal"] and c["kind"] == "edit"]
                    edge(before["id"], cid, "same_test_command", "同一测试命令再次执行", "rule", turnId=turn_id,
                         interveningEdits=[c["id"] for c in edits],
                         evidence=[evidence("command + cwd", card["testCommands"][0]["command"], "同轮、相同字面参数及工作目录；不表示因果或修复")])
                group.append(card)
        counts = Counter(op for c in operations for op in set(c["operations"]))
        written = {ref["key"] for c in operations for ref in c["files"] if ref["relation"] == "writes"}
        read = {ref["key"] for c in operations for ref in c["files"] if ref["relation"] == "reads"}
        test_cards = [c for c in operations if c["testCommands"]]
        parts = []
        inspect = sum(bool(set(c["operations"]) & {"read", "search", "list", "web", "image"}) for c in operations)
        if inspect:
            parts.append(f"读取 / 检索 {inspect} 项操作")
        if counts["edit"]:
            parts.append(f"{counts['edit']} 条文件修改记录" + (f"，完成修改涉及 {len(written)} 个文件" if written else ""))
        if test_cards:
            parts.append(f"{len(test_cards)} 次测试调用")
        checks = sum(bool(set(c["operations"]) & {"check", "build"}) for c in operations)
        if checks:
            parts.append(f"{checks} 次检查 / 构建")
        uncategorized = sum(c["kind"] == "command" for c in operations)
        other = len(operations) - sum(c["phase"] in {"inspect", "change", "verify"} for c in operations)
        if other:
            parts.append(f"{other} 次其他操作")
        if not parts:
            parts.append("本轮没有工具操作记录" if turn_cards else "本轮尚无可读事件")
        passed = sum(c["testOutcome"] == "passed" for c in test_cards)
        failed = sum(c["testOutcome"] == "failed" for c in test_cards)
        unreported = len(test_cards) - passed - failed
        summaries.append({"id": turn_id, "summary": "；".join(parts), "operationCount": len(operations),
                          "statementCount": sum(c["sourceKind"] == "statement" and c["readable"] for c in turn_cards),
                          "writtenFiles": len(written), "readFiles": len(read), "testCalls": len(test_cards), "testPassed": passed, "testFailed": failed, "testUnreported": unreported,
                          "attentionCount": sum(c["attention"] for c in operations), "unclassifiedCommands": uncategorized,
                          "stages": stages, "testSeries": [{"id": key, "cardIds": [c["id"] for c in group], "label": group[0]["testCommands"][0]["runner"]} for key, group in test_groups.items() if len(group) > 1]})
    return {"version": VERSION, "cards": [{k: v for k, v in c.items() if not k.startswith("_")} for c in cards],
            "turns": summaries, "graph": {"nodes": nodes, "edges": edges}}
