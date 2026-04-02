from __future__ import annotations

import asyncio
import json
import os
import shutil

from .config import AppConfig
from .github_support import resolve_github_repo_from_origin
from .models import CheckStatus, ExecutionMode, PreflightCheck, PreflightReport, WorkItem


class PreflightRunner:
    def __init__(self, config: AppConfig):
        self.config = config

    async def run(self, repo_path: str, plan: list[WorkItem]) -> PreflightReport:
        checks: list[PreflightCheck] = []
        checks.append(await self._check_git_repo(repo_path))
        dirty_check = await self._check_repo_dirty_for_isolated_cli_steps(repo_path, plan)
        if dirty_check is not None:
            checks.append(dirty_check)
        checks.extend(self._check_planning_blocks(plan))
        checks.extend(self._check_managed_assignments(plan))
        checks.extend(await self._check_required_commands(plan))
        checks.extend(await self._check_openclaw_profiles(repo_path, plan))
        if any(bool(item.metadata.get("requires_origin_remote")) for item in plan):
            checks.append(await self._check_origin_remote(repo_path))
        if any(bool(item.metadata.get("requires_origin_remote")) for item in plan) or any(
            item.mode == ExecutionMode.GITHUB for item in plan
        ):
            checks.append(await self._check_remote_base_sync(repo_path))
        if any(item.mode == ExecutionMode.GITHUB for item in plan):
            checks.append(await self._check_github_repo_resolution(repo_path))
            checks.append(await self._check_gh_auth())
            checks.extend(self._check_github_workflow_files(repo_path, plan))
        return PreflightReport(checks=checks)

    @staticmethod
    def _uses_isolated_cli_workspace(item: WorkItem) -> bool:
        source_branch = str(item.metadata.get("source_branch", "")).strip()
        if item.mode == ExecutionMode.CLI:
            return not source_branch
        return (
            item.mode == ExecutionMode.OPENCLAW
            and bool(item.metadata.get("export_branch", False))
            and not source_branch
        )

    async def _check_repo_dirty_for_isolated_cli_steps(
        self,
        repo_path: str,
        plan: list[WorkItem],
    ) -> PreflightCheck | None:
        affected_steps = [item.id for item in plan if self._uses_isolated_cli_workspace(item)]
        if not affected_steps:
            return None

        process = await asyncio.create_subprocess_exec(
            "git",
            "-C",
            repo_path,
            "status",
            "--porcelain",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            message = stderr.decode("utf-8", errors="replace").strip() or "Unable to inspect repository dirty state."
            return PreflightCheck(
                name="git_dirty_worktree_base",
                status=CheckStatus.WARNING if self.config.runtime.dry_run else CheckStatus.FAILED,
                message=message,
                details={"affected_steps": affected_steps},
            )

        raw_output = stdout.decode("utf-8", errors="replace")
        if not raw_output.strip():
            return PreflightCheck(
                name="git_dirty_worktree_base",
                status=CheckStatus.PASSED,
                message=(
                    "Repository working tree is clean; isolated worktree steps will run from the current committed base."
                ),
                details={"affected_steps": affected_steps},
            )

        changed_paths = [line[3:] for line in raw_output.splitlines() if len(line) > 3]
        return PreflightCheck(
            name="git_dirty_worktree_base",
            status=CheckStatus.WARNING if self.config.runtime.dry_run else CheckStatus.FAILED,
            message=(
                "Repository has uncommitted changes. Isolated worktree steps run from committed HEAD and "
                "will not see local edits; commit or stash changes before live runs."
            ),
            details={
                "affected_steps": affected_steps,
                "changed_paths": changed_paths,
            },
        )

    def _check_planning_blocks(self, plan: list[WorkItem]) -> list[PreflightCheck]:
        checks: list[PreflightCheck] = []
        for item in plan:
            if not item.planning_blocked_reason:
                continue
            checks.append(
                PreflightCheck(
                    name=f"planning:{item.id}",
                    status=CheckStatus.WARNING,
                    message=f"Step `{item.id}` is blocked before execution: {item.planning_blocked_reason}",
                    details={
                        "assignment": item.assignment,
                        "managed_agent": item.managed_agent,
                        "profile": item.profile,
                        "required_capabilities": item.required_capabilities,
                        "assignment_candidates": item.assignment_candidates,
                        "assignment_attempts": item.assignment_attempts,
                        "planning_blocked_reason": item.planning_blocked_reason,
                    },
                )
            )
        return checks

    def _check_managed_assignments(self, plan: list[WorkItem]) -> list[PreflightCheck]:
        checks: list[PreflightCheck] = []
        for item in plan:
            if not item.assignment or item.planning_blocked_reason:
                continue

            managed_agent = item.managed_agent or "unknown"
            details = {
                "assignment": item.assignment,
                "managed_agent": managed_agent,
                "profile": item.profile,
                "fallback_chain": item.fallback_chain,
                "required_capabilities": item.required_capabilities,
                "assignment_candidates": item.assignment_candidates,
                "assignment_attempts": item.assignment_attempts,
            }
            if item.assignment_reason:
                details["assignment_reason"] = item.assignment_reason

            if item.fallback_used:
                checks.append(
                    PreflightCheck(
                        name=f"assignment:{item.id}",
                        status=CheckStatus.WARNING,
                        message=(
                            f"Step `{item.id}` resolved via fallback managed agent `{managed_agent}`."
                        ),
                        details=details,
                    )
                )
                continue

            checks.append(
                PreflightCheck(
                    name=f"assignment:{item.id}",
                    status=CheckStatus.PASSED,
                    message=f"Step `{item.id}` resolved to managed agent `{managed_agent}`.",
                    details=details,
                )
            )
        return checks

    async def _check_git_repo(self, repo_path: str) -> PreflightCheck:
        process = await asyncio.create_subprocess_exec(
            "git",
            "-C",
            repo_path,
            "rev-parse",
            "--is-inside-work-tree",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        if process.returncode == 0 and stdout.decode("utf-8", errors="replace").strip() == "true":
            return PreflightCheck(
                name="git_repo",
                status=CheckStatus.PASSED,
                message="Repository is a valid git work tree.",
                details={"repo_path": repo_path},
            )
        return PreflightCheck(
            name="git_repo",
            status=CheckStatus.FAILED,
            message="Repository is not a valid git work tree.",
            details={"repo_path": repo_path, "stderr": stderr.decode("utf-8", errors="replace").strip()},
        )

    async def _check_required_commands(self, plan: list[WorkItem]) -> list[PreflightCheck]:
        command_names: set[str] = {"git"}
        for item in plan:
            if item.mode == ExecutionMode.SYSTEM:
                continue
            profile = self.config.profiles[item.profile]
            if item.mode == ExecutionMode.CLI and profile.command:
                command_names.add(profile.command[0])
            if item.mode == ExecutionMode.OPENCLAW:
                command_names.add("openclaw")
            if item.mode == ExecutionMode.GITHUB:
                command_names.add("gh")

        checks: list[PreflightCheck] = []
        for command_name in sorted(command_names):
            resolved = shutil.which(command_name)
            if resolved:
                checks.append(
                    PreflightCheck(
                        name=f"command:{command_name}",
                        status=CheckStatus.PASSED,
                        message=f"Command `{command_name}` is available.",
                        details={"path": resolved},
                    )
                )
                continue

            status = CheckStatus.WARNING if self.config.runtime.dry_run else CheckStatus.FAILED
            checks.append(
                PreflightCheck(
                    name=f"command:{command_name}",
                    status=status,
                    message=f"Command `{command_name}` is not available.",
                )
            )
        return checks

    async def _check_openclaw_profiles(self, repo_path: str, plan: list[WorkItem]) -> list[PreflightCheck]:
        profile_map = {
            item.profile: self.config.profiles[item.profile]
            for item in plan
            if item.mode == ExecutionMode.OPENCLAW
        }
        if not profile_map or shutil.which("openclaw") is None:
            return []

        process = await asyncio.create_subprocess_exec(
            "openclaw",
            "agents",
            "list",
            "--json",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        output = stdout.decode("utf-8", errors="replace").strip()
        error_output = stderr.decode("utf-8", errors="replace").strip()

        if process.returncode != 0:
            status = CheckStatus.WARNING if self.config.runtime.dry_run else CheckStatus.FAILED
            return [
                PreflightCheck(
                    name="openclaw_agents",
                    status=status,
                    message="OpenClaw agent list is not available.",
                    details={"output": error_output or output},
                )
            ]

        try:
            raw_agents = json.loads(output or "[]")
        except json.JSONDecodeError:
            status = CheckStatus.WARNING if self.config.runtime.dry_run else CheckStatus.FAILED
            return [
                PreflightCheck(
                    name="openclaw_agents",
                    status=status,
                    message="OpenClaw agent list returned invalid JSON.",
                    details={"output": output},
                )
            ]

        agents = {
            str(agent.get("id", "")).strip(): agent
            for agent in raw_agents
            if isinstance(agent, dict) and str(agent.get("id", "")).strip()
        }
        available_agent_ids = sorted(agents.keys())

        checks: list[PreflightCheck] = []
        normalized_repo_path = os.path.realpath(repo_path)
        for profile_name, profile in profile_map.items():
            agent_id = profile.openclaw_agent_id.strip()
            status = CheckStatus.WARNING if self.config.runtime.dry_run else CheckStatus.FAILED
            if not agent_id:
                available_text = (
                    f" Available local agents: {', '.join(available_agent_ids)}."
                    if available_agent_ids
                    else ""
                )
                checks.append(
                    PreflightCheck(
                        name=f"openclaw_agent:{profile_name}",
                        status=status,
                        message=(
                            "OpenClaw profile has no openclaw_agent_id configured."
                            f"{available_text}"
                        ),
                        details={"available_agent_ids": available_agent_ids},
                    )
                )
                continue

            agent = agents.get(agent_id)
            if not agent:
                available_text = (
                    f" Available local agents: {', '.join(available_agent_ids)}."
                    if available_agent_ids
                    else ""
                )
                checks.append(
                    PreflightCheck(
                        name=f"openclaw_agent:{profile_name}",
                        status=status,
                        message=(
                            f"OpenClaw agent `{agent_id}` is not configured locally."
                            f"{available_text}"
                        ),
                        details={"available_agent_ids": available_agent_ids},
                    )
                )
                continue

            workspace = str(agent.get("workspace", "")).strip()
            normalized_workspace = os.path.realpath(workspace) if workspace else ""
            checks.append(
                PreflightCheck(
                    name=f"openclaw_agent:{profile_name}",
                    status=CheckStatus.PASSED,
                    message=f"OpenClaw agent `{agent_id}` is available.",
                    details={"workspace": workspace, "agent_dir": str(agent.get('agentDir', '')).strip()},
                )
            )
            if normalized_workspace and self._is_within_repo(normalized_workspace, normalized_repo_path):
                location_text = "repo root" if normalized_workspace == normalized_repo_path else "repository tree"
                checks.append(
                    PreflightCheck(
                        name=f"openclaw_workspace:{profile_name}",
                        status=CheckStatus.WARNING,
                        message=(
                            f"OpenClaw agent `{agent_id}` workspace points inside the {location_text}; "
                            "OpenClaw runtime files may be written into the repository."
                        ),
                        details={"workspace": workspace, "repo_path": repo_path},
                    )
                )
            elif normalized_workspace:
                checks.append(
                    PreflightCheck(
                        name=f"openclaw_workspace:{profile_name}",
                        status=CheckStatus.PASSED,
                        message=(
                            f"OpenClaw agent `{agent_id}` workspace is isolated from the repository root; "
                            "repo access will be passed via absolute path handoff."
                        ),
                        details={"workspace": workspace, "repo_path": repo_path},
                    )
                )
        return checks

    @staticmethod
    def _is_within_repo(workspace_path: str, repo_path: str) -> bool:
        try:
            return os.path.commonpath([workspace_path, repo_path]) == repo_path
        except ValueError:
            return False

    async def _check_origin_remote(self, repo_path: str) -> PreflightCheck:
        process = await asyncio.create_subprocess_exec(
            "git",
            "-C",
            repo_path,
            "remote",
            "get-url",
            "origin",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        if process.returncode == 0:
            return PreflightCheck(
                name="git_origin_remote",
                status=CheckStatus.PASSED,
                message="Git remote `origin` is configured.",
                details={"origin": stdout.decode("utf-8", errors="replace").strip()},
            )

        status = CheckStatus.WARNING if self.config.runtime.dry_run else CheckStatus.FAILED
        return PreflightCheck(
            name="git_origin_remote",
            status=status,
            message="Git remote `origin` is not configured.",
            details={"stderr": stderr.decode("utf-8", errors="replace").strip()},
        )

    async def _check_remote_base_sync(self, repo_path: str) -> PreflightCheck:
        branch_process = await asyncio.create_subprocess_exec(
            "git",
            "-C",
            repo_path,
            "rev-parse",
            "--abbrev-ref",
            "HEAD",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        branch_stdout, branch_stderr = await branch_process.communicate()
        current_branch = branch_stdout.decode("utf-8", errors="replace").strip()
        if branch_process.returncode != 0 or not current_branch:
            status = CheckStatus.WARNING if self.config.runtime.dry_run else CheckStatus.FAILED
            return PreflightCheck(
                name="git_remote_base_sync",
                status=status,
                message="Could not determine the current branch for remote-base sync checks.",
                details={"stderr": branch_stderr.decode("utf-8", errors="replace").strip()},
            )

        upstream_process = await asyncio.create_subprocess_exec(
            "git",
            "-C",
            repo_path,
            "rev-parse",
            "--abbrev-ref",
            "--symbolic-full-name",
            "@{upstream}",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        upstream_stdout, upstream_stderr = await upstream_process.communicate()
        upstream_branch = upstream_stdout.decode("utf-8", errors="replace").strip()
        if upstream_process.returncode != 0 or not upstream_branch:
            return PreflightCheck(
                name="git_remote_base_sync",
                status=CheckStatus.WARNING,
                message=(
                    f"Current branch `{current_branch}` has no upstream; remote-base sync could not be verified."
                ),
                details={"current_branch": current_branch, "stderr": upstream_stderr.decode("utf-8", errors="replace").strip()},
            )

        divergence_process = await asyncio.create_subprocess_exec(
            "git",
            "-C",
            repo_path,
            "rev-list",
            "--left-right",
            "--count",
            f"{upstream_branch}...HEAD",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        divergence_stdout, divergence_stderr = await divergence_process.communicate()
        if divergence_process.returncode != 0:
            status = CheckStatus.WARNING if self.config.runtime.dry_run else CheckStatus.FAILED
            return PreflightCheck(
                name="git_remote_base_sync",
                status=status,
                message="Could not compare the current branch against its upstream.",
                details={
                    "current_branch": current_branch,
                    "upstream_branch": upstream_branch,
                    "stderr": divergence_stderr.decode("utf-8", errors="replace").strip(),
                },
            )

        counts = divergence_stdout.decode("utf-8", errors="replace").strip().split()
        behind = int(counts[0]) if len(counts) >= 1 else 0
        ahead = int(counts[1]) if len(counts) >= 2 else 0
        details = {
            "current_branch": current_branch,
            "upstream_branch": upstream_branch,
            "ahead": ahead,
            "behind": behind,
        }
        if ahead > 0:
            status = CheckStatus.WARNING if self.config.runtime.dry_run else CheckStatus.FAILED
            return PreflightCheck(
                name="git_remote_base_sync",
                status=status,
                message=(
                    f"Current branch `{current_branch}` is ahead of `{upstream_branch}` by {ahead} commit(s). "
                    "Exported implementation branches will include those unpublished commits when opened against the remote base; "
                    "push or sync the base branch first."
                ),
                details=details,
            )
        if behind > 0:
            return PreflightCheck(
                name="git_remote_base_sync",
                status=CheckStatus.WARNING,
                message=(
                    f"Current branch `{current_branch}` is behind `{upstream_branch}` by {behind} commit(s); "
                    "exported branches may be based on a stale local base."
                ),
                details=details,
            )
        return PreflightCheck(
            name="git_remote_base_sync",
            status=CheckStatus.PASSED,
            message=f"Current branch `{current_branch}` is in sync with `{upstream_branch}`.",
            details=details,
        )

    async def _check_github_repo_resolution(self, repo_path: str) -> PreflightCheck:
        repo = self.config.github.repo.strip()
        if repo:
            return PreflightCheck(
                name="github_repo",
                status=CheckStatus.PASSED,
                message="GitHub repo is configured.",
                details={"repo": repo, "source": "config"},
            )

        if self.config.github.use_origin_remote_fallback:
            resolved_repo, origin_url, error_output = await resolve_github_repo_from_origin(repo_path)
            if resolved_repo:
                return PreflightCheck(
                    name="github_repo",
                    status=CheckStatus.PASSED,
                    message="GitHub repo resolved from `origin` remote fallback.",
                    details={"repo": resolved_repo, "source": "git_origin", "origin": origin_url},
                )

            status = CheckStatus.WARNING if self.config.runtime.dry_run else CheckStatus.FAILED
            return PreflightCheck(
                name="github_repo",
                status=status,
                message="GitHub repo is not configured and could not be resolved from `origin`.",
                details={"output": error_output, "source": "git_origin"},
            )

        status = CheckStatus.WARNING if self.config.runtime.dry_run else CheckStatus.FAILED
        return PreflightCheck(
            name="github_repo",
            status=status,
            message="GitHub repo is not configured.",
            details={"source": "config"},
        )

    async def _check_gh_auth(self) -> PreflightCheck:
        resolved = shutil.which("gh")
        if not resolved:
            status = CheckStatus.WARNING if self.config.runtime.dry_run else CheckStatus.FAILED
            return PreflightCheck(
                name="gh_auth",
                status=status,
                message="Cannot check gh auth because `gh` is not installed.",
            )

        process = await asyncio.create_subprocess_exec(
            "gh",
            "auth",
            "status",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        output = stdout.decode("utf-8", errors="replace").strip()
        error_output = stderr.decode("utf-8", errors="replace").strip()
        if process.returncode == 0:
            combined_output = output or error_output
            message = "GitHub CLI authentication is ready."
            details = {"output": combined_output}
            if "github_pat_" in combined_output or "\n  - Token: github_pat_" in combined_output:
                message = (
                    "GitHub CLI authentication is ready. Active credential appears to be a personal access token; "
                    "workflow dispatch may still require additional token permissions."
                )
                details["credential_hint"] = "personal_access_token"
            return PreflightCheck(
                name="gh_auth",
                status=CheckStatus.PASSED,
                message=message,
                details=details,
            )

        status = CheckStatus.WARNING if self.config.runtime.dry_run else CheckStatus.FAILED
        return PreflightCheck(
            name="gh_auth",
            status=status,
            message="GitHub CLI authentication is not ready.",
            details={"output": error_output or output},
        )

    def _check_github_workflow_files(self, repo_path: str, plan: list[WorkItem]) -> list[PreflightCheck]:
        checks: list[PreflightCheck] = []
        seen_profiles: set[str] = set()
        for item in plan:
            if item.mode != ExecutionMode.GITHUB or not item.profile or item.profile in seen_profiles:
                continue

            seen_profiles.add(item.profile)
            profile = self.config.profiles[item.profile]
            if profile.action != "workflow_dispatch":
                continue

            workflow_name = profile.workflow_name.strip()
            status = CheckStatus.WARNING if self.config.runtime.dry_run else CheckStatus.FAILED
            if not workflow_name:
                checks.append(
                    PreflightCheck(
                        name=f"github_workflow:{item.profile}",
                        status=status,
                        message=(
                            f"GitHub workflow profile `{item.profile}` has no workflow_name configured."
                        ),
                        details={"profile": item.profile},
                    )
                )
                continue

            workflow_path = os.path.join(repo_path, ".github", "workflows", workflow_name)
            if os.path.exists(workflow_path):
                checks.append(
                    PreflightCheck(
                        name=f"github_workflow:{item.profile}",
                        status=CheckStatus.PASSED,
                        message=f"GitHub workflow file `{workflow_name}` exists locally.",
                        details={"profile": item.profile, "workflow_path": workflow_path},
                    )
                )
                continue

            checks.append(
                PreflightCheck(
                    name=f"github_workflow:{item.profile}",
                    status=status,
                    message=(
                        f"GitHub workflow file `{workflow_name}` was not found under `.github/workflows/`."
                    ),
                    details={"profile": item.profile, "workflow_path": workflow_path},
                )
            )
        return checks
