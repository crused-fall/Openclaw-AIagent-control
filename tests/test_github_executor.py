import unittest
from unittest import mock
import json

from openclaw_v2.config import load_app_config
from openclaw_v2.executors.github import GitHubWorkflowExecutor
from openclaw_v2.models import AgentType, ExecutionContext, ExecutionMode, TaskStatus, WorkItem


class _FakeProcess:
    def __init__(self, returncode: int, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self._stdout = stdout.encode("utf-8")
        self._stderr = stderr.encode("utf-8")

    async def communicate(self):
        return self._stdout, self._stderr


class GitHubExecutorTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.config = load_app_config("config_v2.yaml")
        self.config.github.repo = "owner/repo"
        self.executor = GitHubWorkflowExecutor(self.config)
        self.context = ExecutionContext(
            run_id="run-1",
            user_request="test",
            repo_path="/tmp/repo",
            dry_run=True,
            artifacts_dir="/tmp/artifacts",
            worktrees_dir="/tmp/worktrees",
        )

    def test_extract_resource_refs_reads_issue_pr_and_workflow_urls(self) -> None:
        output = """
        Issue: https://github.com/owner/repo/issues/12
        PR: https://github.com/owner/repo/pull/34
        Workflow: https://github.com/owner/repo/actions/runs/56
        """.strip()

        artifacts = GitHubWorkflowExecutor._extract_resource_refs("workflow_dispatch", output)

        self.assertEqual(artifacts["issue_number"], "12")
        self.assertEqual(artifacts["pr_number"], "34")
        self.assertEqual(artifacts["workflow_run_id"], "56")

    async def test_dry_run_issue_comment_preserves_issue_reference(self) -> None:
        work_item = WorkItem(
            id="update_issue",
            title="Update issue",
            profile="copilot_issue_followup",
            agent=AgentType.COPILOT,
            mode=ExecutionMode.GITHUB,
            prompt_template="",
            metadata={"primary_issue_ref": "https://github.com/owner/repo/issues/77"},
        )
        profile = self.config.profiles["copilot_issue_followup"]

        result = await self.executor.execute(work_item, profile, self.context, "hello")

        self.assertEqual(result.artifacts["issue_number"], "77")
        self.assertEqual(
            result.artifacts["issue_url"],
            "https://github.com/owner/repo/issues/77",
        )

    async def test_dry_run_workflow_dispatch_uses_resolved_repo_and_base_branch(self) -> None:
        work_item = WorkItem(
            id="dispatch_review",
            title="Dispatch review",
            profile="github_review_workflow",
            agent=AgentType.COPILOT,
            mode=ExecutionMode.GITHUB,
            prompt_template="",
            metadata={},
        )
        profile = self.config.profiles["github_review_workflow"]

        result = await self.executor.execute(work_item, profile, self.context, "hello")

        self.assertEqual(result.artifacts["workflow_ref"], "main")
        self.assertEqual(
            result.artifacts["workflow_run_url"],
            "https://github.com/owner/repo/actions/runs/WORKFLOW_RUN_ID",
        )
        self.assertEqual(
            result.command,
            ["gh", "workflow", "run", "openclaw-review.yml", "--repo", "owner/repo", "--ref", "main"],
        )

    async def test_dry_run_can_resolve_repo_from_origin_when_fallback_is_enabled(self) -> None:
        self.config.github.repo = ""
        self.config.github.use_origin_remote_fallback = True
        work_item = WorkItem(
            id="sync_issue",
            title="Sync issue",
            profile="copilot_issue",
            agent=AgentType.COPILOT,
            mode=ExecutionMode.GITHUB,
            prompt_template="",
        )
        profile = self.config.profiles["copilot_issue"]

        with mock.patch(
            "openclaw_v2.github_support.asyncio.create_subprocess_exec",
            new=mock.AsyncMock(return_value=_FakeProcess(0, "git@github.com:owner/repo.git")),
        ):
            result = await self.executor.execute(work_item, profile, self.context, "hello")

        self.assertEqual(result.status, TaskStatus.SUCCEEDED)
        self.assertEqual(result.artifacts["repo"], "owner/repo")
        self.assertEqual(result.artifacts["repo_source"], "git_origin")

    async def test_live_issue_create_missing_label_retries_without_labels(self) -> None:
        context = ExecutionContext(
            run_id="run-1",
            user_request="test",
            repo_path="/tmp/repo",
            dry_run=False,
            artifacts_dir="/tmp/artifacts",
            worktrees_dir="/tmp/worktrees",
        )
        work_item = WorkItem(
            id="sync_issue",
            title="Sync issue",
            profile="copilot_issue",
            agent=AgentType.COPILOT,
            mode=ExecutionMode.GITHUB,
            prompt_template="",
        )
        profile = self.config.profiles["copilot_issue"]
        create_process = mock.AsyncMock(
            side_effect=[
                _FakeProcess(1, "", "could not add label: 'openclaw' not found"),
                _FakeProcess(0, "https://github.com/owner/repo/issues/12"),
            ]
        )

        with mock.patch(
            "openclaw_v2.executors.github.asyncio.create_subprocess_exec",
            new=create_process,
        ):
            result = await self.executor.execute(work_item, profile, context, "hello")

        self.assertEqual(result.status, TaskStatus.SUCCEEDED)
        self.assertEqual(result.artifacts["github_attempt_count"], 2)
        self.assertTrue(result.artifacts["github_retried"])
        self.assertTrue(result.artifacts["github_label_fallback_used"])
        self.assertEqual(result.artifacts["github_requested_labels"], "openclaw, planning")
        self.assertEqual(result.artifacts["github_ignored_labels"], "openclaw, planning")
        self.assertEqual(result.artifacts["issue_number"], "12")
        self.assertNotIn("--label", result.command)
        self.assertIn("Retried without labels", result.summary)
        self.assertEqual(create_process.await_count, 2)

    async def test_live_issue_comment_without_issue_reference_is_blocked(self) -> None:
        context = ExecutionContext(
            run_id="run-1",
            user_request="test",
            repo_path="/tmp/repo",
            dry_run=False,
            artifacts_dir="/tmp/artifacts",
            worktrees_dir="/tmp/worktrees",
        )
        work_item = WorkItem(
            id="update_issue",
            title="Update issue",
            profile="copilot_issue_followup",
            agent=AgentType.COPILOT,
            mode=ExecutionMode.GITHUB,
            prompt_template="",
            metadata={},
        )
        profile = self.config.profiles["copilot_issue_followup"]

        result = await self.executor.execute(work_item, profile, context, "hello")

        self.assertEqual(result.status, TaskStatus.BLOCKED)
        self.assertIn("blocked", result.summary.lower())
        self.assertIn("No issue reference available", result.artifacts["blocked_reason"])
        self.assertEqual(result.artifacts["github_failure_kind"], "reference_missing")
        self.assertIn("upstream steps produced", result.artifacts["github_recovery_hint"])

    async def test_live_issue_comment_auth_error_is_blocked_and_classified(self) -> None:
        context = ExecutionContext(
            run_id="run-1",
            user_request="test",
            repo_path="/tmp/repo",
            dry_run=False,
            artifacts_dir="/tmp/artifacts",
            worktrees_dir="/tmp/worktrees",
        )
        work_item = WorkItem(
            id="update_issue",
            title="Update issue",
            profile="copilot_issue_followup",
            agent=AgentType.COPILOT,
            mode=ExecutionMode.GITHUB,
            prompt_template="",
            metadata={"primary_issue_ref": "77"},
        )
        profile = self.config.profiles["copilot_issue_followup"]

        with mock.patch(
            "openclaw_v2.executors.github.asyncio.create_subprocess_exec",
            new=mock.AsyncMock(return_value=_FakeProcess(1, "", "authentication required")),
        ):
            result = await self.executor.execute(work_item, profile, context, "hello")

        self.assertEqual(result.status, TaskStatus.BLOCKED)
        self.assertEqual(result.artifacts["github_failure_kind"], "auth_required")
        self.assertTrue(result.artifacts["github_retryable"])
        self.assertEqual(result.artifacts["blocked_reason"], "GitHub authentication is required.")
        self.assertIn("gh auth", result.artifacts["github_recovery_hint"])

    async def test_live_workflow_dispatch_parses_run_url_from_stderr(self) -> None:
        context = ExecutionContext(
            run_id="run-1",
            user_request="test",
            repo_path="/tmp/repo",
            dry_run=False,
            artifacts_dir="/tmp/artifacts",
            worktrees_dir="/tmp/worktrees",
        )
        work_item = WorkItem(
            id="dispatch_review",
            title="Dispatch review",
            profile="github_review_workflow",
            agent=AgentType.COPILOT,
            mode=ExecutionMode.GITHUB,
            prompt_template="",
            metadata={"source_branch": "feature/test"},
        )
        profile = self.config.profiles["github_review_workflow"]

        with mock.patch(
            "openclaw_v2.executors.github.asyncio.create_subprocess_exec",
            new=mock.AsyncMock(
                return_value=_FakeProcess(
                    0,
                    "",
                    "Created workflow run: https://github.com/owner/repo/actions/runs/123456789",
                )
            ),
        ):
            result = await self.executor.execute(work_item, profile, context, "hello")

        self.assertEqual(result.artifacts["workflow_name"], "openclaw-review.yml")
        self.assertEqual(result.artifacts["workflow_ref"], "feature/test")
        self.assertEqual(result.artifacts["workflow_run_id"], "123456789")
        self.assertEqual(
            result.artifacts["workflow_run_url"],
            "https://github.com/owner/repo/actions/runs/123456789",
        )

    async def test_live_workflow_dispatch_permission_error_is_blocked_with_actionable_hint(self) -> None:
        context = ExecutionContext(
            run_id="run-1",
            user_request="test",
            repo_path="/tmp/repo",
            dry_run=False,
            artifacts_dir="/tmp/artifacts",
            worktrees_dir="/tmp/worktrees",
        )
        work_item = WorkItem(
            id="dispatch_review",
            title="Dispatch review",
            profile="github_review_workflow",
            agent=AgentType.COPILOT,
            mode=ExecutionMode.GITHUB,
            prompt_template="",
            metadata={"source_branch": "feature/test"},
        )
        profile = self.config.profiles["github_review_workflow"]

        with mock.patch(
            "openclaw_v2.executors.github.asyncio.create_subprocess_exec",
            new=mock.AsyncMock(
                return_value=_FakeProcess(
                    1,
                    "",
                    "could not create workflow dispatch event: HTTP 403: Resource not accessible by personal access token",
                )
            ),
        ):
            result = await self.executor.execute(work_item, profile, context, "hello")

        self.assertEqual(result.status, TaskStatus.BLOCKED)
        self.assertEqual(result.artifacts["github_failure_kind"], "insufficient_token_permissions")
        self.assertFalse(result.artifacts["github_retryable"])
        self.assertIn("workflow", result.artifacts["github_recovery_hint"])
        self.assertIn("does not have enough permission", result.artifacts["blocked_reason"])

    async def test_live_workflow_view_succeeds_for_completed_success_run(self) -> None:
        context = ExecutionContext(
            run_id="run-1",
            user_request="test",
            repo_path="/tmp/repo",
            dry_run=False,
            artifacts_dir="/tmp/artifacts",
            worktrees_dir="/tmp/worktrees",
        )
        work_item = WorkItem(
            id="collect_review",
            title="Collect review",
            profile="github_review_workflow_status",
            agent=AgentType.COPILOT,
            mode=ExecutionMode.GITHUB,
            prompt_template="",
            metadata={"primary_workflow_run_ref": "123456789"},
        )
        profile = self.config.profiles["github_review_workflow_status"]
        payload = json.dumps(
            {
                "databaseId": 123456789,
                "url": "https://github.com/owner/repo/actions/runs/123456789",
                "workflowName": "openclaw-review.yml",
                "status": "completed",
                "conclusion": "success",
                "headBranch": "feature/test",
                "attempt": 1,
                "number": 42,
            }
        )

        with mock.patch(
            "openclaw_v2.executors.github.asyncio.create_subprocess_exec",
            new=mock.AsyncMock(return_value=_FakeProcess(0, payload)),
        ):
            result = await self.executor.execute(work_item, profile, context, "hello")

        self.assertEqual(result.status, TaskStatus.SUCCEEDED)
        self.assertEqual(result.artifacts["workflow_run_id"], "123456789")
        self.assertEqual(result.artifacts["workflow_status"], "completed")
        self.assertEqual(result.artifacts["workflow_conclusion"], "success")
        self.assertEqual(result.artifacts["workflow_head_branch"], "feature/test")

    async def test_live_workflow_view_polls_until_completed_success_run(self) -> None:
        self.config.runtime.github_workflow_view_poll_attempts = 2
        self.config.runtime.github_workflow_view_poll_interval_seconds = 0
        context = ExecutionContext(
            run_id="run-1",
            user_request="test",
            repo_path="/tmp/repo",
            dry_run=False,
            artifacts_dir="/tmp/artifacts",
            worktrees_dir="/tmp/worktrees",
        )
        work_item = WorkItem(
            id="collect_review",
            title="Collect review",
            profile="github_review_workflow_status",
            agent=AgentType.COPILOT,
            mode=ExecutionMode.GITHUB,
            prompt_template="",
            metadata={"primary_workflow_run_ref": "123456789"},
        )
        profile = self.config.profiles["github_review_workflow_status"]
        queued_payload = json.dumps(
            {
                "databaseId": 123456789,
                "url": "https://github.com/owner/repo/actions/runs/123456789",
                "workflowName": "openclaw-review.yml",
                "status": "queued",
                "conclusion": "",
            }
        )
        success_payload = json.dumps(
            {
                "databaseId": 123456789,
                "url": "https://github.com/owner/repo/actions/runs/123456789",
                "workflowName": "openclaw-review.yml",
                "status": "completed",
                "conclusion": "success",
                "headBranch": "feature/test",
            }
        )

        with mock.patch(
            "openclaw_v2.executors.github.asyncio.create_subprocess_exec",
            new=mock.AsyncMock(
                side_effect=[_FakeProcess(0, queued_payload), _FakeProcess(0, success_payload)]
            ),
        ), mock.patch("openclaw_v2.executors.github.asyncio.sleep", new=mock.AsyncMock()):
            result = await self.executor.execute(work_item, profile, context, "hello")

        self.assertEqual(result.status, TaskStatus.SUCCEEDED)
        self.assertEqual(result.artifacts["github_attempt_count"], 2)
        self.assertEqual(result.artifacts["workflow_poll_attempt_count"], 2)
        self.assertIn("Resolved after 2 status polls.", result.summary)

    async def test_live_workflow_view_blocks_while_run_is_in_progress(self) -> None:
        self.config.runtime.github_workflow_view_poll_attempts = 1
        context = ExecutionContext(
            run_id="run-1",
            user_request="test",
            repo_path="/tmp/repo",
            dry_run=False,
            artifacts_dir="/tmp/artifacts",
            worktrees_dir="/tmp/worktrees",
        )
        work_item = WorkItem(
            id="collect_review",
            title="Collect review",
            profile="github_review_workflow_status",
            agent=AgentType.COPILOT,
            mode=ExecutionMode.GITHUB,
            prompt_template="",
            metadata={"primary_workflow_run_ref": "123456789"},
        )
        profile = self.config.profiles["github_review_workflow_status"]
        payload = json.dumps(
            {
                "databaseId": 123456789,
                "url": "https://github.com/owner/repo/actions/runs/123456789",
                "workflowName": "openclaw-review.yml",
                "status": "in_progress",
                "conclusion": "",
            }
        )

        with mock.patch(
            "openclaw_v2.executors.github.asyncio.create_subprocess_exec",
            new=mock.AsyncMock(return_value=_FakeProcess(0, payload)),
        ):
            result = await self.executor.execute(work_item, profile, context, "hello")

        self.assertEqual(result.status, TaskStatus.BLOCKED)
        self.assertEqual(result.artifacts["workflow_status"], "in_progress")
        self.assertIn("still in_progress", result.artifacts["blocked_reason"])

    async def test_live_workflow_view_reports_failed_jobs_for_failed_run(self) -> None:
        context = ExecutionContext(
            run_id="run-1",
            user_request="test",
            repo_path="/tmp/repo",
            dry_run=False,
            artifacts_dir="/tmp/artifacts",
            worktrees_dir="/tmp/worktrees",
        )
        work_item = WorkItem(
            id="collect_review",
            title="Collect review",
            profile="github_review_workflow_status",
            agent=AgentType.COPILOT,
            mode=ExecutionMode.GITHUB,
            prompt_template="",
            metadata={"primary_workflow_run_ref": "123456789"},
        )
        profile = self.config.profiles["github_review_workflow_status"]
        payload = json.dumps(
            {
                "databaseId": 123456789,
                "url": "https://github.com/owner/repo/actions/runs/123456789",
                "workflowName": "openclaw-review.yml",
                "status": "completed",
                "conclusion": "failure",
                "jobs": [
                    {"name": "lint", "status": "completed", "conclusion": "failure"},
                    {"name": "tests", "status": "completed", "conclusion": "success"},
                ],
            }
        )

        with mock.patch(
            "openclaw_v2.executors.github.asyncio.create_subprocess_exec",
            new=mock.AsyncMock(return_value=_FakeProcess(0, payload)),
        ):
            result = await self.executor.execute(work_item, profile, context, "hello")

        self.assertEqual(result.status, TaskStatus.FAILED)
        self.assertEqual(result.artifacts["workflow_failed_job_count"], 1)
        self.assertEqual(result.artifacts["workflow_failed_jobs"], "lint")
        self.assertIn("Failed jobs: lint.", result.summary)

    async def test_live_retryable_network_failure_retries_and_then_succeeds(self) -> None:
        self.config.runtime.github_retry_attempts = 2
        self.config.runtime.github_retry_backoff_seconds = 0
        context = ExecutionContext(
            run_id="run-1",
            user_request="test",
            repo_path="/tmp/repo",
            dry_run=False,
            artifacts_dir="/tmp/artifacts",
            worktrees_dir="/tmp/worktrees",
        )
        work_item = WorkItem(
            id="dispatch_review",
            title="Dispatch review",
            profile="github_review_workflow",
            agent=AgentType.COPILOT,
            mode=ExecutionMode.GITHUB,
            prompt_template="",
            metadata={"source_branch": "feature/test"},
        )
        profile = self.config.profiles["github_review_workflow"]
        create_process = mock.AsyncMock(
            side_effect=[
                _FakeProcess(1, "", "connection refused"),
                _FakeProcess(
                    0,
                    "",
                    "Created workflow run: https://github.com/owner/repo/actions/runs/123456789",
                ),
            ]
        )

        with mock.patch(
            "openclaw_v2.executors.github.asyncio.create_subprocess_exec",
            new=create_process,
        ):
            result = await self.executor.execute(work_item, profile, context, "hello")

        self.assertEqual(result.status, TaskStatus.SUCCEEDED)
        self.assertEqual(result.artifacts["github_attempt_count"], 2)
        self.assertTrue(result.artifacts["github_retried"])
        self.assertIn("after 2 attempts", result.summary)
        self.assertEqual(result.artifacts["workflow_run_id"], "123456789")
        self.assertEqual(create_process.await_count, 2)

    async def test_blocked_auth_failure_does_not_retry_even_when_attempts_are_enabled(self) -> None:
        self.config.runtime.github_retry_attempts = 3
        self.config.runtime.github_retry_backoff_seconds = 0
        context = ExecutionContext(
            run_id="run-1",
            user_request="test",
            repo_path="/tmp/repo",
            dry_run=False,
            artifacts_dir="/tmp/artifacts",
            worktrees_dir="/tmp/worktrees",
        )
        work_item = WorkItem(
            id="update_issue",
            title="Update issue",
            profile="copilot_issue_followup",
            agent=AgentType.COPILOT,
            mode=ExecutionMode.GITHUB,
            prompt_template="",
            metadata={"primary_issue_ref": "77"},
        )
        profile = self.config.profiles["copilot_issue_followup"]
        create_process = mock.AsyncMock(return_value=_FakeProcess(1, "", "authentication required"))

        with mock.patch(
            "openclaw_v2.executors.github.asyncio.create_subprocess_exec",
            new=create_process,
        ):
            result = await self.executor.execute(work_item, profile, context, "hello")

        self.assertEqual(result.status, TaskStatus.BLOCKED)
        self.assertEqual(result.artifacts["github_attempt_count"], 1)
        self.assertNotIn("github_retried", result.artifacts)
        self.assertEqual(create_process.await_count, 1)

    async def test_live_failure_keeps_command_and_github_error_artifact(self) -> None:
        context = ExecutionContext(
            run_id="run-1",
            user_request="test",
            repo_path="/tmp/repo",
            dry_run=False,
            artifacts_dir="/tmp/artifacts",
            worktrees_dir="/tmp/worktrees",
        )
        work_item = WorkItem(
            id="draft_pr",
            title="Draft PR",
            profile="copilot_pr",
            agent=AgentType.COPILOT,
            mode=ExecutionMode.GITHUB,
            prompt_template="",
            metadata={"primary_pr_ref": "42", "source_branch": "feature/test"},
        )
        profile = self.config.profiles["copilot_pr"]

        with mock.patch(
            "openclaw_v2.executors.github.asyncio.create_subprocess_exec",
            new=mock.AsyncMock(return_value=_FakeProcess(1, "", "connection refused")),
        ):
            result = await self.executor.execute(work_item, profile, context, "hello")

        self.assertEqual(result.status, TaskStatus.FAILED)
        self.assertTrue(result.command)
        self.assertEqual(result.artifacts["action"], "pr")
        self.assertIn("connection refused", result.artifacts["github_error"])
        self.assertEqual(result.artifacts["github_failure_kind"], "network_or_transport")
        self.assertTrue(result.artifacts["github_retryable"])
        self.assertIn("Retry after GitHub or network connectivity recovers", result.artifacts["github_recovery_hint"])
        self.assertEqual(result.artifacts["github_attempt_count"], 1)


if __name__ == "__main__":
    unittest.main()
