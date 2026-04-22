import tempfile
import textwrap
import unittest

from openclaw_v2.config import diagnose_app_config, load_app_config
from openclaw_v2.models import CheckStatus


class ConfigDiagnosticsTests(unittest.TestCase):
    def test_doctor_reports_valid_config_as_non_failing(self) -> None:
        config = load_app_config("config_v2.yaml")

        checks = diagnose_app_config(config)

        self.assertTrue(any(check.name.startswith("managed_agent:") for check in checks))
        self.assertFalse(any(check.status == CheckStatus.FAILED for check in checks))

    def test_doctor_reports_managed_agent_kind_mismatch(self) -> None:
        content = textwrap.dedent(
            """
            runtime:
              pipeline: demo
            profiles:
              codex_local:
                agent: codex
                mode: cli
            managed_agents:
              claude_router:
                kind: claude
                profile: codex_local
            assignments: {}
            pipelines: {}
            """
        ).strip()

        with tempfile.NamedTemporaryFile("w+", suffix=".yaml", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            config = load_app_config(handle.name)

        checks = diagnose_app_config(config)
        target = next(check for check in checks if check.name == "managed_agent:claude_router")

        self.assertEqual(target.status, CheckStatus.FAILED)
        self.assertIn("does not match", target.message)

    def test_doctor_reports_unknown_assignment_reference(self) -> None:
        content = textwrap.dedent(
            """
            runtime:
              pipeline: demo
            profiles:
              claude_local:
                agent: claude
                mode: cli
            managed_agents: {}
            assignments: {}
            pipelines:
              demo:
                - id: triage
                  title: Triage
                  assignment: triage_local
                  prompt_template: test
            """
        ).strip()

        with tempfile.NamedTemporaryFile("w+", suffix=".yaml", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            config = load_app_config(handle.name)

        checks = diagnose_app_config(config)
        target = next(check for check in checks if check.name == "pipeline:demo:triage")

        self.assertEqual(target.status, CheckStatus.FAILED)
        self.assertIn("unknown assignment", target.message)

    def test_doctor_reports_unknown_pipeline_dependency_reference(self) -> None:
        content = textwrap.dedent(
            """
            runtime:
              pipeline: demo
            profiles:
              claude_local:
                agent: claude
                mode: cli
            managed_agents:
              triage_agent:
                kind: claude
                profile: claude_local
            assignments:
              triage_local:
                agent: triage_agent
            pipelines:
              demo:
                - id: triage
                  title: Triage
                  assignment: triage_local
                  prompt_template: test
                - id: publish_branch
                  title: Publish
                  assignment: triage_local
                  depends_on:
                    - review
                  prompt_template: test
            """
        ).strip()

        with tempfile.NamedTemporaryFile("w+", suffix=".yaml", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            config = load_app_config(handle.name)

        checks = diagnose_app_config(config)
        target = next(check for check in checks if check.name == "pipeline:demo:publish_branch:depends_on")

        self.assertEqual(target.status, CheckStatus.FAILED)
        self.assertIn("unknown dependencies", target.message)

    def test_doctor_reports_circular_pipeline_dependencies(self) -> None:
        content = textwrap.dedent(
            """
            runtime:
              pipeline: demo
            profiles:
              claude_local:
                agent: claude
                mode: cli
            managed_agents:
              triage_agent:
                kind: claude
                profile: claude_local
            assignments:
              triage_local:
                agent: triage_agent
            pipelines:
              demo:
                - id: triage
                  title: Triage
                  assignment: triage_local
                  depends_on:
                    - review
                  prompt_template: test
                - id: review
                  title: Review
                  assignment: triage_local
                  depends_on:
                    - triage
                  prompt_template: test
            """
        ).strip()

        with tempfile.NamedTemporaryFile("w+", suffix=".yaml", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            config = load_app_config(handle.name)

        checks = diagnose_app_config(config)
        target = next(check for check in checks if check.name == "pipeline:demo:cycles")

        self.assertEqual(target.status, CheckStatus.FAILED)
        self.assertIn("circular dependencies", target.message)

    def test_doctor_reports_invalid_github_retry_runtime(self) -> None:
        content = textwrap.dedent(
            """
            runtime:
              pipeline: demo
              cli_command_timeout_seconds: -1
              github_retry_attempts: 0
              github_retry_backoff_seconds: -1
              github_workflow_view_poll_attempts: 0
              github_workflow_view_poll_interval_seconds: -1
            profiles: {}
            managed_agents: {}
            assignments: {}
            pipelines: {}
            """
        ).strip()

        with tempfile.NamedTemporaryFile("w+", suffix=".yaml", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            config = load_app_config(handle.name)

        checks = diagnose_app_config(config)
        failed_names = {check.name for check in checks if check.status == CheckStatus.FAILED}

        self.assertIn("runtime:cli_command_timeout_seconds", failed_names)
        self.assertIn("runtime:github_retry_attempts", failed_names)
        self.assertIn("runtime:github_retry_backoff_seconds", failed_names)
        self.assertIn("runtime:github_workflow_view_poll_attempts", failed_names)
        self.assertIn("runtime:github_workflow_view_poll_interval_seconds", failed_names)

    def test_doctor_reports_invalid_github_profile_action(self) -> None:
        content = textwrap.dedent(
            """
            runtime:
              pipeline: demo
            profiles:
              bad_profile:
                agent: copilot
                mode: github
                action: nope
            managed_agents: {}
            assignments: {}
            pipelines: {}
            """
        ).strip()

        with tempfile.NamedTemporaryFile("w+", suffix=".yaml", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            config = load_app_config(handle.name)

        checks = diagnose_app_config(config)

        profile_check = next(check for check in checks if check.name == "profile:bad_profile")
        self.assertEqual(profile_check.status, CheckStatus.FAILED)
        self.assertIn("unsupported action", profile_check.message)


if __name__ == "__main__":
    unittest.main()
