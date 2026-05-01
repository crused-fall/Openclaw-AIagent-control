from __future__ import annotations

import asyncio
import secrets
import json
import os
import re
import shutil
import subprocess
import uuid
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from aiohttp import web

from .config import diagnose_app_config, load_app_config, resolve_runtime_path
from .github_support import normalize_github_repo, resolve_github_repo_from_origin
from .models import TaskStatus
from .orchestrator import HybridOrchestrator

APP_CONFIG_PATH = web.AppKey("config_path", str)
APP_REPO_PATH = web.AppKey("repo_path", str)
APP_STATIC_ROOT = web.AppKey("static_root", str)
APP_TASK_MANAGER = web.AppKey("task_manager", Any)
APP_ALLOW_PATH_OVERRIDE = web.AppKey("allow_path_override", bool)
APP_HOUSEKEEPING_TOKEN = web.AppKey("housekeeping_token", str)
APP_ARTIFACTS_ROOT = web.AppKey("artifacts_root", str)
APP_WORKTREES_ROOT = web.AppKey("worktrees_root", str)

SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; "
        "script-src 'self'; "
        "style-src 'self'; "
        "img-src 'self' data:; "
        "connect-src 'self'; "
        "object-src 'none'; "
        "base-uri 'self'; "
        "form-action 'self'; "
        "frame-ancestors 'none'"
    ),
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Cache-Control": "no-store",
}


