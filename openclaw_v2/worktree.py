from __future__ import annotations

import asyncio
import os
import re

from .models import ExecutionContext, ExecutionMode, WorkItem


class WorktreeManager:
    def __init__(self) -> None:
        self._repo_root_cache: dict[str, str] = {}
        self._base_ref_cache: dict[str, str] = {}

    async def prepare(self, work_item: WorkItem, context: ExecutionContext) -> None:
        uses_isolated_workspace = (
            work_item.mode == ExecutionMode.CLI
            or (
                work_item.mode == ExecutionMode.OPENCLAW
                and bool(work_item.metadata.get("export_branch", False))
            )
        )
        if not uses_isolated_workspace:
            work_item.workspace_path = context.repo_path
            work_item.branch_name = ""
            work_item.metadata["workspace_strategy"] = "shared"
            return

        source_workspace_path = str(work_item.metadata.get("source_workspace_path", "")).strip()
        source_branch = str(work_item.metadata.get("source_branch", "")).strip()
        if bool(work_item.metadata.get("reuse_source_workspace", False)) and source_branch and source_workspace_path:
            work_item.workspace_path = source_workspace_path
            work_item.branch_name = source_branch
            work_item.metadata["workspace_strategy"] = "reuse-source-workspace"
            work_item.metadata["workspace_repo_root"] = context.repo_path
            work_item.metadata["workspace_prepared"] = True
            return

        if source_branch:
            work_item.workspace_path = context.repo_path
            work_item.branch_name = source_branch
            work_item.metadata["workspace_strategy"] = "reuse-source-branch"
            work_item.metadata["workspace_repo_root"] = context.repo_path
            work_item.metadata["workspace_prepared"] = True
            return

        workspace_path = os.path.join(context.worktrees_dir, work_item.id)
        branch_name = self._branch_name(context.run_id, work_item.id)

        work_item.workspace_path = workspace_path
        work_item.branch_name = branch_name
        work_item.metadata["workspace_strategy"] = "git-worktree"
        work_item.metadata["workspace_repo_root"] = context.repo_path

        if context.dry_run:
            work_item.metadata["workspace_prepared"] = False
            work_item.metadata["workspace_prepare_command"] = [
                "git",
                "-C",
                context.repo_path,
                "worktree",
                "add",
                "-b",
                branch_name,
                workspace_path,
                self._default_base_ref(),
            ]
            return

        repo_root = await self._git_repo_root(context.repo_path)
        base_ref = await self._git_base_ref(repo_root)
        os.makedirs(context.worktrees_dir, exist_ok=True)
        work_item.metadata["workspace_repo_root"] = repo_root

        if os.path.exists(workspace_path):
            raise RuntimeError(f"Workspace already exists: {workspace_path}")

        command = [
            "git",
            "-C",
            repo_root,
            "worktree",
            "add",
            "-b",
            branch_name,
            workspace_path,
            base_ref,
        ]
        await self._run(command)

        work_item.metadata["workspace_prepared"] = True
        work_item.metadata["workspace_prepare_command"] = command
        work_item.metadata["workspace_base_ref"] = base_ref

    async def cleanup(
        self,
        work_items: list[WorkItem],
        context: ExecutionContext,
        cleanup_enabled: bool,
        retain_failed_worktrees: bool,
        run_success: bool,
        run_has_failures: bool,
    ) -> None:
        for work_item in work_items:
            uses_isolated_workspace = (
                work_item.mode == ExecutionMode.CLI
                or (
                    work_item.mode == ExecutionMode.OPENCLAW
                    and bool(work_item.metadata.get("export_branch", False))
                )
            )
            if not uses_isolated_workspace:
                continue

            if not work_item.workspace_path:
                continue

            if work_item.metadata.get("workspace_strategy") in {"reuse-source-branch", "reuse-source-workspace"}:
                work_item.metadata["workspace_cleanup_status"] = "skipped_reused_branch"
                continue

            if not cleanup_enabled:
                work_item.metadata["workspace_cleanup_status"] = "disabled"
                continue

            if run_has_failures and not run_success and retain_failed_worktrees:
                work_item.metadata["workspace_cleanup_status"] = "retained_on_failure"
                continue

            repo_root = str(work_item.metadata.get("workspace_repo_root", context.repo_path))
            cleanup_commands = [
                ["git", "-C", repo_root, "worktree", "remove", "--force", work_item.workspace_path],
                ["git", "-C", repo_root, "branch", "-D", work_item.branch_name],
            ]
            work_item.metadata["workspace_cleanup_commands"] = cleanup_commands

            if context.dry_run:
                work_item.metadata["workspace_cleanup_status"] = "planned"
                continue

            try:
                await self._run(cleanup_commands[0])
            except RuntimeError as error:
                if not self._workspace_absent_error(str(error)):
                    raise
            try:
                await self._run(cleanup_commands[1])
            except RuntimeError as error:
                if not self._branch_absent_error(str(error)):
                    raise
            work_item.metadata["workspace_cleanup_status"] = "completed"

    async def _git_repo_root(self, repo_path: str) -> str:
        if repo_path in self._repo_root_cache:
            return self._repo_root_cache[repo_path]

        process = await asyncio.create_subprocess_exec(
            "git",
            "-C",
            repo_path,
            "rev-parse",
            "--show-toplevel",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            message = stderr.decode("utf-8", errors="replace").strip() or "Not a git repository."
            raise RuntimeError(message)

        repo_root = stdout.decode("utf-8", errors="replace").strip()
        self._repo_root_cache[repo_path] = repo_root
        return repo_root

    async def _git_base_ref(self, repo_root: str) -> str:
        if repo_root in self._base_ref_cache:
            return self._base_ref_cache[repo_root]

        command = [
            "git",
            "-C",
            repo_root,
            "rev-parse",
            "--abbrev-ref",
            "HEAD",
        ]
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await process.communicate()
        base_ref = stdout.decode("utf-8", errors="replace").strip() or self._default_base_ref()
        if base_ref == "HEAD":
            base_ref = self._default_base_ref()
        self._base_ref_cache[repo_root] = base_ref
        return base_ref

    @staticmethod
    async def _run(command: list[str]) -> None:
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await process.communicate()
        if process.returncode != 0:
            message = stderr.decode("utf-8", errors="replace").strip()
            raise RuntimeError(message or f"Command failed: {' '.join(command)}")

    @staticmethod
    def _branch_name(run_id: str, work_item_id: str) -> str:
        # Keep orchestration branches flat to avoid git ref file/dir conflicts.
        raw = f"openclaw-{run_id.lower()}-{work_item_id.lower()}"
        return re.sub(r"[^a-z0-9_-]+", "-", raw).strip("-")

    @staticmethod
    def _workspace_absent_error(message: str) -> bool:
        normalized = message.lower()
        return any(
            token in normalized
            for token in (
                "already absent",
                "not a working tree",
                "does not exist",
                "no such file or directory",
            )
        )

    @staticmethod
    def _branch_absent_error(message: str) -> bool:
        normalized = message.lower()
        return any(
            token in normalized
            for token in (
                "not found",
                "does not exist",
                "no such ref",
                "unknown branch",
            )
        )

    @staticmethod
    def _default_base_ref() -> str:
        return "main"
