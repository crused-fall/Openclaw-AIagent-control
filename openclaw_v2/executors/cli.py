from __future__ import annotations

import asyncio

from ..config import ProfileConfig
from ..models import AgentResult, ExecutionContext, TaskStatus, WorkItem
from .base import Executor


class CLIExecutor(Executor):
    """Run local CLI-based agents.

    The executor stays in dry-run mode by default. Once concrete agent CLIs are
    available, switch `runtime.dry_run` to false in config_v2.yaml.
    """

    @staticmethod
    def _render_command(template: list[str], prompt: str, context: ExecutionContext, work_item: WorkItem) -> list[str]:
        values = {
            "prompt": prompt,
            "repo_path": context.repo_path,
            "run_id": context.run_id,
            "artifacts_dir": context.artifacts_dir,
            "workspace_path": work_item.workspace_path or context.repo_path,
            "branch_name": work_item.branch_name,
        }
        return [token.format(**values) for token in template]

    async def execute(
        self,
        work_item: WorkItem,
        profile: ProfileConfig,
        context: ExecutionContext,
        rendered_prompt: str,
    ) -> AgentResult:
        if not profile.command:
            return AgentResult(
                work_item_id=work_item.id,
                profile=work_item.profile,
                agent=work_item.agent,
                mode=work_item.mode,
                status=TaskStatus.FAILED,
                summary="CLI profile has no command configured.",
            )

        command = self._render_command(profile.command, rendered_prompt, context, work_item)
        workspace_path = work_item.workspace_path or context.repo_path
        if context.dry_run:
            return AgentResult(
                work_item_id=work_item.id,
                profile=work_item.profile,
                agent=work_item.agent,
                mode=work_item.mode,
                status=TaskStatus.SUCCEEDED,
                summary=f"Dry-run only. Planned CLI command for {work_item.title}.",
                output=rendered_prompt,
                command=command,
                artifacts={
                    "workspace_path": workspace_path,
                    "branch_name": work_item.branch_name,
                    "exports_branch": bool(work_item.metadata.get("export_branch", False)),
                    "workspace_prepare_command": work_item.metadata.get("workspace_prepare_command", []),
                },
            )

        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=workspace_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        output = stdout.decode("utf-8", errors="replace").strip()
        error_output = stderr.decode("utf-8", errors="replace").strip()

        if process.returncode == 0:
            return AgentResult(
                work_item_id=work_item.id,
                profile=work_item.profile,
                agent=work_item.agent,
                mode=work_item.mode,
                status=TaskStatus.SUCCEEDED,
                summary=f"CLI task {work_item.title} finished successfully.",
                output=output,
                command=command,
                artifacts={
                    "workspace_path": workspace_path,
                    "branch_name": work_item.branch_name,
                    "exports_branch": bool(work_item.metadata.get("export_branch", False)),
                },
            )

        return AgentResult(
            work_item_id=work_item.id,
            profile=work_item.profile,
            agent=work_item.agent,
            mode=work_item.mode,
            status=TaskStatus.FAILED,
            summary=f"CLI task {work_item.title} failed with exit code {process.returncode}.",
            output=error_output or output,
            command=command,
            artifacts={
                "workspace_path": workspace_path,
                "branch_name": work_item.branch_name,
                "exports_branch": bool(work_item.metadata.get("export_branch", False)),
            },
        )
