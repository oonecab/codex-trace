import http.client
import json
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from http.server import ThreadingHTTPServer

from trace_viewer.__main__ import handler_for
from trace_viewer.normalize import normalize, public_event, statistics
from trace_viewer.store import HistoryStore


class DatabaseFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="codex_trace_test_")
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        state = sqlite3.connect(self.home / "state_5.sqlite")
        state.executescript("CREATE TABLE threads(id TEXT PRIMARY KEY, title TEXT, name TEXT, cwd TEXT, model TEXT, updated_at INT, created_at INT, archived INT, rollout_path TEXT, originator TEXT, history_mode TEXT);")
        state.execute("INSERT INTO threads VALUES(?,?,?,?,?,?,?,?,?,?,?)", ("thread-a", "中文 <script>测试</script>", None, r"\\?\E:\项目\示例", "example-model", 1700000001, 1700000000, 0, None, "Codex Desktop", "paginated"))
        state.commit(); state.close()
        hist = sqlite3.connect(self.home / "thread_history_1.sqlite")
        hist.executescript("""
          CREATE TABLE thread_turns(thread_id TEXT,turn_id TEXT,rollout_ordinal INT,status TEXT,started_at INT,completed_at INT,duration_ms INT,error_json TEXT);
          CREATE TABLE thread_items(thread_id TEXT,turn_id TEXT,item_id TEXT,rollout_ordinal INT,created_at_ms INT,item_json TEXT,item_type TEXT,started_at_ms INT,completed_at_ms INT);
        """)
        hist.execute("INSERT INTO thread_turns VALUES(?,?,?,?,?,?,?,?)", ("thread-a", "turn-a", 0, "completed", 1700000000, 1700000002, 2000, None))
        items = [
            {"type":"userMessage","id":"user","content":[{"type":"text","text":"检查中文路径"}]},
            {"type":"commandExecution","id":"cmd","command":"python 测试.py","aggregatedOutput":"测试通过 <img src=x onerror=alert(1)>","exitCode":0,"durationMs":1300,"status":"completed"},
            {"type":"fileChange","id":"edit","changes":[{"path":"E:/项目/测试.py","diff":"+中文"}],"status":"completed"},
            {"type":"reasoning","id":"think","summary":[],"content":["nonpublic test fixture"],"encrypted_content":"opaque"},
            {"type":"mcpToolCall","id":"mcp","tool":"read","arguments":{},"result":{"isError":True,"content":[{"type":"text","text":"读取失败"}]}},
            {"type":"subAgentActivity","id":"activity","agentThreadId":"child","kind":"completed"},
            {"type":"futureEvent","id":"future","text":"未来事件也保留"},
        ]
        for i,item in enumerate(items):
            hist.execute("INSERT INTO thread_items VALUES(?,?,?,?,?,?,?,?,?)",("thread-a","turn-a",item["id"],i,1700000000000+i*100,json.dumps(item,ensure_ascii=False),item["type"],1700000000000+i*100,1700000000100+i*100))
        hist.commit();hist.close()
        self.store=HistoryStore(self.home)

    def test_reads_unicode_preserves_source_and_statistics(self):
        r=self.store.load("thread-a")
        self.assertEqual(r["session"]["cwd"],r"E:\项目\示例")
        self.assertEqual(r["session"]["project"],"示例")
        self.assertEqual(r["stats"]["toolCalls"],3)
        self.assertEqual(r["stats"]["errors"],1)
        self.assertEqual(r["stats"]["files"],1)
        self.assertEqual(r["turns"][0]["startedAt"],1700000000000)
        self.assertEqual(self.store.detail("thread-a","cmd")["output"],"测试通过 <img src=x onerror=alert(1)>")
        self.assertEqual(r["events"][-1]["category"],"other")
        self.assertNotIn("_detail",public_event(r["events"][1]))

    def test_connection_is_read_only(self):
        con=self.store.connect(self.store.state)
        self.addCleanup(con.close)
        with self.assertRaises(sqlite3.OperationalError):
            con.execute("UPDATE threads SET title='changed'")

    def test_no_invented_thoughts_or_exposure_of_opaque_content(self):
        d=self.store.detail("thread-a","think")
        self.assertEqual(d["body"],"")
        self.assertFalse(d["hasReadableText"])
        self.assertNotIn("nonpublic test fixture",json.dumps(d))
        self.assertNotEqual(d["raw"]["encrypted_content"],"opaque")
        self.assertNotIn("nonpublic test fixture",json.dumps(self.store.load("thread-a")["analysis"]))

    def test_missing_thread_and_item(self):
        with self.assertRaises(KeyError):self.store.load("../../auth.json")
        with self.assertRaises(KeyError):self.store.detail("thread-a","missing")

    def test_api_origin_boundary_and_no_arbitrary_file_route(self):
        server=ThreadingHTTPServer(("127.0.0.1",0),handler_for(self.store))
        worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
        self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        def get(path,headers=None):
            conn=http.client.HTTPConnection("127.0.0.1",server.server_port)
            conn.request("GET",path,headers=headers or {})
            res=conn.getresponse();status=res.status;body=res.read();conn.close();return status,json.loads(body)
        self.assertEqual(get("/api/sessions")[0],200)
        status,session=get("/api/sessions/thread-a")
        self.assertEqual(status,200)
        self.assertEqual(len(session["analysis"]["cards"]),len(session["events"]))
        self.assertNotIn("_detail",json.dumps(session["analysis"]))
        self.assertTrue(any(e["kind"]=="writes" for e in session["analysis"]["graph"]["edges"]))
        self.assertEqual(get("/api/sessions/thread-a/items/cmd?turn=turn-a")[1]["output"],"测试通过 <img src=x onerror=alert(1)>")
        self.assertEqual(get("/api/sessions",{"Origin":"https://foreign.example"})[0],403)
        self.assertEqual(get("/api/sessions",{"Host":"foreign.example"})[0],403)
        self.assertEqual(get("/../../auth.json")[0],404)
        self.assertEqual(get("/api/sessions/thread-a")[1]["fingerprint"],session["fingerprint"])
        conn=http.client.HTTPConnection("127.0.0.1",server.server_port)
        for asset in ("/style.css","/theme.css","/app.js","/process.js"):
            conn.request("GET",asset);res=conn.getresponse();res.read();self.assertEqual(res.status,200,asset)
        conn.close()
        self.assertEqual(get("/api/sessions/%27%20OR%201=1--")[0],404)

    def test_refresh_reads_new_events_without_writing_source(self):
        first=self.store.load("thread-a")
        con=sqlite3.connect(self.home/"thread_history_1.sqlite")
        item={"type":"agentMessage","id":"final","text":"新事件","phase":"final"}
        con.execute("INSERT INTO thread_items VALUES(?,?,?,?,?,?,?,?,?)",("thread-a","turn-a","final",99,1700000010000,json.dumps(item),"agentMessage",None,None));con.commit();con.close()
        second=self.store.load("thread-a",refresh=True)
        self.assertEqual(len(second["events"]),len(first["events"])+1)
        self.assertEqual(len(second["analysis"]["cards"]),len(first["analysis"]["cards"])+1)
        self.assertEqual(second["analysis"]["cards"][-1]["kind"],"final")


class RolloutTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix="trace_rollout_");self.addCleanup(self.temp.cleanup)
        self.home=Path(self.temp.name);self.folder=self.home/"sessions/2026/10/07";self.folder.mkdir(parents=True)
        self.path=self.folder/"rollout-sample.jsonl"
    def write(self,rows,tail=""):
        meta={"type":"session_meta","payload":{"id":"rollout-id","cwd":"E:/中文项目","timestamp":"2026-10-07T01:00:00Z"}}
        self.path.write_text("\n".join(json.dumps(r,ensure_ascii=False) for r in [meta,*rows])+"\n"+tail,encoding="utf-8")
    def test_modern_items_not_duplicated_by_response_item(self):
        event={"type":"event_msg","timestamp":"2026-10-07T01:00:02Z","payload":{"type":"item_completed","turn_id":"t","item":{"type":"CommandExecution","id":"cmd","command":["powershell","-Command","Write-Output 中文"],"aggregated_output":"中文","exit_code":0,"duration":{"secs":1,"nanos":250000000}}}}
        self.write([{"type":"event_msg","payload":{"type":"task_started","turn_id":"t"}},event,event,{"type":"response_item","payload":{"type":"function_call","call_id":"same","name":"exec_command","arguments":"{}"}}],'{"unfinished":')
        r=HistoryStore(self.home).load("rollout-id")
        self.assertEqual(len(r["events"]),1)
        self.assertEqual(r["events"][0]["durationMs"],1250)
        self.assertEqual(r["events"][0]["_detail"]["output"],"中文")
        self.assertEqual(len(r["warnings"]),1)
    def test_legacy_call_output_matching_and_incomplete_call(self):
        self.write([
            {"type":"response_item","timestamp":"2026-10-07T01:00:00Z","payload":{"type":"function_call","call_id":"c1","name":"exec_command","arguments":'{"cmd":"pytest"}'}},
            {"type":"response_item","timestamp":"2026-10-07T01:00:01Z","payload":{"type":"function_call","call_id":"c2","name":"some_tool","arguments":"{}"}},
            {"type":"response_item","timestamp":"2026-10-07T01:00:01Z","payload":{"type":"function_call","call_id":"c3","name":"pending_tool","arguments":"{}"}},
            {"type":"response_item","timestamp":"2026-10-07T01:00:02Z","payload":{"type":"function_call_output","call_id":"c2","output":"second finished first"}},
            {"type":"response_item","timestamp":"2026-10-07T01:00:03Z","payload":{"type":"function_call_output","call_id":"c1","output":"passed"}},
        ])
        r=HistoryStore(self.home).load("rollout-id")
        self.assertEqual(len(r["events"]),3)
        self.assertEqual(r["events"][0]["_detail"]["output"],"passed")
        self.assertEqual(r["events"][0]["durationMs"],3000)
        self.assertEqual(r["events"][1]["_detail"]["output"],"second finished first")
        self.assertEqual(r["events"][1]["durationMs"],1000)
        self.assertEqual(r["events"][2]["status"],"inProgress")
    def test_outside_home_is_not_opened(self):
        result=HistoryStore(self.home)._read_rollout(str(self.home.parent/"some-other-file"))
        self.assertEqual(result[0],[])
        self.assertTrue(result[2])

    def test_duplicate_legacy_calls_keep_correct_result_pairing(self):
        call={"type":"response_item","payload":{"type":"function_call","call_id":"c1","name":"exec_command","arguments":'{"cmd":"pytest"}'}}
        self.write([call,call,{"type":"response_item","payload":{"type":"function_call_output","call_id":"c1","output":"passed once"}}])
        events=HistoryStore(self.home).load("rollout-id")["events"]
        self.assertEqual(len(events),1)
        self.assertEqual(events[0]["_detail"]["output"],"passed once")

    def test_malformed_structures_do_not_hide_valid_events(self):
        self.write([None,[],{"type":"event_msg","payload":None},{"type":"event_msg","payload":{"type":"item_completed","turn_id":"t","item":None}},{"type":"event_msg","payload":{"type":"item_completed","turn_id":"t","item":{"id":"new","text":"new shape"}}}])
        result=HistoryStore(self.home).load("rollout-id")
        self.assertTrue(result["warnings"])
        self.assertEqual(len(result["events"]),1)
        self.assertEqual(result["events"][0]["type"],"unknown")


