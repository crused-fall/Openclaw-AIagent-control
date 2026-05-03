import asyncio
import json
import os
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock

from aiohttp.test_utils import TestClient, TestServer

from openclaw_v2.models import AgentResult, AgentType, ExecutionMode, RunResult, TaskStatus, WorkItem
from openclaw_v2.config import load_app_config
from openclaw_v2.web import (
    APP_HOUSEKEEPING_TOKEN,
    APP_TASK_MANAGER,
    _summarize_run_insights,
    create_web_app,
)


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
        self.app = create_web_app(
            config_path=self.config_path,
            repo_path=self.repo_path,
        )
        self.housekeeping_headers = {
            "X-OpenClaw-Housekeeping-Token": self.app[APP_HOUSEKEEPING_TOKEN],
        }
        self.client = TestClient(
            TestServer(
                self.app
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
        self.assertIn("frame-ancestors 'none'", response.headers["Content-Security-Policy"])
        self.assertEqual(response.headers["X-Frame-Options"], "DENY")
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
        payload = await response.json()

        self.assertEqual(payload["snapshot"]["defaultPipeline"], "demo_pipeline")
        self.assertIn("demo_pipeline", payload["snapshot"]["pipelines"])
        self.assertEqual(payload["snapshot"]["currentPlan"][0]["id"], "implement")
        self.assertEqual(payload["repoPath"], _normalized_path(self.repo_path))
        self.assertEqual(payload["worktreesRoot"], "/tmp/openclaw-worktrees")
        self.assertIn("defaultOpenClawAgentId", payload)
        self.assertIn("housekeeping", payload)
        self.assertEqual(payload["housekeeping"]["confirmationToken"], self.housekeeping_headers["X-OpenClaw-Housekeeping-Token"])
        self.assertIn("integrations", payload)
        self.assertIn("github", payload["integrations"])
        self.assertIn("hermes", payload["integrations"])
        self.assertNotIn("originUrl", payload["integrations"]["github"])
        self.assertNotIn("resolutionError", payload["integrations"]["github"])
        self.assertNotIn("defaultLabels", payload["integrations"]["github"])
        self.assertNotIn("envPath", payload["integrations"]["hermes"])
        self.assertNotIn("managedAgents", payload["snapshot"])
        self.assertNotIn("assignments", payload["snapshot"])
    async def test_index_serves_readiness_and_output_controls(self) -> None:
        response = await self.client.get("/")
        self.assertEqual(response.status, 200)
        self.assertIn("frame-ancestors 'none'", response.headers["Content-Security-Policy"])
        self.assertEqual(response.headers["X-Frame-Options"], "DENY")
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
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
        self.assertNotIn("healthRaw", payload)
        self.assertNotIn("knownAgents", payload)

    async def test_health_endpoint_tolerates_malformed_openclaw_health_payload(self) -> None:
        malformed_health = {
            "ok": True,
            "channelOrder": "not-a-list",
            "channels": "not-a-dict",
            "channelLabels": "not-a-dict",
            "agents": "not-a-list",
            "defaultAgentId": 123,
        }
        with mock.patch(
            "openclaw_v2.web._command_snapshot",
            side_effect=[
                {"ok": True, "stdout": json.dumps(malformed_health), "stderr": "", "exitCode": 0},
                {"ok": True, "stdout": "Gateway: ok", "stderr": "", "exitCode": 0},
                {"ok": True, "stdout": "Embeddings: ready", "stderr": "", "exitCode": 0},
            ],
        ):
            response = await self.client.get("/api/system/health?agentId=openclaw-control-ext")

        self.assertEqual(response.status, 200)
        payload = await response.json()
        self.assertTrue(payload["healthOk"])
        self.assertEqual(payload["defaultAgentId"], "")
        self.assertFalse(payload["targetAgentPresent"])
        self.assertEqual(payload["channels"], [])

    async def test_health_unhandled_error_still_carries_security_headers(self) -> None:
        with mock.patch(
            "openclaw_v2.web._openclaw_health_snapshot",
            side_effect=RuntimeError("health probe failed"),
        ):
            response = await self.client.get("/api/system/health?agentId=openclaw-control-ext")

        self.assertEqual(response.status, 500)
        self.assertIn("frame-ancestors 'none'", response.headers["Content-Security-Policy"])
        self.assertEqual(response.headers["X-Frame-Options"], "DENY")
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
        self.assertIn("Internal server error", await response.text())

    async def test_bootstrap_allows_in_repo_config_override(self) -> None:
        alt_dir = os.path.join(self.repo_path, "configs")
        os.makedirs(alt_dir, exist_ok=True)
        alt_config_path = os.path.join(alt_dir, "alt_config.yaml")
        _write_minimal_config(alt_config_path)

        response = await self.client.get("/api/bootstrap", params={"configPath": "configs/alt_config.yaml"})
        self.assertEqual(response.status, 200)
        payload = await response.json()
        self.assertEqual(payload["configPath"], _normalized_path(alt_config_path))

    async def test_bootstrap_rejects_unknown_pipeline_override(self) -> None:
        response = await self.client.get("/api/bootstrap", params={"pipeline": "missing_pipeline"})
        self.assertEqual(response.status, 400)
        self.assertIn("frame-ancestors 'none'", response.headers["Content-Security-Policy"])
        self.assertEqual(response.headers["X-Frame-Options"], "DENY")
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
        self.assertIn("missing_pipeline", await response.text())

    async def test_bootstrap_skips_runs_with_non_object_summary_json(self) -> None:
        run_dir = os.path.join(self.repo_path, ".openclaw", "runs", "run-array-summary")
        os.makedirs(run_dir, exist_ok=True)
        with open(os.path.join(run_dir, "summary.json"), "w", encoding="utf-8") as handle:
            json.dump([], handle)

        response = await self.client.get("/api/bootstrap")
        self.assertEqual(response.status, 200)
        payload = await response.json()
        self.assertFalse(any(item["runId"] == "run-array-summary" for item in payload["recentRuns"]))

    async def test_bootstrap_skips_runs_with_invalid_utf8_summary_json(self) -> None:
        run_dir = os.path.join(self.repo_path, ".openclaw", "runs", "run-bad-bytes")
        os.makedirs(run_dir, exist_ok=True)
        with open(os.path.join(run_dir, "summary.json"), "wb") as handle:
            handle.write(b"\xff")

        response = await self.client.get("/api/bootstrap")
        self.assertEqual(response.status, 200)
        payload = await response.json()
        self.assertFalse(any(item["runId"] == "run-bad-bytes" for item in payload["recentRuns"]))

    async def test_bootstrap_skips_runs_if_summary_disappears_during_read(self) -> None:
        run_dir = os.path.join(self.repo_path, ".openclaw", "runs", "run-vanish")
        os.makedirs(run_dir, exist_ok=True)
        with open(os.path.join(run_dir, "summary.json"), "w", encoding="utf-8") as handle:
            json.dump({"run_id": "run-vanish", "plan": [], "results": [], "success": True}, handle)

        real_open = Path.open

        def flaky_open(path_self, *args, **kwargs):
            if path_self.as_posix().endswith("/run-vanish/summary.json"):
                raise FileNotFoundError("summary disappeared")
            return real_open(path_self, *args, **kwargs)

        with mock.patch.object(Path, "open", autospec=True, side_effect=flaky_open):
            response = await self.client.get("/api/bootstrap")

        self.assertEqual(response.status, 200)
        payload = await response.json()
        self.assertFalse(any(item["runId"] == "run-vanish" for item in payload["recentRuns"]))

    async def test_bootstrap_tolerates_preflight_disappearing_during_read(self) -> None:
        run_dir = os.path.join(self.repo_path, ".openclaw", "runs", "run-preflight-race")
        metadata_dir = os.path.join(run_dir, "metadata")
        os.makedirs(metadata_dir, exist_ok=True)
        with open(os.path.join(run_dir, "summary.json"), "w", encoding="utf-8") as handle:
            json.dump({"run_id": "run-preflight-race", "plan": [], "results": [], "success": True}, handle)
        with open(os.path.join(run_dir, "context.json"), "w", encoding="utf-8") as handle:
            json.dump({"repo_path": self.repo_path, "user_request": "demo"}, handle)
        with open(os.path.join(metadata_dir, "preflight.json"), "w", encoding="utf-8") as handle:
            json.dump({"checks": [{"name": "noop", "status": "passed"}]}, handle)

        real_open = open

        def flaky_open(file, *args, **kwargs):
            if isinstance(file, str) and file.endswith("/metadata/preflight.json"):
                raise FileNotFoundError("preflight disappeared during read")
            return real_open(file, *args, **kwargs)

        with mock.patch("builtins.open", side_effect=flaky_open):
            response = await self.client.get("/api/bootstrap")

        self.assertEqual(response.status, 200)
        payload = await response.json()
        self.assertTrue(any(item["runId"] == "run-preflight-race" for item in payload["recentRuns"]))

    async def test_bootstrap_skips_runs_if_run_directory_stat_disappears_during_sort(self) -> None:
        runs_root = os.path.join(self.repo_path, ".openclaw", "runs")
        os.makedirs(runs_root, exist_ok=True)
        for index, run_id in enumerate(["run-a", "run-stat-race", "run-c"], start=1):
            run_dir = os.path.join(runs_root, run_id)
            os.makedirs(run_dir, exist_ok=True)
            with open(os.path.join(run_dir, "summary.json"), "w", encoding="utf-8") as handle:
                json.dump({"run_id": run_id, "plan": [], "results": [], "success": True}, handle)
            os.utime(run_dir, (index, index))

        path_cls = Path(self.repo_path).__class__
        real_stat = path_cls.stat

        def flaky_stat(path_self, *args, **kwargs):
            if path_self.name == "run-stat-race":
                raise FileNotFoundError("run disappeared while sorting recent runs")
            return real_stat(path_self, *args, **kwargs)

        with mock.patch.object(path_cls, "stat", autospec=True, side_effect=flaky_stat):
            response = await self.client.get("/api/bootstrap")

        self.assertEqual(response.status, 200)
        payload = await response.json()
        self.assertFalse(any(item["runId"] == "run-stat-race" for item in payload["recentRuns"]))

    async def test_bootstrap_tolerates_non_list_summary_sections(self) -> None:
        run_dir = os.path.join(self.repo_path, ".openclaw", "runs", "run-weird-summary")
        os.makedirs(run_dir, exist_ok=True)
        with open(os.path.join(run_dir, "summary.json"), "w", encoding="utf-8") as handle:
            json.dump({"run_id": "run-weird-summary", "plan": {}, "results": {}, "success": True}, handle)

        response = await self.client.get("/api/bootstrap")
        self.assertEqual(response.status, 200)
        payload = await response.json()
        recent = next(item for item in payload["recentRuns"] if item["runId"] == "run-weird-summary")
        self.assertEqual(recent["stepCount"], 0)
        self.assertEqual(recent["resultCount"], 0)

    async def test_bootstrap_and_history_treat_string_flags_conservatively(self) -> None:
        run_dir = os.path.join(self.repo_path, ".openclaw", "runs", "run-string-flags")
        os.makedirs(run_dir, exist_ok=True)
        with open(os.path.join(run_dir, "summary.json"), "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "run_id": "run-string-flags",
                    "plan": [],
                    "results": [],
                    "success": "false",
                },
                handle,
            )
        with open(os.path.join(run_dir, "context.json"), "w", encoding="utf-8") as handle:
            json.dump({"repo_path": self.repo_path, "user_request": "flag demo", "dry_run": "false"}, handle)

        bootstrap_response = await self.client.get("/api/bootstrap")
        self.assertEqual(bootstrap_response.status, 200)
        bootstrap_payload = await bootstrap_response.json()
        bootstrap_recent = next(item for item in bootstrap_payload["recentRuns"] if item["runId"] == "run-string-flags")
        self.assertFalse(bootstrap_recent["success"])

        history_response = await self.client.get("/api/history/run-string-flags")
        self.assertEqual(history_response.status, 200)
        history_payload = await history_response.json()
        self.assertFalse(history_payload["insights"]["dryRun"])

    async def test_bootstrap_treats_runtime_snapshot_flags_and_lists_conservatively(self) -> None:
        class DummyOrchestrator:
            def __init__(self, config) -> None:
                self.config = config

            def build_plan(self, selected_steps=None):
                return []

        with mock.patch("openclaw_v2.web.load_app_config") as load_config, mock.patch(
            "openclaw_v2.web.HybridOrchestrator",
            DummyOrchestrator,
        ):
            config = load_config.return_value
            config.runtime.pipeline = "demo_pipeline"
            config.runtime.dry_run = "false"
            config.runtime.require_step_selection_for_live = "false"
            config.runtime.allow_fallback_in_live = "true"
            config.runtime.allowed_live_steps = "implement"
            config.runtime.artifacts_dir = ".openclaw/runs"
            config.runtime.worktrees_dir = "/tmp/openclaw-worktrees"
            config.github.repo = ""
            config.github.base_branch = "main"
            config.github.use_origin_remote_fallback = "true"
            config.profiles = {}
            config.managed_agents = {}
            config.assignments = {}
            config.pipelines = {"demo_pipeline": []}

            response = await self.client.get("/api/bootstrap")

        self.assertEqual(response.status, 200)
        payload = await response.json()
        runtime = payload["snapshot"]["runtime"]
        self.assertFalse(runtime["dry_run"])
        self.assertFalse(runtime["require_step_selection_for_live"])
        self.assertFalse(runtime["allow_fallback_in_live"])
        self.assertEqual(runtime["allowed_live_steps"], [])
        self.assertFalse(payload["integrations"]["github"]["useOriginRemoteFallback"])

    async def test_bootstrap_rejects_in_repo_config_override_that_changes_artifacts_root(self) -> None:
        alt_dir = os.path.join(self.repo_path, "configs")
        os.makedirs(alt_dir, exist_ok=True)
        alt_config_path = os.path.join(alt_dir, "alt_config.yaml")
        with open(alt_config_path, "w", encoding="utf-8") as handle:
            handle.write(
                textwrap.dedent(
                    f"""
                    runtime:
                      pipeline: demo_pipeline
                      dry_run: true
                      artifacts_dir: {self.external_dir.name}

                    profiles:
                      codex_local:
                        agent: codex
                        mode: cli
                        command:
                          - echo
                          - "{{prompt}}"

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
                            {{user_request}}
                    """
                ).strip()
            )
            handle.write("\n")

        response = await self.client.get("/api/bootstrap", params={"configPath": "configs/alt_config.yaml"})
        self.assertEqual(response.status, 400)
        self.assertIn("cannot change the artifacts root", await response.text())

    async def test_bootstrap_rejects_repo_override_outside_configured_root(self) -> None:
        response = await self.client.get("/api/bootstrap", params={"repoPath": self.external_dir.name})
        self.assertEqual(response.status, 400)
        self.assertIn("frame-ancestors 'none'", response.headers["Content-Security-Policy"])
        self.assertEqual(response.headers["X-Frame-Options"], "DENY")
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
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

    async def test_history_endpoint_tolerates_config_disappearing_after_initial_load(self) -> None:
        run_dir = os.path.join(self.repo_path, ".openclaw", "runs", "run-1")
        os.makedirs(run_dir, exist_ok=True)
        with open(os.path.join(run_dir, "summary.json"), "w", encoding="utf-8") as handle:
            json.dump({"run_id": "run-1", "plan": [], "results": [], "success": True}, handle)
        with open(os.path.join(run_dir, "context.json"), "w", encoding="utf-8") as handle:
            json.dump({"repo_path": self.repo_path, "user_request": "demo"}, handle)

        loaded = load_app_config(self.config_path)
        with mock.patch(
            "openclaw_v2.web.load_app_config",
            side_effect=[loaded, FileNotFoundError("config vanished after first load")],
        ):
            response = await self.client.get("/api/history/run-1")

        self.assertEqual(response.status, 200)
        payload = await response.json()
        self.assertEqual(payload["runId"], "run-1")

    async def test_history_endpoint_skips_files_that_disappear_during_listing(self) -> None:
        run_dir = os.path.join(self.repo_path, ".openclaw", "runs", "run-list-race")
        prompt_path = Path(run_dir) / "prompts" / "implement.txt"
        os.makedirs(prompt_path.parent, exist_ok=True)
        with open(os.path.join(run_dir, "summary.json"), "w", encoding="utf-8") as handle:
            json.dump({"run_id": "run-list-race", "plan": [], "results": [], "success": True}, handle)
        with open(os.path.join(run_dir, "context.json"), "w", encoding="utf-8") as handle:
            json.dump({"repo_path": self.repo_path, "user_request": "demo"}, handle)
        prompt_path.write_text("hello prompt\n", encoding="utf-8")

        path_cls = prompt_path.__class__
        real_stat = path_cls.stat

        def flaky_is_file(path_self, *args, **kwargs):
            return os.path.isfile(path_self)

        def flaky_stat(path_self, *args, **kwargs):
            if path_self.name == "implement.txt" and path_self.parent.name == "prompts":
                raise FileNotFoundError("artifact disappeared during listing")
            return real_stat(path_self, *args, **kwargs)

        with mock.patch.object(path_cls, "is_file", autospec=True, side_effect=flaky_is_file):
            with mock.patch.object(path_cls, "stat", autospec=True, side_effect=flaky_stat):
                response = await self.client.get("/api/history/run-list-race")

        self.assertEqual(response.status, 200)
        payload = await response.json()
        self.assertEqual(payload["runId"], "run-list-race")
        self.assertEqual([item["path"] for item in payload["files"]], ["context.json", "summary.json"])

    async def test_history_endpoint_tolerates_artifact_tree_glob_failure(self) -> None:
        run_dir = os.path.join(self.repo_path, ".openclaw", "runs", "run-rglob-race")
        os.makedirs(os.path.join(run_dir, "prompts"), exist_ok=True)
        with open(os.path.join(run_dir, "summary.json"), "w", encoding="utf-8") as handle:
            json.dump({"run_id": "run-rglob-race", "plan": [], "results": [], "success": True}, handle)
        with open(os.path.join(run_dir, "context.json"), "w", encoding="utf-8") as handle:
            json.dump({"repo_path": self.repo_path, "user_request": "demo"}, handle)

        path_cls = Path(self.repo_path).__class__
        real_rglob = path_cls.rglob

        def flaky_rglob(path_self, pattern):
            if path_self.name == "run-rglob-race":
                raise FileNotFoundError("artifact tree disappeared during glob")
            return real_rglob(path_self, pattern)

        with mock.patch.object(path_cls, "rglob", autospec=True, side_effect=flaky_rglob):
            response = await self.client.get("/api/history/run-rglob-race")

        self.assertEqual(response.status, 200)
        payload = await response.json()
        self.assertEqual(payload["runId"], "run-rglob-race")
        self.assertEqual(payload["files"], [])

    async def test_history_file_endpoint_returns_content_if_file_disappears_after_read(self) -> None:
        run_dir = os.path.join(self.repo_path, ".openclaw", "runs", "run-file-race")
        prompt_text = "hello prompt\n"

        class VanishingArtifact:
            def read_bytes(self) -> bytes:
                return prompt_text.encode("utf-8")

            def stat(self):
                raise FileNotFoundError("artifact disappeared after read")

        with mock.patch("openclaw_v2.web._safe_run_path", return_value=VanishingArtifact()):
            response = await self.client.get("/api/history/run-file-race/file?path=prompts/implement.txt")

        self.assertEqual(response.status, 200)
        payload = await response.json()
        self.assertEqual(payload["path"], "prompts/implement.txt")
        self.assertEqual(payload["content"], prompt_text)
        self.assertEqual(payload["size"], len(prompt_text.encode("utf-8")))
        self.assertFalse(payload["truncated"])
        self.assertEqual(payload["encoding"], "utf-8")

    async def test_history_file_endpoint_uses_original_size_when_stat_disappears_after_truncation(self) -> None:
        run_dir = os.path.join(self.repo_path, ".openclaw", "runs", "run-truncated-race")
        prompt_text = "x" * 200_100

        class TruncatedArtifact:
            def read_bytes(self) -> bytes:
                return prompt_text.encode("utf-8")

            def stat(self):
                raise FileNotFoundError("artifact disappeared after truncation")

        with mock.patch("openclaw_v2.web._safe_run_path", return_value=TruncatedArtifact()):
            response = await self.client.get("/api/history/run-truncated-race/file?path=prompts/implement.txt")

        self.assertEqual(response.status, 200)
        payload = await response.json()
        self.assertEqual(payload["size"], len(prompt_text.encode("utf-8")))
        self.assertTrue(payload["truncated"])

    async def test_history_endpoint_rejects_malformed_summary_json(self) -> None:
        run_dir = os.path.join(self.repo_path, ".openclaw", "runs", "run-bad-summary")
        os.makedirs(run_dir, exist_ok=True)
        with open(os.path.join(run_dir, "summary.json"), "w", encoding="utf-8") as handle:
            handle.write("{")

        response = await self.client.get("/api/history/run-bad-summary")

        self.assertEqual(response.status, 400)
        self.assertIn("frame-ancestors 'none'", response.headers["Content-Security-Policy"])
        self.assertEqual(response.headers["X-Frame-Options"], "DENY")
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
        self.assertIn("Run summary is not valid JSON", await response.text())

    async def test_history_endpoint_rejects_non_object_summary_json(self) -> None:
        run_dir = os.path.join(self.repo_path, ".openclaw", "runs", "run-array-summary")
        os.makedirs(run_dir, exist_ok=True)
        with open(os.path.join(run_dir, "summary.json"), "w", encoding="utf-8") as handle:
            json.dump([], handle)

        response = await self.client.get("/api/history/run-array-summary")

        self.assertEqual(response.status, 400)
        self.assertIn("Run summary must be a JSON object", await response.text())

    async def test_history_endpoint_rejects_non_object_context_json(self) -> None:
        run_dir = os.path.join(self.repo_path, ".openclaw", "runs", "run-array-context")
        os.makedirs(run_dir, exist_ok=True)
        with open(os.path.join(run_dir, "summary.json"), "w", encoding="utf-8") as handle:
            json.dump({"run_id": "run-array-context", "plan": [], "results": [], "success": True}, handle)
        with open(os.path.join(run_dir, "context.json"), "w", encoding="utf-8") as handle:
            json.dump([], handle)

        response = await self.client.get("/api/history/run-array-context")

        self.assertEqual(response.status, 400)
        self.assertIn("Run context must be a JSON object", await response.text())

    async def test_history_endpoint_tolerates_malformed_preflight_json(self) -> None:
        run_dir = os.path.join(self.repo_path, ".openclaw", "runs", "run-bad-preflight")
        os.makedirs(os.path.join(run_dir, "metadata"), exist_ok=True)
        with open(os.path.join(run_dir, "summary.json"), "w", encoding="utf-8") as handle:
            json.dump({"run_id": "run-bad-preflight", "plan": [], "results": [], "success": True}, handle)
        with open(os.path.join(run_dir, "metadata", "preflight.json"), "w", encoding="utf-8") as handle:
            handle.write("{")

        response = await self.client.get("/api/history/run-bad-preflight")

        self.assertEqual(response.status, 200)
        payload = await response.json()
        self.assertIsNone(payload["preflight"])

    async def test_history_endpoint_returns_404_if_summary_disappears_during_read(self) -> None:
        run_dir = os.path.join(self.repo_path, ".openclaw", "runs", "run-vanish")
        os.makedirs(run_dir, exist_ok=True)
        with open(os.path.join(run_dir, "summary.json"), "w", encoding="utf-8") as handle:
            json.dump({"run_id": "run-vanish", "plan": [], "results": [], "success": True}, handle)

        real_open = Path.open

        def flaky_open(path_self, *args, **kwargs):
            if path_self.as_posix().endswith("/run-vanish/summary.json"):
                raise FileNotFoundError("summary disappeared")
            return real_open(path_self, *args, **kwargs)

        with mock.patch.object(Path, "open", autospec=True, side_effect=flaky_open):
            response = await self.client.get("/api/history/run-vanish")

        self.assertEqual(response.status, 404)
        self.assertIn("Run summary not found", await response.text())

    async def test_history_endpoint_returns_404_if_run_directory_disappears_during_stamp_read(self) -> None:
        run_dir = os.path.join(self.repo_path, ".openclaw", "runs", "run-stamp-vanish")
        os.makedirs(run_dir, exist_ok=True)
        with open(os.path.join(run_dir, "summary.json"), "w", encoding="utf-8") as handle:
            json.dump({"run_id": "run-stamp-vanish", "plan": [], "results": [], "success": True}, handle)

        path_cls = Path(self.repo_path).__class__
        real_stat = path_cls.stat

        def flaky_stat(path_self, *args, **kwargs):
            if path_self.as_posix().endswith("/run-stamp-vanish"):
                raise FileNotFoundError("run directory disappeared during stamp read")
            return real_stat(path_self, *args, **kwargs)

        with mock.patch.object(path_cls, "stat", autospec=True, side_effect=flaky_stat):
            response = await self.client.get("/api/history/run-stamp-vanish")

        self.assertEqual(response.status, 404)
        self.assertIn("Run summary not found", await response.text())

    async def test_history_endpoint_tolerates_non_list_summary_sections(self) -> None:
        run_dir = os.path.join(self.repo_path, ".openclaw", "runs", "run-weird-summary")
        os.makedirs(run_dir, exist_ok=True)
        with open(os.path.join(run_dir, "summary.json"), "w", encoding="utf-8") as handle:
            json.dump({"run_id": "run-weird-summary", "plan": {}, "results": {}, "success": True}, handle)

        response = await self.client.get("/api/history/run-weird-summary")

        self.assertEqual(response.status, 200)
        payload = await response.json()
        self.assertEqual(payload["insights"]["statusCounts"], {})
        self.assertEqual(payload["insights"]["stepIds"], [])

    async def test_history_file_endpoint_rejects_path_escape_attempts(self) -> None:
        run_dir = os.path.join(self.repo_path, ".openclaw", "runs", "run-escape")
        os.makedirs(run_dir, exist_ok=True)
        with open(os.path.join(run_dir, "summary.json"), "w", encoding="utf-8") as handle:
            json.dump({"run_id": "run-escape", "plan": [], "results": [], "success": True}, handle)

        response = await self.client.get("/api/history/run-escape/file?path=../summary.json")

        self.assertEqual(response.status, 400)
        self.assertIn("escapes run directory", await response.text())

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

    async def test_history_compare_treats_string_success_flags_conservatively(self) -> None:
        runs_root = os.path.join(self.repo_path, ".openclaw", "runs")
        os.makedirs(runs_root, exist_ok=True)

        run_a = os.path.join(runs_root, "run-string-a")
        os.makedirs(run_a, exist_ok=True)
        with open(os.path.join(run_a, "summary.json"), "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "run_id": "run-string-a",
                    "plan": [{"id": "publish_branch", "title": "Publish branch"}],
                    "results": [
                        {
                            "work_item_id": "publish_branch",
                            "status": "succeeded",
                            "mode": "cli",
                            "artifacts": {"source_branch": "branch-a"},
                        }
                    ],
                    "success": "true",
                },
                handle,
            )
        with open(os.path.join(run_a, "context.json"), "w", encoding="utf-8") as handle:
            json.dump({"repo_path": self.repo_path, "user_request": "alpha"}, handle)

        run_b = os.path.join(runs_root, "run-string-b")
        os.makedirs(run_b, exist_ok=True)
        with open(os.path.join(run_b, "summary.json"), "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "run_id": "run-string-b",
                    "plan": [{"id": "publish_branch", "title": "Publish branch"}],
                    "results": [
                        {
                            "work_item_id": "publish_branch",
                            "status": "blocked",
                            "mode": "cli",
                            "artifacts": {"source_branch": "branch-b"},
                        }
                    ],
                    "success": "false",
                },
                handle,
            )
        with open(os.path.join(run_b, "context.json"), "w", encoding="utf-8") as handle:
            json.dump({"repo_path": self.repo_path, "user_request": "beta"}, handle)

        response = await self.client.post("/api/history/compare", json={"runIds": ["run-string-a", "run-string-b"]})
        self.assertEqual(response.status, 200)
        payload = await response.json()
        self.assertFalse(payload["runs"][0]["success"])
        self.assertFalse(payload["runs"][1]["success"])

    async def test_history_compare_tolerates_malformed_insight_counts(self) -> None:
        malformed_left = {
            "runId": "left",
            "updatedAt": "2026-05-01T00:00:00Z",
            "summary": {"plan": [], "results": [], "success": True},
            "context": {"user_request": "alpha"},
            "insights": {
                "statusCounts": {"succeeded": "oops"},
                "github": {"branch": "branch-a", "workflow": "not-an-object"},
                "hermes": {"sessionCount": "bad"},
            },
        }
        malformed_right = {
            "runId": "right",
            "updatedAt": "2026-05-01T00:00:00Z",
            "summary": {"plan": [], "results": [], "success": True},
            "context": {"user_request": "beta"},
            "insights": {
                "statusCounts": {"succeeded": "still-bad"},
                "github": {"branch": "branch-a", "workflow": "also-not-an-object"},
                "hermes": {"sessionCount": "still-bad"},
            },
        }

        with mock.patch(
            "openclaw_v2.web._read_run_history",
            side_effect=[malformed_left, malformed_right],
        ):
            response = await self.client.post("/api/history/compare", json={"runIds": ["left", "right"]})

        self.assertEqual(response.status, 200)
        payload = await response.json()
        self.assertEqual(payload["comparison"]["hermesSessionDelta"], 0)
        self.assertEqual(payload["comparison"]["countDiffs"][0]["left"], 0)
        self.assertEqual(payload["comparison"]["countDiffs"][0]["right"], 0)

    async def test_history_compare_tolerates_non_list_summary_sections(self) -> None:
        malformed_left = {
            "runId": "left",
            "updatedAt": "2026-05-01T00:00:00Z",
            "summary": {"plan": {}, "results": {}, "success": True},
            "context": {"user_request": "alpha"},
            "insights": {
                "statusCounts": {},
                "github": {"branch": "branch-a"},
                "hermes": {"sessionCount": 0},
            },
        }
        malformed_right = {
            "runId": "right",
            "updatedAt": "2026-05-01T00:00:00Z",
            "summary": {"plan": {}, "results": {}, "success": True},
            "context": {"user_request": "beta"},
            "insights": {
                "statusCounts": {},
                "github": {"branch": "branch-b"},
                "hermes": {"sessionCount": 0},
            },
        }

        with mock.patch(
            "openclaw_v2.web._read_run_history",
            side_effect=[malformed_left, malformed_right],
        ):
            response = await self.client.post("/api/history/compare", json={"runIds": ["left", "right"]})

        self.assertEqual(response.status, 200)
        payload = await response.json()
        self.assertEqual(payload["comparison"]["stepDiffs"], [])
        self.assertTrue(payload["comparison"]["branchChanged"])

    async def test_history_compare_endpoint_rejects_invalid_run_ids_payloads(self) -> None:
        response = await self.client.post("/api/history/compare", json={"runIds": "run-a"})
        self.assertEqual(response.status, 400)
        self.assertIn("runIds must be a list", await response.text())

        response = await self.client.post("/api/history/compare", json={"runIds": ["run-a"]})
        self.assertEqual(response.status, 400)
        self.assertIn("Two run ids are required", await response.text())

        response = await self.client.post("/api/history/compare", json={"runIds": ["run-a", "run-b", "run-c"]})
        self.assertEqual(response.status, 400)
        self.assertIn("Two run ids are required", await response.text())

        response = await self.client.post("/api/history/compare", json={"runIds": ["run-a", 123]})
        self.assertEqual(response.status, 400)
        self.assertIn("runIds must contain non-empty strings", await response.text())

        response = await self.client.post("/api/history/compare", json={"runIds": ["run-a", "run-a"]})
        self.assertEqual(response.status, 400)
        self.assertIn("two different runs", await response.text())

    async def test_cleanup_endpoint_removes_run_directory(self) -> None:
        run_dir = os.path.join(self.repo_path, ".openclaw", "runs", "run-cleanup")
        os.makedirs(run_dir, exist_ok=True)
        with open(os.path.join(run_dir, "summary.json"), "w", encoding="utf-8") as handle:
            json.dump({"run_id": "run-cleanup", "plan": [], "results": [], "success": True}, handle)

        response = await self.client.post(
            "/api/history/run-cleanup/cleanup",
            json={},
            headers=self.housekeeping_headers,
        )
        self.assertEqual(response.status, 200)
        payload = await response.json()
        self.assertEqual(payload["runId"], "run-cleanup")
        self.assertFalse(os.path.exists(run_dir))

    async def test_cleanup_endpoint_tolerates_config_disappearing_after_initial_load(self) -> None:
        run_dir = os.path.join(self.repo_path, ".openclaw", "runs", "run-cleanup")
        os.makedirs(run_dir, exist_ok=True)
        with open(os.path.join(run_dir, "summary.json"), "w", encoding="utf-8") as handle:
            json.dump({"run_id": "run-cleanup", "plan": [], "results": [], "success": True}, handle)

        loaded = load_app_config(self.config_path)
        with mock.patch(
            "openclaw_v2.web.load_app_config",
            side_effect=[loaded, FileNotFoundError("config vanished after first load")],
        ):
            response = await self.client.post(
                "/api/history/run-cleanup/cleanup",
                json={},
                headers=self.housekeeping_headers,
            )

        self.assertEqual(response.status, 200)
        payload = await response.json()
        self.assertEqual(payload["runId"], "run-cleanup")
        self.assertFalse(os.path.exists(run_dir))

    async def test_cleanup_endpoint_tolerates_run_directory_disappearing_before_artifact_delete(self) -> None:
        run_dir = os.path.join(self.repo_path, ".openclaw", "runs", "run-cleanup-race")
        os.makedirs(run_dir, exist_ok=True)
        with open(os.path.join(run_dir, "summary.json"), "w", encoding="utf-8") as handle:
            json.dump({"run_id": "run-cleanup-race", "plan": [], "results": [], "success": True}, handle)

        def flaky_rmtree(path, *args, **kwargs):
            raise FileNotFoundError("run directory disappeared before artifact delete")

        with mock.patch("openclaw_v2.web.shutil.rmtree", side_effect=flaky_rmtree):
            response = await self.client.post(
                "/api/history/run-cleanup-race/cleanup",
                json={"removeWorktrees": False, "removeArtifacts": True},
                headers=self.housekeeping_headers,
            )

        self.assertEqual(response.status, 200)
        payload = await response.json()
        self.assertEqual(payload["runId"], "run-cleanup-race")
        self.assertTrue(any(item["type"] == "artifacts_delete" for item in payload["operations"]))

    async def test_cleanup_endpoint_marks_artifact_delete_errors_as_failures(self) -> None:
        run_dir = os.path.join(self.repo_path, ".openclaw", "runs", "run-cleanup-failure")
        os.makedirs(run_dir, exist_ok=True)
        with open(os.path.join(run_dir, "summary.json"), "w", encoding="utf-8") as handle:
            json.dump({"run_id": "run-cleanup-failure", "plan": [], "results": [], "success": True}, handle)

        with mock.patch("openclaw_v2.web.shutil.rmtree", side_effect=PermissionError("denied")):
            response = await self.client.post(
                "/api/history/run-cleanup-failure/cleanup",
                json={"removeWorktrees": False, "removeArtifacts": True},
                headers=self.housekeeping_headers,
            )

        self.assertEqual(response.status, 200)
        payload = await response.json()
        artifact_ops = [item for item in payload["operations"] if item["type"] == "artifacts_delete"]
        self.assertEqual(len(artifact_ops), 1)
        self.assertFalse(artifact_ops[0]["ok"])
        self.assertNotIn("skipped", artifact_ops[0])
        self.assertIn("denied", artifact_ops[0]["stderr"])

    async def test_cleanup_endpoint_skips_invalid_utf8_workspace_manifests(self) -> None:
        run_dir = os.path.join(self.repo_path, ".openclaw", "runs", "run-invalid-manifest")
        workspaces_dir = os.path.join(run_dir, "workspaces")
        os.makedirs(workspaces_dir, exist_ok=True)
        with open(os.path.join(run_dir, "summary.json"), "w", encoding="utf-8") as handle:
            json.dump({"run_id": "run-invalid-manifest", "plan": [], "results": [], "success": True}, handle)
        with open(os.path.join(workspaces_dir, "broken.json"), "wb") as handle:
            handle.write(b"\xff")

        response = await self.client.post(
            "/api/history/run-invalid-manifest/cleanup",
            json={"removeWorktrees": True, "removeArtifacts": False},
            headers=self.housekeeping_headers,
        )
        self.assertEqual(response.status, 200)
        payload = await response.json()
        self.assertEqual(payload["operations"], [])

    async def test_cleanup_endpoint_skips_workspace_manifests_that_disappear_during_read(self) -> None:
        run_dir = os.path.join(self.repo_path, ".openclaw", "runs", "run-vanish-manifest")
        workspaces_dir = os.path.join(run_dir, "workspaces")
        os.makedirs(workspaces_dir, exist_ok=True)
        with open(os.path.join(run_dir, "summary.json"), "w", encoding="utf-8") as handle:
            json.dump({"run_id": "run-vanish-manifest", "plan": [], "results": [], "success": True}, handle)
        manifest_path = os.path.join(workspaces_dir, "implement.json")
        with open(manifest_path, "w", encoding="utf-8") as handle:
            json.dump({"workspace_path": run_dir, "branch_name": "openclaw-run-vanish-manifest-implement"}, handle)

        path_cls = Path(self.repo_path).__class__
        real_open = path_cls.open

        def flaky_open(path_self, *args, **kwargs):
            if path_self.name == "implement.json" and path_self.parent.name == "workspaces":
                raise FileNotFoundError("workspace manifest disappeared during read")
            return real_open(path_self, *args, **kwargs)

        with mock.patch.object(path_cls, "open", autospec=True, side_effect=flaky_open):
            response = await self.client.post(
                "/api/history/run-vanish-manifest/cleanup",
                json={"removeWorktrees": True, "removeArtifacts": False},
                headers=self.housekeeping_headers,
            )

        self.assertEqual(response.status, 200)
        payload = await response.json()
        self.assertEqual(payload["operations"], [])

    async def test_cleanup_endpoint_tolerates_workspace_manifest_glob_failure(self) -> None:
        run_dir = os.path.join(self.repo_path, ".openclaw", "runs", "run-glob-race")
        workspaces_dir = os.path.join(run_dir, "workspaces")
        os.makedirs(workspaces_dir, exist_ok=True)
        with open(os.path.join(run_dir, "summary.json"), "w", encoding="utf-8") as handle:
            json.dump({"run_id": "run-glob-race", "plan": [], "results": [], "success": True}, handle)

        path_cls = Path(self.repo_path).__class__
        real_glob = path_cls.glob

        def flaky_glob(path_self, pattern):
            if path_self.name == "workspaces" and pattern == "*.json":
                raise FileNotFoundError("workspace manifest glob disappeared")
            return real_glob(path_self, pattern)

        with mock.patch.object(path_cls, "glob", autospec=True, side_effect=flaky_glob):
            response = await self.client.post(
                "/api/history/run-glob-race/cleanup",
                json={"removeWorktrees": True, "removeArtifacts": False},
                headers=self.housekeeping_headers,
            )

        self.assertEqual(response.status, 200)
        payload = await response.json()
        self.assertEqual(payload["operations"], [])

    async def test_cleanup_endpoint_requires_housekeeping_token(self) -> None:
        run_dir = os.path.join(self.repo_path, ".openclaw", "runs", "run-no-token")
        os.makedirs(run_dir, exist_ok=True)
        with open(os.path.join(run_dir, "summary.json"), "w", encoding="utf-8") as handle:
            json.dump({"run_id": "run-no-token", "plan": [], "results": [], "success": True}, handle)

        response = await self.client.post("/api/history/run-no-token/cleanup", json={})
        self.assertEqual(response.status, 403)
        self.assertIn("frame-ancestors 'none'", response.headers["Content-Security-Policy"])
        self.assertEqual(response.headers["X-Frame-Options"], "DENY")
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
        self.assertIn("confirmation token", await response.text())

    async def test_cleanup_endpoint_rejects_non_boolean_remove_flags(self) -> None:
        run_dir = os.path.join(self.repo_path, ".openclaw", "runs", "run-bad-flags")
        os.makedirs(run_dir, exist_ok=True)
        with open(os.path.join(run_dir, "summary.json"), "w", encoding="utf-8") as handle:
            json.dump({"run_id": "run-bad-flags", "plan": [], "results": [], "success": True}, handle)

        response = await self.client.post(
            "/api/history/run-bad-flags/cleanup",
            json={"removeArtifacts": "false"},
            headers=self.housekeeping_headers,
        )
        self.assertEqual(response.status, 400)
        self.assertIn("Content-Security-Policy", response.headers)
        self.assertIn("frame-ancestors 'none'", response.headers["Content-Security-Policy"])
        self.assertEqual(response.headers["X-Frame-Options"], "DENY")
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
        self.assertIn("removeArtifacts must be a boolean", await response.text())

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
                headers=self.housekeeping_headers,
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
                    headers=self.housekeeping_headers,
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

        response = await self.client.post(
            "/api/history/prune",
            json={"keepLatest": 1},
            headers=self.housekeeping_headers,
        )
        self.assertEqual(response.status, 200)
        payload = await response.json()
        self.assertEqual(len(payload["removed"]), 2)
        self.assertTrue(os.path.exists(os.path.join(runs_root, "run-c")))
        self.assertFalse(os.path.exists(os.path.join(runs_root, "run-a")))
        self.assertFalse(os.path.exists(os.path.join(runs_root, "run-b")))

    async def test_prune_endpoint_tolerates_config_disappearing_after_initial_load(self) -> None:
        runs_root = os.path.join(self.repo_path, ".openclaw", "runs")
        os.makedirs(runs_root, exist_ok=True)
        for index, run_id in enumerate(["run-a", "run-b", "run-c"], start=1):
            run_dir = os.path.join(runs_root, run_id)
            os.makedirs(run_dir, exist_ok=True)
            with open(os.path.join(run_dir, "summary.json"), "w", encoding="utf-8") as handle:
                json.dump({"run_id": run_id, "plan": [], "results": [], "success": True}, handle)
            os.utime(run_dir, (index, index))

        loaded = load_app_config(self.config_path)
        with mock.patch(
            "openclaw_v2.web.load_app_config",
            side_effect=[loaded, FileNotFoundError("config vanished after first load")],
        ):
            response = await self.client.post(
                "/api/history/prune",
                json={"keepLatest": 1, "removeWorktrees": False, "removeArtifacts": True},
                headers=self.housekeeping_headers,
            )

        self.assertEqual(response.status, 200)
        payload = await response.json()
        self.assertEqual(len(payload["removed"]), 2)

    async def test_prune_endpoint_skips_runs_if_run_directory_stat_disappears_during_sort(self) -> None:
        runs_root = os.path.join(self.repo_path, ".openclaw", "runs")
        os.makedirs(runs_root, exist_ok=True)
        for index, run_id in enumerate(["run-a", "run-stat-race", "run-c"], start=1):
            run_dir = os.path.join(runs_root, run_id)
            os.makedirs(run_dir, exist_ok=True)
            with open(os.path.join(run_dir, "summary.json"), "w", encoding="utf-8") as handle:
                json.dump({"run_id": run_id, "plan": [], "results": [], "success": True}, handle)
            os.utime(run_dir, (index, index))

        path_cls = Path(self.repo_path).__class__
        real_stat = path_cls.stat

        def flaky_stat(path_self, *args, **kwargs):
            if path_self.name == "run-stat-race":
                raise FileNotFoundError("run disappeared while sorting prune candidates")
            return real_stat(path_self, *args, **kwargs)

        with mock.patch.object(path_cls, "stat", autospec=True, side_effect=flaky_stat):
            response = await self.client.post(
                "/api/history/prune",
                json={"keepLatest": 0},
                headers=self.housekeeping_headers,
            )

        self.assertEqual(response.status, 200)
        payload = await response.json()
        self.assertEqual(len(payload["removed"]), 2)
        self.assertTrue(os.path.exists(os.path.join(runs_root, "run-stat-race")))
        self.assertFalse(os.path.exists(os.path.join(runs_root, "run-a")))
        self.assertFalse(os.path.exists(os.path.join(runs_root, "run-c")))

    async def test_prune_endpoint_rejects_non_numeric_keep_latest(self) -> None:
        response = await self.client.post(
            "/api/history/prune",
            json={"keepLatest": "abc"},
            headers=self.housekeeping_headers,
        )
        self.assertEqual(response.status, 400)
        self.assertIn("keepLatest", await response.text())

    async def test_prune_endpoint_rejects_boolean_keep_latest(self) -> None:
        response = await self.client.post(
            "/api/history/prune",
            json={"keepLatest": True},
            headers=self.housekeeping_headers,
        )
        self.assertEqual(response.status, 400)
        self.assertIn("Content-Security-Policy", response.headers)
        self.assertIn("frame-ancestors 'none'", response.headers["Content-Security-Policy"])
        self.assertEqual(response.headers["X-Frame-Options"], "DENY")
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
        self.assertIn("keepLatest must be an integer", await response.text())

    async def test_prune_endpoint_rejects_negative_keep_latest(self) -> None:
        response = await self.client.post(
            "/api/history/prune",
            json={"keepLatest": -1},
            headers=self.housekeeping_headers,
        )
        self.assertEqual(response.status, 400)
        self.assertIn("frame-ancestors 'none'", response.headers["Content-Security-Policy"])
        self.assertEqual(response.headers["X-Frame-Options"], "DENY")
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
        self.assertIn("greater than or equal to 0", await response.text())

    async def test_prune_endpoint_rejects_non_boolean_remove_flags(self) -> None:
        response = await self.client.post(
            "/api/history/prune",
            json={"keepLatest": 1, "removeWorktrees": "false"},
            headers=self.housekeeping_headers,
        )
        self.assertEqual(response.status, 400)
        self.assertIn("Content-Security-Policy", response.headers)
        self.assertIn("frame-ancestors 'none'", response.headers["Content-Security-Policy"])
        self.assertEqual(response.headers["X-Frame-Options"], "DENY")
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
        self.assertIn("removeWorktrees must be a boolean", await response.text())

    async def test_prune_endpoint_requires_housekeeping_token(self) -> None:
        response = await self.client.post("/api/history/prune", json={"keepLatest": 1})
        self.assertEqual(response.status, 403)
        self.assertIn("confirmation token", await response.text())


class WebRunTaskTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.external_dir = tempfile.TemporaryDirectory()
        self.repo_path = self.temp_dir.name
        self.config_path = os.path.join(self.repo_path, "config_v2.yaml")
        _write_minimal_config(self.config_path)
        self.app = create_web_app(
            config_path=self.config_path,
            repo_path=self.repo_path,
        )
        self.client = TestClient(
            TestServer(
                self.app
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

    async def test_task_create_rejects_invalid_json_payloads(self) -> None:
        response = await self.client.post("/api/tasks", data="{", headers={"Content-Type": "application/json"})
        self.assertEqual(response.status, 400)
        self.assertIn("Invalid JSON", await response.text())

    async def test_task_create_rejects_non_object_json_payloads(self) -> None:
        response = await self.client.post("/api/tasks", json=["run"])
        self.assertEqual(response.status, 400)
        self.assertIn("must be an object", await response.text())

    async def test_task_create_rejects_non_boolean_live_flag(self) -> None:
        response = await self.client.post(
            "/api/tasks",
            json={
                "action": "run",
                "repoPath": self.repo_path,
                "configPath": self.config_path,
                "request": "Demo run",
                "live": "false",
            },
        )
        self.assertEqual(response.status, 400)
        self.assertIn("Content-Security-Policy", response.headers)
        self.assertIn("frame-ancestors 'none'", response.headers["Content-Security-Policy"])
        self.assertEqual(response.headers["X-Frame-Options"], "DENY")
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
        self.assertIn("live must be a boolean", await response.text())

    async def test_task_create_rejects_non_string_steps_items(self) -> None:
        response = await self.client.post(
            "/api/tasks",
            json={
                "action": "run",
                "repoPath": self.repo_path,
                "configPath": self.config_path,
                "request": "Demo run",
                "steps": [123],
                "live": False,
            },
        )
        self.assertEqual(response.status, 400)
        self.assertIn("Content-Security-Policy", response.headers)
        self.assertIn("frame-ancestors 'none'", response.headers["Content-Security-Policy"])
        self.assertEqual(response.headers["X-Frame-Options"], "DENY")
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
        self.assertIn("steps must be a comma-separated string", await response.text())
        self.assertEqual(len(self.app[APP_TASK_MANAGER].tasks), 0)

    async def test_task_create_rejects_blank_run_request_without_queuing_task(self) -> None:
        response = await self.client.post(
            "/api/tasks",
            json={
                "action": "run",
                "repoPath": self.repo_path,
                "configPath": self.config_path,
                "request": "   ",
                "steps": ["implement"],
                "live": False,
            },
        )
        self.assertEqual(response.status, 400)
        self.assertIn("frame-ancestors 'none'", response.headers["Content-Security-Policy"])
        self.assertEqual(response.headers["X-Frame-Options"], "DENY")
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
        self.assertIn("Request text is required", await response.text())
        self.assertEqual(len(self.app[APP_TASK_MANAGER].tasks), 0)

    async def test_task_create_rejects_unknown_steps_without_queuing_task(self) -> None:
        response = await self.client.post(
            "/api/tasks",
            json={
                "action": "run",
                "repoPath": self.repo_path,
                "configPath": self.config_path,
                "request": "Demo run",
                "steps": ["missing-step"],
                "live": False,
            },
        )
        self.assertEqual(response.status, 400)
        self.assertIn("frame-ancestors 'none'", response.headers["Content-Security-Policy"])
        self.assertEqual(response.headers["X-Frame-Options"], "DENY")
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
        self.assertIn("Unknown step ids", await response.text())
        self.assertEqual(len(self.app[APP_TASK_MANAGER].tasks), 0)

    async def test_task_create_rejects_config_override_that_changes_worktrees_root(self) -> None:
        alt_dir = os.path.join(self.repo_path, "configs")
        os.makedirs(alt_dir, exist_ok=True)
        alt_config_path = os.path.join(alt_dir, "alt_config.yaml")
        with open(alt_config_path, "w", encoding="utf-8") as handle:
            handle.write(
                textwrap.dedent(
                    f"""
                    runtime:
                      pipeline: demo_pipeline
                      dry_run: true
                      worktrees_dir: {self.external_dir.name}

                    profiles:
                      codex_local:
                        agent: codex
                        mode: cli
                        command:
                          - echo
                          - "{{prompt}}"

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
                            {{user_request}}
                    """
                ).strip()
            )
            handle.write("\n")

        response = await self.client.post(
            "/api/tasks",
            json={
                "action": "doctor",
                "repoPath": self.repo_path,
                "configPath": alt_config_path,
            },
        )
        self.assertEqual(response.status, 400)
        self.assertIn("cannot change the worktrees root", await response.text())


class WebHermesInsightTests(unittest.TestCase):
    def test_record_summary_is_classified_as_recorder_in_run_insights(self) -> None:
        summary = {
            "results": [
                {
                    "work_item_id": "record_summary",
                    "status": "succeeded",
                    "artifacts": {
                        "hermes_session_id": "session-1",
                        "hermes_provider": "custom",
                        "hermes_model": "gpt-5",
                        "hermes_toolsets": ["file"],
                        "hermes_skills": ["repo-review"],
                    },
                },
                {
                    "work_item_id": "triage",
                    "status": "succeeded",
                    "artifacts": {"hermes_session_id": "session-2"},
                },
            ],
            "plan": [],
        }

        insights = _summarize_run_insights(
            summary,
            {},
            None,
            default_github_repo="",
            github_base_branch="main",
        )

        roles = {item["stepId"]: item["role"] for item in insights["hermes"]["roles"]}
        self.assertEqual(roles["record_summary"], "recorder")
        self.assertEqual(roles["triage"], "supervisor")
        self.assertEqual(insights["hermes"]["sessionCount"], 2)
        self.assertTrue(insights["hermes"]["used"])


class WebGitHubInsightTests(unittest.TestCase):
    def test_collect_review_failed_jobs_are_preserved_in_run_insights(self) -> None:
        summary = {
            "results": [
                {
                    "work_item_id": "collect_review",
                    "status": "failed",
                    "artifacts": {
                        "workflow_run_id": "123456789",
                        "workflow_run_url": "https://github.com/owner/repo/actions/runs/123456789",
                        "workflow_status": "completed",
                        "workflow_conclusion": "failure",
                        "workflow_failed_job_count": 2,
                        "workflow_failed_jobs": "lint, tests",
                    },
                }
            ],
            "plan": [],
        }

        insights = _summarize_run_insights(
            summary,
            {},
            None,
            default_github_repo="",
            github_base_branch="main",
        )

        workflow = insights["github"]["workflow"]
        cards = insights["github"]["cards"]
        self.assertEqual(workflow["status"], "completed")
        self.assertEqual(workflow["conclusion"], "failure")
        self.assertEqual(workflow["failedJobCount"], 2)
        self.assertEqual(workflow["failedJobs"], "lint, tests")
        self.assertEqual(workflow["id"], "123456789")
        self.assertEqual(cards[0]["workflowFailedJobs"], "lint, tests")
        self.assertEqual(cards[0]["workflowFailedJobCount"], 2)
