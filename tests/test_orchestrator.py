import os
import unittest
from unittest import mock

from openclaw_v2.config import load_app_config
from openclaw_v2.models import AgentResult, AgentType, ExecutionContext, ExecutionMode, TaskStatus, WorkItem
from openclaw_v2.orchestrator import HybridOrchestrator


class OrchestratorDependencyTests(unittest.TestCase):
    def test_blocked_summary_includes_dependency_reason(self) -> None:
        work_item = WorkItem(
            id="implement",
            title="Implement main changes locally",
            profile="codex_local",
            agent=AgentType.CODEX,
            mode=ExecutionMode.CLI,
            prompt_template="",
            depends_on=["triage"],
        )
        completed = {
            "triage": AgentResult(
                work_item_id="triage",
                profile="claude_local",
                agent=AgentType.CLAUDE,
                mode=ExecutionMode.CLI,
                status=TaskStatus.BLOCKED,
                summary="CLI task Triage user request blocked: missing login page",
                artifacts={"blocked_reason": "仓库中不存在登录页面"},
            )
        }

        summary = HybridOrchestrator._blocked_summary(work_item, completed)
        outcomes = HybridOrchestrator._dependency_outcomes(work_item, completed)

        self.assertEqual(summary, "Skipped because dependency triage was blocked: 仓库中不存在登录页面")
        self.assertEqual(outcomes["blocked"][0]["id"], "triage")
        self.assertEqual(outcomes["blocked"][0]["blocked_reason"], "仓库中不存在登录页面")
        self.assertEqual(outcomes["failed"], [])
        self.assertEqual(outcomes["skipped"], [])

    def test_failed_summary_includes_dependency_summary(self) -> None:
        work_item = WorkItem(
            id="publish_branch",
            title="Publish implementation branch to origin",
            profile="git_push_branch",
            agent=AgentType.SYSTEM,
            mode=ExecutionMode.CLI,
            prompt_template="",
            depends_on=["implement"],
        )
        completed = {
            "implement": AgentResult(
                work_item_id="implement",
                profile="codex_local",
                agent=AgentType.CODEX,
                mode=ExecutionMode.CLI,
                status=TaskStatus.FAILED,
                summary="CLI task Implement main changes locally failed with exit code 1.",
            )
        }

        summary = HybridOrchestrator._blocked_summary(work_item, completed)

        self.assertEqual(
            summary,
            "Skipped because dependency implement failed: CLI task Implement main changes locally failed with exit code 1.",
        )

    def test_skipped_summary_includes_dependency_summary(self) -> None:
        work_item = WorkItem(
            id="review",
            title="Review implementation before publish",
            profile="claude_review_local",
            agent=AgentType.CLAUDE,
            mode=ExecutionMode.CLI,
            prompt_template="",
            depends_on=["implement"],
        )
        completed = {
            "implement": AgentResult(
                work_item_id="implement",
                profile="codex_local",
                agent=AgentType.CODEX,
                mode=ExecutionMode.CLI,
                status=TaskStatus.SKIPPED,
                summary="Skipped because dependency triage was blocked: 仓库中不存在登录页面",
            )
        }

        summary = HybridOrchestrator._blocked_summary(work_item, completed)
        outcomes = HybridOrchestrator._dependency_outcomes(work_item, completed)

        self.assertEqual(
            summary,
            "Skipped because dependency implement was skipped: Skipped because dependency triage was blocked: 仓库中不存在登录页面",
        )
        self.assertEqual(outcomes["skipped"][0]["id"], "implement")

    def test_collect_dependency_values_includes_workflow_run_reference(self) -> None:
        work_item = WorkItem(
            id="collect_review",
            title="Collect GitHub review workflow status",
            profile="github_review_workflow_status",
            agent=AgentType.COPILOT,
            mode=ExecutionMode.GITHUB,
            prompt_template="",
            depends_on=["dispatch_review"],
        )
        completed = {
            "dispatch_review": AgentResult(
                work_item_id="dispatch_review",
                profile="github_review_workflow",
                agent=AgentType.COPILOT,
                mode=ExecutionMode.GITHUB,
                status=TaskStatus.SUCCEEDED,
                summary="Workflow dispatched.",
                artifacts={"workflow_run_id": "123456789"},
            )
        }

        values = HybridOrchestrator._collect_dependency_values(work_item, completed)

        self.assertEqual(values["primary_workflow_run_ref"], "123456789")

    def test_collect_dependency_values_falls_back_to_source_branch_when_no_exported_branch_exists(self) -> None:
        work_item = WorkItem(
            id="update_issue",
            title="Update issue",
            profile="copilot_issue_followup",
            agent=AgentType.COPILOT,
            mode=ExecutionMode.GITHUB,
            prompt_template="",
            depends_on=["publish_branch"],
        )
        completed = {
            "publish_branch": AgentResult(
                work_item_id="publish_branch",
                profile="git_push_branch",
                agent=AgentType.SYSTEM,
                mode=ExecutionMode.CLI,
                status=TaskStatus.SKIPPED,
                summary="Skipped because dependency implement produced no file changes.",
                artifacts={
                    "source_branch": "openclaw-run-1-implement",
                    "noop_dependencies": [{"id": "implement", "summary": "noop"}],
                },
            )
        }

        values = HybridOrchestrator._collect_dependency_values(work_item, completed)

        self.assertEqual(values["primary_branch_name"], "openclaw-run-1-implement")
        self.assertEqual(values["source_branch"], "openclaw-run-1-implement")

    def test_collect_dependency_values_ignores_missing_dependencies(self) -> None:
        work_item = WorkItem(
            id="publish_branch",
            title="Publish implementation branch to origin",
            profile="git_push_branch",
            agent=AgentType.SYSTEM,
            mode=ExecutionMode.CLI,
            prompt_template="",
            depends_on=["implement", "review"],
        )
        completed = {
            "implement": AgentResult(
                work_item_id="implement",
                profile="codex_local",
                agent=AgentType.CODEX,
                mode=ExecutionMode.CLI,
                status=TaskStatus.SUCCEEDED,
                summary="noop",
                artifacts={
                    "branch_name": "openclaw-run-1-implement",
                    "exports_branch": True,
                    "source_branch": "openclaw-run-1-implement",
                },
            )
        }

        values = HybridOrchestrator._collect_dependency_values(work_item, completed)

        self.assertEqual(values["primary_branch_name"], "openclaw-run-1-implement")
        self.assertEqual(values["source_branch"], "openclaw-run-1-implement")

    def test_noop_summary_includes_dependency_id(self) -> None:
        work_item = WorkItem(
            id="publish_branch",
            title="Publish implementation branch to origin",
            profile="git_push_branch",
            agent=AgentType.SYSTEM,
            mode=ExecutionMode.CLI,
            prompt_template="",
            depends_on=["implement"],
            metadata={"requires_workspace_changes": True},
        )
        completed = {
            "implement": AgentResult(
                work_item_id="implement",
                profile="codex_local",
                agent=AgentType.CODEX,
                mode=ExecutionMode.CLI,
                status=TaskStatus.SUCCEEDED,
                summary="CLI task Implement main changes locally finished successfully with no file changes required.",
                artifacts={"noop_result": True},
            )
        }

        summary = HybridOrchestrator._noop_summary(work_item, completed)

        self.assertEqual(summary, "Skipped because dependency implement produced no file changes.")

    def test_dependency_is_satisfied_by_allowed_noop_skipped_dependency(self) -> None:
        work_item = WorkItem(
            id="update_issue",
            title="Update issue",
            profile="copilot_issue_followup",
            agent=AgentType.COPILOT,
            mode=ExecutionMode.GITHUB,
            prompt_template="",
            depends_on=["publish_branch"],
            metadata={"allow_noop_skipped_dependencies": ["publish_branch"]},
        )
        completed = {
            "publish_branch": AgentResult(
                work_item_id="publish_branch",
                profile="git_push_branch",
                agent=AgentType.SYSTEM,
                mode=ExecutionMode.CLI,
                status=TaskStatus.SKIPPED,
                summary="Skipped because dependency implement produced no file changes.",
                artifacts={"noop_dependencies": [{"id": "implement", "summary": "noop"}]},
            )
        }

        self.assertTrue(HybridOrchestrator._dependency_is_satisfied(work_item, "publish_branch", completed))

    def test_dependency_is_not_satisfied_by_unallowed_noop_skipped_dependency(self) -> None:
        work_item = WorkItem(
            id="draft_pr",
            title="Draft PR",
            profile="copilot_pr",
            agent=AgentType.COPILOT,
            mode=ExecutionMode.GITHUB,
            prompt_template="",
            depends_on=["publish_branch"],
        )
        completed = {
            "publish_branch": AgentResult(
                work_item_id="publish_branch",
                profile="git_push_branch",
                agent=AgentType.SYSTEM,
                mode=ExecutionMode.CLI,
                status=TaskStatus.SKIPPED,
                summary="Skipped because dependency implement produced no file changes.",
                artifacts={"noop_dependencies": [{"id": "implement", "summary": "noop"}]},
            )
        }

        self.assertFalse(HybridOrchestrator._dependency_is_satisfied(work_item, "publish_branch", completed))


