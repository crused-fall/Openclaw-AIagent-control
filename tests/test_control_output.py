import unittest

from openclaw_v2.models import TaskStatus, parse_control_output


class ControlOutputTests(unittest.TestCase):
    def test_ready_marker_is_parsed_and_removed_from_output(self) -> None:
        signal = parse_control_output(
            "OPENCLAW_STATUS: ready\n1. 修改 README\n2. 运行验证"
        )

        self.assertEqual(signal.status, TaskStatus.SUCCEEDED)
        self.assertEqual(signal.cleaned_output, "1. 修改 README\n2. 运行验证")
        self.assertEqual(signal.block_reason, "")

    def test_blocked_marker_extracts_reason(self) -> None:
        signal = parse_control_output(
            "OPENCLAW_STATUS: blocked\n"
            "OPENCLAW_BLOCK_REASON: 登录页不在当前仓库中\n"
            "请提供正确仓库或文件路径。"
        )

        self.assertEqual(signal.status, TaskStatus.BLOCKED)
        self.assertEqual(signal.block_reason, "登录页不在当前仓库中")
        self.assertEqual(signal.cleaned_output, "请提供正确仓库或文件路径。")

    def test_blocked_marker_falls_back_to_first_content_line(self) -> None:
        signal = parse_control_output(
            "OPENCLAW_STATUS: blocked\n"
            "当前仓库只有 CLI 编排代码，没有登录页实现。"
        )

        self.assertEqual(signal.status, TaskStatus.BLOCKED)
        self.assertEqual(signal.block_reason, "当前仓库只有 CLI 编排代码，没有登录页实现。")

    def test_markdown_wrapped_markers_are_still_detected(self) -> None:
        signal = parse_control_output(
            "**OPENCLAW_STATUS: blocked**\n"
            "**OPENCLAW_BLOCK_REASON: 仓库中不存在登录页面**\n"
            "请提供正确仓库。"
        )

        self.assertEqual(signal.status, TaskStatus.BLOCKED)
        self.assertEqual(signal.block_reason, "仓库中不存在登录页面")
        self.assertEqual(signal.cleaned_output, "请提供正确仓库。")


if __name__ == "__main__":
    unittest.main()
