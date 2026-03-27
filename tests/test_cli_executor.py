import asyncio
import os
import unittest
from unittest import mock

from openclaw_v2.config import load_app_config
from openclaw_v2.executors.cli import CLIExecutor
from openclaw_v2.models import AgentType, ExecutionContext, ExecutionMode, TaskStatus, WorkItem


class _FakeProcess:
    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = "", delay: float = 0.0) -> None:
        self.returncode = returncode
        self._stdout = stdout.encode("utf-8")
        self._stderr = stderr.encode("utf-8")
        self._delay = delay
        self.killed = False

    async def communicate(self):
        if self._delay:
            await asyncio.sleep(self._delay)
        return self._stdout, self._stderr

    def kill(self) -> None:
        self.killed = True
        if self.returncode == 0:
            self.returncode = -9


class CLIExecutorTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.config = load_app_config("config_v2.yaml")
        self.config.runtime.cli_command_timeout_seconds = 0
        self.executor = CLIExecutor(self.config)
        self.context = ExecutionContext(
            run_id="run-1",
            user_request="test",
            repo_path="/tmp/repo",
            dry_run=False,
            artifacts_dir="/tmp/artifacts",
            worktrees_dir="/tmp/worktrees",
        )

    async def test_cli_timeout_marks_result_failed_and_kills_process(self) -> None:
        self.config.runtime.cli_command_timeout_seconds = 0.01
        process = _FakeProcess(delay=0.05)
        work_item = WorkItem(
            id="triage",
            title="Triage user request",
            profile="claude_local_isolated",
            agent=AgentType.CLAUDE,
            mode=ExecutionMode.CLI,
            prompt_template="hello",
        )
        profile = self.config.profiles["claude_local_isolated"]

        with mock.patch(
            "openclaw_v2.executors.cli.asyncio.create_subprocess_exec",
            new=mock.AsyncMock(return_value=process),
        ):
            result = await self.executor.execute(work_item, profile, self.context, "hello")

        self.assertEqual(result.status, TaskStatus.FAILED)
        self.assertIn("timed out after", result.summary)
        self.assertTrue(process.killed)
        self.assertTrue(result.artifacts["cli_timed_out"])
        self.assertEqual(result.artifacts["cli_timeout_seconds"], 0.01)
        self.assertEqual(result.artifacts["cli_failure_kind"], "timeout")
        self.assertIn("claude_router_isolated", result.artifacts["cli_recovery_hint"])

    async def test_claude_login_failure_sets_recovery_hint(self) -> None:
        process = _FakeProcess(returncode=1, stderr="Not logged in · Please run /login")
        work_item = WorkItem(
            id="triage",
            title="Triage user request",
            profile="claude_local",
            agent=AgentType.CLAUDE,
            mode=ExecutionMode.CLI,
            prompt_template="hello",
        )
        profile = self.config.profiles["claude_local"]

        with mock.patch(
            "openclaw_v2.executors.cli.asyncio.create_subprocess_exec",
            new=mock.AsyncMock(return_value=process),
        ):
            result = await self.executor.execute(work_item, profile, self.context, "hello")

        self.assertEqual(result.status, TaskStatus.FAILED)
        self.assertEqual(result.artifacts["cli_failure_kind"], "auth_required")
        self.assertIn("claude auth login", result.artifacts["cli_recovery_hint"])

    async def test_cli_profile_unset_env_is_removed_from_spawned_process(self) -> None:
        process = _FakeProcess(stdout="ok")
        work_item = WorkItem(
            id="triage",
            title="Triage user request",
            profile="claude_local_isolated",
            agent=AgentType.CLAUDE,
            mode=ExecutionMode.CLI,
            prompt_template="hello",
        )
        profile = self.config.profiles["claude_local_isolated"]
        previous_base_url = os.environ.get("ANTHROPIC_BASE_URL")
        previous_auth_token = os.environ.get("ANTHROPIC_AUTH_TOKEN")
        os.environ["ANTHROPIC_BASE_URL"] = "http://proxy.example/api"
        os.environ["ANTHROPIC_AUTH_TOKEN"] = "bad-token"

        create_process = mock.AsyncMock(return_value=process)
        try:
            with mock.patch(
                "openclaw_v2.executors.cli.asyncio.create_subprocess_exec",
                new=create_process,
            ):
                result = await self.executor.execute(work_item, profile, self.context, "hello")
        finally:
            if previous_base_url is None:
                os.environ.pop("ANTHROPIC_BASE_URL", None)
            else:
                os.environ["ANTHROPIC_BASE_URL"] = previous_base_url
            if previous_auth_token is None:
                os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)
            else:
                os.environ["ANTHROPIC_AUTH_TOKEN"] = previous_auth_token

        self.assertEqual(result.status, TaskStatus.SUCCEEDED)
        spawn_env = create_process.await_args.kwargs["env"]
        self.assertNotIn("ANTHROPIC_BASE_URL", spawn_env)
        self.assertNotIn("ANTHROPIC_AUTH_TOKEN", spawn_env)


if __name__ == "__main__":
    unittest.main()
