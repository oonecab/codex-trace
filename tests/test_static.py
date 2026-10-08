"""Static front-end consistency checks. No browser and no third-party packages needed."""
import http.client
import re
import shutil
import subprocess
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

from trace_viewer.__main__ import STATIC, handler_for
from trace_viewer.store import HistoryStore


def read(name):
    return (STATIC / name).read_text(encoding="utf-8")


class StaticAssets(unittest.TestCase):
    def test_every_linked_asset_is_served(self):
        html = read("index.html")
        linked = re.findall(r'(?:href|src)="/([\w.\-]+)"', html)
        self.assertIn("style.css", linked)
        import tempfile
        with tempfile.TemporaryDirectory() as home:
            server = ThreadingHTTPServer(("127.0.0.1", 0), handler_for(HistoryStore(home)))
            threading.Thread(target=server.serve_forever, daemon=True).start()
            self.addCleanup(server.server_close)
            self.addCleanup(server.shutdown)
            conn = http.client.HTTPConnection("127.0.0.1", server.server_port)
            for name in sorted(set(linked)):
                conn.request("GET", "/" + name)
                res = conn.getresponse()
                res.read()
                self.assertEqual(res.status, 200, name)
            for hidden in ("/.hidden", "/..%2fTECH.md", "/static", "/a:b"):
                conn.request("GET", hidden)
                res = conn.getresponse()
                res.read()
                self.assertEqual(res.status, 404, hidden)
            conn.close()

    def test_script_element_ids_exist_in_html(self):
        html = read("index.html")
        ids = set(re.findall(r'id="([\w\-]+)"', html))
        used = set()
        for name in ("app.js", "process.js", "dropdown.js"):
            js = read(name)
            used |= set(re.findall(r'\$\("([\w\-]+)"\)', js))
            if name == "process.js":  # its own `get` helper; app.js calls `.get(` on URLSearchParams
                used |= set(re.findall(r'(?<![.\w])get\("([\w\-]+)"\)', js))
        # ids built from a prefix, e.g. get(name + "-view"), are covered by the view tabs below
        for view in ("process", "timeline", "graph"):
            used |= {view + "-view", "view-" + view}
        # created at runtime or only used behind a feature check
        self.assertEqual(sorted(used - ids), [])

    def test_css_variables_are_defined(self):
        css = "".join(read(n) for n in ("style.css", "theme.css"))
        defined = set(re.findall(r"(--[\w\-]+)\s*:", css))
        used = set(re.findall(r"var\((--[\w\-]+)", css))
        # set from JavaScript per element
        runtime = {"--event-color", "--phase-color"}
        self.assertEqual(sorted(used - defined - runtime), [])
        category_vars = {"--" + c for c in ("thinking", "command", "file", "tool", "message", "request", "agent",
                                            "context", "wait", "image", "other")}
        self.assertTrue(category_vars <= defined)

    def test_dark_palette_covers_every_light_token(self):
        css = read("theme.css")
        light = set(re.findall(r"(--(?:bg|bd|tx)-[\w]+)\s*:", css.split("@media")[0]))
        start = css.index(":root[data-theme=dark] {")
        dark_block = css[start:css.index("}", start)]
        missing = [t for t in light if t + ":" not in dark_block]
        self.assertEqual(missing, [])

    @unittest.skipUnless(shutil.which("node"), "node is only a development tool")
    def test_javascript_parses(self):
        for name in ("app.js", "process.js", "dropdown.js"):
            result = subprocess.run(["node", "--check", str(STATIC / name)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, name + "\n" + result.stderr)


if __name__ == "__main__":
    unittest.main()
