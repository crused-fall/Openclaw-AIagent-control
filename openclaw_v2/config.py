from __future__ import annotations

import json
import os
import re
import subprocess
from collections import deque
from copy import deepcopy
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
    allowed_live_steps: list[str] = field(
        default_factory=lambda: ["triage", "implement", "review", "record_summary", "publish_branch"]
    )


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
    hermes_provider: str = ""
    hermes_model: str = ""
    hermes_toolsets: list[str] = field(default_factory=list)
    hermes_skills: list[str] = field(default_factory=list)
    hermes_source: str = "tool"
    hermes_max_turns: int = 0
    hermes_yolo: bool = False


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

        for step in steps:
            missing_dependencies = [dependency for dependency in step.depends_on if dependency not in step_ids]
            if not missing_dependencies:
                continue
            checks.append(
                PreflightCheck(
                    name=f"pipeline:{pipeline_name}:{step.id}:depends_on",
                    status=CheckStatus.FAILED,
                    message=(
                        f"Pipeline `{pipeline_name}` step `{step.id}` references unknown dependencies: "
                        f"{', '.join(missing_dependencies)}."
                    ),
                    details={
                        "step_id": step.id,
                        "dependencies": list(step.depends_on),
                    },
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

        if not duplicate_ids:
            cycle_nodes = _find_pipeline_cycle_nodes(steps)
            if cycle_nodes:
                checks.append(
                    PreflightCheck(
                        name=f"pipeline:{pipeline_name}:cycles",
                        status=CheckStatus.FAILED,
                        message=(
                            f"Pipeline `{pipeline_name}` contains circular dependencies among steps: "
                            f"{', '.join(cycle_nodes)}."
                        ),
                        details={"steps": cycle_nodes},
                    )
                )

    return checks


def _normalize_pipeline_step_spec(raw_step: Any, pipeline_name: str) -> dict[str, Any]:
    if not isinstance(raw_step, dict):
        raise ValueError(f"Pipeline `{pipeline_name}` contains a step that is not a mapping.")

    step_id = str(raw_step.get("id", "")).strip()
    if not step_id:
        raise ValueError(f"Pipeline `{pipeline_name}` contains a step without an id.")

    payload: dict[str, Any] = {"id": step_id}
    for key in ("title", "profile", "assignment", "prompt_template"):
        if key in raw_step and raw_step[key] is not None:
            payload[key] = raw_step[key]

    if "depends_on" in raw_step:
        depends_on = raw_step["depends_on"]
        if depends_on is None:
            payload["depends_on"] = []
        elif isinstance(depends_on, list):
            payload["depends_on"] = [str(item).strip() for item in depends_on if str(item).strip()]
        else:
            raise ValueError(
                f"Pipeline `{pipeline_name}` step `{step_id}` must use a list for depends_on."
            )

    if "metadata" in raw_step:
        metadata = raw_step["metadata"]
        if metadata is None:
            payload["metadata"] = {}
        elif isinstance(metadata, dict):
            payload["metadata"] = dict(metadata)
        else:
            raise ValueError(
                f"Pipeline `{pipeline_name}` step `{step_id}` must use a mapping for metadata."
            )

    if "insert_before" in raw_step and raw_step["insert_before"] is not None:
        payload["insert_before"] = str(raw_step["insert_before"]).strip()
    if "insert_after" in raw_step and raw_step["insert_after"] is not None:
        payload["insert_after"] = str(raw_step["insert_after"]).strip()
    if "remove" in raw_step:
        payload["remove"] = bool(raw_step["remove"])

    return payload


def _find_pipeline_cycle_nodes(steps: list[PipelineStepConfig]) -> list[str]:
    if not steps:
        return []

    step_map = {step.id: step for step in steps}
    indegree = {step.id: 0 for step in steps}
    dependents: dict[str, list[str]] = {step.id: [] for step in steps}

    for step in steps:
        for dependency in step.depends_on:
            if dependency not in step_map:
                return []
            indegree[step.id] += 1
            dependents[dependency].append(step.id)

    queue = deque(step_id for step_id, degree in indegree.items() if degree == 0)
    visited_count = 0

    while queue:
        step_id = queue.popleft()
        visited_count += 1
        for dependent_id in dependents[step_id]:
            indegree[dependent_id] -= 1
            if indegree[dependent_id] == 0:
                queue.append(dependent_id)

    if visited_count == len(steps):
        return []

    return [step_id for step_id, degree in indegree.items() if degree > 0]


def _strip_pipeline_step_controls(step: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in step.items()
        if key not in {"insert_before", "insert_after", "remove"}
    }


def _prune_pipeline_step_dependencies(
    steps: list[dict[str, Any]],
    removed_step_ids: set[str],
) -> list[dict[str, Any]]:
    if not removed_step_ids:
        return steps

    pruned_steps: list[dict[str, Any]] = []
    for step in steps:
        depends_on = [dependency for dependency in step.get("depends_on", []) if dependency not in removed_step_ids]
        if depends_on == list(step.get("depends_on", [])):
            pruned_steps.append(step)
            continue

        updated_step = deepcopy(step)
        updated_step["depends_on"] = depends_on
        pruned_steps.append(updated_step)
    return pruned_steps


def _merge_pipeline_step_payload(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(base)
    for key, value in override.items():
        if key in {"id", "insert_before", "insert_after", "remove"}:
            continue
        if key == "metadata":
            merged_metadata = dict(merged.get("metadata", {}))
            merged_metadata.update(value)
            merged["metadata"] = merged_metadata
            continue
        if key == "depends_on":
            merged["depends_on"] = list(value)
            continue
        merged[key] = value
    return merged


def _find_pipeline_step_index(steps: list[dict[str, Any]], step_id: str) -> int | None:
    for index, step in enumerate(steps):
        if step.get("id") == step_id:
            return index
    return None


def _apply_pipeline_step_spec(
    steps: list[dict[str, Any]],
    raw_step: Any,
    pipeline_name: str,
) -> list[dict[str, Any]]:
    payload = _normalize_pipeline_step_spec(raw_step, pipeline_name)
    step_id = payload["id"]
    remove = bool(payload.get("remove", False))
    insert_before = str(payload.get("insert_before", "")).strip()
    insert_after = str(payload.get("insert_after", "")).strip()

    if remove:
        if insert_before or insert_after:
            raise ValueError(
                f"Pipeline `{pipeline_name}` step `{step_id}` cannot both remove and reposition a step."
            )
        remaining = [step for step in steps if step.get("id") != step_id]
        if len(remaining) == len(steps):
            raise ValueError(
                f"Pipeline `{pipeline_name}` cannot remove step `{step_id}` because it does not exist."
            )
        return remaining

    if insert_before and insert_after:
        raise ValueError(
            f"Pipeline `{pipeline_name}` step `{step_id}` cannot use both insert_before and insert_after."
        )

    existing_index = _find_pipeline_step_index(steps, step_id)
    if existing_index is not None:
        merged = _merge_pipeline_step_payload(steps[existing_index], payload)
        if insert_before or insert_after:
            anchor_id = insert_before or insert_after
            if anchor_id == step_id:
                raise ValueError(
                    f"Pipeline `{pipeline_name}` step `{step_id}` cannot be repositioned relative to itself."
                )
            stepped = [step for index, step in enumerate(steps) if index != existing_index]
            anchor_index = _find_pipeline_step_index(stepped, anchor_id)
            if anchor_index is None:
                raise ValueError(
                    f"Pipeline `{pipeline_name}` step `{step_id}` references unknown insertion anchor `{anchor_id}`."
                )
            insert_index = anchor_index if insert_before else anchor_index + 1
            stepped.insert(insert_index, _strip_pipeline_step_controls(merged))
            return stepped

        steps[existing_index] = _strip_pipeline_step_controls(merged)
        return steps

    if "title" not in payload or "prompt_template" not in payload:
        raise ValueError(
            f"Pipeline `{pipeline_name}` introduces step `{step_id}` without a title or prompt_template."
        )

    new_step = _strip_pipeline_step_controls(payload)
    if insert_before or insert_after:
        anchor_id = insert_before or insert_after
        anchor_index = _find_pipeline_step_index(steps, anchor_id)
        if anchor_index is None:
            raise ValueError(
                f"Pipeline `{pipeline_name}` step `{step_id}` references unknown insertion anchor `{anchor_id}`."
            )
        insert_index = anchor_index if insert_before else anchor_index + 1
        steps = list(steps)
        steps.insert(insert_index, new_step)
        return steps

    steps = list(steps)
    steps.append(new_step)
    return steps


def _resolve_pipeline_payloads(
    pipeline_name: str,
    raw_pipelines: dict[str, Any],
    resolved: dict[str, list[dict[str, Any]]],
    stack: list[str],
) -> list[dict[str, Any]]:
    if pipeline_name in resolved:
        return deepcopy(resolved[pipeline_name])

    if pipeline_name in stack:
        cycle = " -> ".join([*stack, pipeline_name])
        raise ValueError(f"Circular pipeline inheritance detected: {cycle}")

    if pipeline_name not in raw_pipelines:
        raise ValueError(f"Unknown pipeline referenced by extends: {pipeline_name}")

    stack.append(pipeline_name)
    try:
        raw_pipeline = raw_pipelines[pipeline_name]
        if isinstance(raw_pipeline, list):
            steps = [_normalize_pipeline_step_spec(raw_step, pipeline_name) for raw_step in raw_pipeline]
        elif isinstance(raw_pipeline, dict):
            extends_name = str(raw_pipeline.get("extends", "")).strip()
            steps = []
            removed_step_ids: set[str] = set()
            if extends_name:
                steps = _resolve_pipeline_payloads(extends_name, raw_pipelines, resolved, stack)

            remove_steps = raw_pipeline.get("remove_steps", [])
            if remove_steps:
                if not isinstance(remove_steps, list):
                    raise ValueError(
                        f"Pipeline `{pipeline_name}` must use a list for remove_steps."
                    )
                remove_ids = [str(item).strip() for item in remove_steps if str(item).strip()]
                for remove_id in remove_ids:
                    before_count = len(steps)
                    steps = [step for step in steps if step.get("id") != remove_id]
                    if len(steps) == before_count:
                        raise ValueError(
                            f"Pipeline `{pipeline_name}` cannot remove step `{remove_id}` because it does not exist."
                        )
                removed_step_ids.update(remove_ids)

            raw_steps = raw_pipeline.get("steps", [])
            if raw_steps is None:
                raw_steps = []
            if not isinstance(raw_steps, list):
                raise ValueError(f"Pipeline `{pipeline_name}` must use a list for steps.")
            for raw_step in raw_steps:
                steps = _apply_pipeline_step_spec(steps, raw_step, pipeline_name)

            if removed_step_ids:
                final_step_ids = {str(step.get("id", "")).strip() for step in steps}
                prunable_step_ids = {
                    step_id for step_id in removed_step_ids if step_id and step_id not in final_step_ids
                }
                if prunable_step_ids:
                    steps = _prune_pipeline_step_dependencies(steps, prunable_step_ids)
        else:
            raise ValueError(
                f"Pipeline `{pipeline_name}` must be defined as a list or mapping."
            )

        resolved[pipeline_name] = deepcopy(steps)
        return deepcopy(steps)
    finally:
        stack.pop()


def _coerce_pipeline_step_config(raw_step: dict[str, Any]) -> PipelineStepConfig:
    step_id = str(raw_step.get("id", "")).strip()
    title = str(raw_step.get("title") or "")
    prompt_template = str(raw_step.get("prompt_template") or "")
    if not step_id or not title.strip() or not prompt_template.strip():
        raise ValueError(
            f"Pipeline step `{step_id or 'unknown'}` must define a non-empty title and prompt_template."
        )

    return PipelineStepConfig(
        id=step_id,
        title=title,
        profile=str(raw_step.get("profile") or ""),
        assignment=str(raw_step.get("assignment") or ""),
        prompt_template=prompt_template,
        depends_on=[str(item).strip() for item in raw_step.get("depends_on", []) if str(item).strip()],
        metadata=dict(raw_step.get("metadata", {})),
    )


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
        (
            "path = ARGV.fetch(0); "
            "raw = File.read(path); "
            "data = YAML.safe_load(raw, aliases: true) || {}; "
            "puts JSON.generate(data)"
        ),
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
        if "No such file or directory" in message or "Errno::ENOENT" in message:
            raise FileNotFoundError(path) from error
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
            hermes_provider=raw.get("hermes_provider", ""),
            hermes_model=raw.get("hermes_model", ""),
            hermes_toolsets=raw.get("hermes_toolsets", []),
            hermes_skills=raw.get("hermes_skills", []),
            hermes_source=raw.get("hermes_source", "tool"),
            hermes_max_turns=raw.get("hermes_max_turns", 0),
            hermes_yolo=raw.get("hermes_yolo", False),
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

    raw_pipelines = data.get("pipelines", {}) or {}
    if not isinstance(raw_pipelines, dict):
        raise ValueError("Config `pipelines` must be a mapping of pipeline names to definitions.")
    resolved_pipelines: dict[str, list[dict[str, Any]]] = {}
    pipelines: dict[str, list[PipelineStepConfig]] = {}
    for pipeline_name in raw_pipelines:
        resolved_steps = _resolve_pipeline_payloads(
            pipeline_name,
            raw_pipelines,
            resolved_pipelines,
            [],
        )
        pipelines[pipeline_name] = [
            _coerce_pipeline_step_config(raw_step)
            for raw_step in resolved_steps
        ]

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
