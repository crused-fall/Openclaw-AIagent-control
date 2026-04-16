from __future__ import annotations

import asyncio
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
from .models import TaskStatus
from .orchestrator import HybridOrchestrator

APP_CONFIG_PATH = web.AppKey("config_path", str)
APP_REPO_PATH = web.AppKey("repo_path", str)
APP_STATIC_ROOT = web.AppKey("static_root", str)
APP_TASK_MANAGER = web.AppKey("task_manager", Any)


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


def _resolve_user_path(raw_path: str, base_path: str | None = None) -> str:
    expanded = os.path.expanduser((raw_path or "").strip())
    if not expanded:
        return os.path.abspath(base_path or os.getcwd())
    if os.path.isabs(expanded):
        return os.path.abspath(expanded)
    if base_path:
        return os.path.abspath(os.path.join(base_path, expanded))
    return os.path.abspath(expanded)


def _selected_steps(payload: dict[str, Any]) -> list[str] | None:
    raw_steps = payload.get("steps", [])
    if isinstance(raw_steps, str):
        values = [step.strip() for step in raw_steps.split(",") if step.strip()]
        return values or None
    if isinstance(raw_steps, list):
        values = [str(step).strip() for step in raw_steps if str(step).strip()]
        return values or None
    return None


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


def _summarize_recent_runs(artifacts_root: str, limit: int = 8) -> list[dict[str, Any]]:
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
                manifests.append(json.load(handle))
        except json.JSONDecodeError:
            continue
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


