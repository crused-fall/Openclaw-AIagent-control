from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass, field
from typing import Any

try:
    import yaml
except ModuleNotFoundError:
    yaml = None

from .models import AgentType, CheckStatus, ExecutionMode, PreflightCheck


@dataclass
class RuntimeConfig:
    pipeline: str = "mission_control_default"
    dry_run: bool = True
    artifacts_dir: str = ".openclaw/runs"
    worktrees_dir: str = "/tmp/openclaw-worktrees"
    cleanup_worktrees: bool = True
    retain_failed_worktrees: bool = True
    require_step_selection_for_live: bool = True
    allow_fallback_in_live: bool = False
    cli_command_timeout_seconds: float = 0.0
    github_retry_attempts: int = 1
    github_retry_backoff_seconds: float = 1.0
    github_workflow_view_poll_attempts: int = 1
    github_workflow_view_poll_interval_seconds: float = 2.0
    allowed_live_steps: list[str] = field(default_factory=lambda: ["triage", "implement", "review", "publish_branch"])


@dataclass
class GitHubConfig:
    repo: str = ""
    base_branch: str = "main"
    use_origin_remote_fallback: bool = False
    default_labels: list[str] = field(default_factory=list)


@dataclass
class ProfileConfig:
    name: str
    agent: AgentType
    mode: ExecutionMode
    command: list[str] = field(default_factory=list)
    unset_env: list[str] = field(default_factory=list)
    action: str = "issue"
    labels: list[str] = field(default_factory=list)
    title_template: str = ""
    body_template: str = ""
    workflow_name: str = ""
    openclaw_agent_id: str = ""
    openclaw_profile: str = ""
    openclaw_local: bool = True


@dataclass
class ManagedAgentConfig:
    name: str
    kind: AgentType
    profile: str
    capabilities: list[str] = field(default_factory=list)
    manager: str = "openclaw"
    enabled: bool = True
    notes: str = ""


@dataclass
class AssignmentConfig:
    name: str
    agent: str
    manager: str = "openclaw"
    required_capabilities: list[str] = field(default_factory=list)
    fallback: list[str] = field(default_factory=list)


@dataclass
class PipelineStepConfig:
    id: str
    title: str
    prompt_template: str
    profile: str = ""
    assignment: str = ""
    depends_on: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class AppConfig:
    runtime: RuntimeConfig
    github: GitHubConfig
    profiles: dict[str, ProfileConfig]
    managed_agents: dict[str, ManagedAgentConfig]
    assignments: dict[str, AssignmentConfig]
    pipelines: dict[str, list[PipelineStepConfig]]


