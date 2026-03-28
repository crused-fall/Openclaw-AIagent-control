import json
import asyncio
import unittest
from unittest import mock

from openclaw_v2.config import ProfileConfig, load_app_config
from openclaw_v2.executors.openclaw import OpenClawExecutor
from openclaw_v2.models import AgentType, ExecutionContext, ExecutionMode, TaskStatus, WorkItem, parse_control_output


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


class OpenClawExecutorTests(unittest.TestCase):
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
            profile="openclaw_local",
            agent=AgentType.OPENCLAW,
            mode=ExecutionMode.OPENCLAW,
            prompt_template="",
            workspace_path="/tmp/repo-worktree",
        )

        prompt = OpenClawExecutor._prepare_prompt("hello world", context, work_item)

        self.assertIn("OpenClaw repository handoff:", prompt)
        self.assertIn("Primary repository path: /tmp/repo-worktree", prompt)
        self.assertIn("/tmp/repo-worktree/AGENTS.md", prompt)
        self.assertTrue(prompt.endswith("hello world"))

    def test_build_command_uses_local_json_agent_mode(self) -> None:
        profile = ProfileConfig(
            name="openclaw_local",
            agent=AgentType.OPENCLAW,
            mode=ExecutionMode.OPENCLAW,
            openclaw_agent_id="repo-agent",
            openclaw_profile="repo",
            openclaw_local=True,
        )

        command = OpenClawExecutor._build_command(profile, "hello world")

        self.assertEqual(
            command,
            [
                "openclaw",
                "--profile",
                "repo",
                "agent",
                "--local",
                "--json",
                "--agent",
                "repo-agent",
                "--message",
                "hello world",
            ],
        )

    def test_parse_response_output_extracts_text_and_metadata(self) -> None:
        output = json.dumps(
            {
                "payloads": [{"text": "alpha"}, {"text": "beta"}],
                "meta": {
                    "agentMeta": {
                        "sessionId": "session-1",
                        "provider": "custom-1",
                        "model": "deepseek-reasoner",
                        "usage": {"total": 42},
                    },
                    "systemPromptReport": {
                        "workspaceDir": "/tmp/repo",
                        "sessionKey": "agent:repo:main",
                    },
                },
                "stopReason": "stop",
            }
        )

        text, artifacts = OpenClawExecutor._parse_response_output(output)

        self.assertEqual(text, "alpha\n\nbeta")
        self.assertEqual(artifacts["openclaw_session_id"], "session-1")
        self.assertEqual(artifacts["openclaw_provider"], "custom-1")
        self.assertEqual(artifacts["openclaw_model"], "deepseek-reasoner")
        self.assertEqual(artifacts["workspace_path"], "/tmp/repo")
        self.assertEqual(artifacts["openclaw_session_key"], "agent:repo:main")
        self.assertEqual(artifacts["stop_reason"], "stop")

    def test_parse_response_output_reads_stop_reason_from_meta_fallback(self) -> None:
        output = json.dumps(
            {
                "payloads": [{"text": "alpha"}],
                "meta": {
                    "stopReason": "stop",
                    "agentMeta": {},
                    "systemPromptReport": {},
                },
            }
        )

        _, artifacts = OpenClawExecutor._parse_response_output(output)

        self.assertEqual(artifacts["stop_reason"], "stop")

    def test_payload_text_can_drive_control_markers(self) -> None:
        output = json.dumps(
            {
                "payloads": [
                    {
                        "text": "\n".join(
                            [
                                "OPENCLAW_STATUS: blocked",
                                "OPENCLAW_BLOCK_REASON: 仓库中不存在登录页",
                                "",
                                "目标页面缺失",
                            ]
                        )
                    }
                ]
            }
        )

        text, _ = OpenClawExecutor._parse_response_output(output)
        signal = parse_control_output(text)

        self.assertEqual(signal.status.value, "blocked")
        self.assertEqual(signal.block_reason, "仓库中不存在登录页")
        self.assertEqual(signal.cleaned_output, "目标页面缺失")


class OpenClawExecutorExecutionTests(unittest.IsolatedAsyncioTestCase):
    async def test_execute_marks_noop_when_expected_changes_are_missing(self) -> None:
        executor = OpenClawExecutor(load_app_config("config_v2.yaml"))
        context = ExecutionContext(
            run_id="run-1",
            user_request="update readme",
            repo_path="/tmp/repo",
            dry_run=False,
            artifacts_dir="/tmp/artifacts",
            worktrees_dir="/tmp/worktrees",
        )
        work_item = WorkItem(
            id="implement",
            title="Implement main changes locally",
            profile="openclaw_local",
            agent=AgentType.OPENCLAW,
            mode=ExecutionMode.OPENCLAW,
            prompt_template="hello",
            workspace_path="/tmp/repo",
            metadata={"expects_file_changes": True, "export_branch": True},
            branch_name="openclaw-run-1-implement",
        )
        profile = ProfileConfig(
            name="openclaw_local",
            agent=AgentType.OPENCLAW,
            mode=ExecutionMode.OPENCLAW,
            openclaw_agent_id="repo-agent",
            openclaw_local=True,
        )
        openclaw_output = json.dumps(
            {
                "payloads": [{"text": "OPENCLAW_STATUS: ready\nImplemented."}],
                "meta": {"agentMeta": {}, "systemPromptReport": {}},
            }
        )
        process = _FakeProcess(stdout=openclaw_output)
        status_process = _FakeProcess(stdout="")

        create_process = mock.AsyncMock(side_effect=[process, status_process])
        with mock.patch(
            "openclaw_v2.executors.openclaw.asyncio.create_subprocess_exec",
            new=create_process,
        ):
            result = await executor.execute(work_item, profile, context, "hello")

        self.assertEqual(result.status, TaskStatus.SUCCEEDED)
        self.assertTrue(result.artifacts["noop_result"])
        self.assertFalse(result.artifacts["workspace_has_changes"])
        self.assertEqual(result.artifacts["workspace_changed_files"], [])
        self.assertEqual(result.artifacts["branch_name"], "openclaw-run-1-implement")
        self.assertTrue(result.artifacts["exports_branch"])
        self.assertEqual(result.artifacts["source_branch"], "openclaw-run-1-implement")
        self.assertIn("no file changes required", result.summary)


if __name__ == "__main__":
    unittest.main()
