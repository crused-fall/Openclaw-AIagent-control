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

    def test_required_dependency_branch_reason_detects_missing_exported_branch(self) -> None:
        work_item = WorkItem(
            id="publish_branch",
            title="Publish implementation branch to origin",
            profile="git_push_branch",
            agent=AgentType.SYSTEM,
            mode=ExecutionMode.CLI,
            prompt_template="",
            depends_on=["implement", "review"],
            metadata={"requires_dependency_branch": True},
        )
        completed = {
            "implement": AgentResult(
                work_item_id="implement",
                profile="openclaw_local",
                agent=AgentType.OPENCLAW,
                mode=ExecutionMode.OPENCLAW,
                status=TaskStatus.SUCCEEDED,
                summary="Implemented locally.",
                artifacts={"workspace_has_changes": True, "workspace_changed_files": ["README.md"]},
            ),
            "review": AgentResult(
                work_item_id="review",
                profile="openclaw_local",
                agent=AgentType.OPENCLAW,
                mode=ExecutionMode.OPENCLAW,
                status=TaskStatus.SUCCEEDED,
                summary="Reviewed.",
            ),
        }

        reason = HybridOrchestrator._required_dependency_branch_reason(work_item, completed)

        self.assertIn("requires an exported dependency branch", reason)

    def test_required_dependency_commit_reason_detects_uncommitted_workspace_changes(self) -> None:
        work_item = WorkItem(
            id="publish_branch",
            title="Publish implementation branch to origin",
            profile="git_push_branch",
            agent=AgentType.SYSTEM,
            mode=ExecutionMode.CLI,
            prompt_template="",
            depends_on=["implement", "review"],
            metadata={"requires_committed_dependency_changes": True},
        )
        completed = {
            "implement": AgentResult(
                work_item_id="implement",
                profile="codex_local",
                agent=AgentType.CODEX,
                mode=ExecutionMode.CLI,
                status=TaskStatus.SUCCEEDED,
                summary="Implemented locally.",
                artifacts={
                    "branch_name": "openclaw-run-1-implement",
                    "exports_branch": True,
                    "source_branch": "openclaw-run-1-implement",
                    "workspace_has_changes": True,
                    "workspace_changed_files": ["README.md"],
                },
            ),
            "review": AgentResult(
                work_item_id="review",
                profile="openclaw_local",
                agent=AgentType.OPENCLAW,
                mode=ExecutionMode.OPENCLAW,
                status=TaskStatus.SUCCEEDED,
                summary="Reviewed.",
            ),
        }

        reason = HybridOrchestrator._required_dependency_commit_reason(work_item, completed)

        self.assertIn("requires dependency changes to be committed before push", reason)


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

    async def test_run_allows_issue_followup_after_noop_publish_in_openclaw_default_flow(self) -> None:
        orchestrator = HybridOrchestrator(load_app_config("config_v2.yaml"))
        repo_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

        triage = WorkItem(
            id="triage",
            title="Triage user request with local OpenClaw",
            profile="openclaw_local",
            agent=AgentType.OPENCLAW,
            mode=ExecutionMode.OPENCLAW,
            prompt_template="",
            assignment="triage_openclaw",
            managed_agent="openclaw_router",
            depends_on=[],
            workspace_path=repo_path,
        )
        implement = WorkItem(
            id="implement",
            title="Implement main changes locally",
            profile="codex_local",
            agent=AgentType.CODEX,
            mode=ExecutionMode.CLI,
            prompt_template="",
            assignment="implement_local",
            managed_agent="codex_builder",
            depends_on=["triage"],
            workspace_path="/tmp/worktrees/implement",
            branch_name="openclaw-run-1-implement",
        )
        review = WorkItem(
            id="review",
            title="Review implementation before publish with local OpenClaw",
            profile="openclaw_local",
            agent=AgentType.OPENCLAW,
            mode=ExecutionMode.OPENCLAW,
            prompt_template="",
            assignment="review_openclaw",
            managed_agent="openclaw_router",
            depends_on=["implement"],
            workspace_path=repo_path,
        )
        publish_branch = WorkItem(
            id="publish_branch",
            title="Publish implementation branch to origin",
            profile="git_push_branch",
            agent=AgentType.SYSTEM,
            mode=ExecutionMode.CLI,
            prompt_template="",
            assignment="publish_branch_local",
            managed_agent="git_branch_publisher",
            depends_on=["implement", "review"],
            metadata={"requires_workspace_changes": True},
            workspace_path=repo_path,
            branch_name="openclaw-run-1-implement",
        )
        sync_issue = WorkItem(
            id="sync_issue",
            title="Sync planning issue to GitHub",
            profile="copilot_issue",
            agent=AgentType.COPILOT,
            mode=ExecutionMode.GITHUB,
            prompt_template="",
            assignment="sync_issue_bridge",
            managed_agent="github_issue_bridge",
            depends_on=["triage"],
            workspace_path=repo_path,
        )
        update_issue = WorkItem(
            id="update_issue",
            title="Update GitHub issue with implementation status",
            profile="copilot_issue_followup",
            agent=AgentType.COPILOT,
            mode=ExecutionMode.GITHUB,
            prompt_template="",
            assignment="update_issue_bridge",
            managed_agent="github_issue_followup_bridge",
            depends_on=["publish_branch", "review", "sync_issue"],
            metadata={"allow_noop_skipped_dependencies": ["publish_branch"]},
            workspace_path=repo_path,
        )
        draft_pr = WorkItem(
            id="draft_pr",
            title="Prepare GitHub draft PR summary",
            profile="copilot_pr",
            agent=AgentType.COPILOT,
            mode=ExecutionMode.GITHUB,
            prompt_template="",
            assignment="draft_pr_bridge",
            managed_agent="github_pr_bridge",
            depends_on=["publish_branch", "review", "sync_issue", "update_issue"],
            workspace_path=repo_path,
        )
        dispatch_review = WorkItem(
            id="dispatch_review",
            title="Trigger GitHub review workflow",
            profile="github_review_workflow",
            agent=AgentType.COPILOT,
            mode=ExecutionMode.GITHUB,
            prompt_template="",
            assignment="dispatch_review_bridge",
            managed_agent="github_review_bridge",
            depends_on=["publish_branch", "review", "draft_pr"],
            workspace_path=repo_path,
        )
        collect_review = WorkItem(
            id="collect_review",
            title="Collect GitHub review workflow status",
            profile="github_review_workflow_status",
            agent=AgentType.COPILOT,
            mode=ExecutionMode.GITHUB,
            prompt_template="",
            assignment="collect_review_bridge",
            managed_agent="github_review_followup_bridge",
            depends_on=["dispatch_review"],
            workspace_path=repo_path,
        )
        plan = [
            triage,
            implement,
            review,
            publish_branch,
            sync_issue,
            update_issue,
            draft_pr,
            dispatch_review,
            collect_review,
        ]

        async def execute_openclaw(
            work_item: WorkItem,
            profile,
            context: ExecutionContext,
            rendered_prompt: str,
        ) -> AgentResult:
            if work_item.id == "triage":
                return AgentResult(
                    work_item_id="triage",
                    profile=work_item.profile,
                    agent=work_item.agent,
                    mode=work_item.mode,
                    status=TaskStatus.SUCCEEDED,
                    summary="Triage ok.",
                )
            if work_item.id == "review":
                return AgentResult(
                    work_item_id="review",
                    profile=work_item.profile,
                    agent=work_item.agent,
                    mode=work_item.mode,
                    status=TaskStatus.SUCCEEDED,
                    summary="Review ok.",
                )
            raise AssertionError(f"unexpected OpenClaw execution for {work_item.id}")

        async def execute_cli(
            work_item: WorkItem,
            profile,
            context: ExecutionContext,
            rendered_prompt: str,
        ) -> AgentResult:
            if work_item.id == "implement":
                return AgentResult(
                    work_item_id="implement",
                    profile=work_item.profile,
                    agent=work_item.agent,
                    mode=work_item.mode,
                    status=TaskStatus.SUCCEEDED,
                    summary="Implement finished with no file changes required.",
                    artifacts={
                        "noop_result": True,
                        "source_branch": "openclaw-run-1-implement",
                    },
                )
            raise AssertionError(f"unexpected CLI execution for {work_item.id}")

        async def execute_github(
            work_item: WorkItem,
            profile,
            context: ExecutionContext,
            rendered_prompt: str,
        ) -> AgentResult:
            if work_item.id == "sync_issue":
                return AgentResult(
                    work_item_id="sync_issue",
                    profile=work_item.profile,
                    agent=work_item.agent,
                    mode=work_item.mode,
                    status=TaskStatus.SUCCEEDED,
                    summary="Issue synced.",
                    artifacts={"issue_number": "42"},
                )
            if work_item.id == "update_issue":
                return AgentResult(
                    work_item_id="update_issue",
                    profile=work_item.profile,
                    agent=work_item.agent,
                    mode=work_item.mode,
                    status=TaskStatus.SUCCEEDED,
                    summary="Issue updated.",
                    artifacts={"issue_number": "42"},
                )
            raise AssertionError(f"unexpected GitHub execution for {work_item.id}")

        preflight_report = mock.Mock(ok=True, checks=[])

        with mock.patch.object(orchestrator, "build_plan", return_value=plan), mock.patch.object(
            orchestrator.preflight_runner,
            "run",
            new=mock.AsyncMock(return_value=preflight_report),
        ), mock.patch.object(
            orchestrator.worktree_manager,
            "prepare",
            new=mock.AsyncMock(),
        ), mock.patch.object(
            orchestrator.artifact_store,
            "initialize_run",
        ), mock.patch.object(
            orchestrator.artifact_store,
            "write_preflight_report",
        ), mock.patch.object(
            orchestrator.artifact_store,
            "write_workspace_manifest",
        ), mock.patch.object(
            orchestrator.artifact_store,
            "write_prompt",
            return_value="/tmp/prompt.txt",
        ), mock.patch.object(
            orchestrator.artifact_store,
            "write_result",
        ), mock.patch.object(
            orchestrator.artifact_store,
            "write_run_summary",
        ):
            orchestrator.executors[ExecutionMode.OPENCLAW].execute = mock.AsyncMock(side_effect=execute_openclaw)
            orchestrator.executors[ExecutionMode.CLI].execute = mock.AsyncMock(side_effect=execute_cli)
            orchestrator.executors[ExecutionMode.GITHUB].execute = mock.AsyncMock(side_effect=execute_github)

            result = await orchestrator.run(
                "在 README 中补一行，说明 GitHub bridge 的 403 token 权限不足恢复方式",
                repo_path,
                selected_steps=["collect_review"],
            )

        results_by_id = {item.work_item_id: item for item in result.results}

        self.assertTrue(result.success)
        self.assertEqual(results_by_id["triage"].status, TaskStatus.SUCCEEDED)
        self.assertEqual(results_by_id["implement"].status, TaskStatus.SUCCEEDED)
        self.assertTrue(results_by_id["implement"].artifacts["noop_result"])
        self.assertEqual(results_by_id["sync_issue"].status, TaskStatus.SUCCEEDED)
        self.assertEqual(results_by_id["publish_branch"].status, TaskStatus.SKIPPED)
        self.assertEqual(
            results_by_id["publish_branch"].artifacts["source_branch"],
            "openclaw-run-1-implement",
        )
        self.assertEqual(results_by_id["review"].status, TaskStatus.SUCCEEDED)
        self.assertEqual(results_by_id["update_issue"].status, TaskStatus.SUCCEEDED)
        self.assertEqual(results_by_id["draft_pr"].status, TaskStatus.SKIPPED)
        self.assertEqual(results_by_id["dispatch_review"].status, TaskStatus.SKIPPED)
        self.assertEqual(results_by_id["collect_review"].status, TaskStatus.SKIPPED)
        self.assertIn("publish_branch", results_by_id["draft_pr"].summary)
        self.assertEqual(results_by_id["update_issue"].artifacts["issue_number"], "42")

    async def test_run_blocks_publish_branch_without_exported_dependency_branch(self) -> None:
        orchestrator = HybridOrchestrator(load_app_config("config_v2.yaml"))
        repo_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

        implement = WorkItem(
            id="implement",
            title="Implement main changes locally",
            profile="openclaw_local",
            agent=AgentType.OPENCLAW,
            mode=ExecutionMode.OPENCLAW,
            prompt_template="",
            assignment="implement_local",
            managed_agent="openclaw_builder",
            depends_on=[],
            workspace_path=repo_path,
        )
        review = WorkItem(
            id="review",
            title="Review implementation before publish with local OpenClaw",
            profile="openclaw_local",
            agent=AgentType.OPENCLAW,
            mode=ExecutionMode.OPENCLAW,
            prompt_template="",
            assignment="review_openclaw",
            managed_agent="openclaw_router",
            depends_on=["implement"],
            workspace_path=repo_path,
        )
        publish_branch = WorkItem(
            id="publish_branch",
            title="Publish implementation branch to origin",
            profile="git_push_branch",
            agent=AgentType.SYSTEM,
            mode=ExecutionMode.CLI,
            prompt_template="",
            assignment="publish_branch_local",
            managed_agent="git_branch_publisher",
            depends_on=["implement", "review"],
            metadata={"requires_dependency_branch": True},
            workspace_path=repo_path,
        )
        plan = [implement, review, publish_branch]

        async def execute_openclaw(
            work_item: WorkItem,
            profile,
            context: ExecutionContext,
            rendered_prompt: str,
        ) -> AgentResult:
            if work_item.id == "implement":
                return AgentResult(
                    work_item_id="implement",
                    profile=work_item.profile,
                    agent=work_item.agent,
                    mode=work_item.mode,
                    status=TaskStatus.SUCCEEDED,
                    summary="Implemented locally.",
                    artifacts={"workspace_has_changes": True, "workspace_changed_files": ["README.md"]},
                )
            if work_item.id == "review":
                return AgentResult(
                    work_item_id="review",
                    profile=work_item.profile,
                    agent=work_item.agent,
                    mode=work_item.mode,
                    status=TaskStatus.SUCCEEDED,
                    summary="Reviewed locally.",
                )
            raise AssertionError(f"unexpected OpenClaw execution for {work_item.id}")

        preflight_report = mock.Mock(ok=True, checks=[])
        with mock.patch.object(orchestrator, "build_plan", return_value=plan), mock.patch.object(
            orchestrator.preflight_runner,
            "run",
            new=mock.AsyncMock(return_value=preflight_report),
        ), mock.patch.object(
            orchestrator.worktree_manager,
            "prepare",
            new=mock.AsyncMock(),
        ), mock.patch.object(
            orchestrator.artifact_store,
            "initialize_run",
        ), mock.patch.object(
            orchestrator.artifact_store,
            "write_preflight_report",
        ), mock.patch.object(
            orchestrator.artifact_store,
            "write_workspace_manifest",
        ), mock.patch.object(
            orchestrator.artifact_store,
            "write_prompt",
            return_value="/tmp/prompt.txt",
        ), mock.patch.object(
            orchestrator.artifact_store,
            "write_result",
        ), mock.patch.object(
            orchestrator.artifact_store,
            "write_run_summary",
        ):
            orchestrator.executors[ExecutionMode.OPENCLAW].execute = mock.AsyncMock(side_effect=execute_openclaw)
            result = await orchestrator.run(
                "test request",
                repo_path,
                selected_steps=["publish_branch"],
            )

        results_by_id = {item.work_item_id: item for item in result.results}

        self.assertEqual(results_by_id["implement"].status, TaskStatus.SUCCEEDED)
        self.assertEqual(results_by_id["review"].status, TaskStatus.SUCCEEDED)
        self.assertEqual(results_by_id["publish_branch"].status, TaskStatus.BLOCKED)
        self.assertIn("requires an exported dependency branch", results_by_id["publish_branch"].summary)

    async def test_run_blocks_publish_branch_with_uncommitted_dependency_changes(self) -> None:
        orchestrator = HybridOrchestrator(load_app_config("config_v2.yaml"))
        repo_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

        implement = WorkItem(
            id="implement",
            title="Implement main changes locally",
            profile="codex_local",
            agent=AgentType.CODEX,
            mode=ExecutionMode.CLI,
            prompt_template="",
            assignment="implement_local",
            managed_agent="codex_builder",
            depends_on=[],
            workspace_path="/tmp/worktrees/implement",
            branch_name="openclaw-run-1-implement",
        )
        review = WorkItem(
            id="review",
            title="Review implementation before publish with local OpenClaw",
            profile="openclaw_local",
            agent=AgentType.OPENCLAW,
            mode=ExecutionMode.OPENCLAW,
            prompt_template="",
            assignment="review_openclaw",
            managed_agent="openclaw_router",
            depends_on=["implement"],
            workspace_path=repo_path,
        )
        publish_branch = WorkItem(
            id="publish_branch",
            title="Publish implementation branch to origin",
            profile="git_push_branch",
            agent=AgentType.SYSTEM,
            mode=ExecutionMode.CLI,
            prompt_template="",
            assignment="publish_branch_local",
            managed_agent="git_branch_publisher",
            depends_on=["implement", "review"],
            metadata={
                "requires_dependency_branch": True,
                "requires_committed_dependency_changes": True,
            },
            workspace_path=repo_path,
        )
        plan = [implement, review, publish_branch]

        async def execute_cli(
            work_item: WorkItem,
            profile,
            context: ExecutionContext,
            rendered_prompt: str,
        ) -> AgentResult:
            if work_item.id == "implement":
                return AgentResult(
                    work_item_id="implement",
                    profile=work_item.profile,
                    agent=work_item.agent,
                    mode=work_item.mode,
                    status=TaskStatus.SUCCEEDED,
                    summary="Implemented locally.",
                    artifacts={
                        "branch_name": "openclaw-run-1-implement",
                        "exports_branch": True,
                        "source_branch": "openclaw-run-1-implement",
                        "workspace_has_changes": True,
                        "workspace_changed_files": ["README.md"],
                    },
                )
            raise AssertionError(f"unexpected CLI execution for {work_item.id}")

        async def execute_openclaw(
            work_item: WorkItem,
            profile,
            context: ExecutionContext,
            rendered_prompt: str,
        ) -> AgentResult:
            if work_item.id == "review":
                return AgentResult(
                    work_item_id="review",
                    profile=work_item.profile,
                    agent=work_item.agent,
                    mode=work_item.mode,
                    status=TaskStatus.SUCCEEDED,
                    summary="Reviewed locally.",
                )
            raise AssertionError(f"unexpected OpenClaw execution for {work_item.id}")

        preflight_report = mock.Mock(ok=True, checks=[])
        with mock.patch.object(orchestrator, "build_plan", return_value=plan), mock.patch.object(
            orchestrator.preflight_runner,
            "run",
            new=mock.AsyncMock(return_value=preflight_report),
        ), mock.patch.object(
            orchestrator.worktree_manager,
            "prepare",
            new=mock.AsyncMock(),
        ), mock.patch.object(
            orchestrator.artifact_store,
            "initialize_run",
        ), mock.patch.object(
            orchestrator.artifact_store,
            "write_preflight_report",
        ), mock.patch.object(
            orchestrator.artifact_store,
            "write_workspace_manifest",
        ), mock.patch.object(
            orchestrator.artifact_store,
            "write_prompt",
            return_value="/tmp/prompt.txt",
        ), mock.patch.object(
            orchestrator.artifact_store,
            "write_result",
        ), mock.patch.object(
            orchestrator.artifact_store,
            "write_run_summary",
        ):
            orchestrator.executors[ExecutionMode.CLI].execute = mock.AsyncMock(side_effect=execute_cli)
            orchestrator.executors[ExecutionMode.OPENCLAW].execute = mock.AsyncMock(side_effect=execute_openclaw)
            result = await orchestrator.run(
                "test request",
                repo_path,
                selected_steps=["publish_branch"],
            )

        results_by_id = {item.work_item_id: item for item in result.results}

        self.assertEqual(results_by_id["implement"].status, TaskStatus.SUCCEEDED)
        self.assertEqual(results_by_id["review"].status, TaskStatus.SUCCEEDED)
        self.assertEqual(results_by_id["publish_branch"].status, TaskStatus.BLOCKED)
        self.assertIn("requires dependency changes to be committed before push", results_by_id["publish_branch"].summary)

    async def test_run_allows_publish_after_commit_changes_succeeds(self) -> None:
        orchestrator = HybridOrchestrator(load_app_config("config_v2.yaml"))
        repo_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

        implement = WorkItem(
            id="implement",
            title="Implement main changes locally",
            profile="codex_local",
            agent=AgentType.CODEX,
            mode=ExecutionMode.CLI,
            prompt_template="",
            assignment="implement_local",
            managed_agent="codex_builder",
            depends_on=[],
            workspace_path="/tmp/worktrees/implement",
            branch_name="openclaw-run-1-implement",
        )
        review = WorkItem(
            id="review",
            title="Review implementation before publish with local OpenClaw",
            profile="openclaw_local",
            agent=AgentType.OPENCLAW,
            mode=ExecutionMode.OPENCLAW,
            prompt_template="",
            assignment="review_openclaw",
            managed_agent="openclaw_router",
            depends_on=["implement"],
            workspace_path=repo_path,
        )
        commit_changes = WorkItem(
            id="commit_changes",
            title="Commit implementation changes locally",
            profile="git_commit_changes",
            agent=AgentType.SYSTEM,
            mode=ExecutionMode.CLI,
            prompt_template="",
            assignment="commit_changes_local",
            managed_agent="git_change_committer",
            depends_on=["implement", "review"],
            metadata={
                "requires_workspace_changes": True,
                "requires_dependency_branch": True,
                "reuse_source_workspace": True,
                "commits_workspace_changes": True,
                "export_branch": True,
            },
            workspace_path="/tmp/worktrees/implement",
            branch_name="openclaw-run-1-implement",
        )
        publish_branch = WorkItem(
            id="publish_branch",
            title="Publish implementation branch to origin",
            profile="git_push_branch",
            agent=AgentType.SYSTEM,
            mode=ExecutionMode.CLI,
            prompt_template="",
            assignment="publish_branch_local",
            managed_agent="git_branch_publisher",
            depends_on=["commit_changes", "review"],
            metadata={
                "requires_dependency_branch": True,
                "requires_committed_dependency_changes": True,
            },
            workspace_path=repo_path,
        )
        plan = [implement, review, commit_changes, publish_branch]

        async def execute_cli(
            work_item: WorkItem,
            profile,
            context: ExecutionContext,
            rendered_prompt: str,
        ) -> AgentResult:
            if work_item.id == "implement":
                return AgentResult(
                    work_item_id="implement",
                    profile=work_item.profile,
                    agent=work_item.agent,
                    mode=work_item.mode,
                    status=TaskStatus.SUCCEEDED,
                    summary="Implemented locally.",
                    artifacts={
                        "branch_name": "openclaw-run-1-implement",
                        "exports_branch": True,
                        "source_branch": "openclaw-run-1-implement",
                        "workspace_path": "/tmp/worktrees/implement",
                        "workspace_has_changes": True,
                        "workspace_changed_files": ["README.md"],
                    },
                )
            if work_item.id == "commit_changes":
                return AgentResult(
                    work_item_id="commit_changes",
                    profile=work_item.profile,
                    agent=work_item.agent,
                    mode=work_item.mode,
                    status=TaskStatus.SUCCEEDED,
                    summary="Committed local changes.",
                    artifacts={
                        "branch_name": "openclaw-run-1-implement",
                        "exports_branch": True,
                        "source_branch": "openclaw-run-1-implement",
                        "workspace_path": "/tmp/worktrees/implement",
                        "workspace_has_changes": True,
                        "workspace_changed_files": ["README.md"],
                        "changes_committed": True,
                        "head_commit": "abc123",
                    },
                )
            if work_item.id == "publish_branch":
                return AgentResult(
                    work_item_id="publish_branch",
                    profile=work_item.profile,
                    agent=work_item.agent,
                    mode=work_item.mode,
                    status=TaskStatus.SUCCEEDED,
                    summary="Published branch.",
                    artifacts={
                        "branch_name": "openclaw-run-1-implement",
                        "exports_branch": True,
                        "source_branch": "openclaw-run-1-implement",
                    },
                )
            raise AssertionError(f"unexpected CLI execution for {work_item.id}")

        async def execute_openclaw(
            work_item: WorkItem,
            profile,
            context: ExecutionContext,
            rendered_prompt: str,
        ) -> AgentResult:
            if work_item.id == "review":
                return AgentResult(
                    work_item_id="review",
                    profile=work_item.profile,
                    agent=work_item.agent,
                    mode=work_item.mode,
                    status=TaskStatus.SUCCEEDED,
                    summary="Reviewed locally.",
                )
            raise AssertionError(f"unexpected OpenClaw execution for {work_item.id}")

        preflight_report = mock.Mock(ok=True, checks=[])
        with mock.patch.object(orchestrator, "build_plan", return_value=plan), mock.patch.object(
            orchestrator.preflight_runner,
            "run",
            new=mock.AsyncMock(return_value=preflight_report),
        ), mock.patch.object(
            orchestrator.worktree_manager,
            "prepare",
            new=mock.AsyncMock(),
        ), mock.patch.object(
            orchestrator.artifact_store,
            "initialize_run",
        ), mock.patch.object(
            orchestrator.artifact_store,
            "write_preflight_report",
        ), mock.patch.object(
            orchestrator.artifact_store,
            "write_workspace_manifest",
        ), mock.patch.object(
            orchestrator.artifact_store,
            "write_prompt",
            return_value="/tmp/prompt.txt",
        ), mock.patch.object(
            orchestrator.artifact_store,
            "write_result",
        ), mock.patch.object(
            orchestrator.artifact_store,
            "write_run_summary",
        ):
            orchestrator.executors[ExecutionMode.CLI].execute = mock.AsyncMock(side_effect=execute_cli)
            orchestrator.executors[ExecutionMode.OPENCLAW].execute = mock.AsyncMock(side_effect=execute_openclaw)
            result = await orchestrator.run(
                "test request",
                repo_path,
                selected_steps=["publish_branch"],
            )

        results_by_id = {item.work_item_id: item for item in result.results}

        self.assertEqual(results_by_id["implement"].status, TaskStatus.SUCCEEDED)
        self.assertEqual(results_by_id["review"].status, TaskStatus.SUCCEEDED)
        self.assertEqual(results_by_id["commit_changes"].status, TaskStatus.SUCCEEDED)
        self.assertEqual(results_by_id["publish_branch"].status, TaskStatus.SUCCEEDED)


if __name__ == "__main__":
    unittest.main()
