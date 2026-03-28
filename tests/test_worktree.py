import unittest

from openclaw_v2.worktree import WorktreeManager


class WorktreeManagerTests(unittest.TestCase):
    def test_branch_name_is_flat_and_stable(self) -> None:
        branch_name = WorktreeManager._branch_name("run-20260316T110107Z", "triage")

        self.assertEqual(branch_name, "openclaw-run-20260316t110107z-triage")
        self.assertNotIn("/", branch_name)

    def test_branch_name_sanitizes_invalid_characters(self) -> None:
        branch_name = WorktreeManager._branch_name("Run 1", "Implement:Fix")

        self.assertEqual(branch_name, "openclaw-run-1-implement-fix")
if __name__ == "__main__":
    unittest.main()
