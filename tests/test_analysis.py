import copy
import unittest

from trace_viewer.analysis import build_analysis, path_key, test_reports
from trace_viewer.normalize import normalize


def event(kind, id_, ordinal=1, turn="t", **fields):
    return normalize({"type": kind, "id": id_, **fields}, turn_id=turn, ordinal=ordinal)


def command(id_="c", ordinal=1, turn="t", **fields):
    fields.setdefault("command", "python -m unittest discover -s tests -v")
    fields.setdefault("cwd", r"E:\项目")
    return event("commandExecution", id_, ordinal, turn, **fields)


def analyse(*events):
    turns = [{"id": t} for t in dict.fromkeys(e["turnId"] for e in events)]
    return build_analysis(list(events), turns, session_id="s", cwd=r"E:\项目")


class CardTests(unittest.TestCase):
    def test_shell_wrapper_and_multiline_commands(self):
        e=command(command='"C:\\Program Files\\PowerShell\\pwsh.exe" -Command "& \'C:\\Python\\python.exe\' -m unittest discover\nnode --check app.js"', aggregatedOutput="Ran 17 tests in 0.58s\n\nOK\n", exitCode=0)
        c=analyse(e)["cards"][0]
        self.assertEqual(c["kind"],"test")
        self.assertIn("check",c["operations"])
        self.assertEqual(c["testOutcome"],"passed")
        self.assertEqual(c["testReports"][0]["total"],17)

    def test_printed_test_commands_and_here_strings_are_not_execution(self):
        for script in ["Write-Output 'pytest test_a.py'", 'echo "python -m unittest"', "@'\npytest test_a.py\npython -m unittest\n'@ | python", 'python -c "print(\'pytest test_a.py\')"', '# pytest test_a.py']:
            with self.subTest(script=script):
                c=analyse(command(command=script,aggregatedOutput="Ran 8 tests in 1.0s\n\nOK\n"))["cards"][0]
                self.assertFalse(c["testCommands"])
                self.assertFalse(c["testReports"])

    def test_collection_and_help_do_not_count_as_test_runs(self):
        for script in ["pytest --collect-only", "python -m unittest --help"]:
            c=analyse(command(command=script))["cards"][0]
            self.assertFalse(c["testCommands"])

    def test_zero_exit_does_not_invent_passing_tests(self):
        c=analyse(command(exitCode=0,aggregatedOutput="nothing here"))["cards"][0]
        self.assertEqual(c["testOutcome"],"unreported")
        self.assertEqual(c["resultLabel"],"命令退出 0")

    def test_success_report_and_nonzero_exit_remain_distinct(self):
        c=analyse(command(exitCode=1,aggregatedOutput="Ran 3 tests in 1.0s\n\nOK\n"))["cards"][0]
        self.assertEqual(c["testOutcome"],"passed")
        self.assertTrue(c["attention"])
        self.assertIn("整条命令退出 1",c["resultLabel"])

    def test_reported_failure_survives_zero_exit_of_compound_command(self):
        c=analyse(command(exitCode=0,aggregatedOutput="Ran 3 tests in 1.0s\n\nFAILED (failures=1)\n"))["cards"][0]
        self.assertEqual(c["testOutcome"],"failed")
        self.assertTrue(c["attention"])

    def test_pytest_summary_and_ansi(self):
        reports=test_reports("\x1b[32m================ 2 passed, 1 skipped in 0.02s ================\x1b[0m\n")
        self.assertEqual(len(reports),1)
        self.assertEqual(reports[0]["status"],"passed")
        self.assertIn("1 项跳过",reports[0]["label"])
        self.assertEqual(test_reports("================ 1 failed, 2 passed in 1.2s ================\n")[0]["status"],"failed")

    def test_unittest_skips_are_visible(self):
        r=test_reports("Ran 5 tests in 0.5s\n\nOK (skipped=2)\n")[0]
        self.assertIn("skipped=2",r["label"])

    def test_literal_read_paths_with_spaces_and_chinese(self):
        c=analyse(command(command="Get-Content -LiteralPath 'src/中文 文件.py','src/b.py' -TotalCount 20"))["cards"][0]
        self.assertEqual(c["kind"],"read")
        self.assertEqual({r["key"] for r in c["files"]},{"e:/项目/src/中文 文件.py","e:/项目/src/b.py"})

    def test_dynamic_paths_stay_unlinked(self):
        for script in ['Get-Content -LiteralPath "$env:TEMP/a.py"', 'Get-Content -LiteralPath (Join-Path $base a.py)', 'cat ~/file.py']:
            c=analyse(command(command=script))["cards"][0]
            self.assertEqual(c["files"],[])

    def test_here_string_mask_does_not_leak_into_display(self):
        c=analyse(command(command="@'\nprint('hello')\n'@ | python"))["cards"][0]
        self.assertEqual(c["title"],"python")

    def test_cwd_case_and_slash_normalization(self):
        self.assertEqual(path_key(r"src\..\Cache.py",r"E:\项目"),path_key("e:/项目/cache.py"))
        self.assertNotEqual(path_key("/repo/A.py"),path_key("/repo/a.py"))
        self.assertIsNone(path_key("src/a.py"))
        self.assertIsNone(path_key("C:a.py",r"E:\项目"))
        self.assertEqual(path_key(r"\src\a.py",r"E:\项目"),"e:/src/a.py")

    def test_statements_are_not_promoted_to_observed_success(self):
        e=event("agentMessage","m",text="已完成修复，测试通过",phase="final_answer")
        r=analyse(e);c=r["cards"][0]
        self.assertEqual(c["sourceKind"],"statement")
        self.assertEqual(c["statementHint"],"结果措辞")
        self.assertFalse(c["hasResult"])
        self.assertEqual(r["turns"][0]["testPassed"],0)

    def test_unknown_and_private_reasoning_are_not_interpreted(self):
        r=analyse(event("futureEvent","u",text="opaque"),event("reasoning","r",content=["secret thought"],summary=[]))
        self.assertEqual(r["cards"][0]["kind"],"other")
        self.assertNotIn("secret thought",str(r))
        self.assertFalse(r["cards"][1]["readable"])


