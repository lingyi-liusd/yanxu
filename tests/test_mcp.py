import json, os, pathlib, shutil, socket, subprocess, sys, tempfile, time, unittest
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
SERVER = ROOT / "server.py"
MCP = ROOT / "mcp-server.js"
NODE = shutil.which("node")

def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port

@unittest.skipUnless(NODE, "node is required for MCP tests")
class MCPCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="research-desk-mcp-")
        self.data_dir = pathlib.Path(self.tmp.name)
        self.port = free_port()
        env = os.environ.copy()
        env["RESEARCH_DESK_DATA_DIR"] = str(self.data_dir)
        env["PORT"] = str(self.port)
        self.server = subprocess.Popen([sys.executable, str(SERVER)], cwd=str(ROOT), env=env,
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deadline = time.time() + 5
        while time.time() < deadline:
            if self.server.poll() is not None:
                self.fail("isolated MCP test server exited before readiness")
            token_file = self.data_dir / "api-token"
            if token_file.exists():
                request = urllib.request.Request(f"http://127.0.0.1:{self.port}/api/state",
                    headers={"Authorization":"Bearer " + token_file.read_text().strip()})
                try:
                    with urllib.request.urlopen(request,timeout=.5) as response:
                        if response.status == 200: return
                except (OSError,ValueError):
                    pass
            time.sleep(0.05)
        self.fail("isolated MCP test server did not become ready")
    def tearDown(self):
        if getattr(self, "server", None) and self.server.poll() is None:
            self.server.terminate()
            self.server.wait(timeout=3)
        self.tmp.cleanup()

    def call(self, name, args):
        env = os.environ.copy()
        env["RESEARCH_DESK_DATA_DIR"] = str(self.data_dir)
        env["RESEARCH_DESK_BASE_URL"] = f"http://127.0.0.1:{self.port}"
        lines = [
            {"jsonrpc":"2.0","id":1,"method":"initialize","params":{}},
            {"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":name,"arguments":args}},
        ]
        proc = subprocess.run([NODE, str(MCP)], cwd=str(ROOT), env=env,
                              input="\n".join(json.dumps(x) for x in lines) + "\n",
                              text=True, capture_output=True, timeout=8)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        rows = [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]
        result = next(x for x in rows if x.get("id") == 2)["result"]
        text = result["content"][0]["text"]
        if result.get("isError"):
            return {"error": text}
        return json.loads(text)

    def test_project_tools_and_agent_history(self):
        out = self.call("research_project_upsert", {
            "id":"p1","name":"Agent Project","goal":"managed","stages":["Plan"]
        })
        self.assertTrue(out["ok"])
        history = self.call("research_history", {})
        self.assertEqual(history[0]["actor"], "agent")
        self.assertIn("Agent Project", history[0]["summary"])
    def test_project_delete_requires_confirm(self):
        self.call("research_project_upsert", {"id":"p1","name":"Delete Test"})
        out = self.call("research_project_delete", {"id":"p1","confirm":False})
        self.assertIn("confirm=true", out["error"])
        state = self.call("research_state", {})
        self.assertEqual(len(state["projects"]), 1)

    def test_project_delete_confirmed(self):
        self.call("research_project_upsert", {"id":"p1","name":"Delete Test"})
        out = self.call("research_project_delete", {"id":"p1","confirm":True})
        self.assertTrue(out["ok"])
        state = self.call("research_state", {})
        self.assertFalse(state["projects"])

    def test_batch_cannot_bypass_project_delete_confirmation(self):
        self.call("research_project_upsert", {"id":"p1","name":"Protected"})
        out = self.call("research_batch", {
            "ops":[{"collection":"projects","op":"delete","id":"p1"}]
        })
        self.assertIn("research_project_delete", out["error"])

    def test_agent_brief_contains_recent_agent_change(self):
        self.call("research_project_upsert", {"id":"p1","name":"Brief Test"})
        brief = self.call("research_agent_brief", {})
        self.assertEqual(brief["projects"][0]["name"], "Brief Test")
        self.assertTrue(brief["recentAgentChanges"])
        self.assertEqual(brief["recentAgentChanges"][0]["actor"], "agent")

if __name__ == "__main__":
    unittest.main(verbosity=2)
