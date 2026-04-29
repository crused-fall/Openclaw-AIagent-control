from __future__ import annotations

import asyncio
import os
import re

from ..config import ProfileConfig
from ..models import AgentResult, ExecutionContext, TaskStatus, WorkItem, parse_control_output
from .base import Executor


class HermesExecutor(Executor):
    """Run local Hermes turns for supervision and recording steps."""

    _SESSION_PATTERNS = [
        re.compile(r"^Resume this session with:\s*$", re.IGNORECASE),
        re.compile(r"^hermes\s+(?:chat\s+)?(?:--resume|-r)\s+\S+.*$", re.IGNORECASE),
        re.compile(r"^Session:\s*(\S+)\s*$", re.IGNORECASE),
        re.compile(r"^Duration:\s+.+$", re.IGNORECASE),
        re.compile(r"^Messages:\s+.+$", re.IGNORECASE),
    ]

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
    def _prepare_prompt(
        rendered_prompt: str,
        context: ExecutionContext,
        work_item: WorkItem,
    ) -> str:
        target_path = work_item.workspace_path or context.repo_path
        agents_path = os.path.join(target_path, "AGENTS.md")
        lines = [
            "Hermes repository handoff:",
            f"- Primary repository path: {target_path}",
            f"- If `{agents_path}` exists, read it before acting.",
            "- Use absolute paths under the repository path when you inspect files.",
            "- Do not edit files unless the task explicitly asks for implementation.",
            "",
            rendered_prompt.strip(),
        ]
        return "\n".join(lines).strip()

    @staticmethod
    def _csv(values: list[str]) -> str:
        return ",".join(value.strip() for value in values if value.strip())

    @classmethod
    def _build_command(cls, profile: ProfileConfig, prepared_prompt: str) -> list[str]:
        command = [
            "hermes",
            "chat",
            "-q",
            prepared_prompt,
            "-Q",
            "--source",
            profile.hermes_source.strip() or "tool",
        ]
        provider = profile.hermes_provider.strip()
        if provider:
            command.extend(["--provider", provider])

        model = profile.hermes_model.strip()
        if model:
            command.extend(["--model", model])

        toolsets = cls._csv(profile.hermes_toolsets)
        if toolsets:
            command.extend(["--toolsets", toolsets])

        skills = cls._csv(profile.hermes_skills)
        if skills:
            command.extend(["--skills", skills])

        if profile.hermes_max_turns > 0:
            command.extend(["--max-turns", str(int(profile.hermes_max_turns))])

        if profile.hermes_yolo:
            command.append("--yolo")

        return command

    @classmethod
    def _strip_session_footer(cls, output: str) -> tuple[str, str]:
        lines = output.splitlines()
        tail = len(lines)
        while tail > 0 and not lines[tail - 1].strip():
            tail -= 1

        session_id = ""
        start = tail
        while start > 0:
            stripped = lines[start - 1].strip()
            if not stripped and start < tail:
                start -= 1
                continue

            matched = False
            for pattern in cls._SESSION_PATTERNS:
                match = pattern.match(stripped)
                if not match:
                    continue
                matched = True
                if stripped.lower().startswith("session:"):
                    session_id = match.group(1).strip()
                start -= 1
                break

            if not matched:
                break

        cleaned_output = "\n".join(lines[:start]).strip()
        if not cleaned_output:
            cleaned_output = output.strip()
        return cleaned_output, session_id

    async def execute(
        self,
        work_item: WorkItem,
        profile: ProfileConfig,
        context: ExecutionContext,
        rendered_prompt: str,
    ) -> AgentResult:
        prepared_prompt = self._prepare_prompt(rendered_prompt, context, work_item)
        command = self._build_command(profile, prepared_prompt)
        workspace_path = work_item.workspace_path or context.repo_path
        artifacts = self._artifacts(
            work_item,
            workspace_path,
            exports_branch=bool(work_item.metadata.get("export_branch", False)),
        )
        artifacts.update(
            {
                "hermes_provider": profile.hermes_provider,
                "hermes_model": profile.hermes_model,
                "hermes_toolsets": list(profile.hermes_toolsets),
                "hermes_skills": list(profile.hermes_skills),
                "hermes_source": profile.hermes_source,
                "hermes_max_turns": profile.hermes_max_turns,
                "hermes_yolo": profile.hermes_yolo,
                "hermes_prepared_prompt": prepared_prompt,
            }
        )

        if context.dry_run:
            return AgentResult(
                work_item_id=work_item.id,
                profile=work_item.profile,
                agent=work_item.agent,
                mode=work_item.mode,
                status=TaskStatus.SUCCEEDED,
                summary=f"Dry-run only. Planned Hermes command for {work_item.title}.",
                output=prepared_prompt,
                stdout=prepared_prompt,
                exit_code=0,
                command=command,
                artifacts=artifacts,
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

        if process.returncode != 0:
            return AgentResult(
                work_item_id=work_item.id,
                profile=work_item.profile,
                agent=work_item.agent,
                mode=work_item.mode,
                status=TaskStatus.FAILED,
                summary=f"Hermes task {work_item.title} failed with exit code {process.returncode}.",
                output=error_output or output,
                stdout=output,
                stderr=error_output,
                exit_code=process.returncode,
                command=command,
                artifacts=artifacts,
            )

        cleaned_stdout, session_id = self._strip_session_footer(output)
        if session_id:
            artifacts["hermes_session_id"] = session_id

        control_signal = parse_control_output(cleaned_stdout)
        status = control_signal.status or TaskStatus.SUCCEEDED
        cleaned_output = control_signal.cleaned_output or cleaned_stdout
        blocked_reason = control_signal.block_reason
        if blocked_reason:
            artifacts["blocked_reason"] = blocked_reason

        summary = (
            f"Hermes task {work_item.title} blocked: {blocked_reason}"
            if status == TaskStatus.BLOCKED
            else f"Hermes task {work_item.title} finished successfully."
        )

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
