import os
import tempfile
import textwrap
import unittest

from openclaw_v2.config import load_app_config
from openclaw_v2.models import ExecutionMode
from openclaw_v2.planner import PipelinePlanner


class PipelineConfigTests(unittest.TestCase):
    def test_default_pipeline_is_mission_control_default(self) -> None:
        config = load_app_config("config_v2.yaml")

        self.assertEqual(config.runtime.pipeline, "mission_control_default")
        self.assertEqual(config.runtime.cli_command_timeout_seconds, 180.0)
        self.assertEqual(config.runtime.github_retry_attempts, 1)
        self.assertEqual(config.runtime.github_retry_backoff_seconds, 1.0)
        self.assertEqual(config.runtime.github_workflow_view_poll_attempts, 6)
        self.assertEqual(config.runtime.github_workflow_view_poll_interval_seconds, 2.0)
        self.assertIn("review", config.runtime.allowed_live_steps)

    def test_mission_control_pipeline_contains_review_gate(self) -> None:
        config = load_app_config("config_v2.yaml")
        planner = PipelinePlanner(config)

        plan = planner.build_plan()
        work_items = {item.id: item for item in plan}

        self.assertIn("review", work_items)
        self.assertEqual(work_items["review"].depends_on, ["implement"])
        self.assertEqual(work_items["triage"].assignment, "triage_local")
        self.assertEqual(work_items["triage"].managed_agent, "claude_router")
        self.assertFalse(work_items["triage"].fallback_used)
        self.assertEqual(work_items["implement"].assignment, "implement_local")
        self.assertEqual(work_items["implement"].managed_agent, "codex_builder")
        self.assertEqual(work_items["implement"].fallback_chain, ["cursor_editor"])
        self.assertEqual(work_items["review"].assignment, "review_local")
        self.assertEqual(work_items["review"].managed_agent, "claude_router")
        self.assertEqual(sorted(work_items["publish_branch"].depends_on), ["implement", "review"])
        self.assertEqual(sorted(work_items["update_issue"].depends_on), ["publish_branch", "review", "sync_issue"])
        self.assertEqual(
            work_items["update_issue"].metadata["allow_noop_skipped_dependencies"],
            ["publish_branch"],
        )
        self.assertEqual(sorted(work_items["draft_pr"].depends_on), ["publish_branch", "review", "sync_issue", "update_issue"])
        self.assertEqual(work_items["dispatch_review"].depends_on, ["publish_branch", "review", "draft_pr"])
        self.assertEqual(work_items["collect_review"].depends_on, ["dispatch_review"])
        self.assertEqual(work_items["collect_review"].assignment, "collect_review_bridge")
        self.assertEqual(work_items["collect_review"].managed_agent, "github_review_followup_bridge")

    def test_openclaw_pipeline_uses_openclaw_for_triage_only(self) -> None:
        config = load_app_config("config_v2.yaml")
        config.runtime.pipeline = "mission_control_openclaw_triage"
        planner = PipelinePlanner(config)

        plan = planner.build_plan()
        work_items = {item.id: item for item in plan}

        self.assertEqual(work_items["triage"].profile, "openclaw_local")
        self.assertEqual(work_items["triage"].assignment, "triage_openclaw")
        self.assertEqual(work_items["triage"].managed_agent, "openclaw_router")
        self.assertEqual(work_items["triage"].mode, ExecutionMode.OPENCLAW)
        self.assertEqual(work_items["implement"].mode, ExecutionMode.CLI)
        self.assertEqual(work_items["review"].mode, ExecutionMode.CLI)

    def test_openclaw_default_pipeline_uses_openclaw_for_triage_and_review(self) -> None:
        config = load_app_config("config_v2.yaml")
        config.runtime.pipeline = "mission_control_openclaw_default"
        planner = PipelinePlanner(config)

        plan = planner.build_plan()
        work_items = {item.id: item for item in plan}

        self.assertEqual(work_items["triage"].profile, "openclaw_local")
        self.assertEqual(work_items["triage"].assignment, "triage_openclaw")
        self.assertEqual(work_items["triage"].managed_agent, "openclaw_router")
        self.assertEqual(work_items["triage"].mode, ExecutionMode.OPENCLAW)
        self.assertEqual(work_items["implement"].mode, ExecutionMode.CLI)
        self.assertEqual(work_items["review"].profile, "openclaw_local")
        self.assertEqual(work_items["review"].assignment, "review_openclaw")
        self.assertEqual(work_items["review"].managed_agent, "openclaw_router")
        self.assertEqual(work_items["review"].mode, ExecutionMode.OPENCLAW)

    def test_openclaw_default_pipeline_can_override_implement_to_openclaw_builder(self) -> None:
        previous = os.environ.get("OPENCLAW_ASSIGN_IMPLEMENT_LOCAL")
        os.environ["OPENCLAW_ASSIGN_IMPLEMENT_LOCAL"] = "openclaw_builder"
        try:
            config = load_app_config("config_v2.yaml")
        finally:
            if previous is None:
                os.environ.pop("OPENCLAW_ASSIGN_IMPLEMENT_LOCAL", None)
            else:
                os.environ["OPENCLAW_ASSIGN_IMPLEMENT_LOCAL"] = previous
        config.runtime.pipeline = "mission_control_openclaw_default"
        planner = PipelinePlanner(config)

        plan = planner.build_plan()
        work_items = {item.id: item for item in plan}

        self.assertEqual(work_items["implement"].managed_agent, "openclaw_builder")
        self.assertEqual(work_items["implement"].profile, "openclaw_local")
        self.assertEqual(work_items["implement"].mode, ExecutionMode.OPENCLAW)

    def test_github_bridge_smoke_pipeline_only_contains_review_workflow_steps(self) -> None:
        config = load_app_config("config_v2.yaml")
        config.runtime.pipeline = "github_bridge_smoke"
        planner = PipelinePlanner(config)

        plan = planner.build_plan()
        work_items = {item.id: item for item in plan}

        self.assertEqual(list(work_items.keys()), ["dispatch_review", "collect_review"])
        self.assertEqual(work_items["dispatch_review"].mode, ExecutionMode.GITHUB)
        self.assertEqual(work_items["dispatch_review"].assignment, "dispatch_review_bridge")
        self.assertEqual(work_items["dispatch_review"].managed_agent, "github_review_bridge")
        self.assertEqual(work_items["dispatch_review"].depends_on, [])
        self.assertEqual(work_items["collect_review"].mode, ExecutionMode.GITHUB)
        self.assertEqual(work_items["collect_review"].assignment, "collect_review_bridge")
        self.assertEqual(work_items["collect_review"].managed_agent, "github_review_followup_bridge")
        self.assertEqual(work_items["collect_review"].depends_on, ["dispatch_review"])

    def test_all_named_pipelines_build_without_duplicate_step_ids(self) -> None:
        config = load_app_config("config_v2.yaml")

        for pipeline_name in [
            "mission_control_default",
            "hybrid_default",
            "mission_control_openclaw_triage",
            "mission_control_openclaw_default",
            "github_bridge_smoke",
        ]:
            config.runtime.pipeline = pipeline_name
            planner = PipelinePlanner(config)
            plan = planner.build_plan()
            step_ids = [item.id for item in plan]
            self.assertEqual(len(step_ids), len(set(step_ids)), pipeline_name)

    def test_assignment_uses_enabled_fallback_managed_agent(self) -> None:
        content = textwrap.dedent(
            """
            runtime:
              pipeline: demo
            profiles:
              codex_local:
                agent: codex
                mode: cli
              cursor_local:
                agent: cursor
                mode: cli
            managed_agents:
              codex_builder:
                kind: codex
                profile: codex_local
                enabled: false
              cursor_editor:
                kind: cursor
                profile: cursor_local
            assignments:
              implement_local:
                agent: codex_builder
                fallback:
                  - cursor_editor
            pipelines:
              demo:
                - id: implement
                  title: Implement
                  assignment: implement_local
                  prompt_template: test
            """
        ).strip()

        with tempfile.NamedTemporaryFile("w+", suffix=".yaml", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            config = load_app_config(handle.name)

        planner = PipelinePlanner(config)
        plan = planner.build_plan()

        self.assertEqual(plan[0].managed_agent, "cursor_editor")
        self.assertEqual(plan[0].profile, "cursor_local")
        self.assertTrue(plan[0].fallback_used)
        self.assertEqual(plan[0].fallback_chain, ["cursor_editor"])

    def test_assignment_without_usable_managed_agent_builds_blocked_system_step(self) -> None:
        content = textwrap.dedent(
            """
            runtime:
              pipeline: demo
            profiles:
              codex_local:
                agent: codex
                mode: cli
            managed_agents:
              codex_builder:
                kind: codex
                profile: codex_local
                capabilities: [implement]
                enabled: false
            assignments:
              implement_local:
                agent: codex_builder
                required_capabilities: [implement]
            pipelines:
              demo:
                - id: implement
                  title: Implement
                  assignment: implement_local
                  prompt_template: test
            """
        ).strip()

        with tempfile.NamedTemporaryFile("w+", suffix=".yaml", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            config = load_app_config(handle.name)

        planner = PipelinePlanner(config)
        plan = planner.build_plan()

        self.assertEqual(plan[0].mode, ExecutionMode.SYSTEM)
        self.assertEqual(plan[0].profile, "")
        self.assertIn("could not resolve a usable managed agent", plan[0].planning_blocked_reason)
        self.assertEqual(plan[0].assignment_candidates, ["codex_builder"])
        self.assertEqual(plan[0].assignment_attempts, ["codex_builder: managed agent is disabled."])

    def test_unknown_assignment_builds_blocked_system_step(self) -> None:
        content = textwrap.dedent(
            """
            runtime:
              pipeline: demo
            profiles: {}
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

        planner = PipelinePlanner(config)
        plan = planner.build_plan()

        self.assertEqual(plan[0].mode, ExecutionMode.SYSTEM)
        self.assertIn("Assignment `triage_local` referenced by step `triage` is not defined.", plan[0].planning_blocked_reason)


if __name__ == "__main__":
    unittest.main()
