import json
import os
import tempfile
import unittest
from unittest import mock

from openclaw_v2.config import load_app_config
from openclaw_v2.models import AgentType, ExecutionMode, WorkItem
from openclaw_v2.preflight import CheckStatus, PreflightRunner


class _FakeProcess:
    def __init__(self, returncode: int, stdout: str, stderr: str = "") -> None:
        self.returncode = returncode
        self._stdout = stdout.encode("utf-8")
        self._stderr = stderr.encode("utf-8")

    async def communicate(self):
        return self._stdout, self._stderr


class PreflightOpenClawTests(unittest.IsolatedAsyncioTestCase):
    def test_assignment_check_warns_when_fallback_is_used(self) -> None:
        config = load_app_config("config_v2.yaml")
        runner = PreflightRunner(config)
        plan = [
            WorkItem(
                id="implement",
                title="Implement main changes locally",
                profile="cursor_local",
                agent=AgentType.CURSOR,
                mode=ExecutionMode.CLI,
                prompt_template="",
                assignment="implement_local",
                assignment_source="openclaw",
                managed_agent="cursor_editor",
                assignment_reason="Resolved by assignment implement_local to managed agent cursor_editor. Fallback was used.",
                fallback_used=True,
                fallback_chain=["cursor_editor"],
            )
        ]

        checks = runner._check_managed_assignments(plan)

        self.assertEqual(checks[0].status, CheckStatus.WARNING)
        self.assertIn("fallback managed agent `cursor_editor`", checks[0].message)

    def test_planning_block_check_warns_for_blocked_step(self) -> None:
        config = load_app_config("config_v2.yaml")
        runner = PreflightRunner(config)
        plan = [
            WorkItem(
                id="implement",
                title="Implement main changes locally",
                profile="",
                agent=AgentType.SYSTEM,
                mode=ExecutionMode.SYSTEM,
                prompt_template="",
                assignment="implement_local",
                required_capabilities=["implement"],
                assignment_candidates=["codex_builder", "cursor_editor"],
                assignment_attempts=[
                    "codex_builder: managed agent is disabled.",
                    "cursor_editor: missing capabilities implement.",
                ],
                planning_blocked_reason="Assignment `implement_local` could not resolve a usable managed agent.",
            )
        ]

        checks = runner._check_planning_blocks(plan)

        self.assertEqual(checks[0].status, CheckStatus.WARNING)
        self.assertIn("blocked before execution", checks[0].message)
        self.assertEqual(checks[0].details["assignment_candidates"], ["codex_builder", "cursor_editor"])

    async def test_openclaw_workspace_at_repo_root_warns(self) -> None:
        config = load_app_config("config_v2.yaml")
        config.profiles["openclaw_local"].openclaw_agent_id = "openclaw-control"
        runner = PreflightRunner(config)
        plan = [
            WorkItem(
                id="triage",
                title="Triage user request with local OpenClaw",
                profile="openclaw_local",
                agent=AgentType.OPENCLAW,
                mode=ExecutionMode.OPENCLAW,
                prompt_template="",
            )
        ]
        repo_path = "/tmp/repo"
        agent_list = json.dumps(
            [
                {
                    "id": "openclaw-control",
                    "workspace": repo_path,
                    "agentDir": "/tmp/agent",
                }
            ]
        )

        with mock.patch("openclaw_v2.preflight.shutil.which", return_value="/usr/bin/openclaw"):
            with mock.patch(
                "openclaw_v2.preflight.asyncio.create_subprocess_exec",
                new=mock.AsyncMock(return_value=_FakeProcess(0, agent_list)),
            ):
                checks = await runner._check_openclaw_profiles(repo_path, plan)

        self.assertEqual(checks[0].status, CheckStatus.PASSED)
        self.assertEqual(checks[1].status, CheckStatus.WARNING)
        self.assertIn("repo root", checks[1].message)

    async def test_openclaw_workspace_outside_repo_passes(self) -> None:
        config = load_app_config("config_v2.yaml")
        config.profiles["openclaw_local"].openclaw_agent_id = "openclaw-control-ext"
        runner = PreflightRunner(config)
        plan = [
            WorkItem(
                id="triage",
                title="Triage user request with local OpenClaw",
                profile="openclaw_local",
                agent=AgentType.OPENCLAW,
                mode=ExecutionMode.OPENCLAW,
                prompt_template="",
            )
        ]
        repo_path = "/tmp/repo"
        agent_list = json.dumps(
            [
                {
                    "id": "openclaw-control-ext",
                    "workspace": "/tmp/openclaw-workspace",
                    "agentDir": "/tmp/agent",
                }
            ]
        )

        with mock.patch("openclaw_v2.preflight.shutil.which", return_value="/usr/bin/openclaw"):
            with mock.patch(
                "openclaw_v2.preflight.asyncio.create_subprocess_exec",
                new=mock.AsyncMock(return_value=_FakeProcess(0, agent_list)),
            ):
                checks = await runner._check_openclaw_profiles(repo_path, plan)

        self.assertEqual(checks[0].status, CheckStatus.PASSED)
        self.assertEqual(checks[1].status, CheckStatus.PASSED)
        self.assertIn("isolated from the repository root", checks[1].message)

    async def test_openclaw_missing_agent_id_lists_available_agents(self) -> None:
        config = load_app_config("config_v2.yaml")
        config.profiles["openclaw_local"].openclaw_agent_id = ""
        runner = PreflightRunner(config)
        plan = [
            WorkItem(
                id="triage",
                title="Triage user request with local OpenClaw",
                profile="openclaw_local",
                agent=AgentType.OPENCLAW,
                mode=ExecutionMode.OPENCLAW,
                prompt_template="",
            )
        ]
        agent_list = json.dumps(
            [
                {"id": "main", "workspace": "/tmp/openclaw-main", "agentDir": "/tmp/main"},
                {"id": "openclaw-control-ext", "workspace": "/tmp/openclaw-ext", "agentDir": "/tmp/ext"},
            ]
        )

        with mock.patch("openclaw_v2.preflight.shutil.which", return_value="/usr/bin/openclaw"):
            with mock.patch(
                "openclaw_v2.preflight.asyncio.create_subprocess_exec",
                new=mock.AsyncMock(return_value=_FakeProcess(0, agent_list)),
            ):
                checks = await runner._check_openclaw_profiles("/tmp/repo", plan)

        self.assertEqual(checks[0].status, CheckStatus.WARNING)
        self.assertIn("Available local agents: main, openclaw-control-ext.", checks[0].message)
        self.assertEqual(checks[0].details["available_agent_ids"], ["main", "openclaw-control-ext"])

    def test_github_workflow_preflight_fails_when_file_is_missing_in_live_mode(self) -> None:
        config = load_app_config("config_v2.yaml")
        config.runtime.dry_run = False
        runner = PreflightRunner(config)
        plan = [
            WorkItem(
                id="dispatch_review",
                title="Trigger GitHub review workflow",
                profile="github_review_workflow",
                agent=AgentType.COPILOT,
                mode=ExecutionMode.GITHUB,
                prompt_template="",
            )
        ]

        checks = runner._check_github_workflow_files("/tmp/repo", plan)

        self.assertEqual(checks[0].status, CheckStatus.FAILED)
        self.assertIn("was not found", checks[0].message)
        self.assertTrue(checks[0].details["workflow_path"].endswith(os.path.join(".github", "workflows", "openclaw-review.yml")))

    def test_github_workflow_preflight_passes_when_file_exists(self) -> None:
        config = load_app_config("config_v2.yaml")
        runner = PreflightRunner(config)
        plan = [
            WorkItem(
                id="dispatch_review",
                title="Trigger GitHub review workflow",
                profile="github_review_workflow",
                agent=AgentType.COPILOT,
                mode=ExecutionMode.GITHUB,
                prompt_template="",
            )
        ]

        with tempfile.TemporaryDirectory() as repo_path:
            os.makedirs(os.path.join(repo_path, ".github", "workflows"), exist_ok=True)
            workflow_path = os.path.join(repo_path, ".github", "workflows", "openclaw-review.yml")
            with open(workflow_path, "w", encoding="utf-8") as handle:
                handle.write("name: test\n")

            checks = runner._check_github_workflow_files(repo_path, plan)

        self.assertEqual(checks[0].status, CheckStatus.PASSED)
        self.assertIn("exists locally", checks[0].message)
        self.assertTrue(checks[0].details["workflow_path"].endswith("openclaw-review.yml"))

    async def test_dirty_repo_blocks_live_isolated_cli_steps(self) -> None:
        config = load_app_config("config_v2.yaml")
        config.runtime.dry_run = False
        runner = PreflightRunner(config)
        plan = [
            WorkItem(
                id="implement",
                title="Implement main changes locally",
                profile="codex_local",
                agent=AgentType.CODEX,
                mode=ExecutionMode.CLI,
                prompt_template="",
            )
        ]

        with mock.patch(
            "openclaw_v2.preflight.asyncio.create_subprocess_exec",
            new=mock.AsyncMock(return_value=_FakeProcess(0, " M README.md\n?? docs/new.md\n")),
        ):
            check = await runner._check_repo_dirty_for_isolated_cli_steps("/tmp/repo", plan)

        assert check is not None
        self.assertEqual(check.status, CheckStatus.FAILED)
        self.assertIn("commit or stash changes before live runs", check.message)
        self.assertEqual(check.details["affected_steps"], ["implement"])
        self.assertEqual(check.details["changed_paths"], ["README.md", "docs/new.md"])

    async def test_clean_repo_passes_isolated_cli_dirty_check(self) -> None:
        config = load_app_config("config_v2.yaml")
        runner = PreflightRunner(config)
        plan = [
            WorkItem(
                id="implement",
                title="Implement main changes locally",
                profile="codex_local",
                agent=AgentType.CODEX,
                mode=ExecutionMode.CLI,
                prompt_template="",
            )
        ]

        with mock.patch(
            "openclaw_v2.preflight.asyncio.create_subprocess_exec",
            new=mock.AsyncMock(return_value=_FakeProcess(0, "")),
        ):
            check = await runner._check_repo_dirty_for_isolated_cli_steps("/tmp/repo", plan)

        assert check is not None
        self.assertEqual(check.status, CheckStatus.PASSED)
        self.assertIn("working tree is clean", check.message)

    async def test_github_repo_can_resolve_from_origin_when_fallback_is_enabled(self) -> None:
        config = load_app_config("config_v2.yaml")
        config.github.repo = ""
        config.github.use_origin_remote_fallback = True
        runner = PreflightRunner(config)

        with mock.patch(
            "openclaw_v2.github_support.asyncio.create_subprocess_exec",
            new=mock.AsyncMock(return_value=_FakeProcess(0, "git@github.com:owner/repo.git")),
        ):
            check = await runner._check_github_repo_resolution("/tmp/repo")

        self.assertEqual(check.status, CheckStatus.PASSED)
        self.assertEqual(check.details["repo"], "owner/repo")
        self.assertEqual(check.details["source"], "git_origin")


if __name__ == "__main__":
    unittest.main()
