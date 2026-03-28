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
if __name__ == "__main__":
    unittest.main()
