from __future__ import annotations

import asyncio
import os

from ..config import ProfileConfig
from ..models import AgentResult, AgentType, ExecutionContext, TaskStatus, WorkItem, parse_control_output
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

    @staticmethod
    def _artifacts(
        work_item: WorkItem,
        workspace_path: str,
        exports_branch: bool,
        blocked_reason: str = "",
    ) -> dict[str, object]:
        artifacts: dict[str, object] = {
            "workspace_path": workspace_path,
            "branch_name": work_item.branch_name,
            "exports_branch": exports_branch,
            "source_branch": work_item.branch_name if exports_branch else "",
            "workspace_prepare_command": work_item.metadata.get("workspace_prepare_command", []),
        }
        if blocked_reason:
            artifacts["blocked_reason"] = blocked_reason
        return artifacts

    @staticmethod
    def _build_env(profile: ProfileConfig) -> dict[str, str]:
        env = os.environ.copy()
        for key in profile.unset_env:
            env.pop(key, None)
        return env

    @staticmethod
    async def _workspace_change_artifacts(workspace_path: str) -> dict[str, object]:
        process = await asyncio.create_subprocess_exec(
            "git",
            "-C",
            workspace_path,
            "status",
            "--porcelain",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await process.communicate()
        if process.returncode != 0:
            return {}

        raw_output = stdout.decode("utf-8", errors="replace")
        changed_paths = [line[3:] for line in raw_output.splitlines() if len(line) > 3]
        if not changed_paths:
            return {
                "workspace_has_changes": False,
                "workspace_changed_files": [],
                "noop_result": True,
            }
        return {
            "workspace_has_changes": True,
            "workspace_changed_files": changed_paths,
        }

    @staticmethod
    def _timeout_recovery_hint(work_item: WorkItem) -> str:
        hint = "Rerun the printed command manually to inspect whether the agent is hanging or waiting for input."
        if work_item.agent != AgentType.CLAUDE:
            return hint
        if work_item.id == "triage":
            return (
                "Verify Claude connectivity or custom ANTHROPIC_* settings. "
                "For triage, retry with `OPENCLAW_ASSIGN_TRIAGE_LOCAL=claude_router_isolated` "
                "to isolate ANTHROPIC_* env, or switch to `--pipeline mission_control_openclaw_triage`."
            )
        return (
            "Verify Claude connectivity or custom ANTHROPIC_* settings, then rerun the printed command manually."
        )

    @classmethod
    def _failure_artifacts(
        cls,
        work_item: WorkItem,
        stderr: str,
        *,
        timed_out: bool = False,
    ) -> dict[str, object]:
        stderr_text = stderr.strip()
        if timed_out:
            return {
                "cli_failure_kind": "timeout",
                "cli_recovery_hint": cls._timeout_recovery_hint(work_item),
            }

        if work_item.agent == AgentType.CLAUDE:
            lowered = stderr_text.lower()
            if "not logged in" in lowered or "/login" in lowered:
                return {
                    "cli_failure_kind": "auth_required",
                    "cli_recovery_hint": "Run `claude auth login` in the same shell, then retry the step.",
                }
            if "invalid bearer token" in lowered or "401" in lowered:
                hint = (
                    "Verify your `ANTHROPIC_AUTH_TOKEN` or remove invalid custom `ANTHROPIC_*` overrides."
                )
                if work_item.id == "triage":
                    hint += " For triage, `OPENCLAW_ASSIGN_TRIAGE_LOCAL=claude_router_isolated` is the safest comparison path."
                return {
                    "cli_failure_kind": "invalid_token",
                    "cli_recovery_hint": hint,
                }
            if "connection error" in lowered or "econnrefused" in lowered or ":3010" in lowered:
                hint = "Check your configured `ANTHROPIC_BASE_URL` or upstream proxy reachability."
                if work_item.id == "triage":
                    hint += " If the proxy is optional, retry with `OPENCLAW_ASSIGN_TRIAGE_LOCAL=claude_router_isolated`."
                return {
                    "cli_failure_kind": "connectivity_error",
                    "cli_recovery_hint": hint,
                }

        if work_item.agent == AgentType.CODEX:
            lowered = stderr_text.lower()
            if "usage limit" in lowered or "more access now" in lowered:
                return {
                    "cli_failure_kind": "usage_limit",
                    "cli_recovery_hint": (
                        "Codex is authenticated but the current account has hit its usage limit. "
                        "Retry after the reported reset time or request more access."
                    ),
                }

        return {
            "cli_failure_kind": "nonzero_exit",
            "cli_recovery_hint": "Inspect `stderr` and rerun the printed command manually if needed.",
        }

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
                stdout=rendered_prompt,
                exit_code=0,
                command=command,
                artifacts={
                    "workspace_path": workspace_path,
                    "branch_name": work_item.branch_name,
                    "exports_branch": bool(work_item.metadata.get("export_branch", False)),
                    "source_branch": work_item.branch_name if bool(work_item.metadata.get("export_branch", False)) else "",
                    "workspace_prepare_command": work_item.metadata.get("workspace_prepare_command", []),
                },
            )

        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=workspace_path,
            env=self._build_env(profile),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        timeout_seconds = max(0.0, float(self.app_config.runtime.cli_command_timeout_seconds))
        timed_out = False
        try:
            if timeout_seconds > 0:
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout_seconds)
            else:
                stdout, stderr = await process.communicate()
        except asyncio.TimeoutError:
            timed_out = True
            process.kill()
            stdout, stderr = await process.communicate()
        output = stdout.decode("utf-8", errors="replace").strip()
        error_output = stderr.decode("utf-8", errors="replace").strip()

        if timed_out:
            artifacts = self._artifacts(
                work_item,
                workspace_path,
                exports_branch=False,
            )
            artifacts["cli_timeout_seconds"] = timeout_seconds
            artifacts["cli_timed_out"] = True
            artifacts.update(self._failure_artifacts(work_item, error_output, timed_out=True))
            return AgentResult(
                work_item_id=work_item.id,
                profile=work_item.profile,
                agent=work_item.agent,
                mode=work_item.mode,
                status=TaskStatus.FAILED,
                summary=(
                    f"CLI task {work_item.title} timed out after {timeout_seconds} seconds."
                ),
                output=error_output or output,
                stdout=output,
                stderr=error_output,
                exit_code=process.returncode,
                command=command,
                artifacts=artifacts,
            )

        if process.returncode == 0:
            control_signal = parse_control_output(output)
            status = control_signal.status or TaskStatus.SUCCEEDED
            blocked_reason = control_signal.block_reason
            exports_branch = bool(work_item.metadata.get("export_branch", False)) and status == TaskStatus.SUCCEEDED
            cleaned_output = control_signal.cleaned_output or output
            artifacts = self._artifacts(
                work_item,
                workspace_path,
                exports_branch=exports_branch,
                blocked_reason=blocked_reason,
            )
            if status == TaskStatus.SUCCEEDED and bool(work_item.metadata.get("expects_file_changes", False)):
                artifacts.update(await self._workspace_change_artifacts(workspace_path))
            summary = (
                f"CLI task {work_item.title} blocked: {blocked_reason}"
                if status == TaskStatus.BLOCKED
                else f"CLI task {work_item.title} finished successfully."
            )
            if status == TaskStatus.SUCCEEDED and artifacts.get("noop_result"):
                summary = f"CLI task {work_item.title} finished successfully with no file changes required."
            return AgentResult(
                work_item_id=work_item.id,
                profile=work_item.profile,
                agent=work_item.agent,
                mode=work_item.mode,
                status=status,
                summary=summary,
                output=cleaned_output,
                stdout=output,
                stderr=error_output,
                exit_code=process.returncode,
                command=command,
                artifacts=artifacts,
            )

        result = AgentResult(
            work_item_id=work_item.id,
            profile=work_item.profile,
            agent=work_item.agent,
            mode=work_item.mode,
            status=TaskStatus.FAILED,
            summary=f"CLI task {work_item.title} failed with exit code {process.returncode}.",
            output=error_output or output,
            stdout=output,
            stderr=error_output,
            exit_code=process.returncode,
            command=command,
            artifacts=self._artifacts(
                work_item,
                workspace_path,
                exports_branch=bool(work_item.metadata.get("export_branch", False)),
            ),
        )
        result.artifacts.update(self._failure_artifacts(work_item, error_output))
        return result
