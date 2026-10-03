import json, os, pathlib, socket, sqlite3, subprocess, sys, tempfile, time, unittest
import urllib.error, urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
SERVER = ROOT / "server.py"

def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port

class ServerCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="research-desk-test-")
        self.data_dir = pathlib.Path(self.tmp.name)
        self.port = free_port()
        env = os.environ.copy()
        env["RESEARCH_DESK_DATA_DIR"] = str(self.data_dir)
        env["PORT"] = str(self.port)
        env.pop("RESEARCH_FOCUS_API_URL", None)
        env.pop("RESEARCH_FOCUS_API_KEY", None)
        env.pop("RESEARCH_FOCUS_MODEL", None)
        self.proc = subprocess.Popen(
            [sys.executable, str(SERVER)],
            cwd=str(ROOT), env=env,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        self.base = f"http://127.0.0.1:{self.port}"
        self._wait_ready()
    def tearDown(self):
        if getattr(self, "proc", None) and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        if getattr(self, "tmp", None):
            self.tmp.cleanup()

    def _wait_ready(self):
        token_file = self.data_dir / "api-token"
        deadline = time.time() + 5
        while time.time() < deadline:
            if token_file.exists():
                self.token = token_file.read_text().strip()
                try:
                    code, _, _ = self.api("/api/state")
                    if code == 200:
                        return
                except Exception:
                    pass
            time.sleep(0.05)
        self.fail("server did not become ready")

    def api(self, path, body=None):
        payload = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(
            self.base + path, data=payload,
            headers={"Authorization": "Bearer " + self.token, "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=3) as res:
                return res.status, int(res.headers.get("X-Rev") or 0), json.loads(res.read())
        except urllib.error.HTTPError as exc:
            return exc.code, int(exc.headers.get("X-Rev") or 0), json.loads(exc.read())
    def create_project(self, pid="p1", name="Project"):
        code, rev, state = self.api("/api/state")
        self.assertEqual(code, 200)
        op = {"collection": "projects", "item": {"id": pid, "name": name, "goal": "", "stages": []}}
        code, rev, state = self.api("/api/action", {"ifRev": rev, "ops": [op]})
        self.assertEqual(code, 200)
        return rev, state

    def create_task(self, tid, title, project="p1", **extra):
        code, rev, _ = self.api("/api/state")
        item = {
            "id": tid, "project": project, "title": title, "priority": "P2",
            "status": "待开始", "stage": "", "start": "", "end": "",
            "completed": "", "milestone": False, "parent": "", "deps": [], "note": "",
        }
        item.update(extra)
        code, rev, state = self.api("/api/action", {
            "ifRev": rev, "ops": [{"collection": "tasks", "item": item}]
        })
        self.assertEqual(code, 200)
        return rev, state

    def test_brand_logo_is_served_without_api_token(self):
        with urllib.request.urlopen(self.base + "/", timeout=3) as response:
            page = response.read().decode("utf-8")
            self.assertIn('src="/assets/yanxu-logo.png"', page)
            self.assertIn('rel="icon" type="image/png" href="/assets/yanxu-logo.png"', page)
        with urllib.request.urlopen(self.base + "/assets/yanxu-logo.png", timeout=3) as response:
            self.assertEqual(response.headers.get_content_type(), "image/png")
            self.assertTrue(response.read().startswith(b"\x89PNG\r\n\x1a\n"))

    def test_persistent_connection_is_opt_in_human_only_and_read_only(self):
        self.create_project()
        _,rev_before,_=self.api('/api/state')
        code,_,state=self.api('/api/agent-connection?project_id=p1')
        self.assertEqual(code,200);self.assertFalse(state['configured']);self.assertFalse(state['connected'])
        code,_,agents=self.api('/api/agents?project_id=p1')
        self.assertIn('persistent',agents)
        with self.assertRaises(urllib.error.HTTPError):
            urllib.request.urlopen(self.base+'/api/agent-connection',timeout=3)
        self.assertEqual(self.api('/api/agent-connection',{'enabled':True,'if_revision':0})[0],400)
        code,_,preview=self.api('/api/agent-connection',{'enabled':True,'if_revision':0,'dry':True,'consent':'codex-persistent-management-v1'})
        self.assertEqual(code,200);self.assertTrue(preview['preview']);self.assertFalse(self.api('/api/agent-connection')[2]['enabled'])
        code,_,paused=self.api('/api/agent-connection',{'enabled':False,'if_revision':0})
        self.assertEqual(code,200);self.assertEqual(paused['state'],'paused')
        self.assertEqual(self.api('/api/agent-connection',{'enabled':False,'if_revision':0})[0],400)
        body={'model':'example','if_revision':1,'consent':'codex-management-model-v1'}
        self.assertEqual(self.api('/api/agent-connection/model',body)[0],400)
        with self.assertRaises(urllib.error.HTTPError) as denied:
            urllib.request.urlopen(urllib.request.Request(self.base+'/api/agent-connection/model',
                data=json.dumps(body).encode(),headers={'Content-Type':'application/json'}),timeout=3)
        self.assertEqual(denied.exception.code,401)
        _,_,setting=self.api('/api/agent-connection')
        self.assertIsNone(setting['model_selection']['selected_model'])
        self.assertFalse(setting['model_selection']['ready'])
        self.assertEqual(self.api('/api/state')[1],rev_before,'Connection settings cannot rewrite research state')

    def test_summary_schedule_is_human_versioned_dry_and_not_reauthorization(self):
        self.create_project()
        _,rev,_=self.api('/api/state')
        code,_,m=self.api('/api/project/manager',{'project_id':'p1','enabled':False,'max_calls_per_day':4})
        self.assertEqual(code,200)
        body={'project_id':'p1','max_calls_per_day':None,'summary_interval_minutes':30,
              'if_schedule_revision':m['schedule_revision'],'schedule_consent':'scheduled-codex-management-v1'}
        code,_,preview=self.api('/api/project/manager/schedule',dict(body,dry=True))
        self.assertEqual(code,200);self.assertTrue(preview['preview'])
        self.assertEqual(self.api('/api/project/manager?project_id=p1')[2]['max_calls_per_day'],4)
        code,_,saved=self.api('/api/project/manager/schedule',body)
        self.assertEqual(code,200);self.assertIsNone(saved['max_calls_per_day']);self.assertFalse(saved['enabled'])
        self.assertEqual(saved['summary_interval_minutes'],30)
        self.assertEqual(self.api('/api/project/manager/schedule',body)[0],400)
        self.assertEqual(self.api('/api/state')[1],rev)
        with self.assertRaises(urllib.error.HTTPError):
            urllib.request.urlopen(urllib.request.Request(self.base+'/api/project/manager/schedule',
                data=json.dumps(body).encode(),headers={'Content-Type':'application/json'}),timeout=3)

    def test_research_focus_fallback_cache_and_context_invalidation(self):
        self.create_project()
        self.create_task("active", "推进当前主线", status="进行中", priority="P0")
        self.create_task("blocked", "解除关键阻塞", status="受阻", priority="P2")

        code, _, status = self.api("/api/research-focus?scope=global")
        self.assertEqual(code, 200)
        self.assertTrue(status["needs_generation"])
        self.assertIsNone(status["focus"])

        code, _, generated = self.api("/api/research-focus", {"trigger": "daily", "scope": "global"})
        self.assertEqual(code, 200)
        self.assertFalse(generated["provider_configured"])
        self.assertFalse(generated["cached"])
        focus = generated["focus"]
        self.assertEqual(focus["provider"], "fallback")
        self.assertEqual(focus["focus_type"], "unblock")
        self.assertEqual(focus["task_id"], "blocked")
        self.assertTrue(focus["reason"])
        self.assertTrue(focus["goal"])
        self.assertTrue(focus["expected_output"])

        code, _, cached = self.api("/api/research-focus", {"trigger": "task_changed", "scope": "global"})
        self.assertEqual(code, 200)
        self.assertTrue(cached["cached"])
        self.assertEqual(cached["focus"]["focus_id"], focus["focus_id"])

        code, _, _ = self.api("/api/research-focus/feedback", {
            "focus_id": focus["focus_id"], "date": focus["date"], "scope": "global", "action": "alternate",
            "title": focus["title"],
        })
        self.assertEqual(code, 200)
        code, _, after_feedback = self.api("/api/research-focus?scope=global")
        self.assertEqual(code, 200)
        self.assertTrue(after_feedback["needs_generation"])

        code, _, alternate = self.api("/api/research-focus", {
            "trigger": "manual_refresh", "force": True, "scope": "global",
            "exclude_previous_focus_id": focus["focus_id"],
        })
        self.assertEqual(code, 200)
        self.assertNotEqual(alternate["focus"]["focus_id"], focus["focus_id"])
        self.assertNotEqual(alternate["focus"]["task_id"], focus["task_id"])

        self.create_task("blocked", "解除关键阻塞", status="待开始", priority="P2")
        code, _, changed = self.api("/api/research-focus?scope=global")
        self.assertEqual(code, 200)
        self.assertTrue(changed["needs_generation"])
        self.assertNotEqual(changed["context_hash"], alternate["context_hash"])

    def test_research_focus_completed_state_returns_review(self):
        self.create_project()
        self.create_task("done", "已完成的研究动作", status="已完成", completed=time.strftime("%Y-%m-%d"), note="通过核验")
        code, _, result = self.api("/api/research-focus", {"trigger": "daily"})
        self.assertEqual(code, 200)
        self.assertEqual(result["focus"]["focus_type"], "review")
        self.assertIsNone(result["focus"]["task_id"])
        self.assertIn("阶段", result["focus"]["title"])

    def test_research_focus_keeps_inconclusive_evidence_distinct(self):
        self.create_project()
        self.create_task("inc", "边界实验记录", status="已完成", completed=time.strftime("%Y-%m-%d"), note="无结论，仍待验证")
        code, _, result = self.api("/api/research-focus", {"trigger": "daily"})
        self.assertEqual(code, 200)
        self.assertIn("不确定结果", result["focus"]["title"])

    def test_research_focus_due_p0_is_considered(self):
        self.create_project()
        self.create_task("p0", "今天完成关键核验", priority="P0", end=time.strftime("%Y-%m-%d"))
        code, _, result = self.api("/api/research-focus", {"trigger": "daily"})
        self.assertEqual(code, 200)
        self.assertEqual(result["focus"]["task_id"], "p0")
        self.assertEqual(result["focus"]["focus_type"], "task")

    def test_research_focus_negative_p0_is_not_mechanical(self):
        self.create_project()
        self.create_task("failed", "P0 失败方向", priority="P0", note="FAIL：该方向不成立")
        self.create_task("alternative", "P1 替代核验", priority="P1", status="进行中")
        code, _, result = self.api("/api/research-focus", {"trigger": "daily"})
        self.assertEqual(code, 200)
        self.assertEqual(result["focus"]["focus_type"], "review")
        self.assertIsNone(result["focus"]["task_id"])
        self.assertIn("负结果", result["focus"]["title"])

    def test_research_focus_blocker_can_outrank_downstream_p0_tasks(self):
        self.create_project()
        self.create_task("blocker", "P1 前置证据阻塞", priority="P1", status="受阻")
        for index in range(3):
            self.create_task("downstream-%s" % index, "P0 下游任务 %s" % index, priority="P0", deps=["blocker"])
        code, _, result = self.api("/api/research-focus", {"trigger": "daily"})
        self.assertEqual(code, 200)
        self.assertEqual(result["focus"]["task_id"], "blocker")
        self.assertEqual(result["focus"]["focus_type"], "unblock")

    def test_research_focus_without_deadlines_uses_blocker(self):
        self.create_project()
        self.create_task("blocked", "没有截止日期但当前受阻", priority="P2", status="受阻")
        self.create_task("live", "普通进行中任务", priority="P0", status="进行中")
        code, _, result = self.api("/api/research-focus", {"trigger": "daily"})
        self.assertEqual(code, 200)
        self.assertEqual(result["focus"]["task_id"], "blocked")
        self.assertEqual(result["focus"]["focus_type"], "unblock")

    def test_research_focus_changes_after_decisive_negative_result(self):
        self.create_project()
        self.create_task("main", "原方向继续核验", status="进行中")
        code, _, first = self.api("/api/research-focus", {"trigger": "daily"})
        self.assertEqual(code, 200)
        self.assertEqual(first["focus"]["task_id"], "main")
        self.create_task("main", "原方向继续核验", status="进行中", note="FAIL：决定性负结果")
        code, _, status = self.api("/api/research-focus?scope=global")
        self.assertEqual(code, 200)
        self.assertTrue(status["needs_generation"])
        code, _, changed = self.api("/api/research-focus", {"trigger": "evidence_changed"})
        self.assertEqual(code, 200)
        self.assertEqual(changed["focus"]["focus_type"], "review")
        self.assertNotEqual(changed["focus"]["task_id"], "main")

    def test_research_focus_provider_failure_falls_back(self):
        with tempfile.TemporaryDirectory(prefix="research-desk-focus-provider-") as raw:
            env = os.environ.copy()
            env["RESEARCH_DESK_DATA_DIR"] = raw
            env["RESEARCH_FOCUS_API_URL"] = "http://127.0.0.1:1/v1/chat/completions"
            env["RESEARCH_FOCUS_MODEL"] = "test-model"
            script = r'''import json, server
state = {"projects":[{"id":"p1","name":"P","goal":"G","stages":[]}],"tasks":[{"id":"t1","project":"p1","title":"推进任务","priority":"P1","status":"进行中","stage":"","start":"","end":"","completed":"","milestone":False,"parent":"","deps":[],"note":""}],"files":[],"decisions":[]}
with server.connect() as c:
    c.execute("UPDATE state SET body=? WHERE id=1", (json.dumps(state, ensure_ascii=False),)); c.commit()
(server.DATA / 'analysis-policy.json').write_text(json.dumps({'projects':{'p1':{'approved':True,'provider_url':'http://127.0.0.1:1/v1/chat/completions','model':'test-model','context_fields':['tasks'],'max_calls_per_day':1}}}))
print(json.dumps(server._generate_focus({"trigger":"daily","scope":"p1","use_provider":True}), ensure_ascii=False))'''
            output = subprocess.check_output([sys.executable, "-c", script], cwd=str(ROOT), env=env, text=True)
            result = json.loads(output)
        self.assertTrue(result["provider_configured"])
        self.assertEqual(result["focus"]["provider"], "fallback")
        self.assertIn("provider 请求失败", result["focus"]["provider_error"])

    def test_research_focus_trigger_boundaries_are_explicit(self):
        source = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn('document.addEventListener("visibilitychange"', source)
        self.assertIn('window.addEventListener("focus"', source)
        self.assertIn("focusReevaluationTimer = setTimeout(async function ()", source)
        self.assertIn("}, 2500);", source)
        render_start = source.index("function render()")
        render_end = source.index("function field(", render_start)
        self.assertNotIn('api("research-focus"', source[render_start:render_end])
        menu_start = source.index("function toggleToolMenu")
        menu_end = source.index("function tabButton", menu_start)
        self.assertNotIn("loadDailyFocus", source[menu_start:menu_end])

    def test_history_records_actor_and_summary(self):
        code, rev, _ = self.api("/api/state")
        op = {"collection": "projects", "item": {"id": "p1", "name": "AI Project", "goal": "", "stages": []}}
        code, _, _ = self.api("/api/action", {"ifRev": rev, "ops": [op], "actor": "agent", "summary": "创建项目：AI Project"})
        self.assertEqual(code, 200)
        code, _, history = self.api("/api/history")
        self.assertEqual(code, 200)
        self.assertEqual(history[0]["actor"], "agent")
        self.assertEqual(history[0]["summary"], "创建项目：AI Project")

    def test_project_create_and_update(self):
        self.create_project()
        code, rev, _ = self.api("/api/state")
        code, _, state = self.api("/api/action", {
            "ifRev": rev,
            "ops": [{"collection": "projects", "item": {"id": "p1", "name": "Renamed"}}],
        })
        self.assertEqual(code, 200)
        self.assertEqual(state["projects"][0]["name"], "Renamed")
    def test_project_delete_cascades(self):
        self.create_project()
        self.create_task("t1", "Task")
        code, rev, _ = self.api("/api/state")
        ops = [
            {"collection": "files", "item": {"id": "f1", "project": "p1", "path": "a.pdf"}},
            {"collection": "decisions", "item": {"id": "d1", "project": "p1", "title": "D", "status": "待决"}},
        ]
        code, _, _ = self.api("/api/action", {"ifRev": rev, "ops": ops})
        self.assertEqual(code, 200)
        code, rev, _ = self.api("/api/state")
        code, _, state = self.api("/api/action", {
            "ifRev": rev, "ops": [{"collection": "projects", "op": "delete", "id": "p1"}]
        })
        self.assertEqual(code, 200)
        self.assertFalse(state["projects"])
        self.assertFalse(state["tasks"])
        self.assertFalse(state["files"])
        self.assertFalse(state["decisions"])

    def test_dependency_cycle_rejected(self):
        self.create_project()
        code, rev, _ = self.api("/api/state")
        base = lambda tid, dep: {
            "id": tid, "project": "p1", "title": tid, "priority": "P2", "status": "待开始",
            "stage": "", "start": "", "end": "", "completed": "", "milestone": False,
            "parent": "", "deps": dep, "note": "",
        }
        code, _, out = self.api("/api/action", {"ifRev": rev, "ops": [
            {"collection": "tasks", "item": base("a", ["b"])},
            {"collection": "tasks", "item": base("b", ["a"])},
        ]})
        self.assertEqual(code, 400)
        self.assertIn("循环", out["error"])
    def test_parent_cycle_rejected(self):
        self.create_project()
        code, rev, _ = self.api("/api/state")
        def item(tid, parent):
            return {"id": tid, "project": "p1", "title": tid, "priority": "P2", "status": "待开始",
                    "stage": "", "start": "", "end": "", "completed": "", "milestone": False,
                    "parent": parent, "deps": [], "note": ""}
        code, _, out = self.api("/api/action", {"ifRev": rev, "ops": [
            {"collection": "tasks", "item": item("a", "b")},
            {"collection": "tasks", "item": item("b", "a")},
        ]})
        self.assertEqual(code, 400)
        self.assertIn("循环", out["error"])

    def test_delete_task_cleans_relations(self):
        self.create_project()
        self.create_task("parent", "Parent")
        self.create_task("child", "Child", parent="parent", deps=["parent"])
        code, rev, _ = self.api("/api/state")
        code, _, state = self.api("/api/action", {
            "ifRev": rev, "ops": [{"collection": "tasks", "op": "delete", "id": "parent"}]
        })
        self.assertEqual(code, 200)
        child = next(t for t in state["tasks"] if t["id"] == "child")
        self.assertEqual(child["parent"], "")
        self.assertEqual(child["deps"], [])

    def test_rev_conflict_rejected(self):
        self.create_project()
        code, _, out = self.api("/api/action", {
            "ifRev": 0, "ops": [{"collection": "projects", "item": {"id": "p1", "name": "Stale"}}]
        })
        self.assertEqual(code, 400)
        self.assertIn("状态已被修改", out["error"])
    def test_dry_run_does_not_write(self):
        self.create_project()
        code, rev, before = self.api("/api/state")
        code, _, out = self.api("/api/action", {
            "ifRev": rev, "dry": True,
            "ops": [{"collection": "tasks", "item": {
                "project": "p1", "title": "Dry", "priority": "P2", "status": "待开始"
            }}],
        })
        self.assertEqual(code, 200)
        self.assertTrue(out["dry"])
        code, after_rev, after = self.api("/api/state")
        self.assertEqual(rev, after_rev)
        self.assertEqual(before["tasks"], after["tasks"])

    def test_undo_restores_previous_state(self):
        self.create_project()
        self.create_task("t1", "Task")
        code, _, state = self.api("/api/undo", {})
        self.assertEqual(code, 200)
        self.assertFalse(state["tasks"])
        self.assertEqual(len(state["projects"]), 1)

    def test_rollback_restores_snapshot(self):
        self.create_project()
        self.create_task("t1", "Task")
        code, _, history = self.api("/api/history")
        self.assertEqual(code, 200)
        project_only = next(row for row in history if row["projects"] == 1 and row["tasks"] == 0)
        code, _, state = self.api("/api/rollback", {"id": project_only["id"]})
        self.assertEqual(code, 200)
        self.assertEqual(len(state["projects"]), 1)
        self.assertFalse(state["tasks"])
    def test_backup_restore_round_trip(self):
        self.create_project()
        self.create_task("t1", "Task")
        code, rev, saved = self.api("/api/state")
        self.create_task("t2", "Extra")
        code, current_rev, _ = self.api("/api/state")
        code, _, restored = self.api("/api/state", {"ifRev": current_rev, "state": saved})
        self.assertEqual(code, 200)
        self.assertEqual(restored, saved)

    def test_schema_version_is_recorded(self):
        db = self.data_dir / "desk.sqlite3"
        with sqlite3.connect(db) as conn:
            row = conn.execute("SELECT v FROM meta WHERE k='schema_version'").fetchone()
        self.assertEqual(row[0], "1")

    def test_state_endpoint_accepts_wrapped_ifrev(self):
        code, rev, state = self.api("/api/state")
        desired = {"projects": [{"id": "p1", "name": "Wrapped", "goal": "", "stages": []}],
                   "tasks": [], "files": [], "decisions": []}
        code, next_rev, out = self.api("/api/state", {"ifRev": rev, "state": desired})
        self.assertEqual(code, 200)
        self.assertGreater(next_rev, rev)
        self.assertEqual(out, desired)

    def test_old_backup_migrates_on_restore(self):
        code, rev, _ = self.api("/api/state")
        old = {"projects": [{"id": "p1", "name": "Old", "goal": "", "stages": []}],
               "tasks": [{"id": "t1", "project": "p1", "title": "Old task"}], "files": []}
        code, _, state = self.api("/api/state", {"ifRev": rev, "state": old})
        self.assertEqual(code, 200)
        self.assertIn("decisions", state)
        task = state["tasks"][0]
        self.assertEqual(task["status"], "待开始")
        self.assertEqual(task["deps"], [])

    def test_legacy_state_migrates(self):
        with tempfile.TemporaryDirectory(prefix="research-desk-legacy-") as raw:
            legacy = pathlib.Path(raw)
            db = legacy / "desk.sqlite3"
            old = {"projects": [], "tasks": [], "files": []}
            with sqlite3.connect(db) as conn:
                conn.execute("CREATE TABLE state (id INTEGER PRIMARY KEY, body TEXT)")
                conn.execute("INSERT INTO state VALUES(1,?)", (json.dumps(old),))
            port = free_port()
            env = os.environ.copy(); env["RESEARCH_DESK_DATA_DIR"] = raw; env["PORT"] = str(port)
            proc = subprocess.Popen([sys.executable, str(SERVER)], cwd=str(ROOT), env=env,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                deadline = time.time() + 5
                migrated = None
                while time.time() < deadline:
                    if (legacy / "api-token").exists():
                        token = (legacy / "api-token").read_text().strip()
                        req = urllib.request.Request(f"http://127.0.0.1:{port}/api/state",
                                                     headers={"Authorization": "Bearer " + token})
                        try:
                            with urllib.request.urlopen(req, timeout=1) as res: migrated = json.loads(res.read())
                            break
                        except urllib.error.URLError:
                            pass
                    time.sleep(0.05)
                self.assertIsNotNone(migrated, 'legacy server did not become ready')
                self.assertIn("decisions", migrated)
                with sqlite3.connect(db) as conn:
                    version = conn.execute("SELECT v FROM meta WHERE k='schema_version'").fetchone()[0]
                self.assertEqual(version, "1")
            finally:
                proc.terminate(); proc.wait(timeout=3)

if __name__ == "__main__":
    unittest.main(verbosity=2)