def _json_ready(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return _json_ready(asdict(value))
    if isinstance(value, dict):
        return {key: _json_ready(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_ready(item) for item in value]
    return value


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _read_json_body(
    request: web.Request,
    *,
    default: Any | None = None,
    require_object: bool = False,
) -> Any:
    if not request.can_read_body:
        return {} if default is None else default
    try:
        payload = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise web.HTTPBadRequest(text="Invalid JSON body.") from error
    if require_object and not isinstance(payload, dict):
        raise web.HTTPBadRequest(text="JSON body must be an object.")
    return payload


def _read_json_bool_field(payload: dict[str, Any], field_name: str, default: bool) -> bool:
    value = payload.get(field_name, default)
    if isinstance(value, bool):
        return value
    raise web.HTTPBadRequest(text=f"{field_name} must be a boolean.")


def _read_json_int_field(payload: dict[str, Any], field_name: str, default: int) -> int:
    value = payload.get(field_name, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise web.HTTPBadRequest(text=f"{field_name} must be an integer.")
    return value


def _resolve_user_path(raw_path: str, base_path: str | None = None) -> str:
    expanded = os.path.expanduser((raw_path or "").strip())
    if not expanded:
        return os.path.abspath(base_path or os.getcwd())
    if os.path.isabs(expanded):
        return os.path.abspath(expanded)
    if base_path:
        return os.path.abspath(os.path.join(base_path, expanded))
    return os.path.abspath(expanded)


def _canonical_path(path: str) -> Path:
    return Path(path).expanduser().resolve(strict=False)


def _same_path(left: str, right: str) -> bool:
    return _canonical_path(left) == _canonical_path(right)


def _path_within(path: str, root: str) -> bool:
    try:
        _canonical_path(path).relative_to(_canonical_path(root))
    except ValueError:
        return False
    return True


def _resolve_dashboard_scope(
    app: web.Application,
    *,
    raw_repo_path: str,
    raw_config_path: str,
) -> tuple[str, str]:
    default_repo_path = str(app[APP_REPO_PATH])
    default_config_path = str(app[APP_CONFIG_PATH])

    repo_path = _resolve_user_path(raw_repo_path, default_repo_path)
    config_input = raw_config_path or default_config_path
    config_path = _resolve_user_path(config_input, repo_path)

    if bool(app[APP_ALLOW_PATH_OVERRIDE]):
        return str(_canonical_path(repo_path)), str(_canonical_path(config_path))

    if not _same_path(repo_path, default_repo_path):
        raise ValueError("Dashboard repoPath is fixed to the configured repository root.")
    if not (_same_path(config_path, default_config_path) or _path_within(config_path, repo_path)):
        raise ValueError(
            "Dashboard configPath must stay within the repository or match the configured config file."
        )
    return str(_canonical_path(repo_path)), str(_canonical_path(config_path))


def _require_housekeeping_token(request: web.Request) -> None:
    expected = str(request.app[APP_HOUSEKEEPING_TOKEN])
    provided = request.headers.get("X-OpenClaw-Housekeeping-Token", "").strip()
    if not provided or not secrets.compare_digest(provided, expected):
        raise web.HTTPForbidden(text="Housekeeping confirmation token is required.")


def _apply_security_headers(response: web.StreamResponse) -> web.StreamResponse:
    for header, value in SECURITY_HEADERS.items():
        response.headers.setdefault(header, value)
    return response


@web.middleware
async def _security_headers_middleware(
    request: web.Request,
    handler: Any,
) -> web.StreamResponse:
    try:
        response = await handler(request)
    except web.HTTPException as error_response:
        _apply_security_headers(error_response)
        raise
    except Exception as error:
        error_response = web.HTTPInternalServerError(text="Internal server error.")
        _apply_security_headers(error_response)
        raise error_response from error
    return _apply_security_headers(response)


async def _security_headers_on_prepare(request: web.Request, response: web.StreamResponse) -> None:
    _apply_security_headers(response)


def _validate_dashboard_runtime_roots(
    app: web.Application,
    *,
    repo_path: str,
    config: Any,
) -> None:
    artifacts_root = str(_canonical_path(resolve_runtime_path(repo_path, config.runtime.artifacts_dir)))
    worktrees_root = str(_canonical_path(resolve_runtime_path(repo_path, config.runtime.worktrees_dir)))
    if not _same_path(artifacts_root, str(app[APP_ARTIFACTS_ROOT])):
        raise ValueError(
            "Dashboard configPath cannot change the artifacts root; restart the dashboard with that config instead."
        )
    if not _same_path(worktrees_root, str(app[APP_WORKTREES_ROOT])):
        raise ValueError(
            "Dashboard configPath cannot change the worktrees root; restart the dashboard with that config instead."
        )


def _selected_steps(payload: dict[str, Any]) -> list[str] | None:
    raw_steps = payload.get("steps", [])
    if isinstance(raw_steps, str):
        values = [step.strip() for step in raw_steps.split(",") if step.strip()]
        return values or None
    if isinstance(raw_steps, list):
        values: list[str] = []
        for step in raw_steps:
            if not isinstance(step, str):
                raise web.HTTPBadRequest(text="steps must be a comma-separated string or a list of step ids.")
            normalized = step.strip()
            if normalized:
                values.append(normalized)
        return values or None
    if raw_steps in ("", None):
        return None
    raise web.HTTPBadRequest(text="steps must be a comma-separated string or a list of step ids.")


def _default_openclaw_agent_id(config: Any) -> str:
    env_value = os.getenv("OPENCLAW_AGENT_ID", "").strip()
    if env_value:
        return env_value
    for profile in config.profiles.values():
        if profile.mode.value == "openclaw" and profile.openclaw_agent_id.strip():
            return profile.openclaw_agent_id.strip()
    return "openclaw-control-ext"


def _load_preflight_report(artifacts_dir: str) -> dict[str, Any] | None:
    if not artifacts_dir:
        return None
    preflight_path = os.path.join(artifacts_dir, "metadata", "preflight.json")
    if not os.path.exists(preflight_path):
        return None
    with open(preflight_path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _step_status_map(summary: dict[str, Any]) -> dict[str, str]:
    statuses: dict[str, str] = {}
    for item in summary.get("results", []) or []:
        step_id = str(item.get("work_item_id", "")).strip()
        if step_id:
            statuses[step_id] = str(item.get("status", "unknown")).strip() or "unknown"
    return statuses


def _extract_github_repo_from_url(url: str) -> str:
    text = str(url or "").strip()
    if not text:
        return ""
    match = re.search(r"https://github\.com/([^/\s]+)/([^/\s]+)", text)
    if match:
        return f"{match.group(1)}/{match.group(2).removesuffix('.git')}"
    return normalize_github_repo(text)


def _config_profile_for_step(config: Any, step: Any) -> tuple[str, Any | None, str]:
    profile_value = getattr(step, "profile", None)
    if profile_value is None and isinstance(step, dict):
        profile_value = step.get("profile", "")
    profile_name = str(profile_value or "").strip()
    if profile_name:
        return profile_name, config.profiles.get(profile_name), ""

    assignment_value = getattr(step, "assignment", None)
    if assignment_value is None and isinstance(step, dict):
        assignment_value = step.get("assignment", "")
    assignment_name = str(assignment_value or "").strip()
    if not assignment_name:
        return "", None, ""
    assignment = config.assignments.get(assignment_name)
    if assignment is None:
        return "", None, ""
    managed_agent_name = assignment.agent
    managed_agent = config.managed_agents.get(managed_agent_name)
    if managed_agent is None:
        return "", None, managed_agent_name
    profile_name = managed_agent.profile
    return profile_name, config.profiles.get(profile_name), managed_agent_name


def _hermes_role_from_capabilities(capabilities: list[str]) -> str:
    normalized = {str(item).strip() for item in capabilities if str(item).strip()}
    if "record_summary" in normalized:
        return "recorder"
    if {"triage", "review"} & normalized:
        return "supervisor"
    return "support"


def _build_hermes_overview(config: Any) -> dict[str, Any]:
    profiles = []
    for name, profile in sorted(config.profiles.items()):
        if profile.mode.value != "hermes":
            continue
        profiles.append(
            {
                "name": name,
                "provider": profile.hermes_provider,
                "model": profile.hermes_model,
                "toolsets": list(profile.hermes_toolsets),
                "source": profile.hermes_source,
                "maxTurns": profile.hermes_max_turns,
            }
        )

    roles = []
    for name, agent in sorted(config.managed_agents.items()):
        if agent.kind.value != "hermes":
            continue
        roles.append(
            {
                "name": name,
                "profile": agent.profile,
                "role": _hermes_role_from_capabilities(agent.capabilities),
            }
        )

    pipelines = []
    for pipeline_name, steps in sorted(config.pipelines.items()):
        hermes_steps = []
        for step in steps:
            profile_name, profile, managed_agent_name = _config_profile_for_step(config, step)
            if profile is None or profile.mode.value != "hermes":
                continue
            managed_name = managed_agent_name
            if not managed_name:
                assignment_name = str(step.assignment or "").strip()
                if assignment_name and assignment_name in config.assignments:
                    managed_name = config.assignments[assignment_name].agent
            managed_agent = config.managed_agents.get(managed_name) if managed_name else None
            capabilities = list(managed_agent.capabilities) if managed_agent else []
            hermes_steps.append(
                {
                    "id": step.id,
                    "title": step.title,
                    "profile": profile_name,
                    "managedAgent": managed_name,
                    "assignment": step.assignment,
                    "dependsOn": list(step.depends_on),
                    "role": _hermes_role_from_capabilities(capabilities),
                    "capabilities": capabilities,
                }
            )
        if hermes_steps:
            pipelines.append(
                {
                    "name": pipeline_name,
                    "stepCount": len(hermes_steps),
                }
            )

    return {
        "enabled": bool(profiles or roles or pipelines),
        "commandAvailable": shutil.which("hermes") is not None,
        "configPath": "~/.hermes/config.yaml",
        "profiles": profiles,
        "roles": roles,
        "pipelines": pipelines,
    }


async def _build_github_overview(config: Any, repo_path: str) -> dict[str, Any]:
    repo = config.github.repo.strip()
    repo_source = "config" if repo else "unconfigured"
    if not repo and config.github.use_origin_remote_fallback:
        resolved_repo, _, _ = await resolve_github_repo_from_origin(repo_path)
        if resolved_repo:
            repo = resolved_repo
            repo_source = "git_origin"
        else:
            repo_source = "unresolved"
    return {
        "repo": repo,
        "repoSource": repo_source,
        "baseBranch": config.github.base_branch,
        "useOriginRemoteFallback": bool(config.github.use_origin_remote_fallback),
    }


def _summarize_run_insights(
    summary: dict[str, Any],
    context: dict[str, Any],
    preflight: dict[str, Any] | None,
    *,
    default_github_repo: str = "",
    github_base_branch: str = "main",
) -> dict[str, Any]:
    results = summary.get("results", []) or []
    plan = summary.get("plan", []) or []
    plan_titles = {
        str(item.get("id", "")).strip(): str(item.get("title", "")).strip()
        for item in plan
        if isinstance(item, dict)
    }
    status_counts: dict[str, int] = {}
    mode_counts: dict[str, int] = {}
    github_repo = default_github_repo
    github_branch = ""
    github_issue: dict[str, Any] | None = None
    github_pr: dict[str, Any] | None = None
    github_workflow: dict[str, Any] | None = None
    github_cards: list[dict[str, Any]] = []
    hermes_roles: list[dict[str, Any]] = []
    step_ids: list[str] = []

    github_step_map = {
        "publish_branch": ("branch", "Publish branch"),
        "sync_issue": ("issue", "Planning issue"),
        "update_issue": ("issue", "Issue follow-up"),
        "draft_pr": ("pr", "Draft PR"),
        "dispatch_review": ("workflow", "Dispatch review"),
        "collect_review": ("workflow", "Collect review"),
    }

    for item in results:
        if not isinstance(item, dict):
            continue
        work_item_id = str(item.get("work_item_id", "")).strip()
        if work_item_id:
            step_ids.append(work_item_id)
        status = str(item.get("status", "unknown")).strip() or "unknown"
        status_counts[status] = status_counts.get(status, 0) + 1

        mode = str(item.get("mode", "")).strip() or "unknown"
        mode_counts[mode] = mode_counts.get(mode, 0) + 1
        artifacts = item.get("artifacts") if isinstance(item.get("artifacts"), dict) else {}

        github_branch = github_branch or str(
            artifacts.get("source_branch") or artifacts.get("branch_name") or ""
        ).strip()

        for key in ("issue_url", "pr_url", "workflow_run_url"):
            repo_candidate = _extract_github_repo_from_url(str(artifacts.get(key, "")).strip())
            if repo_candidate:
                github_repo = github_repo or repo_candidate

        if work_item_id in github_step_map:
            kind, label = github_step_map[work_item_id]
            card: dict[str, Any] = {
                "kind": kind,
                "stepId": work_item_id,
                "title": plan_titles.get(work_item_id, label),
                "status": status,
            }
            if kind == "branch":
                card["branch"] = github_branch
                if github_repo and github_branch:
                    card["url"] = f"https://github.com/{github_repo}/tree/{github_branch}"
                if github_branch:
                    github_cards.append(card)
            elif kind == "issue":
                issue_url = str(artifacts.get("issue_url", "")).strip()
                issue_number = str(artifacts.get("issue_number", "")).strip()
                if issue_url or issue_number:
                    card["url"] = issue_url
                    card["number"] = issue_number
                    github_cards.append(card)
                    github_issue = {
                        "url": issue_url,
                        "number": issue_number,
                        "status": status,
                        "stepId": work_item_id,
                    }
            elif kind == "pr":
                pr_url = str(artifacts.get("pr_url", "")).strip()
                pr_number = str(artifacts.get("pr_number", "")).strip()
                if pr_url or pr_number:
                    card["url"] = pr_url
                    card["number"] = pr_number
                    github_cards.append(card)
                    github_pr = {
                        "url": pr_url,
                        "number": pr_number,
                        "status": status,
                        "stepId": work_item_id,
                    }
            elif kind == "workflow":
                workflow_url = str(artifacts.get("workflow_run_url", "")).strip()
                workflow_id = str(artifacts.get("workflow_run_id", "")).strip()
                workflow_status = str(artifacts.get("workflow_status", "")).strip()
                workflow_conclusion = str(artifacts.get("workflow_conclusion", "")).strip()
                if workflow_url or workflow_id:
                    card["url"] = workflow_url
                    card["number"] = workflow_id
                    card["workflowStatus"] = workflow_status
                    card["workflowConclusion"] = workflow_conclusion
                    github_cards.append(card)
                    github_workflow = {
                        "url": workflow_url,
                        "id": workflow_id,
                        "status": workflow_status,
                        "conclusion": workflow_conclusion,
                        "stepId": work_item_id,
                    }

        if mode == "hermes" or any(str(key).startswith("hermes_") for key in artifacts):
            hermes_roles.append(
                {
                    "stepId": work_item_id,
                    "title": plan_titles.get(work_item_id, work_item_id),
                    "status": status,
                    "role": "recorder" if "record" in work_item_id else "supervisor",
                    "sessionId": str(artifacts.get("hermes_session_id", "")).strip(),
                    "provider": str(artifacts.get("hermes_provider", "")).strip(),
                    "model": str(artifacts.get("hermes_model", "")).strip(),
                    "toolsets": list(artifacts.get("hermes_toolsets", []) or []),
                    "skills": list(artifacts.get("hermes_skills", []) or []),
                }
            )

    preflight_checks = preflight.get("checks", []) if isinstance(preflight, dict) else []
    github_checks = []
    hermes_checks = []
    for check in preflight_checks:
        if not isinstance(check, dict):
            continue
        name = str(check.get("name", "")).strip()
        item = {
            "name": name,
            "status": str(check.get("status", "")).strip(),
            "message": str(check.get("message", "")).strip(),
        }
        if name.startswith("github_") or name.startswith("github:"):
            github_checks.append(item)
        if name.startswith("hermes_"):
            hermes_checks.append(item)

    return {
        "request": str(context.get("user_request", "")).strip(),
        "dryRun": bool(context.get("dry_run", False)),
        "stepIds": step_ids,
        "statusCounts": status_counts,
        "modeCounts": mode_counts,
        "github": {
            "repo": github_repo,
            "baseBranch": github_base_branch,
            "branch": github_branch,
            "issue": github_issue,
            "pr": github_pr,
            "workflow": github_workflow,
            "cards": github_cards,
            "checks": github_checks,
        },
        "hermes": {
            "used": bool(hermes_roles),
            "sessionCount": len([item for item in hermes_roles if item["sessionId"]]),
            "roles": hermes_roles,
            "checks": hermes_checks,
        },
    }


def _compare_run_histories(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    left_summary = left.get("summary", {}) if isinstance(left.get("summary"), dict) else {}
    right_summary = right.get("summary", {}) if isinstance(right.get("summary"), dict) else {}
    left_status_map = _step_status_map(left_summary)
    right_status_map = _step_status_map(right_summary)
    ordered_steps: list[str] = []
    for source in (
        left_summary.get("plan", []) or [],
        right_summary.get("plan", []) or [],
        left_summary.get("results", []) or [],
        right_summary.get("results", []) or [],
    ):
        for item in source:
            if not isinstance(item, dict):
                continue
            step_id = str(item.get("id") or item.get("work_item_id") or "").strip()
            if step_id and step_id not in ordered_steps:
                ordered_steps.append(step_id)

    left_counts = left.get("insights", {}).get("statusCounts", {})
    right_counts = right.get("insights", {}).get("statusCounts", {})
    count_statuses = sorted(set(left_counts) | set(right_counts))
    count_diffs = [
        {
            "status": status,
            "left": int(left_counts.get(status, 0)),
            "right": int(right_counts.get(status, 0)),
            "delta": int(right_counts.get(status, 0)) - int(left_counts.get(status, 0)),
        }
        for status in count_statuses
    ]
    step_diffs = [
        {
            "stepId": step_id,
            "left": left_status_map.get(step_id, "missing"),
            "right": right_status_map.get(step_id, "missing"),
        }
        for step_id in ordered_steps
        if left_status_map.get(step_id, "missing") != right_status_map.get(step_id, "missing")
    ]
    left_github = left.get("insights", {}).get("github", {})
    right_github = right.get("insights", {}).get("github", {})
    left_hermes = left.get("insights", {}).get("hermes", {})
    right_hermes = right.get("insights", {}).get("hermes", {})
    return {
        "countDiffs": count_diffs,
        "stepDiffs": step_diffs,
        "branchChanged": left_github.get("branch", "") != right_github.get("branch", ""),
        "workflowChanged": (
            (left_github.get("workflow") or {}).get("id", "")
            != (right_github.get("workflow") or {}).get("id", "")
        ),
        "hermesSessionDelta": int(right_hermes.get("sessionCount", 0)) - int(
            left_hermes.get("sessionCount", 0)
        ),
    }


def _summarize_recent_runs(
    artifacts_root: str,
    *,
    default_github_repo: str = "",
    github_base_branch: str = "main",
    limit: int = 8,
) -> list[dict[str, Any]]:
    runs: list[dict[str, Any]] = []
    root = Path(artifacts_root)
    if not root.exists():
        return runs

    candidates = sorted(
        [path for path in root.iterdir() if path.is_dir() and path.name.startswith("run-")],
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )

    for run_dir in candidates[:limit]:
        summary_path = run_dir / "summary.json"
        context_path = run_dir / "context.json"
        if not summary_path.exists():
            continue
        try:
            with summary_path.open("r", encoding="utf-8") as handle:
                summary = json.load(handle)
        except json.JSONDecodeError:
            continue

        context: dict[str, Any] = {}
        if context_path.exists():
            try:
                with context_path.open("r", encoding="utf-8") as handle:
                    context = json.load(handle)
            except json.JSONDecodeError:
                context = {}
        preflight = _load_preflight_report(str(run_dir))

        results = summary.get("results", [])
        status_counts: dict[str, int] = {}
        for item in results:
            status = str(item.get("status", "unknown"))
            status_counts[status] = status_counts.get(status, 0) + 1

        runs.append(
            {
                "runId": summary.get("run_id", run_dir.name),
                "success": bool(summary.get("success", False)),
                "artifactsDir": str(run_dir),
                "request": context.get("user_request", ""),
                "repoPath": context.get("repo_path", ""),
                "stepCount": len(summary.get("plan", [])),
                "resultCount": len(results),
                "statusCounts": status_counts,
                "updatedAt": datetime.fromtimestamp(run_dir.stat().st_mtime, timezone.utc).isoformat(),
                "insights": _summarize_run_insights(
                    summary,
                    context,
                    preflight,
                    default_github_repo=default_github_repo,
                    github_base_branch=github_base_branch,
                ),
            }
        )
    return runs


def _safe_run_path(run_dir: Path, relative_path: str) -> Path:
    if not relative_path:
        raise ValueError("Artifact path is required.")
    candidate = (run_dir / relative_path).resolve()
    run_root = run_dir.resolve()
    if run_root not in candidate.parents and candidate != run_root:
        raise ValueError("Artifact path escapes run directory.")
    if not candidate.exists() or not candidate.is_file():
        raise FileNotFoundError(f"Artifact file not found: {relative_path}")
    return candidate


def _list_run_files(run_dir: Path, limit: int = 200) -> list[dict[str, Any]]:
    if not run_dir.exists():
        return []
    files: list[dict[str, Any]] = []
    for path in sorted([item for item in run_dir.rglob("*") if item.is_file()])[:limit]:
        relative = path.relative_to(run_dir).as_posix()
        suffix = path.suffix.lower().lstrip(".")
        files.append(
            {
                "path": relative,
                "size": path.stat().st_size,
                "kind": suffix or "file",
            }
        )
    return files


def _load_run_workspace_manifests(run_dir: Path) -> list[dict[str, Any]]:
    workspaces_dir = run_dir / "workspaces"
    manifests: list[dict[str, Any]] = []
    if not workspaces_dir.exists():
        return manifests
    for path in sorted(workspaces_dir.glob("*.json")):
        try:
            with path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            manifests.append(payload)
    return manifests


def _read_artifact_file(run_dir: Path, relative_path: str, limit: int = 200_000) -> dict[str, Any]:
    target = _safe_run_path(run_dir, relative_path)
    raw = target.read_bytes()
    truncated = False
    if len(raw) > limit:
        raw = raw[:limit]
        truncated = True
    try:
        content = raw.decode("utf-8")
        encoding = "utf-8"
    except UnicodeDecodeError:
        content = raw.decode("utf-8", errors="replace")
        encoding = "utf-8-replaced"
    return {
        "path": relative_path,
        "content": content,
        "truncated": truncated,
        "size": target.stat().st_size,
        "encoding": encoding,
    }


def _run_cleanup_command(command: list[str]) -> dict[str, Any]:
    result = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
    )
    return {
        "command": command,
        "ok": result.returncode == 0,
        "exitCode": result.returncode,
        "stdout": result.stdout.strip(),
        "stderr": result.stderr.strip(),
    }


def _cleanup_skip(operation_type: str, reason: str, **details: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "type": operation_type,
        "ok": False,
        "skipped": True,
        "reason": reason,
        "exitCode": None,
        "stdout": "",
        "stderr": "",
    }
    payload.update(details)
    return payload


def _managed_cleanup_branch(branch_name: str) -> bool:
    return bool(re.fullmatch(r"openclaw-[a-z0-9_-]+", branch_name))


def _cleanup_run_resources(
    run_dir: Path,
    *,
    allowed_repo_root: str,
    allowed_worktrees_root: str,
    remove_worktrees: bool,
    remove_artifacts: bool,
) -> dict[str, Any]:
    operations: list[dict[str, Any]] = []
    manifests = _load_run_workspace_manifests(run_dir)
    repo_root = str(_canonical_path(allowed_repo_root))
    worktrees_root = str(_canonical_path(allowed_worktrees_root))

    if remove_worktrees:
        for manifest in manifests:
            metadata = manifest.get("metadata") if isinstance(manifest.get("metadata"), dict) else {}
            strategy = str(metadata.get("workspace_strategy", "")).strip()
            if strategy != "git-worktree":
                continue

            workspace_path = str(manifest.get("workspace_path", "")).strip()
            branch_name = str(manifest.get("branch_name", "")).strip()
            manifest_repo_root = str(metadata.get("workspace_repo_root", "")).strip()
            if not manifest_repo_root:
                operations.append(
                    _cleanup_skip(
                        "worktree_remove",
                        "Workspace manifest is missing workspace_repo_root.",
                        workspacePath=workspace_path,
                    )
                )
                if branch_name:
                    operations.append(
                        _cleanup_skip(
                            "branch_delete",
                            "Workspace manifest is missing workspace_repo_root.",
                            branchName=branch_name,
                        )
                    )
                continue

            if not _same_path(manifest_repo_root, repo_root):
                operations.append(
                    _cleanup_skip(
                        "worktree_remove",
                        "Workspace manifest points outside the configured repository.",
                        workspacePath=workspace_path,
                        repoRoot=manifest_repo_root,
                    )
                )
                if branch_name:
                    operations.append(
                        _cleanup_skip(
                            "branch_delete",
                            "Workspace manifest points outside the configured repository.",
                            branchName=branch_name,
                            repoRoot=manifest_repo_root,
                        )
                    )
                continue

            if workspace_path:
                if not _path_within(workspace_path, worktrees_root):
                    operations.append(
                        _cleanup_skip(
                            "worktree_remove",
                            "Workspace path is outside the configured worktrees root.",
                            workspacePath=workspace_path,
                            worktreesRoot=worktrees_root,
                        )
                    )
                elif os.path.exists(workspace_path):
                    operations.append(
                        {
                            "type": "worktree_remove",
                            "workspacePath": str(_canonical_path(workspace_path)),
                            **_run_cleanup_command(
                                [
                                    "git",
                                    "-C",
                                    repo_root,
                                    "worktree",
                                    "remove",
                                    "--force",
                                    str(_canonical_path(workspace_path)),
                                ]
                            ),
                        }
                    )
                else:
                    operations.append(
                        _cleanup_skip(
                            "worktree_remove",
                            "Workspace path is already absent.",
                            workspacePath=workspace_path,
                        )
                    )

            if branch_name and _managed_cleanup_branch(branch_name):
                operations.append(
                    {
                        "type": "branch_delete",
                        "branchName": branch_name,
                        **_run_cleanup_command(["git", "-C", repo_root, "branch", "-D", branch_name]),
                    }
                )
            elif branch_name:
                operations.append(
                    _cleanup_skip(
                        "branch_delete",
                        "Branch name is outside the managed cleanup scope.",
                        branchName=branch_name,
                    )
                )

    if remove_artifacts and run_dir.exists():
        shutil.rmtree(run_dir, ignore_errors=False)
        operations.append(
            {
                "type": "artifacts_delete",
                "path": str(run_dir),
                "ok": True,
                "exitCode": 0,
                "stdout": "",
                "stderr": "",
            }
        )

    return {
        "runId": run_dir.name,
        "removedArtifacts": remove_artifacts,
        "attemptedWorktreeCleanup": remove_worktrees,
        "operations": operations,
    }


def _command_snapshot(
    command: list[str],
    *,
    timeout_seconds: float = 20.0,
) -> dict[str, Any]:
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except FileNotFoundError as error:
        return {
            "ok": False,
            "command": command,
            "exitCode": None,
            "stdout": "",
            "stderr": str(error),
        }
    except subprocess.TimeoutExpired as error:
        return {
            "ok": False,
            "command": command,
            "exitCode": None,
            "stdout": error.stdout or "",
            "stderr": error.stderr or f"Timed out after {timeout_seconds} seconds.",
        }
    return {
        "ok": result.returncode == 0,
        "command": command,
        "exitCode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


def _public_command_snapshot(capture: dict[str, Any]) -> dict[str, Any]:
    return {
        "ok": bool(capture.get("ok", False)),
        "exitCode": capture.get("exitCode"),
        "stdout": str(capture.get("stdout", "")),
        "stderr": str(capture.get("stderr", "")),
    }


def _openclaw_health_snapshot(agent_id: str) -> dict[str, Any]:
    health_capture = _command_snapshot(["openclaw", "health", "--json"], timeout_seconds=30.0)
    gateway_capture = _command_snapshot(["openclaw", "gateway", "status"], timeout_seconds=15.0)
    memory_capture = _command_snapshot(
        ["openclaw", "memory", "status", "--deep", "--agent", agent_id],
        timeout_seconds=30.0,
    )

    health_payload: dict[str, Any] = {}
    if health_capture["stdout"]:
        try:
            health_payload = json.loads(health_capture["stdout"])
        except json.JSONDecodeError:
            health_payload = {}

    channels: list[dict[str, Any]] = []
    for channel_name in health_payload.get("channelOrder", []):
        channel_data = (health_payload.get("channels") or {}).get(channel_name, {})
        probe = channel_data.get("probe") or {}
        channels.append(
            {
                "name": channel_name,
                "label": (health_payload.get("channelLabels") or {}).get(channel_name, channel_name),
                "configured": bool(channel_data.get("configured")),
                "running": bool(channel_data.get("running")),
                "probeOk": bool(probe.get("ok")),
                "lastError": channel_data.get("lastError"),
            }
        )

    agent_ids = [str(item.get("agentId", "")) for item in health_payload.get("agents", [])]
    return {
        "checkedAt": _utc_now(),
        "agentId": agent_id,
        "healthOk": bool(health_payload.get("ok")),
        "defaultAgentId": health_payload.get("defaultAgentId", ""),
        "targetAgentPresent": agent_id in agent_ids,
        "channels": channels,
        "gateway": _public_command_snapshot(gateway_capture),
        "memory": _public_command_snapshot(memory_capture),
    }


def _git_status_snapshot(repo_path: str) -> dict[str, Any]:
    try:
        result = subprocess.run(
            ["git", "-C", repo_path, "status", "--short", "--branch"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError) as error:
        return {
            "ok": False,
            "summary": str(error),
            "branch": "",
            "dirty": False,
            "changedFiles": [],
        }

    lines = [line.rstrip() for line in result.stdout.splitlines() if line.rstrip()]
    branch = ""
    changed_files: list[str] = []
    if lines and lines[0].startswith("## "):
        branch = lines[0][3:]
        lines = lines[1:]
    for line in lines:
        if len(line) > 3:
            changed_files.append(line[3:])
    return {
        "ok": True,
        "summary": branch or "git status available",
        "branch": branch,
        "dirty": bool(changed_files),
        "changedFiles": changed_files,
    }


def _serialize_plan_for_ui(plan: list[Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for step in plan:
        items.append(
            {
                "id": step.id,
                "title": step.title,
                "mode": step.mode.value,
                "agent": step.agent.value,
                "profile": step.profile,
                "assignment": step.assignment,
                "managedAgent": step.managed_agent,
                "dependsOn": step.depends_on,
                "fallbackUsed": step.fallback_used,
                "fallbackChain": step.fallback_chain,
                "assignmentReason": step.assignment_reason,
                "planningBlockedReason": step.planning_blocked_reason,
                "requiredCapabilities": step.required_capabilities,
            }
        )
    return items


def _serialize_runtime_snapshot(runtime: Any) -> dict[str, Any]:
    return {
        "dry_run": bool(runtime.dry_run),
        "require_step_selection_for_live": bool(runtime.require_step_selection_for_live),
        "allow_fallback_in_live": bool(runtime.allow_fallback_in_live),
        "allowed_live_steps": list(runtime.allowed_live_steps),
    }


def _serialize_config_snapshot(config: Any, plan: list[Any]) -> dict[str, Any]:
    return {
        "runtime": _serialize_runtime_snapshot(config.runtime),
        "defaultPipeline": config.runtime.pipeline,
        "pipelines": {
            name: [
                {
                    "id": step.id,
                    "title": step.title,
                    "dependsOn": step.depends_on,
                    "assignment": step.assignment,
                    "profile": step.profile,
                    "metadata": step.metadata,
                }
                for step in steps
            ]
            for name, steps in config.pipelines.items()
        },
        "currentPlan": _serialize_plan_for_ui(plan),
    }


def _validate_live_policy(
    orchestrator: HybridOrchestrator,
    selected_steps: list[str] | None,
    require_step_selection: bool,
    allow_fallback_in_live: bool,
    allowed_live_steps: list[str],
) -> None:
    if require_step_selection and not selected_steps:
        raise ValueError(
            "Live mode requires explicit steps. Select one or more steps before launching."
        )

    effective_plan = orchestrator.build_plan(selected_steps=selected_steps)
    allowed_set = set(allowed_live_steps)
    disallowed = [item.id for item in effective_plan if item.id not in allowed_set]
    if disallowed:
        raise ValueError(
            "Live mode blocked by allowed_live_steps policy. "
            f"Disallowed steps: {', '.join(disallowed)}."
        )

    if not allow_fallback_in_live:
        fallback_items = [item for item in effective_plan if item.fallback_used]
        if fallback_items:
            details = ", ".join(
                f"{item.id} -> {item.managed_agent or 'unknown'}"
                for item in fallback_items
            )
            raise ValueError(
                "Live mode blocked because fallback managed agents were selected. "
                f"Steps: {details}."
            )


@dataclass
class DashboardTask:
    id: str
    action: str
    payload: dict[str, Any]
    created_at: str
    status: str = "queued"
    progress: list[dict[str, str]] = field(default_factory=list)
    result: dict[str, Any] | None = None
    error: str = ""
    runner: asyncio.Task[None] | None = None
    subscribers: list[asyncio.Queue[dict[str, Any]]] = field(default_factory=list)

    def add_progress(self, message: str) -> None:
        self.progress.append({"at": _utc_now(), "message": message})
        if len(self.progress) > 400:
            self.progress = self.progress[-400:]
        self.publish()

    def to_payload(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "action": self.action,
            "status": self.status,
            "createdAt": self.created_at,
            "progress": self.progress,
            "error": self.error,
            "payload": self.payload,
            "result": self.result if self.status in {"completed", "failed"} else None,
        }

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self.subscribers.append(queue)
        queue.put_nowait(self.to_payload())
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        if queue in self.subscribers:
            self.subscribers.remove(queue)

    def publish(self) -> None:
        payload = self.to_payload()
        stale: list[asyncio.Queue[dict[str, Any]]] = []
        for queue in self.subscribers:
            try:
                queue.put_nowait(payload)
            except asyncio.QueueFull:
                stale.append(queue)
        for queue in stale:
            self.unsubscribe(queue)


class DashboardTaskManager:
    def __init__(self, app: web.Application) -> None:
        self.app = app
        self.tasks: dict[str, DashboardTask] = {}
        self._run_lock = asyncio.Lock()

    def submit(self, action: str, payload: dict[str, Any]) -> DashboardTask:
        task = DashboardTask(
            id=uuid.uuid4().hex[:12],
            action=action,
            payload=payload,
            created_at=_utc_now(),
        )
        task.add_progress("Queued.")
        task.runner = asyncio.create_task(self._execute(task))
        self.tasks[task.id] = task
        if len(self.tasks) > 30:
            stale = sorted(self.tasks.values(), key=lambda item: item.created_at)[:-30]
            for item in stale:
                if item.runner and not item.runner.done():
                    continue
                self.tasks.pop(item.id, None)
        return task

    async def _execute(self, task: DashboardTask) -> None:
        try:
            if task.action == "run":
                task.add_progress("Waiting for execution slot.")
                async with self._run_lock:
                    task.status = "running"
                    task.publish()
                    task.result = await _execute_dashboard_action(self.app, task)
            else:
                task.status = "running"
                task.publish()
                task.result = await _execute_dashboard_action(self.app, task)
            task.status = "completed"
            task.add_progress("Completed.")
            task.publish()
        except asyncio.CancelledError:
            task.status = "cancelled"
            task.error = "Cancelled by user."
            task.add_progress("Cancelled.")
            task.publish()
        except Exception as error:
            task.status = "failed"
            task.error = str(error)
            task.add_progress(f"Failed: {error}")
            task.publish()

    def cancel(self, task_id: str) -> DashboardTask:
        task = self.tasks.get(task_id)
        if task is None:
            raise KeyError(task_id)
        if task.status in {"completed", "failed", "cancelled"}:
            return task
        task.add_progress("Cancellation requested.")
        if task.runner is not None and not task.runner.done():
            task.runner.cancel()
        return task

    async def shutdown(self) -> None:
        pending = [
            item.runner
            for item in self.tasks.values()
            if item.runner is not None and not item.runner.done()
        ]
        for runner in pending:
            runner.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)


def _resolve_request_payload(
    app: web.Application,
    payload: dict[str, Any],
) -> tuple[str, str, Any]:
    repo_path, config_path = _resolve_dashboard_scope(
        app,
        raw_repo_path=str(payload.get("repoPath", "")).strip(),
        raw_config_path=str(payload.get("configPath", "")).strip(),
    )
    config = load_app_config(config_path)
    _validate_dashboard_runtime_roots(app, repo_path=repo_path, config=config)
    pipeline = str(payload.get("pipeline", "")).strip()
    if pipeline:
        config.runtime.pipeline = pipeline
    return repo_path, config_path, config


def _validate_task_submission(action: str, payload: dict[str, Any], config: Any) -> None:
    if action == "doctor":
        return

    selected_steps = _selected_steps(payload)

    if action == "run":
        user_request = str(payload.get("request", "")).strip()
        if not user_request:
            raise web.HTTPBadRequest(text="Request text is required before running the pipeline.")
        live = _read_json_bool_field(payload, "live", False)
        config.runtime.dry_run = not live
    else:
        live = False

    orchestrator = HybridOrchestrator(config)
    if action == "run" and live:
        _validate_live_policy(
            orchestrator,
            selected_steps=selected_steps,
            require_step_selection=config.runtime.require_step_selection_for_live,
            allow_fallback_in_live=config.runtime.allow_fallback_in_live,
            allowed_live_steps=config.runtime.allowed_live_steps,
        )
    else:
        orchestrator.build_plan(selected_steps=selected_steps)


async def _execute_dashboard_action(
    app: web.Application,
    task: DashboardTask,
) -> dict[str, Any]:
    payload = task.payload
    repo_path, config_path, config = _resolve_request_payload(app, payload)
    selected_steps = _selected_steps(payload)

    if task.action == "doctor":
        task.add_progress("Running config diagnostics.")
        report = diagnose_app_config(config)
        return {
            "mode": "doctor",
            "configPath": config_path,
            "checks": _json_ready(report),
        }

    orchestrator = HybridOrchestrator(config)

    if task.action in {"diagnose", "preflight"}:
        task.add_progress("Running preflight.")
        plan, report = await orchestrator.preflight(repo_path, selected_steps=selected_steps)
        return {
            "mode": task.action,
            "repoPath": repo_path,
            "configPath": config_path,
            "pipeline": config.runtime.pipeline,
            "selectedSteps": selected_steps or [],
            "plan": _serialize_plan_for_ui(plan),
            "preflight": _json_ready(report),
        }

    if task.action != "run":
        raise ValueError(f"Unsupported dashboard action: {task.action}")

    user_request = str(payload.get("request", "")).strip()
    if not user_request:
        raise ValueError("Request text is required before running the pipeline.")

    live = _read_json_bool_field(payload, "live", False)
    config.runtime.dry_run = not live
    orchestrator = HybridOrchestrator(config)
    if live:
        _validate_live_policy(
            orchestrator,
            selected_steps=selected_steps,
            require_step_selection=config.runtime.require_step_selection_for_live,
            allow_fallback_in_live=config.runtime.allow_fallback_in_live,
            allowed_live_steps=config.runtime.allowed_live_steps,
        )

    task.add_progress(
        f"Launching {config.runtime.pipeline} in {'live' if live else 'dry-run'} mode."
    )
    result = await orchestrator.run(
        user_request,
        repo_path,
        selected_steps=selected_steps,
        progress_callback=task.add_progress,
    )
    history = _read_run_history(repo_path, config_path, result.run_id)
    return {
        "mode": "run",
        "repoPath": repo_path,
        "configPath": config_path,
        "pipeline": config.runtime.pipeline,
        "selectedSteps": selected_steps or [],
        "live": live,
        "runResult": _json_ready(result),
        "preflight": _load_preflight_report(result.artifacts_dir),
        "history": history,
    }


def _read_run_history(
    repo_path: str,
    config_path: str,
    run_id: str,
) -> dict[str, Any]:
    if not re.fullmatch(r"[A-Za-z0-9._-]+", run_id):
        raise ValueError("Invalid run id.")

    config = load_app_config(config_path)
    artifacts_root = resolve_runtime_path(repo_path, config.runtime.artifacts_dir)
    run_dir = Path(artifacts_root) / run_id
    summary_path = run_dir / "summary.json"
    if not summary_path.exists():
        raise FileNotFoundError(f"Run summary not found for {run_id}.")

    with summary_path.open("r", encoding="utf-8") as handle:
        summary = json.load(handle)

    context_path = run_dir / "context.json"
    context = {}
    if context_path.exists():
        with context_path.open("r", encoding="utf-8") as handle:
            context = json.load(handle)

    preflight = _load_preflight_report(str(run_dir))
    updated_at = datetime.fromtimestamp(run_dir.stat().st_mtime, timezone.utc).isoformat()
    return {
        "runId": run_id,
        "updatedAt": updated_at,
        "artifactsDir": str(run_dir),
        "context": context,
        "summary": summary,
        "preflight": preflight,
        "insights": _summarize_run_insights(
            summary,
            context,
            preflight,
            default_github_repo=config.github.repo.strip(),
            github_base_branch=config.github.base_branch,
        ),
        "files": _list_run_files(run_dir),
    }


def _cleanup_run_history(
    repo_path: str,
    config_path: str,
    run_id: str,
    *,
    remove_worktrees: bool,
    remove_artifacts: bool,
) -> dict[str, Any]:
    if not re.fullmatch(r"[A-Za-z0-9._-]+", run_id):
        raise ValueError("Invalid run id.")
    config = load_app_config(config_path)
    artifacts_root = resolve_runtime_path(repo_path, config.runtime.artifacts_dir)
    worktrees_root = resolve_runtime_path(repo_path, config.runtime.worktrees_dir)
    run_dir = Path(artifacts_root) / run_id
    if not run_dir.exists():
        raise FileNotFoundError(f"Run directory not found for {run_id}.")
    return _cleanup_run_resources(
        run_dir,
        allowed_repo_root=repo_path,
        allowed_worktrees_root=worktrees_root,
        remove_worktrees=remove_worktrees,
        remove_artifacts=remove_artifacts,
    )


def _prune_run_history(
    repo_path: str,
    config_path: str,
    *,
    keep_latest: int,
    remove_worktrees: bool,
    remove_artifacts: bool,
) -> dict[str, Any]:
    config = load_app_config(config_path)
    artifacts_root = resolve_runtime_path(repo_path, config.runtime.artifacts_dir)
    worktrees_root = resolve_runtime_path(repo_path, config.runtime.worktrees_dir)
    root = Path(artifacts_root)
    if not root.exists():
        return {
            "artifactsRoot": artifacts_root,
            "keepLatest": keep_latest,
            "removed": [],
        }

    run_dirs = sorted(
        [path for path in root.iterdir() if path.is_dir() and path.name.startswith("run-")],
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    removed: list[dict[str, Any]] = []
    for run_dir in run_dirs[keep_latest:]:
        removed.append(
            _cleanup_run_resources(
                run_dir,
                allowed_repo_root=repo_path,
                allowed_worktrees_root=worktrees_root,
                remove_worktrees=remove_worktrees,
                remove_artifacts=remove_artifacts,
            )
        )
    return {
        "artifactsRoot": artifacts_root,
        "keepLatest": keep_latest,
        "removed": removed,
    }


async def _index_handler(request: web.Request) -> web.StreamResponse:
    static_root = Path(request.app[APP_STATIC_ROOT])
    return web.FileResponse(static_root / "index.html")


async def _bootstrap_handler(request: web.Request) -> web.Response:
    try:
        repo_path, config_path = _resolve_dashboard_scope(
            request.app,
            raw_repo_path=request.query.get("repoPath", ""),
            raw_config_path=request.query.get("configPath", ""),
        )
        config = load_app_config(config_path)
        _validate_dashboard_runtime_roots(request.app, repo_path=repo_path, config=config)
    except (FileNotFoundError, ValueError) as error:
        raise web.HTTPBadRequest(text=str(error)) from error
    pipeline = request.query.get("pipeline", "").strip()
    if pipeline:
        config.runtime.pipeline = pipeline
    orchestrator = HybridOrchestrator(config)
    try:
        plan = orchestrator.build_plan()
    except ValueError as error:
        raise web.HTTPBadRequest(text=str(error)) from error
    artifacts_root = resolve_runtime_path(repo_path, config.runtime.artifacts_dir)
    github_overview = await _build_github_overview(config, repo_path)
    payload = {
        "repoPath": repo_path,
        "configPath": config_path,
        "git": _git_status_snapshot(repo_path),
        "artifactsRoot": artifacts_root,
        "worktreesRoot": resolve_runtime_path(repo_path, config.runtime.worktrees_dir),
        "housekeeping": {
            "confirmationToken": str(request.app[APP_HOUSEKEEPING_TOKEN]),
        },
        "defaultOpenClawAgentId": _default_openclaw_agent_id(config),
        "integrations": {
            "github": github_overview,
            "hermes": _build_hermes_overview(config),
        },
        "snapshot": _serialize_config_snapshot(config, plan),
        "recentRuns": _summarize_recent_runs(
            artifacts_root,
            default_github_repo=github_overview["repo"],
            github_base_branch=github_overview["baseBranch"],
        ),
    }
    return web.json_response(payload)


async def _task_create_handler(request: web.Request) -> web.Response:
    payload = await _read_json_body(request, default={}, require_object=True)
    action = str(payload.get("action", "")).strip()
    if action not in {"diagnose", "preflight", "doctor", "run"}:
        raise web.HTTPBadRequest(text="Unsupported action.")
    try:
        _, _, config = _resolve_request_payload(request.app, payload)
        _validate_task_submission(action, payload, config)
    except (FileNotFoundError, ValueError) as error:
        raise web.HTTPBadRequest(text=str(error)) from error
    task = request.app[APP_TASK_MANAGER].submit(action, payload)
    return web.json_response({"task": task.to_payload()}, status=202)


async def _task_detail_handler(request: web.Request) -> web.Response:
    task_id = request.match_info["task_id"]
    task = request.app[APP_TASK_MANAGER].tasks.get(task_id)
    if task is None:
        raise web.HTTPNotFound(text="Task not found.")
    return web.json_response({"task": task.to_payload()})


async def _task_cancel_handler(request: web.Request) -> web.Response:
    task_id = request.match_info["task_id"]
    try:
        task = request.app[APP_TASK_MANAGER].cancel(task_id)
    except KeyError as error:
        raise web.HTTPNotFound(text="Task not found.") from error
    return web.json_response({"task": task.to_payload()})


async def _task_events_handler(request: web.Request) -> web.StreamResponse:
    task_id = request.match_info["task_id"]
    task = request.app[APP_TASK_MANAGER].tasks.get(task_id)
    if task is None:
        raise web.HTTPNotFound(text="Task not found.")

    response = web.StreamResponse(
        status=200,
        headers={
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )
    await response.prepare(request)

    queue = task.subscribe()
    try:
        while True:
            try:
                payload = await asyncio.wait_for(queue.get(), timeout=15.0)
            except asyncio.TimeoutError:
                await response.write(b": heartbeat\n\n")
                continue
            data = json.dumps({"task": payload}, ensure_ascii=False)
            await response.write(f"event: task\ndata: {data}\n\n".encode("utf-8"))
            if payload["status"] in {"completed", "failed", "cancelled"}:
                break
    except (ConnectionResetError, asyncio.CancelledError):
        pass
    finally:
        task.unsubscribe(queue)
    return response


async def _history_handler(request: web.Request) -> web.Response:
    try:
        repo_path, config_path = _resolve_dashboard_scope(
            request.app,
            raw_repo_path=request.query.get("repoPath", ""),
            raw_config_path=request.query.get("configPath", ""),
        )
        config = load_app_config(config_path)
        _validate_dashboard_runtime_roots(request.app, repo_path=repo_path, config=config)
    except (FileNotFoundError, ValueError) as error:
        raise web.HTTPBadRequest(text=str(error)) from error
    run_id = request.match_info["run_id"]
    try:
        payload = _read_run_history(repo_path, config_path, run_id)
    except FileNotFoundError as error:
        raise web.HTTPNotFound(text=str(error)) from error
    except ValueError as error:
        raise web.HTTPBadRequest(text=str(error)) from error
    return web.json_response(payload)


async def _history_file_handler(request: web.Request) -> web.Response:
    try:
        repo_path, config_path = _resolve_dashboard_scope(
            request.app,
            raw_repo_path=request.query.get("repoPath", ""),
            raw_config_path=request.query.get("configPath", ""),
        )
        config = load_app_config(config_path)
        _validate_dashboard_runtime_roots(request.app, repo_path=repo_path, config=config)
    except (FileNotFoundError, ValueError) as error:
        raise web.HTTPBadRequest(text=str(error)) from error
    run_id = request.match_info["run_id"]
    relative_path = request.query.get("path", "")
    if not re.fullmatch(r"[A-Za-z0-9._-]+", run_id):
        raise web.HTTPBadRequest(text="Invalid run id.")
    artifacts_root = resolve_runtime_path(repo_path, config.runtime.artifacts_dir)
    run_dir = Path(artifacts_root) / run_id
    try:
        payload = _read_artifact_file(run_dir, relative_path)
    except FileNotFoundError as error:
        raise web.HTTPNotFound(text=str(error)) from error
    except ValueError as error:
        raise web.HTTPBadRequest(text=str(error)) from error
    return web.json_response({"runId": run_id, **payload})


async def _history_cleanup_handler(request: web.Request) -> web.Response:
    _require_housekeeping_token(request)
    try:
        repo_path, config_path = _resolve_dashboard_scope(
            request.app,
            raw_repo_path=request.query.get("repoPath", ""),
            raw_config_path=request.query.get("configPath", ""),
        )
        config = load_app_config(config_path)
        _validate_dashboard_runtime_roots(request.app, repo_path=repo_path, config=config)
    except (FileNotFoundError, ValueError) as error:
        raise web.HTTPBadRequest(text=str(error)) from error
    run_id = request.match_info["run_id"]
    body = await _read_json_body(request, default={}, require_object=True)
    remove_worktrees = _read_json_bool_field(body, "removeWorktrees", True)
    remove_artifacts = _read_json_bool_field(body, "removeArtifacts", True)
    try:
        payload = await asyncio.to_thread(
            _cleanup_run_history,
            repo_path,
            config_path,
            run_id,
            remove_worktrees=remove_worktrees,
            remove_artifacts=remove_artifacts,
        )
    except FileNotFoundError as error:
        raise web.HTTPNotFound(text=str(error)) from error
    except ValueError as error:
        raise web.HTTPBadRequest(text=str(error)) from error
    return web.json_response(payload)


async def _history_prune_handler(request: web.Request) -> web.Response:
    _require_housekeeping_token(request)
    try:
        repo_path, config_path = _resolve_dashboard_scope(
            request.app,
            raw_repo_path=request.query.get("repoPath", ""),
            raw_config_path=request.query.get("configPath", ""),
        )
        config = load_app_config(config_path)
        _validate_dashboard_runtime_roots(request.app, repo_path=repo_path, config=config)
    except (FileNotFoundError, ValueError) as error:
        raise web.HTTPBadRequest(text=str(error)) from error
    body = await _read_json_body(request, default={}, require_object=True)
    keep_latest = max(0, _read_json_int_field(body, "keepLatest", 10))
    remove_worktrees = _read_json_bool_field(body, "removeWorktrees", True)
    remove_artifacts = _read_json_bool_field(body, "removeArtifacts", True)
    payload = await asyncio.to_thread(
        _prune_run_history,
        repo_path,
        config_path,
        keep_latest=keep_latest,
        remove_worktrees=remove_worktrees,
        remove_artifacts=remove_artifacts,
    )
    return web.json_response(payload)


async def _history_compare_handler(request: web.Request) -> web.Response:
    try:
        repo_path, config_path = _resolve_dashboard_scope(
            request.app,
            raw_repo_path=request.query.get("repoPath", ""),
            raw_config_path=request.query.get("configPath", ""),
        )
        config = load_app_config(config_path)
        _validate_dashboard_runtime_roots(request.app, repo_path=repo_path, config=config)
    except (FileNotFoundError, ValueError) as error:
        raise web.HTTPBadRequest(text=str(error)) from error
    body = await _read_json_body(request, default={}, require_object=True)
    run_ids = body.get("runIds", [])
    if not isinstance(run_ids, list):
        raise web.HTTPBadRequest(text="runIds must be a list.")
    if len(run_ids) != 2:
        raise web.HTTPBadRequest(text="Two run ids are required for comparison.")
    normalized_ids: list[str] = []
    for run_id in run_ids:
        if not isinstance(run_id, str) or not run_id.strip():
            raise web.HTTPBadRequest(text="runIds must contain non-empty strings.")
        normalized_ids.append(run_id.strip())

    try:
        left = _read_run_history(repo_path, config_path, normalized_ids[0])
        right = _read_run_history(repo_path, config_path, normalized_ids[1])
    except FileNotFoundError as error:
        raise web.HTTPNotFound(text=str(error)) from error
    except ValueError as error:
        raise web.HTTPBadRequest(text=str(error)) from error

    return web.json_response(
        {
            "runs": [
                {
                    "runId": left["runId"],
                    "updatedAt": left["updatedAt"],
                    "request": left["context"].get("user_request", ""),
                    "success": bool(left.get("summary", {}).get("success", False)),
                    "stepCount": len(left.get("summary", {}).get("plan", []) or []),
                    "insights": left["insights"],
                },
                {
                    "runId": right["runId"],
                    "updatedAt": right["updatedAt"],
                    "request": right["context"].get("user_request", ""),
                    "success": bool(right.get("summary", {}).get("success", False)),
                    "stepCount": len(right.get("summary", {}).get("plan", []) or []),
                    "insights": right["insights"],
                },
            ],
            "comparison": _compare_run_histories(left, right),
        }
    )


async def _health_handler(request: web.Request) -> web.Response:
    try:
        _, config_path = _resolve_dashboard_scope(
            request.app,
            raw_repo_path=request.query.get("repoPath", ""),
            raw_config_path=request.query.get("configPath", ""),
        )
        config = load_app_config(config_path)
        _validate_dashboard_runtime_roots(request.app, repo_path=str(request.app[APP_REPO_PATH]), config=config)
    except (FileNotFoundError, ValueError) as error:
        raise web.HTTPBadRequest(text=str(error)) from error
    agent_id = request.query.get("agentId", "").strip() or _default_openclaw_agent_id(config)
    payload = await asyncio.to_thread(_openclaw_health_snapshot, agent_id)
    return web.json_response(payload)


async def _cleanup_background_tasks(app: web.Application) -> None:
    task_manager = app[APP_TASK_MANAGER]
    await task_manager.shutdown()


def create_web_app(
    *,
    config_path: str,
    repo_path: str,
    allow_path_override: bool = False,
) -> web.Application:
    static_root = Path(__file__).with_name("webui")
    resolved_repo_path = str(_canonical_path(repo_path))
    resolved_config_path = str(_canonical_path(config_path))
    startup_config = load_app_config(resolved_config_path)
    app = web.Application(middlewares=[_security_headers_middleware])
    app[APP_CONFIG_PATH] = resolved_config_path
    app[APP_REPO_PATH] = resolved_repo_path
    app[APP_STATIC_ROOT] = str(static_root)
    app[APP_TASK_MANAGER] = DashboardTaskManager(app)
    app[APP_ALLOW_PATH_OVERRIDE] = allow_path_override
    app[APP_HOUSEKEEPING_TOKEN] = secrets.token_urlsafe(24)
    app[APP_ARTIFACTS_ROOT] = str(
        _canonical_path(resolve_runtime_path(resolved_repo_path, startup_config.runtime.artifacts_dir))
    )
    app[APP_WORKTREES_ROOT] = str(
        _canonical_path(resolve_runtime_path(resolved_repo_path, startup_config.runtime.worktrees_dir))
    )
    app.on_response_prepare.append(_security_headers_on_prepare)

    app.router.add_get("/", _index_handler)
    app.router.add_get("/api/bootstrap", _bootstrap_handler)
    app.router.add_post("/api/tasks", _task_create_handler)
    app.router.add_get("/api/tasks/{task_id}", _task_detail_handler)
    app.router.add_post("/api/tasks/{task_id}/cancel", _task_cancel_handler)
    app.router.add_get("/api/tasks/{task_id}/events", _task_events_handler)
    app.router.add_get("/api/history/{run_id}", _history_handler)
    app.router.add_get("/api/history/{run_id}/file", _history_file_handler)
    app.router.add_post("/api/history/{run_id}/cleanup", _history_cleanup_handler)
    app.router.add_post("/api/history/prune", _history_prune_handler)
    app.router.add_post("/api/history/compare", _history_compare_handler)
    app.router.add_get("/api/system/health", _health_handler)
    app.router.add_static("/static/", str(static_root))
    app.on_cleanup.append(_cleanup_background_tasks)
    return app


async def run_web_server(
    *,
    config_path: str,
    repo_path: str,
    host: str,
    port: int,
    allow_path_override: bool = False,
) -> None:
    app = create_web_app(
        config_path=config_path,
        repo_path=repo_path,
        allow_path_override=allow_path_override,
    )
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host=host, port=port)
    await site.start()
    print("OpenClaw Mission Control Web UI is running.")
    print(f"Dashboard: http://{host}:{port}/")
    print(f"Repo: {repo_path}")
    print(f"Config: {config_path}")
    stop_event = asyncio.Event()
    try:
        await stop_event.wait()
    except asyncio.CancelledError:
        pass
    finally:
        await runner.cleanup()
