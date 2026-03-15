from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any

import yaml

from .models import AgentType, ExecutionMode


@dataclass
class RuntimeConfig:
    pipeline: str = "hybrid_default"
    dry_run: bool = True
    artifacts_dir: str = ".openclaw/runs"
    worktrees_dir: str = "/tmp/openclaw-worktrees"
    cleanup_worktrees: bool = True
    retain_failed_worktrees: bool = True


@dataclass
class GitHubConfig:
    repo: str = ""
    base_branch: str = "main"
    default_labels: list[str] = field(default_factory=list)


@dataclass
class ProfileConfig:
    name: str
    agent: AgentType
    mode: ExecutionMode
    command: list[str] = field(default_factory=list)
    action: str = "issue"
    labels: list[str] = field(default_factory=list)
    title_template: str = ""
    body_template: str = ""
    workflow_name: str = ""


@dataclass
class PipelineStepConfig:
    id: str
    title: str
    profile: str
    prompt_template: str
    depends_on: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class AppConfig:
    runtime: RuntimeConfig
    github: GitHubConfig
    profiles: dict[str, ProfileConfig]
    pipelines: dict[str, list[PipelineStepConfig]]


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
    with open(path, "r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
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
            action=raw.get("action", "issue"),
            labels=raw.get("labels", []),
            title_template=raw.get("title_template", ""),
            body_template=raw.get("body_template", ""),
            workflow_name=raw.get("workflow_name", ""),
        )

    pipelines: dict[str, list[PipelineStepConfig]] = {}
    for pipeline_name, raw_steps in data.get("pipelines", {}).items():
        steps: list[PipelineStepConfig] = []
        for raw_step in raw_steps:
            steps.append(
                PipelineStepConfig(
                    id=raw_step["id"],
                    title=raw_step["title"],
                    profile=raw_step["profile"],
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
        pipelines=pipelines,
    )


def resolve_runtime_path(base_path: str, configured_path: str) -> str:
    if os.path.isabs(configured_path):
        return configured_path
    return os.path.join(base_path, configured_path)