class GraphTests(unittest.TestCase):
    def test_changed_shell_directory_disables_relative_links_and_repeat_matching(self):
        script="Set-Location subdir; Get-Content -LiteralPath a.py; python -m unittest"
        r=analyse(command("a",1,command=script),command("b",2,command=script))
        self.assertFalse(r["cards"][0]["files"])
        self.assertFalse(r["turns"][0]["testSeries"])
        self.assertEqual(r["turns"][0]["testCalls"],2)

    def test_summary_counts_mixed_operation_entries_once(self):
        r=analyse(command("r",1,command="Get-Content -LiteralPath a.py; rg token .; dir"),command("c",2,command="node --check app.js; npm run build"))
        self.assertIn("读取 / 检索 1 项操作",r["turns"][0]["summary"])
        self.assertIn("1 次检查 / 构建",r["turns"][0]["summary"])
        self.assertEqual(r["turns"][0]["operationCount"],2)

    def test_graph_has_valid_unique_ids_and_does_not_mutate_source(self):
        events=[event("userMessage","u",0,content=[]),command(exitCode=0),event("fileChange","f",2,status="completed",changes=[{"path":"src/a.py"}])]
        original=copy.deepcopy(events)
        a=analyse(*events);b=analyse(*events)
        self.assertEqual(a,b)
        self.assertEqual(events,original)
        ids=[n["id"] for n in a["graph"]["nodes"]]
        self.assertEqual(len(ids),len(set(ids)))
        edge_ids=[e["id"] for e in a["graph"]["edges"]]
        self.assertEqual(len(edge_ids),len(set(edge_ids)))
        for edge in a["graph"]["edges"]:
            self.assertIn(edge["source"],ids);self.assertIn(edge["target"],ids)

    def test_repeat_is_scoped_to_same_turn_command_and_cwd(self):
        r=analyse(command("a",1),command("b",2),command("c",3,command="python -m unittest other"),command("d",4,cwd="E:/other"),command("e",5,turn="other"))
        edges=[e for e in r["graph"]["edges"] if e["kind"]=="same_test_command"]
        self.assertEqual(len(edges),1)
        self.assertEqual(edges[0]["basis"],"rule")

    def test_changes_between_tests_do_not_become_causal_edges(self):
        r=analyse(command("a",1,exitCode=1),event("fileChange","f",2,status="completed",changes=[{"path":"unrelated.md"}]),command("b",3,exitCode=0))
        repeated=next(e for e in r["graph"]["edges"] if e["kind"]=="same_test_command")
        self.assertEqual(len(repeated["interveningEdits"]),1)
        self.assertFalse({e["kind"] for e in r["graph"]["edges"]}&{"fixes","supports","causes","contradicts"})
        self.assertEqual(r["turns"][0]["testUnreported"],2)

    def test_same_filename_in_different_directories_is_not_merged(self):
        r=analyse(event("fileChange","a",1,status="completed",changes=[{"path":"one/main.py"},{"path":"two/main.py"}]))
        self.assertEqual(len([n for n in r["graph"]["nodes"] if n["type"]=="file"]),2)

    def test_read_and_write_link_same_canonical_file(self):
        r=analyse(command("r",1,command="Get-Content -LiteralPath 'src/Cache.py'"),event("fileChange","w",2,status="completed",changes=[{"path":r"E:\项目\src\cache.py"}]))
        self.assertEqual(len([n for n in r["graph"]["nodes"] if n["type"]=="file"]),1)
        self.assertTrue({"reads","writes"}<={e["kind"] for e in r["graph"]["edges"]})

    def test_failed_edit_is_an_attempt_not_a_completed_write(self):
        r=analyse(event("fileChange","e",1,status="failed",changes=[{"path":"a.py"}]))
        self.assertIn("write_attempt",{e["kind"] for e in r["graph"]["edges"]})
        self.assertEqual(r["turns"][0]["writtenFiles"],0)

    def test_subagent_has_explicit_session_reference(self):
        r=analyse(event("collabAgentToolCall","a",1,tool="spawn",receiverThreadIds=["child"]))
        n=next(n for n in r["graph"]["nodes"] if n["type"]=="agent")
        self.assertEqual(n["sessionId"],"child")

    def test_order_uses_record_ordinal_not_completion_time(self):
        r=analyse(command("later",9),command("earlier",2))
        byid={c["id"]:c for c in r["cards"]}
        e=next(e for e in r["graph"]["edges"] if e["kind"]=="sequence")
        self.assertEqual(byid[e["source"]]["eventId"],"earlier")
        self.assertEqual(e["basis"],"order")

    def test_unrelated_statements_do_not_split_operation_stages(self):
        r=analyse(command("a",1,command="cat a.py"),event("agentMessage","m",2,text="接下来继续读取"),command("b",3,command="cat b.py"))
        stages=r["turns"][0]["stages"]
        self.assertEqual(len(stages),1)
        self.assertEqual(len(stages[0]["cardIds"]),2)

    def test_ids_are_stable_when_new_events_arrive(self):
        a=analyse(command("a",1));b=analyse(command("a",1),command("b",2))
        self.assertEqual(a["cards"][0]["id"],b["cards"][0]["id"])
        self.assertEqual(a["turns"][0]["stages"][0]["id"],b["turns"][0]["stages"][0]["id"])


if __name__=="__main__":
    unittest.main()
