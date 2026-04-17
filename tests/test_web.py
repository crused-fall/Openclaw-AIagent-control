import asyncio
import json
import os
import tempfile
import textwrap
import unittest
from unittest import mock

from aiohttp.test_utils import TestClient, TestServer

from openclaw_v2.models import AgentResult, AgentType, ExecutionMode, RunResult, TaskStatus, WorkItem
from openclaw_v2.web import create_web_app


def _write_minimal_config(path: str) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(
            textwrap.dedent(
                """
                runtime:
                  pipeline: demo_pipeline
                  dry_run: true

                profiles:
                  codex_local:
                    agent: codex
                    mode: cli
                    command:
                      - echo
                      - "{prompt}"

                managed_agents:
                  codex_builder:
                    kind: codex
                    profile: codex_local
                    capabilities:
                      - implement

                assignments:
                  implement_local:
                    agent: codex_builder
                    required_capabilities:
                      - implement

                pipelines:
                  demo_pipeline:
                    - id: implement
                      title: Implement docs
                      assignment: implement_local
                      prompt_template: |
                        Implement request:
                        {user_request}
                """
            ).strip()
        )
        handle.write("\n")


def _normalized_path(path: str) -> str:
    return os.path.realpath(path)


class WebBootstrapTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.external_dir = tempfile.TemporaryDirectory()
        self.repo_path = self.temp_dir.name
        self.config_path = os.path.join(self.repo_path, "config_v2.yaml")
        _write_minimal_config(self.config_path)
        self.client = TestClient(
            TestServer(
                create_web_app(
                    config_path=self.config_path,
                    repo_path=self.repo_path,
                )
            )
        )
        await self.client.start_server()

    async def asyncTearDown(self) -> None:
        await self.client.close()
        self.external_dir.cleanup()
        self.temp_dir.cleanup()

    async def test_bootstrap_returns_pipeline_snapshot(self) -> None:
        response = await self.client.get("/api/bootstrap")
        self.assertEqual(response.status, 200)
        payload = await response.json()

        self.assertEqual(payload["snapshot"]["defaultPipeline"], "demo_pipeline")
        self.assertIn("demo_pipeline", payload["snapshot"]["pipelines"])
        self.assertEqual(payload["snapshot"]["currentPlan"][0]["id"], "implement")
        self.assertEqual(payload["repoPath"], _normalized_path(self.repo_path))
        self.assertIn("defaultOpenClawAgentId", payload)
        self.assertIn("integrations", payload)
        self.assertIn("github", payload["integrations"])
        self.assertIn("hermes", payload["integrations"])
        self.assertNotIn("managedAgents", payload["snapshot"])
        self.assertNotIn("assignments", payload["snapshot"])

    async def test_index_serves_readiness_and_output_controls(self) -> None:
        response = await self.client.get("/")
        self.assertEqual(response.status, 200)
        page = await response.text()

        self.assertIn("Readiness Gate", page)
        self.assertIn('id="readiness-checks"', page)
        self.assertIn('id="result-filter"', page)
        self.assertIn('id="copy-run-summary"', page)
        self.assertIn('id="copy-issue-update"', page)
        self.assertIn('id="copy-pr-note"', page)
        self.assertIn('id="launch-brief"', page)
        self.assertIn('id="pipeline-radar"', page)
        self.assertIn('id="pipeline-dag"', page)
        self.assertIn('id="github-bridge"', page)
        self.assertIn('id="hermes-panel"', page)
        self.assertIn('id="compare-left-run"', page)
        self.assertIn('id="compare-right-run"', page)
        self.assertIn('id="run-compare"', page)
        self.assertIn('id="request-presets"', page)
        self.assertIn('id="repo-path" name="repoPath" type="text" autocomplete="off" readonly', page)
        self.assertIn('id="config-path" name="configPath" type="text" autocomplete="off" readonly', page)

    async def test_health_endpoint_returns_snapshot(self) -> None:
        fake_health = {
            "checkedAt": "2026-04-16T00:00:00Z",
            "agentId": "openclaw-control-ext",
            "healthOk": True,
            "defaultAgentId": "main",
            "targetAgentPresent": True,
            "channels": [],
            "gateway": {"ok": True, "stdout": "Gateway: ok", "stderr": ""},
            "memory": {"ok": True, "stdout": "Embeddings: ready", "stderr": ""},
        }
        with mock.patch("openclaw_v2.web._openclaw_health_snapshot", return_value=fake_health):
            response = await self.client.get("/api/system/health?agentId=openclaw-control-ext")
        self.assertEqual(response.status, 200)
        payload = await response.json()
        self.assertEqual(payload["agentId"], "openclaw-control-ext")
        self.assertTrue(payload["healthOk"])

    async def test_bootstrap_allows_in_repo_config_override(self) -> None:
        alt_dir = os.path.join(self.repo_path, "configs")
        os.makedirs(alt_dir, exist_ok=True)
        alt_config_path = os.path.join(alt_dir, "alt_config.yaml")
        _write_minimal_config(alt_config_path)

        response = await self.client.get("/api/bootstrap", params={"configPath": "configs/alt_config.yaml"})
        self.assertEqual(response.status, 200)
        payload = await response.json()
        self.assertEqual(payload["configPath"], _normalized_path(alt_config_path))

    async def test_bootstrap_rejects_repo_override_outside_configured_root(self) -> None:
        response = await self.client.get("/api/bootstrap", params={"repoPath": self.external_dir.name})
        self.assertEqual(response.status, 400)
        self.assertIn("configured repository root", await response.text())

    async def test_health_rejects_config_override_outside_repo_scope(self) -> None:
        outside_config = os.path.join(self.external_dir.name, "outside_config.yaml")
        response = await self.client.get("/api/system/health", params={"configPath": outside_config})
        self.assertEqual(response.status, 400)
        self.assertIn("Dashboard configPath must stay within the repository", await response.text())

    async def test_history_endpoints_return_files_and_content(self) -> None:
        run_dir = os.path.join(self.repo_path, ".openclaw", "runs", "run-1")
        os.makedirs(os.path.join(run_dir, "prompts"), exist_ok=True)
        with open(os.path.join(run_dir, "summary.json"), "w", encoding="utf-8") as handle:
            json.dump({"run_id": "run-1", "plan": [], "results": [], "success": True}, handle)
        with open(os.path.join(run_dir, "context.json"), "w", encoding="utf-8") as handle:
            json.dump({"repo_path": self.repo_path, "user_request": "demo"}, handle)
        with open(os.path.join(run_dir, "prompts", "implement.txt"), "w", encoding="utf-8") as handle:
            handle.write("hello prompt\n")

        response = await self.client.get("/api/history/run-1")
        self.assertEqual(response.status, 200)
        payload = await response.json()
        self.assertEqual(payload["runId"], "run-1")
        self.assertEqual(payload["files"][0]["path"], "context.json")
        self.assertIn("insights", payload)
        self.assertIn("github", payload["insights"])

        file_response = await self.client.get("/api/history/run-1/file?path=prompts/implement.txt")
        self.assertEqual(file_response.status, 200)
        file_payload = await file_response.json()
        self.assertIn("hello prompt", file_payload["content"])

    async def test_history_compare_endpoint_returns_step_and_bridge_deltas(self) -> None:
        runs_root = os.path.join(self.repo_path, ".openclaw", "runs")
        os.makedirs(runs_root, exist_ok=True)

        run_a = os.path.join(runs_root, "run-a")
        os.makedirs(run_a, exist_ok=True)
        with open(os.path.join(run_a, "summary.json"), "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "run_id": "run-a",
                    "plan": [{"id": "publish_branch", "title": "Publish branch"}],
                    "results": [
                        {
                            "work_item_id": "publish_branch",
                            "status": "succeeded",
                            "mode": "cli",
                            "artifacts": {"source_branch": "branch-a"},
                        },
                        {
                            "work_item_id": "draft_pr",
                            "status": "succeeded",
                            "mode": "github",
                            "artifacts": {
                                "pr_number": "11",
                                "pr_url": "https://github.com/owner/repo/pull/11",
                            },
                        },
                    ],
                    "success": True,
                },
                handle,
            )
        with open(os.path.join(run_a, "context.json"), "w", encoding="utf-8") as handle:
            json.dump({"repo_path": self.repo_path, "user_request": "alpha"}, handle)

        run_b = os.path.join(runs_root, "run-b")
        os.makedirs(run_b, exist_ok=True)
        with open(os.path.join(run_b, "summary.json"), "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "run_id": "run-b",
                    "plan": [{"id": "publish_branch", "title": "Publish branch"}],
                    "results": [
                        {
                            "work_item_id": "publish_branch",
                            "status": "blocked",
                            "mode": "cli",
                            "artifacts": {"source_branch": "branch-b"},
                        },
                        {
                            "work_item_id": "record_summary",
                            "status": "succeeded",
                            "mode": "hermes",
                            "artifacts": {"hermes_session_id": "session-42"},
                        },
                    ],
                    "success": False,
                },
                handle,
            )
        with open(os.path.join(run_b, "context.json"), "w", encoding="utf-8") as handle:
            json.dump({"repo_path": self.repo_path, "user_request": "beta"}, handle)

        response = await self.client.post("/api/history/compare", json={"runIds": ["run-a", "run-b"]})
        self.assertEqual(response.status, 200)
        payload = await response.json()
        self.assertEqual(len(payload["runs"]), 2)
        self.assertTrue(payload["comparison"]["branchChanged"])
        self.assertEqual(payload["comparison"]["hermesSessionDelta"], 1)
        self.assertTrue(any(item["stepId"] == "publish_branch" for item in payload["comparison"]["stepDiffs"]))

    async def test_cleanup_endpoint_removes_run_directory(self) -> None:
        run_dir = os.path.join(self.repo_path, ".openclaw", "runs", "run-cleanup")
        os.makedirs(run_dir, exist_ok=True)
        with open(os.path.join(run_dir, "summary.json"), "w", encoding="utf-8") as handle:
            json.dump({"run_id": "run-cleanup", "plan": [], "results": [], "success": True}, handle)

        response = await self.client.post("/api/history/run-cleanup/cleanup", json={})
        self.assertEqual(response.status, 200)
        payload = await response.json()
        self.assertEqual(payload["runId"], "run-cleanup")
        self.assertFalse(os.path.exists(run_dir))

    async def test_cleanup_endpoint_skips_workspace_manifests_outside_repo_scope(self) -> None:
        run_dir = os.path.join(self.repo_path, ".openclaw", "runs", "run-suspicious")
        workspaces_dir = os.path.join(run_dir, "workspaces")
        os.makedirs(workspaces_dir, exist_ok=True)
        with open(os.path.join(workspaces_dir, "implement.json"), "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "workspace_path": self.external_dir.name,
                    "branch_name": "openclaw-run-suspicious-implement",
                    "metadata": {
                        "workspace_strategy": "git-worktree",
                        "workspace_repo_root": self.external_dir.name,
                    },
                },
                handle,
            )

        with mock.patch("openclaw_v2.web._run_cleanup_command") as run_cleanup:
            response = await self.client.post(
                "/api/history/run-suspicious/cleanup",
                json={"removeArtifacts": False, "removeWorktrees": True},
            )

        self.assertEqual(response.status, 200)
        payload = await response.json()
        self.assertTrue(os.path.exists(run_dir))
        self.assertEqual(run_cleanup.call_count, 0)
        self.assertTrue(all(item.get("skipped") for item in payload["operations"]))
        self.assertTrue(
            any("outside the configured repository" in item.get("reason", "") for item in payload["operations"])
        )

    async def test_cleanup_endpoint_only_executes_commands_for_managed_repo_worktrees(self) -> None:
        run_dir = os.path.join(self.repo_path, ".openclaw", "runs", "run-managed")
        workspaces_dir = os.path.join(run_dir, "workspaces")
        os.makedirs(workspaces_dir, exist_ok=True)
        os.makedirs("/tmp/openclaw-worktrees", exist_ok=True)

        with tempfile.TemporaryDirectory(dir="/tmp/openclaw-worktrees") as workspace_path:
            with open(os.path.join(workspaces_dir, "implement.json"), "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "workspace_path": workspace_path,
                        "branch_name": "openclaw-run-managed-implement",
                        "metadata": {
                            "workspace_strategy": "git-worktree",
                            "workspace_repo_root": self.repo_path,
                        },
                    },
                    handle,
                )

            with mock.patch(
                "openclaw_v2.web._run_cleanup_command",
                side_effect=lambda command: {
                    "command": command,
                    "ok": True,
                    "exitCode": 0,
                    "stdout": "",
                    "stderr": "",
                },
            ) as run_cleanup:
                response = await self.client.post(
                    "/api/history/run-managed/cleanup",
                    json={"removeArtifacts": False, "removeWorktrees": True},
                )

            self.assertEqual(response.status, 200)
            payload = await response.json()
            self.assertEqual(run_cleanup.call_count, 2)
            commands = [call.args[0] for call in run_cleanup.call_args_list]
            self.assertEqual(
                commands[0],
                ["git", "-C", _normalized_path(self.repo_path), "worktree", "remove", "--force", _normalized_path(workspace_path)],
            )
            self.assertEqual(
                commands[1],
                ["git", "-C", _normalized_path(self.repo_path), "branch", "-D", "openclaw-run-managed-implement"],
            )
            self.assertFalse(any(item.get("skipped") for item in payload["operations"]))

    async def test_prune_endpoint_keeps_latest_runs(self) -> None:
        runs_root = os.path.join(self.repo_path, ".openclaw", "runs")
        os.makedirs(runs_root, exist_ok=True)
        for index, run_id in enumerate(["run-a", "run-b", "run-c"], start=1):
            run_dir = os.path.join(runs_root, run_id)
            os.makedirs(run_dir, exist_ok=True)
            with open(os.path.join(run_dir, "summary.json"), "w", encoding="utf-8") as handle:
                json.dump({"run_id": run_id, "plan": [], "results": [], "success": True}, handle)
            os.utime(run_dir, (index, index))

        response = await self.client.post("/api/history/prune", json={"keepLatest": 1})
        self.assertEqual(response.status, 200)
        payload = await response.json()
        self.assertEqual(len(payload["removed"]), 2)
        self.assertTrue(os.path.exists(os.path.join(runs_root, "run-c")))
        self.assertFalse(os.path.exists(os.path.join(runs_root, "run-a")))
        self.assertFalse(os.path.exists(os.path.join(runs_root, "run-b")))


class WebRunTaskTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.external_dir = tempfile.TemporaryDirectory()
        self.repo_path = self.temp_dir.name
        self.config_path = os.path.join(self.repo_path, "config_v2.yaml")
        _write_minimal_config(self.config_path)
        self.client = TestClient(
            TestServer(
                create_web_app(
                    config_path=self.config_path,
                    repo_path=self.repo_path,
                )
            )
        )
        await self.client.start_server()

    async def asyncTearDown(self) -> None:
        await self.client.close()
        self.external_dir.cleanup()
        self.temp_dir.cleanup()

    async def test_run_task_captures_progress_and_result(self) -> None:
        run_artifacts = os.path.join(self.repo_path, ".openclaw", "runs", "run-web-test")
        os.makedirs(run_artifacts, exist_ok=True)
        with open(os.path.join(run_artifacts, "summary.json"), "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "run_id": "run-web-test",
                    "plan": [],
                    "results": [
                        {
                            "work_item_id": "implement",
                            "status": "succeeded",
                            "summary": "Implementation finished.",
                        }
                    ],
                    "success": True,
                    "artifacts_dir": run_artifacts,
                },
                handle,
            )
        with open(os.path.join(run_artifacts, "context.json"), "w", encoding="utf-8") as handle:
            json.dump({"repo_path": self.repo_path, "user_request": "Add a Web UI"}, handle)

        fake_run_result = RunResult(
            run_id="run-web-test",
            plan=[
                WorkItem(
                    id="implement",
                    title="Implement docs",
                    profile="codex_local",
                    agent=AgentType.CODEX,
                    mode=ExecutionMode.CLI,
                    prompt_template="prompt",
                    assignment="implement_local",
                    managed_agent="codex_builder",
                )
            ],
            results=[
                AgentResult(
                    work_item_id="implement",
                    profile="codex_local",
                    agent=AgentType.CODEX,
                    mode=ExecutionMode.CLI,
                    status=TaskStatus.SUCCEEDED,
                    summary="Implementation finished.",
                )
            ],
            success=True,
            artifacts_dir=os.path.join(self.repo_path, ".openclaw", "runs", "run-web-test"),
        )

        class FakeOrchestrator:
            def __init__(self, config) -> None:
                self.config = config

            def build_plan(self, selected_steps=None):
                return []

            async def run(self, user_request, repo_path, selected_steps=None, progress_callback=None):
                if progress_callback is not None:
                    progress_callback("preflight:start")
                    progress_callback("step:done implement -> succeeded")
                return fake_run_result

        with mock.patch("openclaw_v2.web.HybridOrchestrator", FakeOrchestrator):
            response = await self.client.post(
                "/api/tasks",
                json={
                    "action": "run",
                    "repoPath": self.repo_path,
                    "configPath": self.config_path,
                    "pipeline": "demo_pipeline",
                    "request": "Add a Web UI",
                    "steps": ["implement"],
                    "live": False,
                },
            )
            self.assertEqual(response.status, 202)
            payload = await response.json()
            task_id = payload["task"]["id"]

            task_payload = None
            for _ in range(20):
                detail_response = await self.client.get(f"/api/tasks/{task_id}")
                self.assertEqual(detail_response.status, 200)
                detail = await detail_response.json()
                task_payload = detail["task"]
                if task_payload["status"] == "completed":
                    break
                await asyncio.sleep(0.01)

            self.assertIsNotNone(task_payload)
            self.assertEqual(task_payload["status"], "completed")
            messages = [item["message"] for item in task_payload["progress"]]
            self.assertIn("preflight:start", messages)
            self.assertIn("step:done implement -> succeeded", messages)
            self.assertEqual(task_payload["result"]["mode"], "run")
            self.assertEqual(task_payload["result"]["runResult"]["run_id"], "run-web-test")
            self.assertEqual(task_payload["result"]["history"]["runId"], "run-web-test")

    async def test_cancel_run_task_marks_task_cancelled(self) -> None:
        started = asyncio.Event()

        class SlowOrchestrator:
            def __init__(self, config) -> None:
                self.config = config

            def build_plan(self, selected_steps=None):
                return []

            async def run(self, user_request, repo_path, selected_steps=None, progress_callback=None):
                if progress_callback is not None:
                    progress_callback("preflight:start")
                started.set()
                await asyncio.sleep(60)
                raise AssertionError("run should have been cancelled")

        with mock.patch("openclaw_v2.web.HybridOrchestrator", SlowOrchestrator):
            response = await self.client.post(
                "/api/tasks",
                json={
                    "action": "run",
                    "repoPath": self.repo_path,
                    "configPath": self.config_path,
                    "pipeline": "demo_pipeline",
                    "request": "Cancel me",
                    "steps": ["implement"],
                    "live": False,
                },
            )
            self.assertEqual(response.status, 202)
            payload = await response.json()
            task_id = payload["task"]["id"]

            await asyncio.wait_for(started.wait(), timeout=1)

            cancel_response = await self.client.post(f"/api/tasks/{task_id}/cancel")
            self.assertEqual(cancel_response.status, 200)

            task_payload = None
            for _ in range(30):
                detail_response = await self.client.get(f"/api/tasks/{task_id}")
                self.assertEqual(detail_response.status, 200)
                detail = await detail_response.json()
                task_payload = detail["task"]
                if task_payload["status"] == "cancelled":
                    break
                await asyncio.sleep(0.01)

            self.assertIsNotNone(task_payload)
            self.assertEqual(task_payload["status"], "cancelled")
            self.assertEqual(task_payload["error"], "Cancelled by user.")

    async def test_task_events_endpoint_streams_task_payload(self) -> None:
        run_artifacts = os.path.join(self.repo_path, ".openclaw", "runs", "run-stream-test")
        os.makedirs(run_artifacts, exist_ok=True)
        with open(os.path.join(run_artifacts, "summary.json"), "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "run_id": "run-stream-test",
                    "plan": [],
                    "results": [],
                    "success": True,
                    "artifacts_dir": run_artifacts,
                },
                handle,
            )
        with open(os.path.join(run_artifacts, "context.json"), "w", encoding="utf-8") as handle:
            json.dump({"repo_path": self.repo_path, "user_request": "stream demo"}, handle)

        fake_run_result = RunResult(
            run_id="run-stream-test",
            plan=[],
            results=[],
            success=True,
            artifacts_dir=run_artifacts,
        )

        class InstantOrchestrator:
            def __init__(self, config) -> None:
                self.config = config

            def build_plan(self, selected_steps=None):
                return []

            async def run(self, user_request, repo_path, selected_steps=None, progress_callback=None):
                if progress_callback is not None:
                    progress_callback("step:done implement -> succeeded")
                return fake_run_result

        with mock.patch("openclaw_v2.web.HybridOrchestrator", InstantOrchestrator):
            response = await self.client.post(
                "/api/tasks",
                json={
                    "action": "run",
                    "repoPath": self.repo_path,
                    "configPath": self.config_path,
                    "pipeline": "demo_pipeline",
                    "request": "Stream me",
                    "steps": ["implement"],
                    "live": False,
                },
            )
            self.assertEqual(response.status, 202)
            payload = await response.json()
            task_id = payload["task"]["id"]

            events_response = await self.client.get(f"/api/tasks/{task_id}/events")
            self.assertEqual(events_response.status, 200)
            body = await events_response.text()
            self.assertIn("event: task", body)
            self.assertIn('"status": "completed"', body)

    async def test_task_create_rejects_repo_override_outside_configured_root(self) -> None:
        response = await self.client.post(
            "/api/tasks",
            json={
                "action": "doctor",
                "repoPath": self.external_dir.name,
                "configPath": self.config_path,
            },
        )
        self.assertEqual(response.status, 400)
        self.assertIn("configured repository root", await response.text())
