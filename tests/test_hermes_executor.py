import asyncio
import unittest
from unittest import mock

from openclaw_v2.config import ProfileConfig, load_app_config
from openclaw_v2.executors.hermes import HermesExecutor
from openclaw_v2.models import AgentType, ExecutionContext, ExecutionMode, TaskStatus, WorkItem


class _FakeProcess:
    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = "", delay: float = 0.0) -> None:
        self.returncode = returncode
        self._stdout = stdout.encode("utf-8")
        self._stderr = stderr.encode("utf-8")
        self._delay = delay

    async def communicate(self):
        if self._delay:
            await asyncio.sleep(self._delay)
        return self._stdout, self._stderr


class HermesExecutorTests(unittest.TestCase):
    def test_prepare_prompt_includes_repo_handoff(self) -> None:
        context = ExecutionContext(
            run_id="run-1",
            user_request="summarize repo",
            repo_path="/tmp/repo",
            dry_run=False,
            artifacts_dir="/tmp/artifacts",
            worktrees_dir="/tmp/worktrees",
        )
        work_item = WorkItem(
            id="triage",
            title="Triage",
            profile="hermes_local",
            agent=AgentType.HERMES,
            mode=ExecutionMode.HERMES,
            prompt_template="",
            workspace_path="/tmp/repo-worktree",
        )

        prompt = HermesExecutor._prepare_prompt("hello world", context, work_item)

        self.assertIn("Hermes repository handoff:", prompt)
        self.assertIn("Primary repository path: /tmp/repo-worktree", prompt)
        self.assertIn("/tmp/repo-worktree/AGENTS.md", prompt)
        self.assertTrue(prompt.endswith("hello world"))

    def test_build_command_uses_configured_provider_toolsets_and_skills(self) -> None:
        profile = ProfileConfig(
            name="hermes_local",
            agent=AgentType.HERMES,
            mode=ExecutionMode.HERMES,
            hermes_provider="copilot",
            hermes_model="gpt-5",
            hermes_toolsets=["file", "terminal"],
            hermes_skills=["repo-review"],
            hermes_source="tool",
            hermes_max_turns=24,
            hermes_yolo=True,
        )

        command = HermesExecutor._build_command(profile, "hello world")

        self.assertEqual(
            command,
            [
                "hermes",
                "chat",
                "-q",
                "hello world",
                "-Q",
                "--source",
                "tool",
                "--provider",
                "copilot",
                "--model",
                "gpt-5",
                "--toolsets",
                "file,terminal",
                "--skills",
                "repo-review",
                "--max-turns",
                "24",
                "--yolo",
            ],
        )

    def test_strip_session_footer_extracts_session_id(self) -> None:
        output = "\n".join(
            [
                "OPENCLAW_STATUS: ready",
                "1. all good",
                "",
                "Resume this session with:",
                "  hermes --resume 20260416_123456_abcd1234",
                "",
                "Session: 20260416_123456_abcd1234",
                "Duration: 4s",
                "Messages: 3 (1 user, 2 tool calls)",
            ]
        )

        cleaned, session_id = HermesExecutor._strip_session_footer(output)

        self.assertEqual(session_id, "20260416_123456_abcd1234")
        self.assertEqual(cleaned, "OPENCLAW_STATUS: ready\n1. all good")


class HermesExecutorExecutionTests(unittest.IsolatedAsyncioTestCase):
    async def test_execute_dry_run_preserves_artifacts(self) -> None:
        executor = HermesExecutor(load_app_config("config_v2.yaml"))
        context = ExecutionContext(
            run_id="run-1",
            user_request="summarize repo",
            repo_path="/tmp/repo",
            dry_run=True,
            artifacts_dir="/tmp/artifacts",
            worktrees_dir="/tmp/worktrees",
        )
        work_item = WorkItem(
            id="record_summary",
            title="Record collaboration summary with Hermes",
            profile="hermes_local",
            agent=AgentType.HERMES,
            mode=ExecutionMode.HERMES,
            prompt_template="hello",
            workspace_path="/tmp/repo",
        )
        profile = ProfileConfig(
            name="hermes_local",
            agent=AgentType.HERMES,
            mode=ExecutionMode.HERMES,
            hermes_provider="auto",
            hermes_toolsets=["file", "terminal"],
            hermes_source="tool",
            hermes_max_turns=40,
        )

        result = await executor.execute(work_item, profile, context, "hello")

        self.assertEqual(result.status, TaskStatus.SUCCEEDED)
        self.assertEqual(result.artifacts["workspace_path"], "/tmp/repo")
        self.assertEqual(result.artifacts["hermes_source"], "tool")
        self.assertEqual(result.artifacts["hermes_toolsets"], ["file", "terminal"])
        self.assertIn("Hermes repository handoff:", result.output)

    async def test_execute_parses_control_markers_and_session_footer(self) -> None:
        executor = HermesExecutor(load_app_config("config_v2.yaml"))
        context = ExecutionContext(
            run_id="run-1",
            user_request="review branch",
            repo_path="/tmp/repo",
            dry_run=False,
            artifacts_dir="/tmp/artifacts",
            worktrees_dir="/tmp/worktrees",
        )
        work_item = WorkItem(
            id="review",
            title="Review implementation before publish with Hermes",
            profile="hermes_local",
            agent=AgentType.HERMES,
            mode=ExecutionMode.HERMES,
            prompt_template="hello",
            workspace_path="/tmp/repo",
        )
        profile = ProfileConfig(
            name="hermes_local",
            agent=AgentType.HERMES,
            mode=ExecutionMode.HERMES,
            hermes_provider="auto",
            hermes_source="tool",
        )
        hermes_output = "\n".join(
            [
                "OPENCLAW_STATUS: blocked",
                "OPENCLAW_BLOCK_REASON: 缺少实现产物，无法审阅",
                "",
                "当前缺少实现分支。",
                "",
                "Session: 20260416_123456_abcd1234",
                "Duration: 3s",
                "Messages: 2 (1 user, 1 tool call)",
            ]
        )
        process = _FakeProcess(stdout=hermes_output)

        with mock.patch(
            "openclaw_v2.executors.hermes.asyncio.create_subprocess_exec",
            new=mock.AsyncMock(return_value=process),
        ):
            result = await executor.execute(work_item, profile, context, "hello")

        self.assertEqual(result.status, TaskStatus.BLOCKED)
        self.assertEqual(result.artifacts["blocked_reason"], "缺少实现产物，无法审阅")
        self.assertEqual(result.artifacts["hermes_session_id"], "20260416_123456_abcd1234")
        self.assertEqual(result.output, "当前缺少实现分支。")
        self.assertIn("Hermes task Review implementation before publish with Hermes blocked", result.summary)


if __name__ == "__main__":
    unittest.main()