def diagnose_app_config(config: AppConfig) -> list[PreflightCheck]:
    checks: list[PreflightCheck] = []
    supported_github_actions = {
        "issue",
        "issue_comment",
        "pr",
        "pr_comment",
        "workflow_dispatch",
        "workflow_view",
    }

    if config.runtime.github_retry_attempts < 1:
        checks.append(
            PreflightCheck(
                name="runtime:github_retry_attempts",
                status=CheckStatus.FAILED,
                message="runtime.github_retry_attempts must be at least 1.",
            )
        )
    else:
        checks.append(
            PreflightCheck(
                name="runtime:github_retry_attempts",
                status=CheckStatus.PASSED,
                message=f"runtime.github_retry_attempts is set to {config.runtime.github_retry_attempts}.",
            )
        )

    if config.runtime.cli_command_timeout_seconds < 0:
        checks.append(
            PreflightCheck(
                name="runtime:cli_command_timeout_seconds",
                status=CheckStatus.FAILED,
                message="runtime.cli_command_timeout_seconds cannot be negative.",
            )
        )
    else:
        checks.append(
            PreflightCheck(
                name="runtime:cli_command_timeout_seconds",
                status=CheckStatus.PASSED,
                message=(
                    "runtime.cli_command_timeout_seconds is "
                    f"{config.runtime.cli_command_timeout_seconds}."
                ),
            )
        )

    if config.runtime.github_retry_backoff_seconds < 0:
        checks.append(
            PreflightCheck(
                name="runtime:github_retry_backoff_seconds",
                status=CheckStatus.FAILED,
                message="runtime.github_retry_backoff_seconds cannot be negative.",
            )
        )
    else:
        checks.append(
            PreflightCheck(
                name="runtime:github_retry_backoff_seconds",
                status=CheckStatus.PASSED,
                message=(
                    "runtime.github_retry_backoff_seconds is "
                    f"{config.runtime.github_retry_backoff_seconds}."
                ),
            )
        )

    if config.runtime.github_workflow_view_poll_attempts < 1:
        checks.append(
            PreflightCheck(
                name="runtime:github_workflow_view_poll_attempts",
                status=CheckStatus.FAILED,
                message="runtime.github_workflow_view_poll_attempts must be at least 1.",
            )
        )
    else:
        checks.append(
            PreflightCheck(
                name="runtime:github_workflow_view_poll_attempts",
                status=CheckStatus.PASSED,
                message=(
                    "runtime.github_workflow_view_poll_attempts is set to "
                    f"{config.runtime.github_workflow_view_poll_attempts}."
                ),
            )
        )

    if config.runtime.github_workflow_view_poll_interval_seconds < 0:
        checks.append(
            PreflightCheck(
                name="runtime:github_workflow_view_poll_interval_seconds",
                status=CheckStatus.FAILED,
                message="runtime.github_workflow_view_poll_interval_seconds cannot be negative.",
            )
        )
    else:
        checks.append(
            PreflightCheck(
                name="runtime:github_workflow_view_poll_interval_seconds",
                status=CheckStatus.PASSED,
                message=(
                    "runtime.github_workflow_view_poll_interval_seconds is "
                    f"{config.runtime.github_workflow_view_poll_interval_seconds}."
                ),
            )
        )

    if config.github.use_origin_remote_fallback and config.github.repo.strip():
        checks.append(
            PreflightCheck(
                name="github:repo_resolution",
                status=CheckStatus.WARNING,
                message=(
                    "github.use_origin_remote_fallback is enabled, but github.repo is already configured; "
                    "the configured repo will take precedence."
                ),
            )
        )

    for name, profile in sorted(config.profiles.items()):
        if profile.mode != ExecutionMode.GITHUB:
            continue

        if profile.action not in supported_github_actions:
            checks.append(
                PreflightCheck(
                    name=f"profile:{name}",
                    status=CheckStatus.FAILED,
                    message=(
                        f"GitHub profile `{name}` uses unsupported action `{profile.action}`."
                    ),
                )
            )
            continue

        if profile.action == "workflow_dispatch" and not profile.workflow_name.strip():
            checks.append(
                PreflightCheck(
                    name=f"profile:{name}",
                    status=CheckStatus.FAILED,
                    message=(
                        f"GitHub workflow profile `{name}` requires workflow_name for workflow_dispatch."
                    ),
                )
            )
            continue

        checks.append(
            PreflightCheck(
                name=f"profile:{name}",
                status=CheckStatus.PASSED,
                message=f"GitHub profile `{name}` is internally consistent.",
                details={"action": profile.action},
            )
        )

    for name, managed_agent in sorted(config.managed_agents.items()):
        profile_name = managed_agent.profile.strip()
        if not profile_name:
            checks.append(
                PreflightCheck(
                    name=f"managed_agent:{name}",
                    status=CheckStatus.FAILED,
                    message=f"Managed agent `{name}` has no profile configured.",
                )
            )
            continue
        if profile_name not in config.profiles:
            checks.append(
                PreflightCheck(
                    name=f"managed_agent:{name}",
                    status=CheckStatus.FAILED,
                    message=f"Managed agent `{name}` references unknown profile `{profile_name}`.",
                )
            )
            continue
        profile = config.profiles[profile_name]
        if profile.agent != managed_agent.kind:
            checks.append(
                PreflightCheck(
                    name=f"managed_agent:{name}",
                    status=CheckStatus.FAILED,
                    message=(
                        f"Managed agent `{name}` kind `{managed_agent.kind.value}` does not match "
                        f"profile `{profile_name}` agent `{profile.agent.value}`."
                    ),
                )
            )
            continue
        checks.append(
            PreflightCheck(
                name=f"managed_agent:{name}",
                status=CheckStatus.PASSED,
                message=f"Managed agent `{name}` is internally consistent.",
                details={"profile": profile_name, "kind": managed_agent.kind.value},
            )
        )

    for name, assignment in sorted(config.assignments.items()):
        candidates = [candidate for candidate in [assignment.agent, *assignment.fallback] if candidate]
        missing = [candidate for candidate in candidates if candidate not in config.managed_agents]
        if missing:
            checks.append(
                PreflightCheck(
                    name=f"assignment:{name}",
                    status=CheckStatus.FAILED,
                    message=(
                        f"Assignment `{name}` references unknown managed agents: "
                        f"{', '.join(missing)}."
                    ),
                    details={"candidates": candidates},
                )
            )
            continue

        if assignment.required_capabilities:
            capable = [
                candidate
                for candidate in candidates
                if set(assignment.required_capabilities).issubset(
                    set(config.managed_agents[candidate].capabilities)
                )
            ]
            if not capable:
                checks.append(
                    PreflightCheck(
                        name=f"assignment:{name}",
                        status=CheckStatus.WARNING,
                        message=(
                            f"Assignment `{name}` has no managed agent candidates that satisfy "
                            f"required capabilities: {', '.join(assignment.required_capabilities)}."
                        ),
                        details={"candidates": candidates},
                    )
                )
                continue

        checks.append(
            PreflightCheck(
                name=f"assignment:{name}",
                status=CheckStatus.PASSED,
                message=f"Assignment `{name}` references valid managed agents.",
                details={"candidates": candidates},
            )
        )

    for pipeline_name, steps in sorted(config.pipelines.items()):
        step_ids: set[str] = set()
        duplicate_ids: set[str] = set()
        for step in steps:
            if step.id in step_ids:
                duplicate_ids.add(step.id)
            step_ids.add(step.id)
            if step.assignment and step.assignment not in config.assignments:
                checks.append(
                    PreflightCheck(
                        name=f"pipeline:{pipeline_name}:{step.id}",
                        status=CheckStatus.FAILED,
                        message=(
                            f"Pipeline `{pipeline_name}` step `{step.id}` references unknown "
                            f"assignment `{step.assignment}`."
                        ),
                    )
                )
                continue
            if step.profile and step.profile not in config.profiles:
                checks.append(
                    PreflightCheck(
                        name=f"pipeline:{pipeline_name}:{step.id}",
                        status=CheckStatus.FAILED,
                        message=(
                            f"Pipeline `{pipeline_name}` step `{step.id}` references unknown "
                            f"profile `{step.profile}`."
                        ),
                    )
                )
                continue
            if not step.assignment and not step.profile:
                checks.append(
                    PreflightCheck(
                        name=f"pipeline:{pipeline_name}:{step.id}",
                        status=CheckStatus.FAILED,
                        message=(
                            f"Pipeline `{pipeline_name}` step `{step.id}` has neither assignment nor profile."
                        ),
                    )
                )
                continue
            if step.assignment and step.profile:
                checks.append(
                    PreflightCheck(
                        name=f"pipeline:{pipeline_name}:{step.id}",
                        status=CheckStatus.WARNING,
                        message=(
                            f"Pipeline `{pipeline_name}` step `{step.id}` declares both assignment "
                            f"and profile; assignment will be preferred."
                        ),
                    )
                )
                continue
            checks.append(
                PreflightCheck(
                    name=f"pipeline:{pipeline_name}:{step.id}",
                    status=CheckStatus.PASSED,
                    message=f"Pipeline `{pipeline_name}` step `{step.id}` is well-formed.",
                )
            )

        if duplicate_ids:
            checks.append(
                PreflightCheck(
                    name=f"pipeline:{pipeline_name}:duplicates",
                    status=CheckStatus.FAILED,
                    message=(
                        f"Pipeline `{pipeline_name}` contains duplicate step ids: "
                        f"{', '.join(sorted(duplicate_ids))}."
                    ),
                )
            )

    return checks


