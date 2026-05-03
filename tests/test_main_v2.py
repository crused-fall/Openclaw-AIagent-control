import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

from main_v2 import _print_plan_diagnostics, _print_result, _validate_live_policy, main
from openclaw_v2.config import load_app_config
from openclaw_v2.models import AgentResult, AgentType, ExecutionMode, RunResult, TaskStatus, WorkItem
from openclaw_v2.orchestrator import HybridOrchestrator


class MainV2PrintTests(unittest.TestCase):
    def test_print_result_includes_block_reasons(self) -> None:
        run_result = RunResult(
            run_id="run-1",
            plan=[
                WorkItem(
                    id="triage",
                    title="Triage user request",
                    profile="claude_local",
                    agent=AgentType.CLAUDE,
                    mode=ExecutionMode.CLI,
                    prompt_template="",
                    assignment="triage_local",
                    managed_agent="claude_router",
                    assignment_reason="Resolved by assignment triage_local to managed agent claude_router.",
                ),
                WorkItem(
                    id="implement",
                    title="Implement main changes locally",
                    profile="codex_local",
                    agent=AgentType.CODEX,
                    mode=ExecutionMode.CLI,
                    prompt_template="",
                    assignment="implement_local",
                    managed_agent="codex_builder",
                    assignment_reason="Resolved by assignment implement_local to managed agent codex_builder.",
                    depends_on=["triage"],
                ),
            ],
            results=[
                AgentResult(
                    work_item_id="triage",
                    profile="claude_local",
                    agent=AgentType.CLAUDE,
                    mode=ExecutionMode.CLI,
                    status=TaskStatus.BLOCKED,
                    summary="CLI task Triage user request blocked: 仓库中不存在登录页面",
                    artifacts={"blocked_reason": "仓库中不存在登录页面"},
                ),
                AgentResult(
                    work_item_id="implement",
                    profile="codex_local",
                    agent=AgentType.CODEX,
                    mode=ExecutionMode.CLI,
                    status=TaskStatus.SKIPPED,
                    summary="Skipped because dependency triage was blocked: 仓库中不存在登录页面",
                    artifacts={
                        "dependency_outcomes": {
                            "blocked": [
                                {
                                    "id": "triage",
                                    "summary": "CLI task Triage user request blocked: 仓库中不存在登录页面",
                                    "blocked_reason": "仓库中不存在登录页面",
                                }
                            ],
                            "failed": [],
                        }
                    },
                ),
            ],
            success=False,
            artifacts_dir="/tmp/run-1",
        )

        with io.StringIO() as buffer, redirect_stdout(buffer):
            _print_result(run_result)
            output = buffer.getvalue()

        self.assertIn("first_blocked: triage -> 仓库中不存在登录页面", output)
        self.assertIn("blocked_reason: 仓库中不存在登录页面", output)
        self.assertIn("blocked_dependency: triage -> 仓库中不存在登录页面", output)
        self.assertIn("assignment=triage_local", output)
        self.assertIn("managed_agent=claude_router", output)

    def test_print_result_includes_skipped_dependencies(self) -> None:
        run_result = RunResult(
            run_id="run-2",
            plan=[],
            results=[
                AgentResult(
                    work_item_id="review",
                    profile="claude_review_local",
                    agent=AgentType.CLAUDE,
                    mode=ExecutionMode.CLI,
                    status=TaskStatus.SKIPPED,
                    summary="Skipped because dependency implement was skipped: Skipped because dependency triage was blocked: 仓库中不存在登录页面",
                    artifacts={
                        "dependency_outcomes": {
                            "blocked": [],
                            "failed": [],
                            "skipped": [
                                {
                                    "id": "implement",
                                    "summary": "Skipped because dependency triage was blocked: 仓库中不存在登录页面",
                                }
                            ],
                        }
                    },
                )
            ],
            success=False,
            artifacts_dir="/tmp/run-2",
        )

        with io.StringIO() as buffer, redirect_stdout(buffer):
            _print_result(run_result)
            output = buffer.getvalue()

        self.assertIn("skipped_dependency: implement -> Skipped because dependency triage was blocked: 仓库中不存在登录页面", output)

    def test_print_result_includes_cli_timeout_fields(self) -> None:
        run_result = RunResult(
            run_id="run-timeout",
            plan=[],
            results=[
                AgentResult(
                    work_item_id="triage",
                    profile="claude_local",
                    agent=AgentType.CLAUDE,
                    mode=ExecutionMode.CLI,
                    status=TaskStatus.FAILED,
                    summary="CLI task Triage user request timed out after 180.0 seconds.",
                    artifacts={
                        "cli_timed_out": True,
                        "cli_timeout_seconds": 180.0,
                        "cli_failure_kind": "timeout",
                        "cli_recovery_hint": "Retry with `OPENCLAW_ASSIGN_TRIAGE_LOCAL=claude_router_isolated`.",
                    },
                )
            ],
            success=False,
            artifacts_dir="/tmp/run-timeout",
        )

        with io.StringIO() as buffer, redirect_stdout(buffer):
            _print_result(run_result)
            output = buffer.getvalue()

        self.assertIn("cli_timed_out: true", output)
        self.assertIn("cli_timeout_seconds: 180.0", output)
        self.assertIn("cli_failure_kind: timeout", output)
        self.assertIn("cli_recovery_hint: Retry with `OPENCLAW_ASSIGN_TRIAGE_LOCAL=claude_router_isolated`.", output)

    def test_print_result_includes_noop_fields(self) -> None:
        run_result = RunResult(
            run_id="run-noop",
            plan=[],
            results=[
                AgentResult(
                    work_item_id="implement",
                    profile="codex_local",
                    agent=AgentType.CODEX,
                    mode=ExecutionMode.CLI,
                    status=TaskStatus.SUCCEEDED,
                    summary="CLI task Implement main changes locally finished successfully with no file changes required.",
                    artifacts={
                        "noop_result": True,
                        "workspace_has_changes": False,
                    },
                )
            ],
            success=True,
            artifacts_dir="/tmp/run-noop",
        )

        with io.StringIO() as buffer, redirect_stdout(buffer):
            _print_result(run_result)
            output = buffer.getvalue()

        self.assertIn("noop_result: true", output)
        self.assertIn("workspace_has_changes: False", output)

    def test_print_result_includes_commit_change_fields(self) -> None:
        run_result = RunResult(
            run_id="run-commit",
            plan=[],
            results=[
                AgentResult(
                    work_item_id="commit_changes",
                    profile="git_commit_changes",
                    agent=AgentType.SYSTEM,
                    mode=ExecutionMode.CLI,
                    status=TaskStatus.SUCCEEDED,
                    summary="CLI task Commit implementation changes locally finished successfully.",
                    artifacts={
                        "changes_committed": True,
                        "head_commit": "abc123",
                        "workspace_has_uncommitted_changes": True,
                        "workspace_uncommitted_files": ["README.md"],
                    },
                )
            ],
            success=True,
            artifacts_dir="/tmp/run-commit",
        )

        with io.StringIO() as buffer, redirect_stdout(buffer):
            _print_result(run_result)
            output = buffer.getvalue()

        self.assertIn("changes_committed: true", output)
        self.assertIn("head_commit: abc123", output)
        self.assertIn("workspace_has_uncommitted_changes: true", output)
        self.assertIn("workspace_uncommitted_files: ['README.md']", output)

    def test_print_result_includes_planning_block_reason(self) -> None:
        run_result = RunResult(
            run_id="run-3",
            plan=[
                WorkItem(
                    id="triage",
                    title="Triage user request",
                    profile="",
                    agent=AgentType.SYSTEM,
                    mode=ExecutionMode.SYSTEM,
                    prompt_template="",
                    assignment="triage_local",
                    planning_blocked_reason="Assignment `triage_local` could not resolve a usable managed agent.",
                )
            ],
            results=[
                AgentResult(
                    work_item_id="triage",
                    profile="",
                    agent=AgentType.SYSTEM,
                    mode=ExecutionMode.SYSTEM,
                    status=TaskStatus.BLOCKED,
                    summary="Step Triage user request was blocked before execution: Assignment `triage_local` could not resolve a usable managed agent.",
                    artifacts={
                        "planning_blocked_reason": "Assignment `triage_local` could not resolve a usable managed agent.",
                        "blocked_reason": "Assignment `triage_local` could not resolve a usable managed agent.",
                    },
                )
            ],
            success=False,
            artifacts_dir="/tmp/run-3",
        )

        with io.StringIO() as buffer, redirect_stdout(buffer):
            _print_result(run_result)
            output = buffer.getvalue()

        self.assertIn("planning_blocked_reason: Assignment `triage_local` could not resolve a usable managed agent.", output)

    def test_print_result_includes_github_artifact_summary(self) -> None:
        run_result = RunResult(
            run_id="run-4",
            plan=[],
            results=[
                AgentResult(
                    work_item_id="dispatch_review",
                    profile="github_review_workflow",
                    agent=AgentType.COPILOT,
                    mode=ExecutionMode.GITHUB,
                    status=TaskStatus.SUCCEEDED,
                    summary="GitHub workflow task Dispatch review finished successfully.",
                    command=["gh", "workflow", "run", "openclaw-review.yml"],
                    artifacts={
                        "repo": "owner/repo",
                        "repo_source": "git_origin",
                        "action": "workflow_dispatch",
                        "source_branch": "feature/test",
                        "workflow_name": "openclaw-review.yml",
                        "workflow_ref": "feature/test",
                        "workflow_run_id": "123456789",
                        "workflow_run_url": "https://github.com/owner/repo/actions/runs/123456789",
                        "github_attempt_count": 2,
                        "github_retried": True,
                        "github_label_fallback_used": True,
                        "github_requested_labels": "openclaw, planning",
                        "github_ignored_labels": "openclaw, planning",
                        "github_failure_kind": "unknown",
                        "github_retryable": False,
                        "github_recovery_hint": "Inspect `github_error` and rerun the printed `gh` command manually if needed.",
                    },
                    stderr="gh: something happened",
                    exit_code=1,
                )
            ],
            success=True,
            artifacts_dir="/tmp/run-4",
        )

        with io.StringIO() as buffer, redirect_stdout(buffer):
            _print_result(run_result)
            output = buffer.getvalue()

        self.assertIn("github:", output)
        self.assertIn("repo_source: git_origin", output)
        self.assertIn("workflow_run_id: 123456789", output)
        self.assertIn("workflow_run_url: https://github.com/owner/repo/actions/runs/123456789", output)
        self.assertIn("github_attempt_count: 2", output)
        self.assertIn("github_retried: True", output)
        self.assertIn("github_label_fallback_used: True", output)
        self.assertIn("github_requested_labels: openclaw, planning", output)
        self.assertIn("github_ignored_labels: openclaw, planning", output)
        self.assertIn("github_failure_kind: unknown", output)
        self.assertIn("github_retryable: False", output)
        self.assertIn("github_recovery_hint: Inspect `github_error` and rerun the printed `gh` command manually if needed.", output)
        self.assertIn("stderr:", output)
        self.assertIn("gh: something happened", output)

    def test_print_plan_diagnostics_includes_assignment_resolution_fields(self) -> None:
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
                required_capabilities=["implement"],
                assignment_candidates=["codex_builder", "cursor_editor"],
                assignment_attempts=[
                    "codex_builder: managed agent is disabled.",
                    "cursor_editor: selected.",
                ],
                fallback_used=True,
                fallback_chain=["cursor_editor"],
                assignment_reason="Resolved by assignment implement_local to managed agent cursor_editor. Fallback was used.",
                depends_on=["triage"],
            )
        ]

        with io.StringIO() as buffer, redirect_stdout(buffer):
            _print_plan_diagnostics(plan)
            output = buffer.getvalue()

        self.assertIn("assignment_candidates: codex_builder, cursor_editor", output)
        self.assertIn("assignment_attempts: codex_builder: managed agent is disabled.; cursor_editor: selected.", output)
        self.assertIn("fallback_used: true", output)
        self.assertIn("assignment_reason: Resolved by assignment implement_local to managed agent cursor_editor. Fallback was used.", output)


