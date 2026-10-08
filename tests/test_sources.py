"""Claude Code and pi agent sources, built from synthetic logs (no real conversations are copied)."""
import http.client
import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote

from trace_viewer.__main__ import handler_for
from trace_viewer.catalog import Catalog
from trace_viewer.claude_source import ClaudeCodeSource
from trace_viewer.pi_source import PiSource
from trace_viewer.store import HistoryStore

CWD = r"E:\项目\示例"


def write_jsonl(path, rows, raw_lines=()):
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(r, ensure_ascii=False) for r in rows] + list(raw_lines)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def at(minute, second=0):
    return f"2026-10-01T00:{minute:02d}:{second:02d}.000Z"


class SourceFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="codex_trace_sources_")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.claude_home, self.pi_home = self.root / "claude", self.root / "pi"
        self.write_claude()
        self.write_pi()
        self.claude = ClaudeCodeSource(self.claude_home)
        self.pi = PiSource(self.pi_home)

    def write_claude(self):
        def rec(kind, uuid, minute, message, **extra):
            return {"type": kind, "uuid": uuid, "timestamp": at(minute), "cwd": CWD, "sessionId": "sess-1",
                    "isSidechain": False, "message": message, **extra}

        def tool_use(uuid, minute, call_id, name, args):
            return rec("assistant", uuid, minute, {"role": "assistant", "model": "claude-test", "content": [
                {"type": "tool_use", "id": call_id, "name": name, "input": args}]})

        def result(uuid, minute, call_id, content, error=False):
            return rec("user", uuid, minute, {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": call_id, "content": content, "is_error": error}]})

        rows = [
            {"type": "mode", "mode": "normal", "sessionId": "sess-1"},
            rec("user", "u0", 0, {"role": "user", "content": "<local-command-caveat>x</local-command-caveat>"}, isMeta=True),
            rec("user", "u1", 1, {"role": "user", "content": "请读取并修改 a.py"}, promptId="p1"),
            rec("assistant", "a1", 1, {"role": "assistant", "model": "claude-test", "content": [
                {"type": "thinking", "thinking": "", "signature": "SECRET-SIGNATURE"}]}),
            tool_use("a2", 2, "t1", "Read", {"file_path": CWD + r"\a.py"}),
            result("r1", 2, "t1", "1\tprint(1)"),
            tool_use("a3", 3, "t2", "Edit", {"file_path": CWD + r"\a.py", "old_string": "print(1)", "new_string": "print(2)"}),
            result("r2", 3, "t2", "updated"),
            tool_use("a4", 4, "t3", "Bash", {"command": "python -m unittest && echo ok"}),
            result("r3", 4, "t3", "Exit code 1\nFAILED (failures=1)", error=True),
            tool_use("a5", 5, "t4", "mcp__docs__search", {"query": "x"}),
            rec("assistant", "a6", 6, {"role": "assistant", "stop_reason": "end_turn", "content": [{"type": "text", "text": "已完成修改。"}]}),
            rec("assistant", "side", 6, {"role": "assistant", "content": [{"type": "text", "text": "子代理内部"}]}, isSidechain=True),
            rec("assistant", "a6", 6, {"role": "assistant", "content": [{"type": "text", "text": "重复记录"}]}),
            rec("user", "u2", 7, {"role": "user", "content": "<local-command-stdout>ok</local-command-stdout>"}),
            rec("user", "u3", 8, {"role": "user", "content": "<command-name>/model</command-name>\n<command-message>model</command-message>\n<command-args></command-args>"}, promptId="p2"),
            {"type": "ai-title", "aiTitle": "修改 a.py", "sessionId": "sess-1"},
        ]
        write_jsonl(self.claude_home / "projects" / "E--项目-示例" / "sess-1.jsonl", rows, raw_lines=["{broken json"])
        write_jsonl(self.claude_home / "projects" / "top-level.jsonl", rows[:3])  # not inside a project folder
        write_jsonl(self.claude_home / "outside.jsonl", rows[:3])
        (self.claude_home / ".credentials.json").write_text('{"token": "never-read"}', encoding="utf-8")

    def write_pi(self):
        def entry(kind, eid, parent, minute, **extra):
            return {"type": kind, "id": eid, "parentId": parent, "timestamp": at(minute), **extra}

        def msg(eid, parent, minute, message):
            return entry("message", eid, parent, minute, message=message)

        rows = [
            {"type": "session", "version": 3, "id": "pi-1", "timestamp": at(0), "cwd": CWD},
            entry("model_change", "m1", None, 0, provider="p", modelId="pi-model"),
            msg("a", "m1", 1, {"role": "user", "content": [{"type": "text", "text": "读取 b.py 然后运行测试"}]}),
            msg("b", "a", 2, {"role": "assistant", "stopReason": "toolUse", "content": [
                {"type": "thinking", "thinking": "**看看 b.py**", "thinkingSignature": "SECRET-SIGNATURE"},
                {"type": "toolCall", "id": "call|1", "name": "read", "arguments": {"path": "b.py"}}]}),
            msg("z", "b", 2, {"role": "assistant", "content": [{"type": "text", "text": "被放弃的分支"}]}),
            msg("c", "b", 3, {"role": "toolResult", "toolCallId": "call|1", "toolName": "read", "isError": False,
                              "content": [{"type": "text", "text": "print('b')"}]}),
            msg("d", "c", 4, {"role": "assistant", "stopReason": "toolUse", "content": [
                {"type": "toolCall", "id": "call|2", "name": "bash", "arguments": {"command": "pytest -q"}},
                {"type": "toolCall", "id": "call|3", "name": "edit", "arguments": {"path": "b.py", "edits": [{"oldText": "b", "newText": "c"}]}}]}),
            msg("e", "d", 5, {"role": "toolResult", "toolCallId": "call|2", "toolName": "bash", "isError": True,
                              "content": [{"type": "text", "text": "1 failed"}]}),
            msg("e2", "e", 5, {"role": "toolResult", "toolCallId": "call|3", "toolName": "edit", "isError": False,
                               "details": {"diff": "-b\n+c"}, "content": [{"type": "text", "text": "Successfully replaced"}]}),
            msg("f", "e2", 6, {"role": "assistant", "stopReason": "stop", "content": [{"type": "text", "text": "测试失败，已修改。"}]}),
        ]
        write_jsonl(self.pi_home / "sessions" / "--E--项目-示例--" / "2026-10-01T00-00-00-000Z_pi-1.jsonl", rows)
        (self.pi_home / "auth.json").write_text('{"key": "never-read"}', encoding="utf-8")


class ClaudeCodeSourceTests(SourceFixture):
    def test_lists_only_real_session_files(self):
        sessions, warning = self.claude.list_sessions()
        self.assertIsNone(warning)
        self.assertEqual([s["id"] for s in sessions], ["claude:sess-1"])
        s = sessions[0]
        self.assertEqual((s["title"], s["project"], s["source"], s["sourceLabel"], s["model"]),
                         ("修改 a.py", "示例", "claude", "Claude Code", "claude-test"))
        self.assertEqual(s["cwd"], CWD)

    def test_events_pairings_and_hidden_content(self):
        result = self.claude.load("claude:sess-1")
        events = result["events"]
        by_type = {}
        for e in events:
            by_type.setdefault(e["type"], []).append(e)
        self.assertEqual([t["id"] for t in result["turns"]], ["p1", "p2"])
        self.assertEqual([e["title"] for e in by_type["userMessage"]], ["请读取并修改 a.py", "/model"])
        read, bash = [e for e in by_type["commandExecution"] if e["title"].startswith("读取")][0], by_type["commandExecution"][-1]
        self.assertEqual(read["label"], "读取文件")
        self.assertIn("print(1)", self.claude.detail("claude:sess-1", read["id"])["output"])
        self.assertTrue(bash["error"])
        self.assertEqual(bash["exitCode"], 1)
        edit = by_type["fileChange"][0]
        self.assertFalse(edit["error"])
        self.assertIn("+ print(2)", self.claude.detail("claude:sess-1", edit["id"])["input"])
        tool = by_type["mcpToolCall"][0]
        self.assertEqual(tool["status"], "inProgress")  # no result recorded: not invented
        final = [e for e in by_type["agentMessage"]][0]
        self.assertEqual((final["label"], final["answerPhase"]), ("最终答复", "final"))
        thought = by_type["reasoning"][0]
        self.assertFalse(thought["hasReadableText"])
        self.assertNotIn("SECRET-SIGNATURE", json.dumps(result["events"], ensure_ascii=False))
        self.assertNotIn("SECRET-SIGNATURE", json.dumps(self.claude.detail("claude:sess-1", thought["id"]), ensure_ascii=False))

    def test_skips_noise_and_reports_it(self):
        result = self.claude.load("claude:sess-1")
        text = json.dumps(result["events"], ensure_ascii=False)
        for hidden in ("子代理内部", "重复记录", "local-command", "caveat"):
            self.assertNotIn(hidden, text)
        self.assertTrue(any("子代理" in w for w in result["warnings"]))
        self.assertTrue(any("无法解析" in w for w in result["warnings"]))

    def test_analysis_links_files_and_commands(self):
        analysis = self.claude.load("claude:sess-1")["analysis"]
        kinds = {e["kind"] for e in analysis["graph"]["edges"]}
        self.assertTrue({"reads", "writes", "returns"} <= kinds)
        files = [n["label"] for n in analysis["graph"]["nodes"] if n["type"] == "file"]
        self.assertEqual(files, ["a.py"])
        statements = {c["kind"] for c in analysis["cards"]}
        self.assertTrue({"read", "edit", "request"} <= statements)

    def test_unknown_session_and_missing_home(self):
        with self.assertRaises(KeyError):
            self.claude.load("claude:nope")
        empty = ClaudeCodeSource(self.root / "does-not-exist")
        self.assertEqual(empty.list_sessions(), ([], None))
        self.assertFalse(empty.info()["available"])


class PiSourceTests(SourceFixture):
    def test_lists_session_from_header(self):
        sessions, _ = self.pi.list_sessions()
        self.assertEqual([s["id"] for s in sessions], ["pi:pi-1"])
        s = sessions[0]
        self.assertEqual((s["title"], s["project"], s["model"], s["sourceLabel"]), ("读取 b.py 然后运行测试", "示例", "pi-model", "pi agent"))

    def test_active_branch_pairing_and_diff(self):
        result = self.pi.load("pi:pi-1")
        text = json.dumps(result["events"], ensure_ascii=False)
        self.assertNotIn("被放弃的分支", text)
        self.assertNotIn("SECRET-SIGNATURE", text)
        self.assertTrue(any("分支" in w for w in result["warnings"]))
        by_type = {}
        for e in result["events"]:
            by_type.setdefault(e["type"], []).append(e)
        self.assertEqual(len(result["turns"]), 1)
        self.assertEqual(by_type["reasoning"][0]["title"], "**看看 b.py**")
        read = by_type["commandExecution"][0]
        self.assertEqual(self.pi.detail("pi:pi-1", read["id"])["output"], "print('b')")
        bash = by_type["commandExecution"][1]
        self.assertTrue(bash["error"])
        edit = by_type["fileChange"][0]
        self.assertEqual(self.pi.detail("pi:pi-1", edit["id"])["input"].split("\n", 1)[1], "-b\n+c")
        final = by_type["agentMessage"][0]
        self.assertEqual(final["answerPhase"], "final")

    def test_detail_by_event_id_with_pipe_characters(self):
        result = self.pi.load("pi:pi-1")
        read = next(e for e in result["events"] if e["type"] == "commandExecution")
        self.assertEqual(read["id"], "call|1")
        self.assertEqual(self.pi.detail("pi:pi-1", "call|1", read["turnId"])["title"], "读取 b.py")


class CatalogTests(SourceFixture):
    def setUp(self):
        super().setUp()
        self.codex_home = self.root / "codex"
        self.codex_home.mkdir()
        self.catalog = Catalog([HistoryStore(self.codex_home), self.claude, self.pi])

    def test_merges_sources_and_routes_by_prefix(self):
        sessions, _ = self.catalog.list_sessions()
        self.assertEqual({s["source"] for s in sessions}, {"claude", "pi"})
        self.assertEqual(self.catalog.load("pi:pi-1")["session"]["sourceLabel"], "pi agent")
        self.assertEqual(self.catalog.load("claude:sess-1")["session"]["sourceLabel"], "Claude Code")
        with self.assertRaises(KeyError):
            self.catalog.load("unprefixed-codex-id")
        info = self.catalog.info()
        self.assertEqual([s["id"] for s in info["sources"]], ["codex", "claude", "pi"])

    def test_http_serves_prefixed_ids_and_hides_private_paths(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler_for(self.catalog))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)

        def get(path):
            conn = http.client.HTTPConnection("127.0.0.1", server.server_port)
            conn.request("GET", path)
            res = conn.getresponse()
            body = res.read()
            conn.close()
            return res.status, json.loads(body)

        status, listing = get("/api/sessions")
        self.assertEqual(status, 200)
        self.assertNotIn("_path", json.dumps(listing))
        self.assertNotIn(str(self.claude_home), json.dumps(listing))
        status, data = get("/api/sessions/" + quote("claude:sess-1", safe=""))
        self.assertEqual((status, data["session"]["originator"]), (200, "Claude Code"))
        status, detail = get("/api/sessions/" + quote("pi:pi-1", safe="") + "/items/" + quote("call|1", safe="") + "?turn=" + quote(data["turns"][0]["id"]))
        self.assertEqual(status, 404)  # that turn id belongs to the Claude session, not to pi
        status, pi_data = get("/api/sessions/" + quote("pi:pi-1", safe=""))
        status, detail = get("/api/sessions/" + quote("pi:pi-1", safe="") + "/items/" + quote("call|1", safe="") + "?turn=" + quote(pi_data["turns"][0]["id"]))
        self.assertEqual(status, 200)
        self.assertNotIn("never-read", json.dumps([listing, data, pi_data, detail]))


if __name__ == "__main__":
    unittest.main()


class DeepSeekHarnessSourceTests(unittest.TestCase):
    def setUp(self):
        import os
        import time
        self.tmp = tempfile.TemporaryDirectory(prefix="codex_trace_dsh_")
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        folder = self.home / "sessions" / "--E-项目-示例--" / "session-d1"
        t0 = 1790000000000

        def ev(kind, seq, data, offset=0):
            return {"type": kind, "seq": seq, "time": t0 + offset * 1000, "data": data}

        def call(cid, name, args):
            return {"type": "tool-call", "id": cid, "name": name, "arguments": json.dumps(args)}

        def result(cid, text, error=False):
            return {"role": "tool", "toolCallId": cid, "content": [{"type": "text", "text": text}], "isError": error}

        self.rows = [
            {"type": "session", "version": 4, "id": "session-d1", "createdAt": t0, "cwd": CWD},
            ev("model/selection", 1, {"provider": "p", "model": "ds-test"}),
            ev("turn/start", 2, {"turn": 1}, 1),
            ev("user/message", 2, {"content": [{"type": "text", "text": "The approval policy changed."}], "source": {"kind": "user-approval"}, "id": "n1"}, 1),
            ev("user/message", 3, {"content": [{"type": "text", "text": "读取并修改 a.py"}], "source": {"kind": "user"}, "role": "user", "id": "u1"}, 1),
            ev("session/title", 4, {"title": "修改 a.py", "source": {"kind": "fallback"}}, 1),
            {"type": "reasoning-chunks", "seq0": 5, "data": {"texts": ["流式碎片"]}},
            {"type": "assistant/chunk", "seq": 6, "data": {"chunk": {"type": "block-start"}}},
            ev("assistant/message", 7, {"turn": 1, "step": 1, "message": {"role": "assistant", "content": [
                {"type": "reasoning", "text": "先读文件"}, call("c1", "read", {"file_path": CWD + r"\a.py"})]}}, 2),
            ev("tool/call", 8, {"turn": 1, "step": 1, "callId": "c1", "name": "read", "arguments": "{}"}, 2),
            ev("tool/result", 9, {"turn": 1, "step": 1, "message": result("c1", "print(1)")}, 3),
            ev("assistant/message", 10, {"turn": 1, "step": 2, "message": {"role": "assistant", "content": [
                call("c2", "edit", {"file_path": CWD + r"\a.py", "old_string": "print(1)", "new_string": "print(2)"}),
                call("c3", "pwsh", {"command": "python -m unittest"}),
                call("c4", "spawn_teammate", {"name": "helper", "prompt": "帮忙检查"})]}}, 4),
            ev("tool/result", 11, {"turn": 1, "step": 2, "message": result("c2", "ok")}, 5),
            ev("tool/result", 12, {"turn": 1, "step": 2, "message": result("c3", "FAILED", error=True)}, 6),
            ev("team/member", 13, {"version": 2, "teamId": "t", "member": {"id": "child-1", "name": "helper"}}, 7),
            ev("assistant/message", 14, {"turn": 1, "step": 3, "message": {"role": "assistant", "content": [{"type": "text", "text": "已完成。"}]}}, 8),
            ev("turn/end", 15, {"turn": 1, "reason": {"kind": "completed"}}, 9),
            ev("turn/start", 16, {"turn": 2}, 10),
            ev("user/message", 17, {"content": [{"type": "text", "text": "继续"}], "source": {"kind": "user"}, "role": "user", "id": "u2"}, 10),
        ]
        self.folder = folder
        write_jsonl(folder / "session.v4.jsonl", self.rows, raw_lines=["{broken"])
        write_jsonl(folder / "session.jsonl", self.rows[:1] + [ev("session/title", 1, {"title": "旧代内容"})])  # older generation
        child = self.home / "sessions" / "--E-项目-示例--" / "child-1"
        write_jsonl(child / "session.v4.jsonl", [{"type": "session", "version": 4, "id": "child-1", "createdAt": t0, "cwd": CWD},
                                                  ev("subagent/descriptor", 0, {"label": "检查 a.py"}),
                                                  ev("user/message", 1, {"content": [{"type": "text", "text": "检查"}], "source": {"kind": "user"}, "id": "cu"})])
        old = time.time() - 3600
        os.utime(folder / "session.v4.jsonl", (old, old))
        from trace_viewer.dsh_source import DeepSeekHarnessSource
        self.source = DeepSeekHarnessSource(self.home)

    def test_lists_latest_generation_only(self):
        sessions, warning = self.source.list_sessions()
        self.assertIsNone(warning)
        by_id = {s["id"]: s for s in sessions}
        self.assertEqual(set(by_id), {"dsh:session-d1", "dsh:child-1"})
        self.assertEqual((by_id["dsh:session-d1"]["title"], by_id["dsh:session-d1"]["model"], by_id["dsh:session-d1"]["source"]),
                         ("修改 a.py", "ds-test", "dsh"))
        self.assertEqual(by_id["dsh:child-1"]["title"], "子代理：检查 a.py")

    def test_events_turns_and_agent_link(self):
        result = self.source.load("dsh:session-d1")
        text = json.dumps(result["events"], ensure_ascii=False)
        self.assertNotIn("流式碎片", text)
        self.assertEqual([(t["id"], t["status"]) for t in result["turns"]], [("turn-1", "completed"), ("turn-2", "unknown")])
        by_type = {}
        for e in result["events"]:
            by_type.setdefault(e["type"], []).append(e)
        self.assertEqual([e["title"] for e in by_type["userMessage"]], ["读取并修改 a.py", "继续"])  # the approval notice is not a request
        self.assertEqual(by_type["reasoning"][0]["title"], "先读文件")
        read = by_type["commandExecution"][0]
        self.assertEqual((read["label"], self.source.detail("dsh:session-d1", read["id"])["output"]), ("读取文件", "print(1)"))
        self.assertTrue(by_type["commandExecution"][1]["error"])
        self.assertFalse(by_type["fileChange"][0]["error"])
        spawn = by_type["collabAgentToolCall"][0]
        self.assertEqual(spawn["agents"], ["dsh:child-1"])
        final = by_type["agentMessage"][0]
        self.assertEqual((final["label"], final["answerPhase"]), ("最终答复", "final"))
        self.assertTrue(any("无法解析" in w for w in result["warnings"]))

    def test_compressed_logs_need_a_decoder_and_say_so(self):
        import sys
        from unittest import mock
        (self.folder / "session.v4.jsonl").rename(self.folder / "session.v4.jsonl.zstd")  # not valid zstd: only the name matters here
        from trace_viewer.dsh_source import DeepSeekHarnessSource
        with mock.patch.dict(sys.modules, {"zstandard": None, "compression": None, "compression.zstd": None}):
            sessions, warning = DeepSeekHarnessSource(self.home).list_sessions()
        self.assertEqual([s["id"] for s in sessions], ["dsh:child-1"])
        self.assertIn("zstandard", warning)

    def test_zstd_frames_with_a_torn_tail(self):
        try:
            import zstandard
        except ImportError:
            self.skipTest("zstandard is optional")
        plain = (self.folder / "session.v4.jsonl")
        frames = b"".join(zstandard.ZstdCompressor().compress((json.dumps(r, ensure_ascii=False) + "\n").encode("utf-8")) for r in self.rows)
        torn = zstandard.ZstdCompressor().compress(b'{"type":"user/message"}\n')[:-3]
        plain.unlink()
        (self.folder / "session.v4.jsonl.zstd").write_bytes(frames + torn)
        from trace_viewer.dsh_source import DeepSeekHarnessSource
        source = DeepSeekHarnessSource(self.home)
        result = source.load("dsh:session-d1")
        self.assertEqual(len(result["turns"]), 2)
        self.assertTrue(any("尚未写完" in w for w in result["warnings"]))
