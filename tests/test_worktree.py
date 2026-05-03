import tempfile
from unittest import mock
import unittest

from openclaw_v2.models import AgentType, ExecutionContext, ExecutionMode, WorkItem
from openclaw_v2.worktree import WorktreeManager


class WorktreeManagerTests(unittest.TestCase):
    def test_branch_name_is_flat_and_stable(self) -> None:
        branch_name = WorktreeManager._branch_name("run-20260316T110107Z", "triage")

        self.assertEqual(branch_name, "openclaw-run-20260316t110107z-triage")
        self.assertNotIn("/", branch_name)

    def test_branch_name_sanitizes_invalid_characters(self) -> None:
        branch_name = WorktreeManager._branch_name("Run 1", "Implement:Fix")

        self.assertEqual(branch_name, "openclaw-run-1-implement-fix")


class WorktreeManagerReuseTests(unittest.IsolatedAsyncioTestCase):
    async def test_prepare_can_reuse_source_workspace(self) -> None:
        manager = WorktreeManager()
        context = ExecutionContext(
            run_id="run-1",
            user_request="test",
            repo_path="/tmp/repo",
            dry_run=False,
            artifacts_dir="/tmp/artifacts",
            worktrees_dir="/tmp/worktrees",
        )
        work_item = WorkItem(
            id="commit_changes",
            title="Commit implementation changes locally",
            profile="git_commit_changes",
            agent=AgentType.SYSTEM,
            mode=ExecutionMode.CLI,
            prompt_template="",
            metadata={
                "reuse_source_workspace": True,
                "source_branch": "openclaw-run-1-implement",
                "source_workspace_path": "/tmp/worktrees/implement",
            },
        )

        await manager.prepare(work_item, context)

        self.assertEqual(work_item.workspace_path, "/tmp/worktrees/implement")
        self.assertEqual(work_item.branch_name, "openclaw-run-1-implement")
        self.assertEqual(work_item.metadata["workspace_strategy"], "reuse-source-workspace")

    async def test_prepare_openclaw_export_step_uses_worktree_in_dry_run(self) -> None:
        manager = WorktreeManager()
        context = ExecutionContext(
            run_id="run-1",
            user_request="test",
            repo_path="/tmp/repo",
            dry_run=True,
            artifacts_dir="/tmp/artifacts",
            worktrees_dir="/tmp/worktrees",
        )
        work_item = WorkItem(
            id="implement",
            title="Implement with OpenClaw",
            profile="openclaw_local",
            agent=AgentType.OPENCLAW,
            mode=ExecutionMode.OPENCLAW,
            prompt_template="",
            metadata={"export_branch": True},
        )

        await manager.prepare(work_item, context)

        self.assertEqual(work_item.workspace_path, "/tmp/worktrees/implement")
        self.assertEqual(work_item.branch_name, "openclaw-run-1-implement")
        self.assertEqual(work_item.metadata["workspace_strategy"], "git-worktree")

    async def test_cleanup_continues_when_workspace_disappears_before_remove_command(self) -> None:
        manager = WorktreeManager()
        context = ExecutionContext(
            run_id="run-1",
            user_request="test",
            repo_path="/tmp/repo",
            dry_run=False,
            artifacts_dir="/tmp/artifacts",
            worktrees_dir="/tmp/worktrees",
        )
        with tempfile.TemporaryDirectory() as workspace_path:
            work_item = WorkItem(
                id="implement",
                title="Implement with OpenClaw",
                profile="openclaw_local",
                agent=AgentType.OPENCLAW,
                mode=ExecutionMode.CLI,
                prompt_template="",
                workspace_path=workspace_path,
                branch_name="openclaw-run-1-implement",
                metadata={
                    "workspace_strategy": "git-worktree",
                    "workspace_repo_root": context.repo_path,
                },
            )

            commands: list[list[str]] = []

            async def fake_run(command: list[str]) -> None:
                commands.append(command)
                if command[3:5] == ["worktree", "remove"]:
                    raise RuntimeError("workspace already absent")

            with mock.patch.object(WorktreeManager, "_run", side_effect=fake_run):
                await manager.cleanup(
                    [work_item],
                    context,
                    cleanup_enabled=True,
                    retain_failed_worktrees=False,
                    run_success=True,
                    run_has_failures=False,
                )

        self.assertEqual(len(commands), 2)
        self.assertEqual(commands[0][3:5], ["worktree", "remove"])
        self.assertEqual(commands[1][3:5], ["branch", "-D"])
        self.assertEqual(work_item.metadata["workspace_cleanup_status"], "completed")
if __name__ == "__main__":
    unittest.main()