class NormalizeTests(unittest.TestCase):
    def test_mcp_preview_prioritizes_tool_result_over_server_name(self):
        e=normalize({"type":"mcpToolCall","id":"m","server":"browser","tool":"open","result":{"content":[{"type":"text","text":"页面已打开"}]},"arguments":{"url":"http://localhost"}},turn_id="t",ordinal=1)
        self.assertEqual(e["preview"],"页面已打开")
        self.assertEqual(e["_detail"]["body"],"browser")

    def test_new_item_types_register_a_handler_and_unknown_types_stay_visible(self):
        from trace_viewer import normalize as n
        self.addCleanup(n.HANDLERS.pop, "customStep", None)
        n.handles("customStep")(lambda item, label: {"title": "自定义 " + item["name"], "input": item["name"]})
        known = n.normalize({"type": "customStep", "id": "c", "name": "x"}, turn_id="t", ordinal=1)
        self.assertEqual((known["title"], known["category"]), ("自定义 x", "other"))
        unknown = n.normalize({"type": "neverSeenBefore", "id": "u", "text": "保留"}, turn_id="t", ordinal=2)
        self.assertEqual((unknown["title"], unknown["preview"]), ("neverSeenBefore", "保留"))

    def test_desktop_final_answer_phase_is_recognized(self):
        e=normalize({"type":"agentMessage","id":"f","phase":"final_answer","text":"完成"},turn_id="t",ordinal=1)
        self.assertEqual(e["label"],"最终答复")
        self.assertEqual(e["answerPhase"],"final")
        self.assertEqual(e["_detail"]["raw"]["phase"],"final_answer")

    def test_question_reply_readable_and_raw_preserved(self):
        raw='<send_user_message_question_reply>'+json.dumps([{"question":"选择形式？","answer":"本地工具"}],ensure_ascii=False)+'</send_user_message_question_reply>'
        e=normalize({"type":"userMessage","id":"u","content":[{"type":"text","text":raw}]},turn_id="t",ordinal=1)
        self.assertEqual(e["preview"],"选择形式？\n选择：本地工具")
        self.assertEqual(e["_detail"]["raw"]["content"][0]["text"],raw)

    def test_nonzero_exit_and_success_are_distinct(self):
        base={"type":"commandExecution","id":"c","command":"rg needle","exitCode":1}
        e=normalize(base,turn_id="t",ordinal=1)
        self.assertTrue(e["error"]);self.assertEqual(e["exitCode"],1)
        base["exitCode"]=0
        self.assertFalse(normalize(base,turn_id="t",ordinal=1)["error"])
    def test_summary_is_visible_and_only_public_summary_used(self):
        e=normalize({"type":"reasoning","id":"r","summary":["先检查文件，再验证结果"],"content":["not public"]},turn_id="t",ordinal=1)
        self.assertEqual(e["preview"],"先检查文件，再验证结果")
        self.assertNotIn("not public",json.dumps(e))
    def test_repeated_file_changes_count_distinct_paths(self):
        events=[normalize({"type":"fileChange","id":str(i),"changes":[{"path":"a.py"}]},turn_id="t",ordinal=i) for i in range(2)]
        self.assertEqual(statistics(events)["files"],1)
        self.assertEqual(statistics(events)["toolCalls"],2)


if __name__=="__main__":unittest.main()
