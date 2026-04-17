import tempfile
import textwrap
import unittest
from unittest import mock
from types import SimpleNamespace

from openclaw_v2.config import _load_yaml, load_app_config
from openclaw_v2.models import AgentType, ExecutionMode


class ConfigLoaderTests(unittest.TestCase):
    def test_load_yaml_ruby_fallback_uses_safe_load(self) -> None:
        with tempfile.NamedTemporaryFile("w+", suffix=".yaml", encoding="utf-8") as handle:
            handle.write("runtime:\n  pipeline: demo\n")
            handle.flush()
            with mock.patch("openclaw_v2.config.yaml", None):
                with mock.patch(
                    "openclaw_v2.config.subprocess.run",
                    return_value=SimpleNamespace(stdout="{}", stderr="", returncode=0),
                ) as run_mock:
                    _load_yaml(handle.name)

        command = run_mock.call_args.args[0]
        self.assertIn("YAML.safe_load", command[4])
        self.assertNotIn("YAML.load_file", command[4])

    def test_load_yaml_falls_back_without_pyyaml(self) -> None:
        content = textwrap.dedent(
            """
            runtime:
              pipeline: hybrid_default
            github:
              repo: ${OPENCLAW_GITHUB_REPO}
            """
        ).strip()

        with tempfile.NamedTemporaryFile("w+", suffix=".yaml", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            with mock.patch("openclaw_v2.config.yaml", None):
                with mock.patch.dict("os.environ", {"OPENCLAW_GITHUB_REPO": "owner/repo"}, clear=False):
                    data = _load_yaml(handle.name)

        self.assertEqual(data["runtime"]["pipeline"], "hybrid_default")
        self.assertEqual(data["github"]["repo"], "owner/repo")

    def test_load_app_config_reads_openclaw_profile_fields(self) -> None:
        content = textwrap.dedent(
            """
            profiles:
              openclaw_local:
                agent: openclaw
                mode: openclaw
                openclaw_agent_id: repo-agent
                openclaw_profile: repo
                openclaw_local: true
            managed_agents:
              triage_openclaw:
                kind: openclaw
                profile: openclaw_local
                capabilities: [triage]
            assignments:
              triage_local:
                agent: triage_openclaw
                manager: openclaw
                required_capabilities: [triage]
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

        profile = config.profiles["openclaw_local"]
        self.assertEqual(profile.agent, AgentType.OPENCLAW)
        self.assertEqual(profile.mode, ExecutionMode.OPENCLAW)
        self.assertEqual(profile.openclaw_agent_id, "repo-agent")
        self.assertEqual(profile.openclaw_profile, "repo")
        self.assertTrue(profile.openclaw_local)
        self.assertEqual(config.managed_agents["triage_openclaw"].profile, "openclaw_local")
        self.assertEqual(config.managed_agents["triage_openclaw"].kind, AgentType.OPENCLAW)
        self.assertEqual(config.assignments["triage_local"].agent, "triage_openclaw")
        self.assertEqual(config.assignments["triage_local"].manager, "openclaw")
        self.assertEqual(config.assignments["triage_local"].required_capabilities, ["triage"])
        self.assertEqual(config.pipelines["demo"][0].assignment, "triage_local")

    def test_load_app_config_reads_hermes_profile_fields(self) -> None:
        content = textwrap.dedent(
            """
            profiles:
              hermes_local:
                agent: hermes
                mode: hermes
                hermes_provider: copilot
                hermes_model: gpt-5
                hermes_toolsets: [file, terminal]
                hermes_skills: [repo-review]
                hermes_source: tool
                hermes_max_turns: 24
                hermes_yolo: true
            managed_agents:
              hermes_supervisor:
                kind: hermes
                profile: hermes_local
                capabilities: [triage, review]
            assignments:
              triage_local:
                agent: hermes_supervisor
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

        profile = config.profiles["hermes_local"]
        self.assertEqual(profile.agent, AgentType.HERMES)
        self.assertEqual(profile.mode, ExecutionMode.HERMES)
        self.assertEqual(profile.hermes_provider, "copilot")
        self.assertEqual(profile.hermes_model, "gpt-5")
        self.assertEqual(profile.hermes_toolsets, ["file", "terminal"])
        self.assertEqual(profile.hermes_skills, ["repo-review"])
        self.assertEqual(profile.hermes_source, "tool")
        self.assertEqual(profile.hermes_max_turns, 24)
        self.assertTrue(profile.hermes_yolo)
        self.assertEqual(config.managed_agents["hermes_supervisor"].kind, AgentType.HERMES)

    def test_load_app_config_reads_cli_unset_env_fields(self) -> None:
        content = textwrap.dedent(
            """
            profiles:
              claude_local:
                agent: claude
                mode: cli
                unset_env:
                  - ANTHROPIC_BASE_URL
                  - ANTHROPIC_AUTH_TOKEN
                command:
                  - claude
                  - -p
                  - "{prompt}"
            managed_agents:
              claude_router:
                kind: claude
                profile: claude_local
                capabilities: [triage]
            assignments:
              triage_local:
                agent: claude_router
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

        profile = config.profiles["claude_local"]
        self.assertEqual(profile.unset_env, ["ANTHROPIC_BASE_URL", "ANTHROPIC_AUTH_TOKEN"])

    def test_assignment_can_be_overridden_by_environment(self) -> None:
        content = textwrap.dedent(
            """
            profiles:
              claude_local:
                agent: claude
                mode: cli
              gemini_local:
                agent: gemini
                mode: cli
            managed_agents:
              claude_router:
                kind: claude
                profile: claude_local
              gemini_researcher:
                kind: gemini
                profile: gemini_local
            assignments:
              triage_local:
                agent: claude_router
                manager: openclaw
            pipelines: {}
            """
        ).strip()

        with tempfile.NamedTemporaryFile("w+", suffix=".yaml", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            with mock.patch.dict("os.environ", {"OPENCLAW_ASSIGN_TRIAGE_LOCAL": "gemini_researcher"}, clear=False):
                config = load_app_config(handle.name)

        self.assertEqual(config.assignments["triage_local"].agent, "gemini_researcher")


if __name__ == "__main__":
    unittest.main()