def _cleanup_run_resources(
    run_dir: Path,
    *,
    remove_worktrees: bool,
    remove_artifacts: bool,
) -> dict[str, Any]:
    operations: list[dict[str, Any]] = []
    manifests = _load_run_workspace_manifests(run_dir)

    if remove_worktrees:
        for manifest in manifests:
            metadata = manifest.get("metadata") or {}
            strategy = str(metadata.get("workspace_strategy", "")).strip()
            if strategy != "git-worktree":
                continue

            workspace_path = str(manifest.get("workspace_path", "")).strip()
            branch_name = str(manifest.get("branch_name", "")).strip()
            repo_root = str(metadata.get("workspace_repo_root", "")).strip()
            if not repo_root:
                continue

            if workspace_path and os.path.exists(workspace_path):
                operations.append(
                    {
                        "type": "worktree_remove",
                        "workspacePath": workspace_path,
                        **_run_cleanup_command(
                            ["git", "-C", repo_root, "worktree", "remove", "--force", workspace_path]
                        ),
                    }
                )

            if branch_name and branch_name.startswith("openclaw-"):
                operations.append(
                    {
                        "type": "branch_delete",
                        "branchName": branch_name,
                        **_run_cleanup_command(["git", "-C", repo_root, "branch", "-D", branch_name]),
                    }
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
        "knownAgents": [agent_id for agent_id in agent_ids if agent_id],
        "targetAgentPresent": agent_id in agent_ids,
        "channels": channels,
        "healthRaw": health_payload,
        "gateway": gateway_capture,
        "memory": memory_capture,
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


def _serialize_config_snapshot(config: Any, plan: list[Any]) -> dict[str, Any]:
    return {
        "runtime": _json_ready(config.runtime),
        "github": _json_ready(config.github),
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
        "managedAgents": {
            name: _json_ready(agent)
            for name, agent in sorted(config.managed_agents.items())
        },
        "assignments": {
            name: _json_ready(item)
            for name, item in sorted(config.assignments.items())
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
    default_repo_path = str(app[APP_REPO_PATH])
    repo_path = _resolve_user_path(str(payload.get("repoPath", "")).strip(), default_repo_path)
    config_path = _resolve_user_path(
        str(payload.get("configPath", "")).strip() or str(app[APP_CONFIG_PATH]),
        repo_path,
    )
    config = load_app_config(config_path)
    pipeline = str(payload.get("pipeline", "")).strip()
    if pipeline:
        config.runtime.pipeline = pipeline
    return repo_path, config_path, config


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

    live = bool(payload.get("live", False))
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
    return {
        "runId": run_id,
        "artifactsDir": str(run_dir),
        "context": context,
        "summary": summary,
        "preflight": preflight,
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
    run_dir = Path(artifacts_root) / run_id
    if not run_dir.exists():
        raise FileNotFoundError(f"Run directory not found for {run_id}.")
    return _cleanup_run_resources(
        run_dir,
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
    default_repo = str(request.app[APP_REPO_PATH])
    repo_path = _resolve_user_path(request.query.get("repoPath", ""), default_repo)
    config_path = _resolve_user_path(
        request.query.get("configPath", "") or str(request.app[APP_CONFIG_PATH]),
        repo_path,
    )
    config = load_app_config(config_path)
    pipeline = request.query.get("pipeline", "").strip()
    if pipeline:
        config.runtime.pipeline = pipeline
    orchestrator = HybridOrchestrator(config)
    plan = orchestrator.build_plan()
    artifacts_root = resolve_runtime_path(repo_path, config.runtime.artifacts_dir)
    payload = {
        "repoPath": repo_path,
        "configPath": config_path,
        "git": _git_status_snapshot(repo_path),
        "artifactsRoot": artifacts_root,
        "defaultOpenClawAgentId": _default_openclaw_agent_id(config),
        "snapshot": _serialize_config_snapshot(config, plan),
        "recentRuns": _summarize_recent_runs(artifacts_root),
    }
    return web.json_response(payload)


async def _task_create_handler(request: web.Request) -> web.Response:
    payload = await request.json()
    action = str(payload.get("action", "")).strip()
    if action not in {"diagnose", "preflight", "doctor", "run"}:
        raise web.HTTPBadRequest(text="Unsupported action.")
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
    default_repo = str(request.app[APP_REPO_PATH])
    repo_path = _resolve_user_path(request.query.get("repoPath", ""), default_repo)
    config_path = _resolve_user_path(
        request.query.get("configPath", "") or str(request.app[APP_CONFIG_PATH]),
        repo_path,
    )
    run_id = request.match_info["run_id"]
    try:
        payload = _read_run_history(repo_path, config_path, run_id)
    except FileNotFoundError as error:
        raise web.HTTPNotFound(text=str(error)) from error
    except ValueError as error:
        raise web.HTTPBadRequest(text=str(error)) from error
    return web.json_response(payload)


async def _history_file_handler(request: web.Request) -> web.Response:
    default_repo = str(request.app[APP_REPO_PATH])
    repo_path = _resolve_user_path(request.query.get("repoPath", ""), default_repo)
    config_path = _resolve_user_path(
        request.query.get("configPath", "") or str(request.app[APP_CONFIG_PATH]),
        repo_path,
    )
    run_id = request.match_info["run_id"]
    relative_path = request.query.get("path", "")
    if not re.fullmatch(r"[A-Za-z0-9._-]+", run_id):
        raise web.HTTPBadRequest(text="Invalid run id.")
    config = load_app_config(config_path)
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
    default_repo = str(request.app[APP_REPO_PATH])
    repo_path = _resolve_user_path(request.query.get("repoPath", ""), default_repo)
    config_path = _resolve_user_path(
        request.query.get("configPath", "") or str(request.app[APP_CONFIG_PATH]),
        repo_path,
    )
    run_id = request.match_info["run_id"]
    body = await request.json() if request.can_read_body else {}
    remove_worktrees = bool(body.get("removeWorktrees", True))
    remove_artifacts = bool(body.get("removeArtifacts", True))
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
    default_repo = str(request.app[APP_REPO_PATH])
    repo_path = _resolve_user_path(request.query.get("repoPath", ""), default_repo)
    config_path = _resolve_user_path(
        request.query.get("configPath", "") or str(request.app[APP_CONFIG_PATH]),
        repo_path,
    )
    body = await request.json() if request.can_read_body else {}
    keep_latest = max(0, int(body.get("keepLatest", 10)))
    remove_worktrees = bool(body.get("removeWorktrees", True))
    remove_artifacts = bool(body.get("removeArtifacts", True))
    payload = await asyncio.to_thread(
        _prune_run_history,
        repo_path,
        config_path,
        keep_latest=keep_latest,
        remove_worktrees=remove_worktrees,
        remove_artifacts=remove_artifacts,
    )
    return web.json_response(payload)


async def _health_handler(request: web.Request) -> web.Response:
    default_repo = str(request.app[APP_REPO_PATH])
    repo_path = _resolve_user_path(request.query.get("repoPath", ""), default_repo)
    config_path = _resolve_user_path(
        request.query.get("configPath", "") or str(request.app[APP_CONFIG_PATH]),
        repo_path,
    )
    config = load_app_config(config_path)
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
) -> web.Application:
    static_root = Path(__file__).with_name("webui")
    app = web.Application()
    app[APP_CONFIG_PATH] = config_path
    app[APP_REPO_PATH] = repo_path
    app[APP_STATIC_ROOT] = str(static_root)
    app[APP_TASK_MANAGER] = DashboardTaskManager(app)

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
) -> None:
    app = create_web_app(config_path=config_path, repo_path=repo_path)
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