def _expand_env(value: Any) -> Any:
    if isinstance(value, str):
        pattern = re.compile(r"\$\{([^}]+)\}|\$([A-Za-z_][A-Za-z0-9_]*)")

        def replace(match: re.Match[str]) -> str:
            env_name = match.group(1) or match.group(2)
            return os.getenv(env_name, "")

        return pattern.sub(replace, value)
    if isinstance(value, list):
        return [_expand_env(item) for item in value]
    if isinstance(value, dict):
        return {key: _expand_env(item) for key, item in value.items()}
    return value


def _load_yaml(path: str) -> dict[str, Any]:
    if yaml is not None:
        with open(path, "r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
        return _expand_env(data)

    command = [
        "ruby",
        "-rjson",
        "-ryaml",
        "-e",
        "path = ARGV.fetch(0); data = YAML.load_file(path) || {}; puts JSON.generate(data)",
        path,
    ]
    try:
        result = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as error:
        raise RuntimeError(
            "PyYAML is not installed and Ruby is unavailable, so config YAML cannot be loaded."
        ) from error
    except subprocess.CalledProcessError as error:
        message = error.stderr.strip() or error.stdout.strip() or "Unknown YAML parsing error."
        raise RuntimeError(f"Failed to parse YAML config {path}: {message}") from error

    data = json.loads(result.stdout or "{}")
    return _expand_env(data)


def load_app_config(path: str) -> AppConfig:
    data = _load_yaml(path)

    runtime = RuntimeConfig(**data.get("runtime", {}))
    github = GitHubConfig(**data.get("github", {}))

    profiles: dict[str, ProfileConfig] = {}
    for name, raw in data.get("profiles", {}).items():
        profiles[name] = ProfileConfig(
            name=name,
            agent=AgentType(raw["agent"]),
            mode=ExecutionMode(raw["mode"]),
            command=raw.get("command", []),
            unset_env=raw.get("unset_env", []),
            action=raw.get("action", "issue"),
            labels=raw.get("labels", []),
            title_template=raw.get("title_template", ""),
            body_template=raw.get("body_template", ""),
            workflow_name=raw.get("workflow_name", ""),
            openclaw_agent_id=raw.get("openclaw_agent_id", ""),
            openclaw_profile=raw.get("openclaw_profile", ""),
            openclaw_local=raw.get("openclaw_local", True),
        )

    managed_agents: dict[str, ManagedAgentConfig] = {}
    for name, raw in data.get("managed_agents", {}).items():
        managed_agents[name] = ManagedAgentConfig(
            name=name,
            kind=AgentType(raw["kind"]),
            profile=raw["profile"],
            capabilities=raw.get("capabilities", []),
            manager=raw.get("manager", "openclaw"),
            enabled=raw.get("enabled", True),
            notes=raw.get("notes", ""),
        )

    assignments: dict[str, AssignmentConfig] = {}
    for name, raw in data.get("assignments", {}).items():
        if isinstance(raw, str):
            agent_name = raw
            manager = "openclaw"
            fallback: list[str] = []
        else:
            agent_name = raw.get("agent", "")
            manager = raw.get("manager", "openclaw")
            required_capabilities = raw.get("required_capabilities", [])
            fallback = raw.get("fallback", [])
        if isinstance(raw, str):
            required_capabilities = []

        override_name = re.sub(r"[^A-Za-z0-9]+", "_", name.upper()).strip("_")
        env_override = os.getenv(f"OPENCLAW_ASSIGN_{override_name}", "").strip()
        if env_override:
            agent_name = env_override

        assignments[name] = AssignmentConfig(
            name=name,
            agent=agent_name,
            manager=manager,
            required_capabilities=required_capabilities,
            fallback=fallback,
        )

    pipelines: dict[str, list[PipelineStepConfig]] = {}
    for pipeline_name, raw_steps in data.get("pipelines", {}).items():
        steps: list[PipelineStepConfig] = []
        for raw_step in raw_steps:
            steps.append(
                PipelineStepConfig(
                    id=raw_step["id"],
                    title=raw_step["title"],
                    profile=raw_step.get("profile", ""),
                    assignment=raw_step.get("assignment", ""),
                    prompt_template=raw_step["prompt_template"],
                    depends_on=raw_step.get("depends_on", []),
                    metadata=raw_step.get("metadata", {}),
                )
            )
        pipelines[pipeline_name] = steps

    return AppConfig(
        runtime=runtime,
        github=github,
        profiles=profiles,
        managed_agents=managed_agents,
        assignments=assignments,
        pipelines=pipelines,
    )


def resolve_runtime_path(base_path: str, configured_path: str) -> str:
    if os.path.isabs(configured_path):
        return configured_path
    return os.path.join(base_path, configured_path)