class OrchestratorExecutionTests(unittest.IsolatedAsyncioTestCase):
    async def test_execute_ready_items_blocks_planning_errors_without_preparation(self) -> None:
        orchestrator = HybridOrchestrator(load_app_config("config_v2.yaml"))
        context = ExecutionContext(
            run_id="run-1",
            user_request="test",
            repo_path="/tmp/repo",
            dry_run=False,
            artifacts_dir="/tmp/artifacts",
            worktrees_dir="/tmp/worktrees",
        )
        work_item = WorkItem(
            id="triage",
            title="Triage user request",
            profile="",
            agent=AgentType.SYSTEM,
            mode=ExecutionMode.SYSTEM,
            prompt_template="",
            assignment="triage_local",
            planning_blocked_reason="Assignment `triage_local` could not resolve a usable managed agent.",
        )

        with mock.patch.object(
            orchestrator.worktree_manager,
            "prepare",
            new=mock.AsyncMock(),
        ) as prepare:
            results = await orchestrator._execute_ready_items([work_item], context, {})

        self.assertEqual(results[0].status, TaskStatus.BLOCKED)
        self.assertIn("blocked before execution", results[0].summary)
        self.assertEqual(
            results[0].artifacts["blocked_reason"],
            "Assignment `triage_local` could not resolve a usable managed agent.",
        )
        prepare.assert_not_awaited()

    async def test_run_emits_progress_messages_for_dry_run_step(self) -> None:
        config = load_app_config("config_v2.yaml")
        config.runtime.dry_run = True
        orchestrator = HybridOrchestrator(config)
        messages: list[str] = []

        repo_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        result = await orchestrator.run(
            "test request",
            repo_path,
            selected_steps=["triage"],
            progress_callback=messages.append,
        )

        self.assertTrue(result.results)
        self.assertIn("preflight:start", messages)
        self.assertIn("preflight:ok", messages)
        self.assertTrue(any(message.startswith("step:start triage ") for message in messages))
        self.assertIn("step:done triage -> succeeded", messages)


if __name__ == "__main__":
    unittest.main()