class MainV2PolicyTests(unittest.TestCase):
    def test_validate_live_policy_blocks_fallback_usage_by_default(self) -> None:
        config = load_app_config("config_v2.yaml")
        orchestrator = HybridOrchestrator(config)
        config.runtime.allow_fallback_in_live = False
        config.managed_agents["codex_builder"].enabled = False

        with self.assertRaises(SystemExit) as error:
            _validate_live_policy(
                orchestrator,
                selected_steps=["implement"],
                require_step_selection=True,
                allow_fallback_in_live=config.runtime.allow_fallback_in_live,
                allowed_live_steps=config.runtime.allowed_live_steps,
            )

        self.assertIn("fallback managed agents", str(error.exception))
        self.assertIn("implement -> cursor_editor", str(error.exception))


class MainV2WebModeTests(unittest.IsolatedAsyncioTestCase):
    async def test_main_reports_missing_config_as_systemexit(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            missing_config = os.path.join(temp_dir, "missing-config.yaml")
            with (
                mock.patch.object(
                    sys,
                    "argv",
                    [
                        "main_v2.py",
                        "--config",
                        missing_config,
                        "--doctor-config",
                    ],
                ),
                mock.patch("builtins.input", side_effect=AssertionError("should not prompt when config is missing")),
            ):
                with self.assertRaises(SystemExit) as error:
                    await main()

        self.assertIn("Config file not found", str(error.exception))
        self.assertIn(missing_config, str(error.exception))

    async def test_main_runs_doctor_config_and_exits_without_prompting(self) -> None:
        with (
            mock.patch.object(sys, "argv", ["main_v2.py", "--doctor-config"]),
            mock.patch("builtins.input", side_effect=AssertionError("doctor-config should not prompt")),
            io.StringIO() as buffer,
            redirect_stdout(buffer),
        ):
            await main()
            output = buffer.getvalue()

        self.assertIn("Preflight:", output)
        self.assertIn("runtime:github_retry_attempts", output)
        self.assertIn("pipeline:mission_control_default:dispatch_review", output)
        self.assertNotIn("OpenClaw v2 已启动", output)

    async def test_main_starts_web_server_with_expected_args(self) -> None:
        class FakeOrchestrator:
            def __init__(self, config) -> None:
                self.config = config

        with (
            mock.patch.object(
                sys,
                "argv",
                [
                    "main_v2.py",
                    "--web",
                    "--config",
                    "config_v2.yaml",
                    "--repo-path",
                    ".",
                    "--web-host",
                    "0.0.0.0",
                    "--web-port",
                    "9900",
                ],
            ),
            mock.patch("main_v2.HybridOrchestrator", FakeOrchestrator),
            mock.patch("openclaw_v2.web.run_web_server", new_callable=mock.AsyncMock) as run_web_server,
        ):
            await main()

        run_web_server.assert_awaited_once_with(
            config_path=os.path.abspath("config_v2.yaml"),
            repo_path=os.path.abspath("."),
            host="0.0.0.0",
            port=9900,
        )

    async def test_main_rejects_web_with_request(self) -> None:
        class FakeOrchestrator:
            def __init__(self, config) -> None:
                self.config = config

        with (
            mock.patch.object(
                sys,
                "argv",
                [
                    "main_v2.py",
                    "--web",
                    "--request",
                    "hello",
                ],
            ),
            mock.patch("main_v2.HybridOrchestrator", FakeOrchestrator),
        ):
            with self.assertRaises(SystemExit) as error:
                await main()

        self.assertIn("--web cannot be combined", str(error.exception))


if __name__ == "__main__":
    unittest.main()
