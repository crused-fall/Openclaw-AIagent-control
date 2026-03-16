from __future__ import annotations

import asyncio
import shutil

from .config import AppConfig
from .models import CheckStatus, ExecutionMode, PreflightCheck, PreflightReport, WorkItem


class PreflightRunner:
    def __init__(self, config: AppConfig):
        self.config = config

    async def run(self, repo_path: str, plan: list[WorkItem]) -> PreflightReport:
        checks: list[PreflightCheck] = []
        checks.append(await self._check_git_repo(repo_path))
        checks.extend(await self._check_required_commands(plan))
        if any(bool(item.metadata.get("requires_origin_remote")) for item in plan):
            checks.append(await self._check_origin_remote(repo_path))
        if any(item.mode == ExecutionMode.GITHUB for item in plan):
            checks.append(self._check_github_repo_config())
            checks.append(await self._check_gh_auth())
        return PreflightReport(checks=checks)

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
            profile = self.config.profiles[item.profile]
            if item.mode == ExecutionMode.CLI and profile.command:
                command_names.add(profile.command[0])
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

    def _check_github_repo_config(self) -> PreflightCheck:
        repo = self.config.github.repo.strip()
        if repo:
            return PreflightCheck(
                name="github_repo",
                status=CheckStatus.PASSED,
                message="GitHub repo is configured.",
                details={"repo": repo},
            )

        status = CheckStatus.WARNING if self.config.runtime.dry_run else CheckStatus.FAILED
        return PreflightCheck(
            name="github_repo",
            status=status,
            message="GitHub repo is not configured.",
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
            return PreflightCheck(
                name="gh_auth",
                status=CheckStatus.PASSED,
                message="GitHub CLI authentication is ready.",
                details={"output": output or error_output},
            )

        status = CheckStatus.WARNING if self.config.runtime.dry_run else CheckStatus.FAILED
        return PreflightCheck(
            name="gh_auth",
            status=status,
            message="GitHub CLI authentication is not ready.",
            details={"output": error_output or output},
        )
