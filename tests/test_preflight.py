import json
import os
import tempfile
import unittest
from typing import Optional
from unittest import mock

from openclaw_v2.config import load_app_config
from openclaw_v2.models import AgentType, ExecutionMode, WorkItem
from openclaw_v2.preflight import CheckStatus, PreflightRunner


class _FakeProcess:
    def __init__(self, returncode: int, stdout: str, stderr: str = "") -> None:
        self.returncode = returncode
        self._stdout = stdout.encode("utf-8")
        self._stderr = stderr.encode("utf-8")

    async def communicate(self):
        return self._stdout, self._stderr


class PreflightOpenClawTests(unittest.IsolatedAsyncioTestCase):
    def test_assignment_check_warns_when_fallback_is_used(self) -> None:
        config = load_app_config("config_v2.yaml")
        runner = PreflightRunner(config)
        plan = [
            WorkItem(
                id="implement",
                title="Implement main changes locally",
                profile="cursor_local",
                agent=AgentType.CURSOR,
                mode=ExecutionMode.CLI,
                prompt_template="",
                assignment="implement_local",
                assignment_source="openclaw",
                managed_agent="cursor_editor",
                assignment_reason="Resolved by assignment implement_local to managed agent cursor_editor. Fallback was used.",
                fallback_used=True,
                fallback_chain=["cursor_editor"],
            )
        ]

        checks = runner._check_managed_assignments(plan)

        self.assertEqual(checks[0].status, CheckStatus.WARNING)
        self.assertIn("fallback managed agent `cursor_editor`", checks[0].message)

    def test_planning_block_check_warns_for_blocked_step(self) -> None:
        config = load_app_config("config_v2.yaml")
        runner = PreflightRunner(config)
        plan = [
            WorkItem(
                id="implement",
                title="Implement main changes locally",
                profile="",
                agent=AgentType.SYSTEM,
                mode=ExecutionMode.SYSTEM,
                prompt_template="",
                assignment="implement_local",
                required_capabilities=["implement"],
                assignment_candidates=["codex_builder", "cursor_editor"],
                assignment_attempts=[
                    "codex_builder: managed agent is disabled.",
                    "cursor_editor: missing capabilities implement.",
                ],
                planning_blocked_reason="Assignment `implement_local` could not resolve a usable managed agent.",
            )
        ]

        checks = runner._check_planning_blocks(plan)

        self.assertEqual(checks[0].status, CheckStatus.WARNING)
        self.assertIn("blocked before execution", checks[0].message)
        self.assertEqual(checks[0].details["assignment_candidates"], ["codex_builder", "cursor_editor"])

    async def test_openclaw_workspace_at_repo_root_warns(self) -> None:
        config = load_app_config("config_v2.yaml")
        config.profiles["openclaw_local"].openclaw_agent_id = "openclaw-control"
        runner = PreflightRunner(config)
        plan = [
            WorkItem(
                id="triage",
                title="Triage user request with local OpenClaw",
                profile="openclaw_local",
                agent=AgentType.OPENCLAW,
                mode=ExecutionMode.OPENCLAW,
                prompt_template="",
            )
        ]
        repo_path = "/tmp/repo"
        agent_list = json.dumps(
            [
                {
                    "id": "openclaw-control",
                    "workspace": repo_path,
                    "agentDir": "/tmp/agent",
                }
            ]
        )

        with mock.patch("openclaw_v2.preflight.shutil.which", return_value="/usr/bin/openclaw"):
            with mock.patch(
                "openclaw_v2.preflight.asyncio.create_subprocess_exec",
                new=mock.AsyncMock(return_value=_FakeProcess(0, agent_list)),
            ):
                checks = await runner._check_openclaw_profiles(repo_path, plan)

        self.assertEqual(checks[0].status, CheckStatus.PASSED)
        self.assertEqual(checks[1].status, CheckStatus.WARNING)
        self.assertIn("repo root", checks[1].message)

    async def test_openclaw_workspace_outside_repo_passes(self) -> None:
        config = load_app_config("config_v2.yaml")
        config.profiles["openclaw_local"].openclaw_agent_id = "openclaw-control-ext"
        runner = PreflightRunner(config)
        plan = [
            WorkItem(
                id="triage",
                title="Triage user request with local OpenClaw",
                profile="openclaw_local",
                agent=AgentType.OPENCLAW,
                mode=ExecutionMode.OPENCLAW,
                prompt_template="",
            )
        ]
        repo_path = "/tmp/repo"
        agent_list = json.dumps(
            [
                {
                    "id": "openclaw-control-ext",
                    "workspace": "/tmp/openclaw-workspace",
                    "agentDir": "/tmp/agent",
                }
            ]
        )

        with mock.patch("openclaw_v2.preflight.shutil.which", return_value="/usr/bin/openclaw"):
            with mock.patch(
                "openclaw_v2.preflight.asyncio.create_subprocess_exec",
                new=mock.AsyncMock(return_value=_FakeProcess(0, agent_list)),
            ):
                checks = await runner._check_openclaw_profiles(repo_path, plan)

        self.assertEqual(checks[0].status, CheckStatus.PASSED)
        self.assertEqual(checks[1].status, CheckStatus.PASSED)
        self.assertIn("isolated from the repository root", checks[1].message)

    async def test_openclaw_missing_agent_id_lists_available_agents(self) -> None:
        config = load_app_config("config_v2.yaml")
        config.profiles["openclaw_local"].openclaw_agent_id = ""
        runner = PreflightRunner(config)
        plan = [
            WorkItem(
                id="triage",
                title="Triage user request with local OpenClaw",
                profile="openclaw_local",
                agent=AgentType.OPENCLAW,
                mode=ExecutionMode.OPENCLAW,
                prompt_template="",
            )
        ]
        agent_list = json.dumps(
            [
                {"id": "main", "workspace": "/tmp/openclaw-main", "agentDir": "/tmp/main"},
                {"id": "openclaw-control-ext", "workspace": "/tmp/openclaw-ext", "agentDir": "/tmp/ext"},
            ]
        )

        with mock.patch("openclaw_v2.preflight.shutil.which", return_value="/usr/bin/openclaw"):
            with mock.patch(
                "openclaw_v2.preflight.asyncio.create_subprocess_exec",
                new=mock.AsyncMock(return_value=_FakeProcess(0, agent_list)),
            ):
                checks = await runner._check_openclaw_profiles("/tmp/repo", plan)

        self.assertEqual(checks[0].status, CheckStatus.WARNING)
        self.assertIn("Available local agents: main, openclaw-control-ext.", checks[0].message)
        self.assertEqual(checks[0].details["available_agent_ids"], ["main", "openclaw-control-ext"])

    async def test_required_commands_include_hermes_for_hermes_steps(self) -> None:
        config = load_app_config("config_v2.yaml")
        runner = PreflightRunner(config)
        plan = [
            WorkItem(
                id="triage",
                title="Triage user request with local Hermes",
                profile="hermes_local",
                agent=AgentType.HERMES,
                mode=ExecutionMode.HERMES,
                prompt_template="",
            )
        ]

        def fake_which(command: str) -> Optional[str]:
            if command in {"git", "hermes"}:
                return f"/usr/bin/{command}"
            return None

        with mock.patch("openclaw_v2.preflight.shutil.which", side_effect=fake_which):
            checks = await runner._check_required_commands(plan)

        names = {check.name: check for check in checks}
        self.assertEqual(names["command:git"].status, CheckStatus.PASSED)
        self.assertEqual(names["command:hermes"].status, CheckStatus.PASSED)

    def test_hermes_provider_preflight_warns_when_no_credentials_exist(self) -> None:
        config = load_app_config("config_v2.yaml")
        runner = PreflightRunner(config)
        plan = [
            WorkItem(
                id="triage",
                title="Triage user request with local Hermes",
                profile="hermes_local",
                agent=AgentType.HERMES,
                mode=ExecutionMode.HERMES,
                prompt_template="",
            )
        ]

        with tempfile.TemporaryDirectory() as home_dir:
            hermes_home = os.path.join(home_dir, ".hermes")
            os.makedirs(hermes_home, exist_ok=True)
            with open(os.path.join(hermes_home, "config.yaml"), "w", encoding="utf-8") as handle:
                handle.write("model:\n  provider: auto\n  base_url: https://openrouter.ai/api/v1\n")

            with mock.patch.dict("os.environ", {"HOME": home_dir}, clear=True):
                with mock.patch("openclaw_v2.preflight.shutil.which", return_value="/usr/bin/hermes"):
                    checks = runner._check_hermes_profiles(plan)

        self.assertEqual(checks[0].status, CheckStatus.WARNING)
        self.assertIn("no ready inference provider", checks[0].message)

    def test_hermes_provider_preflight_passes_with_env_api_key(self) -> None:
        config = load_app_config("config_v2.yaml")
        runner = PreflightRunner(config)
        plan = [
            WorkItem(
                id="triage",
                title="Triage user request with local Hermes",
                profile="hermes_local",
                agent=AgentType.HERMES,
                mode=ExecutionMode.HERMES,
                prompt_template="",
            )
        ]

        with tempfile.TemporaryDirectory() as home_dir:
            hermes_home = os.path.join(home_dir, ".hermes")
            os.makedirs(hermes_home, exist_ok=True)
            with open(os.path.join(hermes_home, "config.yaml"), "w", encoding="utf-8") as handle:
                handle.write("model:\n  provider: auto\n  base_url: https://openrouter.ai/api/v1\n")
            with open(os.path.join(hermes_home, ".env"), "w", encoding="utf-8") as handle:
                handle.write("OPENROUTER_API_KEY=test-key\n")

            with mock.patch.dict("os.environ", {"HOME": home_dir}, clear=True):
                with mock.patch("openclaw_v2.preflight.shutil.which", return_value="/usr/bin/hermes"):
                    checks = runner._check_hermes_profiles(plan)

        self.assertEqual(checks[0].status, CheckStatus.PASSED)
        self.assertIn("usable inference provider path", checks[0].message)

    def test_hermes_provider_preflight_tolerates_env_disappearing_during_read(self) -> None:
        config = load_app_config("config_v2.yaml")
        runner = PreflightRunner(config)
        plan = [
            WorkItem(
                id="triage",
                title="Triage user request with local Hermes",
                profile="hermes_local",
                agent=AgentType.HERMES,
                mode=ExecutionMode.HERMES,
                prompt_template="",
            )
        ]

        with tempfile.TemporaryDirectory() as home_dir:
            hermes_home = os.path.join(home_dir, ".hermes")
            os.makedirs(hermes_home, exist_ok=True)
            with open(os.path.join(hermes_home, "config.yaml"), "w", encoding="utf-8") as handle:
                handle.write("model:\n  provider: auto\n  base_url: https://openrouter.ai/api/v1\n")
            env_path = os.path.join(hermes_home, ".env")
            with open(env_path, "w", encoding="utf-8") as handle:
                handle.write("OPENROUTER_API_KEY=test-key\n")

            real_open = open

            def flaky_open(file, *args, **kwargs):
                if os.fspath(file) == env_path:
                    raise FileNotFoundError("hermes env disappeared during read")
                return real_open(file, *args, **kwargs)

            with mock.patch.dict("os.environ", {"HOME": home_dir}, clear=True):
                with mock.patch("openclaw_v2.preflight.shutil.which", return_value="/usr/bin/hermes"):
                    with mock.patch("builtins.open", side_effect=flaky_open):
                        checks = runner._check_hermes_profiles(plan)

        self.assertEqual(checks[0].status, CheckStatus.WARNING)
        self.assertIn("no ready inference provider", checks[0].message)

    def test_hermes_provider_preflight_tolerates_config_disappearing_during_read(self) -> None:
        config = load_app_config("config_v2.yaml")
        runner = PreflightRunner(config)
        plan = [
            WorkItem(
                id="triage",
                title="Triage user request with local Hermes",
                profile="hermes_local",
                agent=AgentType.HERMES,
                mode=ExecutionMode.HERMES,
                prompt_template="",
            )
        ]

        with tempfile.TemporaryDirectory() as home_dir:
            hermes_home = os.path.join(home_dir, ".hermes")
            os.makedirs(hermes_home, exist_ok=True)
            config_path = os.path.join(hermes_home, "config.yaml")
            with open(config_path, "w", encoding="utf-8") as handle:
                handle.write("model:\n  provider: auto\n  base_url: https://openrouter.ai/api/v1\n")
            with open(os.path.join(hermes_home, ".env"), "w", encoding="utf-8") as handle:
                handle.write("OPENROUTER_API_KEY=test-key\n")

            real_open = open

            def flaky_open(file, *args, **kwargs):
                if os.fspath(file) == config_path:
                    raise FileNotFoundError("hermes config disappeared during read")
                return real_open(file, *args, **kwargs)

            with mock.patch.dict("os.environ", {"HOME": home_dir}, clear=True):
                with mock.patch("openclaw_v2.preflight.shutil.which", return_value="/usr/bin/hermes"):
                    with mock.patch("builtins.open", side_effect=flaky_open):
                        checks = runner._check_hermes_profiles(plan)

        self.assertEqual(checks[0].status, CheckStatus.PASSED)
        self.assertIn("usable inference provider path", checks[0].message)

    def test_hermes_provider_preflight_treats_parse_failures_as_missing_config_when_file_disappears(self) -> None:
        config = load_app_config("config_v2.yaml")
        runner = PreflightRunner(config)
        plan = [
            WorkItem(
                id="triage",
                title="Triage user request with local Hermes",
                profile="hermes_local",
                agent=AgentType.HERMES,
                mode=ExecutionMode.HERMES,
                prompt_template="",
            )
        ]

        with tempfile.TemporaryDirectory() as home_dir:
            hermes_home = os.path.join(home_dir, ".hermes")
            os.makedirs(hermes_home, exist_ok=True)
            config_path = os.path.join(hermes_home, "config.yaml")
            with open(config_path, "w", encoding="utf-8") as handle:
                handle.write("model:\n  provider: auto\n  base_url: https://openrouter.ai/api/v1\n")
            with open(os.path.join(hermes_home, ".env"), "w", encoding="utf-8") as handle:
                handle.write("OPENROUTER_API_KEY=test-key\n")

            real_exists = os.path.exists
            config_exists_calls = 0

            def flaky_exists(path: str) -> bool:
                nonlocal config_exists_calls
                if os.fspath(path) == config_path:
                    config_exists_calls += 1
                    return config_exists_calls == 1
                return real_exists(path)

            with mock.patch.dict("os.environ", {"HOME": home_dir}, clear=True):
                with mock.patch("openclaw_v2.preflight.shutil.which", return_value="/usr/bin/hermes"):
                    with mock.patch("openclaw_v2.preflight.os.path.exists", side_effect=flaky_exists):
                        with mock.patch(
                            "openclaw_v2.preflight._load_yaml",
                            side_effect=RuntimeError("Failed to parse YAML config /tmp/.hermes/config.yaml: No such file or directory"),
                        ):
                            checks = runner._check_hermes_profiles(plan)

        self.assertEqual(checks[0].status, CheckStatus.PASSED)
        self.assertIn("usable inference provider path", checks[0].message)

    def test_hermes_provider_preflight_checks_tool_call_support_for_custom_endpoint(self) -> None:
        config = load_app_config("config_v2.yaml")
        runner = PreflightRunner(config)
        plan = [
            WorkItem(
                id="triage",
                title="Triage user request with local Hermes",
                profile="hermes_local",
                agent=AgentType.HERMES,
                mode=ExecutionMode.HERMES,
                prompt_template="",
            )
        ]

        with tempfile.TemporaryDirectory() as home_dir:
            hermes_home = os.path.join(home_dir, ".hermes")
            os.makedirs(hermes_home, exist_ok=True)
            with open(os.path.join(hermes_home, "config.yaml"), "w", encoding="utf-8") as handle:
                handle.write(
                    "model:\n"
                    "  provider: custom\n"
                    "  default: gpt-5.4\n"
                    "  base_url: http://127.0.0.1:1234/v1\n"
                )
            with open(os.path.join(hermes_home, ".env"), "w", encoding="utf-8") as handle:
                handle.write("OPENAI_API_KEY=test-key\n")

            with mock.patch.dict("os.environ", {"HOME": home_dir}, clear=True):
                with mock.patch("openclaw_v2.preflight.shutil.which", return_value="/usr/bin/hermes"):
                    with mock.patch.object(
                        PreflightRunner,
                        "_probe_custom_openai_tool_calls",
                        return_value=(False, "unexpected EOF"),
                    ):
                        checks = runner._check_hermes_profiles(plan)

        self.assertEqual(checks[0].status, CheckStatus.PASSED)
        self.assertEqual(checks[1].status, CheckStatus.WARNING)
        self.assertIn("failed the direct tool-call probe", checks[1].message)

    def test_hermes_provider_preflight_passes_tool_call_probe(self) -> None:
        config = load_app_config("config_v2.yaml")
        runner = PreflightRunner(config)
        plan = [
            WorkItem(
                id="triage",
                title="Triage user request with local Hermes",
                profile="hermes_local",
                agent=AgentType.HERMES,
                mode=ExecutionMode.HERMES,
                prompt_template="",
            )
        ]

        with tempfile.TemporaryDirectory() as home_dir:
            hermes_home = os.path.join(home_dir, ".hermes")
            os.makedirs(hermes_home, exist_ok=True)
            with open(os.path.join(hermes_home, "config.yaml"), "w", encoding="utf-8") as handle:
                handle.write(
                    "model:\n"
                    "  provider: custom\n"
                    "  default: gpt-5.4\n"
                    "  base_url: http://127.0.0.1:1234/v1\n"
                )
            with open(os.path.join(hermes_home, ".env"), "w", encoding="utf-8") as handle:
                handle.write("OPENAI_API_KEY=test-key\n")

            with mock.patch.dict("os.environ", {"HOME": home_dir}, clear=True):
                with mock.patch("openclaw_v2.preflight.shutil.which", return_value="/usr/bin/hermes"):
                    with mock.patch.object(
                        PreflightRunner,
                        "_probe_custom_openai_tool_calls",
                        return_value=(True, ""),
                    ):
                        checks = runner._check_hermes_profiles(plan)

        self.assertEqual(checks[0].status, CheckStatus.PASSED)
        self.assertEqual(checks[1].status, CheckStatus.PASSED)
        self.assertIn("supports tool calls", checks[1].message)

    async def test_hermes_runtime_probe_passes_when_ready_marker_is_returned(self) -> None:
        config = load_app_config("config_v2.yaml")
        config.runtime.dry_run = False
        runner = PreflightRunner(config)
        plan = [
            WorkItem(
                id="triage",
                title="Triage user request with local Hermes",
                profile="hermes_local",
                agent=AgentType.HERMES,
                mode=ExecutionMode.HERMES,
                prompt_template="",
            )
        ]

        with tempfile.TemporaryDirectory() as repo_path:
            with open(os.path.join(repo_path, "AGENTS.md"), "w", encoding="utf-8") as handle:
                handle.write("# test\n")

            with mock.patch("openclaw_v2.preflight.shutil.which", return_value="/usr/bin/hermes"):
                with mock.patch(
                    "openclaw_v2.preflight.asyncio.create_subprocess_exec",
                    new=mock.AsyncMock(return_value=_FakeProcess(0, "OPENCLAW_STATUS: ready\n")),
                ):
                    checks = await runner._check_hermes_runtime(repo_path, plan)

        self.assertEqual(checks[0].status, CheckStatus.PASSED)
        self.assertIn("runtime probe succeeded", checks[0].message)

    async def test_hermes_runtime_probe_fails_when_tool_run_errors(self) -> None:
        config = load_app_config("config_v2.yaml")
        config.runtime.dry_run = False
        runner = PreflightRunner(config)
        plan = [
            WorkItem(
                id="triage",
                title="Triage user request with local Hermes",
                profile="hermes_local",
                agent=AgentType.HERMES,
                mode=ExecutionMode.HERMES,
                prompt_template="",
            )
        ]

        with tempfile.TemporaryDirectory() as repo_path:
            with open(os.path.join(repo_path, "AGENTS.md"), "w", encoding="utf-8") as handle:
                handle.write("# test\n")

            with mock.patch("openclaw_v2.preflight.shutil.which", return_value="/usr/bin/hermes"):
                with mock.patch(
                    "openclaw_v2.preflight.asyncio.create_subprocess_exec",
                    new=mock.AsyncMock(return_value=_FakeProcess(1, "API call failed after 3 retries: Connection error.\n")),
                ):
                    checks = await runner._check_hermes_runtime(repo_path, plan)

        self.assertEqual(checks[0].status, CheckStatus.FAILED)
        self.assertIn("runtime probe failed", checks[0].message)

    async def test_hermes_runtime_probe_treats_missing_probe_file_as_warning(self) -> None:
        config = load_app_config("config_v2.yaml")
        config.runtime.dry_run = False
        runner = PreflightRunner(config)
        plan = [
            WorkItem(
                id="triage",
                title="Triage user request with local Hermes",
                profile="hermes_local",
                agent=AgentType.HERMES,
                mode=ExecutionMode.HERMES,
                prompt_template="",
            )
        ]

        with tempfile.TemporaryDirectory() as repo_path:
            probe_file = os.path.join(repo_path, "AGENTS.md")
            with open(probe_file, "w", encoding="utf-8") as handle:
                handle.write("# test\n")

            real_exists = os.path.exists
            probe_exists_calls = 0

            def flaky_exists(path: str) -> bool:
                nonlocal probe_exists_calls
                if os.fspath(path) == probe_file:
                    probe_exists_calls += 1
                    return probe_exists_calls == 1
                return real_exists(path)

            with mock.patch("openclaw_v2.preflight.shutil.which", return_value="/usr/bin/hermes"):
                with mock.patch("openclaw_v2.preflight.os.path.exists", side_effect=flaky_exists):
                    with mock.patch(
                        "openclaw_v2.preflight.asyncio.create_subprocess_exec",
                        new=mock.AsyncMock(return_value=_FakeProcess(1, "API call failed after 3 retries: Connection error.\n")),
                    ):
                        checks = await runner._check_hermes_runtime(repo_path, plan)

        self.assertEqual(checks[0].status, CheckStatus.WARNING)
        self.assertIn("probe file disappeared", checks[0].message)

    def test_github_workflow_preflight_fails_when_file_is_missing_in_live_mode(self) -> None:
        config = load_app_config("config_v2.yaml")
        config.runtime.dry_run = False
        runner = PreflightRunner(config)
        plan = [
            WorkItem(
                id="dispatch_review",
                title="Trigger GitHub review workflow",
                profile="github_review_workflow",
                agent=AgentType.COPILOT,
                mode=ExecutionMode.GITHUB,
                prompt_template="",
            )
        ]

        checks = runner._check_github_workflow_files("/tmp/repo", plan)

        self.assertEqual(checks[0].status, CheckStatus.FAILED)
        self.assertIn("was not found", checks[0].message)
        self.assertTrue(checks[0].details["workflow_path"].endswith(os.path.join(".github", "workflows", "openclaw-review.yml")))

    def test_github_workflow_preflight_passes_when_file_exists(self) -> None:
        config = load_app_config("config_v2.yaml")
        runner = PreflightRunner(config)
        plan = [
            WorkItem(
                id="dispatch_review",
                title="Trigger GitHub review workflow",
                profile="github_review_workflow",
                agent=AgentType.COPILOT,
                mode=ExecutionMode.GITHUB,
                prompt_template="",
            )
        ]

        with tempfile.TemporaryDirectory() as repo_path:
            os.makedirs(os.path.join(repo_path, ".github", "workflows"), exist_ok=True)
            workflow_path = os.path.join(repo_path, ".github", "workflows", "openclaw-review.yml")
            with open(workflow_path, "w", encoding="utf-8") as handle:
                handle.write("name: test\n")

            checks = runner._check_github_workflow_files(repo_path, plan)

        self.assertEqual(checks[0].status, CheckStatus.PASSED)
        self.assertIn("exists locally", checks[0].message)
        self.assertTrue(checks[0].details["workflow_path"].endswith("openclaw-review.yml"))

    async def test_dirty_repo_blocks_live_isolated_cli_steps(self) -> None:
        config = load_app_config("config_v2.yaml")
        config.runtime.dry_run = False
        runner = PreflightRunner(config)
        plan = [
            WorkItem(
                id="implement",
                title="Implement main changes locally",
                profile="codex_local",
                agent=AgentType.CODEX,
                mode=ExecutionMode.CLI,
                prompt_template="",
            )
        ]

        with mock.patch(
            "openclaw_v2.preflight.asyncio.create_subprocess_exec",
            new=mock.AsyncMock(return_value=_FakeProcess(0, " M README.md\n?? docs/new.md\n")),
        ):
            check = await runner._check_repo_dirty_for_isolated_cli_steps("/tmp/repo", plan)

        assert check is not None
        self.assertEqual(check.status, CheckStatus.FAILED)
        self.assertIn("commit or stash changes before live runs", check.message)
        self.assertEqual(check.details["affected_steps"], ["implement"])
        self.assertEqual(check.details["changed_paths"], ["README.md", "docs/new.md"])

    async def test_clean_repo_passes_isolated_cli_dirty_check(self) -> None:
        config = load_app_config("config_v2.yaml")
        runner = PreflightRunner(config)
        plan = [
            WorkItem(
                id="implement",
                title="Implement main changes locally",
                profile="codex_local",
                agent=AgentType.CODEX,
                mode=ExecutionMode.CLI,
                prompt_template="",
            )
        ]

        with mock.patch(
            "openclaw_v2.preflight.asyncio.create_subprocess_exec",
            new=mock.AsyncMock(return_value=_FakeProcess(0, "")),
        ):
            check = await runner._check_repo_dirty_for_isolated_cli_steps("/tmp/repo", plan)

        assert check is not None
        self.assertEqual(check.status, CheckStatus.PASSED)
        self.assertIn("working tree is clean", check.message)

    async def test_openclaw_export_step_participates_in_dirty_check(self) -> None:
        config = load_app_config("config_v2.yaml")
        config.runtime.dry_run = False
        runner = PreflightRunner(config)
        plan = [
            WorkItem(
                id="implement",
                title="Implement main changes with OpenClaw",
                profile="openclaw_local",
                agent=AgentType.OPENCLAW,
                mode=ExecutionMode.OPENCLAW,
                prompt_template="",
                metadata={"export_branch": True},
            )
        ]

        with mock.patch(
            "openclaw_v2.preflight.asyncio.create_subprocess_exec",
            new=mock.AsyncMock(return_value=_FakeProcess(0, " M README.md\n")),
        ):
            check = await runner._check_repo_dirty_for_isolated_cli_steps("/tmp/repo", plan)

        assert check is not None
        self.assertEqual(check.status, CheckStatus.FAILED)
        self.assertEqual(check.details["affected_steps"], ["implement"])

    async def test_github_repo_can_resolve_from_origin_when_fallback_is_enabled(self) -> None:
        config = load_app_config("config_v2.yaml")
        config.github.repo = ""
        config.github.use_origin_remote_fallback = True
        runner = PreflightRunner(config)

        with mock.patch(
            "openclaw_v2.github_support.asyncio.create_subprocess_exec",
            new=mock.AsyncMock(return_value=_FakeProcess(0, "git@github.com:owner/repo.git")),
        ):
            check = await runner._check_github_repo_resolution("/tmp/repo")

        self.assertEqual(check.status, CheckStatus.PASSED)
        self.assertEqual(check.details["repo"], "owner/repo")
        self.assertEqual(check.details["source"], "git_origin")

    async def test_remote_base_sync_fails_live_when_branch_is_ahead_of_upstream(self) -> None:
        config = load_app_config("config_v2.yaml")
        config.runtime.dry_run = False
        runner = PreflightRunner(config)

        with mock.patch(
            "openclaw_v2.preflight.asyncio.create_subprocess_exec",
            new=mock.AsyncMock(
                side_effect=[
                    _FakeProcess(0, "main\n"),
                    _FakeProcess(0, "origin/main\n"),
                    _FakeProcess(0, "0\t16\n"),
                ]
            ),
        ):
            check = await runner._check_remote_base_sync("/tmp/repo")

        self.assertEqual(check.status, CheckStatus.FAILED)
        self.assertIn("ahead of `origin/main` by 16 commit(s)", check.message)
        self.assertEqual(check.details["ahead"], 16)
        self.assertEqual(check.details["behind"], 0)

    async def test_remote_base_sync_passes_when_branch_matches_upstream(self) -> None:
        config = load_app_config("config_v2.yaml")
        runner = PreflightRunner(config)

        with mock.patch(
            "openclaw_v2.preflight.asyncio.create_subprocess_exec",
            new=mock.AsyncMock(
                side_effect=[
                    _FakeProcess(0, "main\n"),
                    _FakeProcess(0, "origin/main\n"),
                    _FakeProcess(0, "0\t0\n"),
                ]
            ),
        ):
            check = await runner._check_remote_base_sync("/tmp/repo")

        self.assertEqual(check.status, CheckStatus.PASSED)
        self.assertIn("is in sync with `origin/main`", check.message)


if __name__ == "__main__":
    unittest.main()
