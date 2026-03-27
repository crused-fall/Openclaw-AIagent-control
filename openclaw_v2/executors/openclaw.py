from __future__ import annotations

import asyncio
import json
import os
from typing import Any

from ..config import ProfileConfig
from ..models import AgentResult, ExecutionContext, TaskStatus, WorkItem, parse_control_output
from .base import Executor


class OpenClawExecutor(Executor):
    """Run local OpenClaw agent turns and normalize their JSON output."""

    @staticmethod
    def _prepare_prompt(
        rendered_prompt: str,
        context: ExecutionContext,
        work_item: WorkItem,
    ) -> str:
        target_path = work_item.workspace_path or context.repo_path
        agents_path = os.path.join(target_path, "AGENTS.md")
        lines = [
            "OpenClaw repository handoff:",
            f"- Primary repository path: {target_path}",
            f"- If `{agents_path}` exists, read it before acting.",
            "- Use absolute paths under the repository path when you inspect or modify files.",
            "- Treat the repository path as the task target even if your OpenClaw workspace differs.",
            "",
            rendered_prompt.strip(),
        ]
        return "\n".join(lines).strip()

    @staticmethod
    def _build_command(profile: ProfileConfig, rendered_prompt: str) -> list[str]:
        agent_id = profile.openclaw_agent_id.strip()
        if not agent_id:
            raise ValueError("openclaw_agent_id is required for OpenClaw profiles.")

        command = ["openclaw"]
        if profile.openclaw_profile.strip():
            command.extend(["--profile", profile.openclaw_profile.strip()])
        command.extend(["agent"])
        if profile.openclaw_local:
            command.append("--local")
        command.extend(["--json", "--agent", agent_id, "--message", rendered_prompt])
        return command

    @staticmethod
    def _join_payload_text(payloads: list[dict[str, Any]]) -> str:
        texts = [
            str(payload.get("text", "")).strip()
            for payload in payloads
            if isinstance(payload, dict) and str(payload.get("text", "")).strip()
        ]
        return "\n\n".join(texts).strip()

    @classmethod
    def _parse_response_output(cls, output: str) -> tuple[str, dict[str, object]]:
        data = json.loads(output or "{}")
        if not isinstance(data, dict):
            raise ValueError("OpenClaw response is not a JSON object.")

        payloads = data.get("payloads", [])
        if not isinstance(payloads, list):
            raise ValueError("OpenClaw response payloads must be a list.")

        response_text = cls._join_payload_text(payloads)
        meta = data.get("meta", {})
        if not isinstance(meta, dict):
            meta = {}

        agent_meta = meta.get("agentMeta", {})
        if not isinstance(agent_meta, dict):
            agent_meta = {}

        system_prompt_report = meta.get("systemPromptReport", {})
        if not isinstance(system_prompt_report, dict):
            system_prompt_report = {}

        artifacts: dict[str, object] = {
            "openclaw_payload_count": len(payloads),
            "openclaw_session_id": str(agent_meta.get("sessionId", "")).strip(),
            "openclaw_provider": str(agent_meta.get("provider", "")).strip(),
            "openclaw_model": str(agent_meta.get("model", "")).strip(),
            "openclaw_usage": agent_meta.get("usage", {}),
            "openclaw_last_call_usage": agent_meta.get("lastCallUsage", {}),
            "openclaw_session_key": str(system_prompt_report.get("sessionKey", "")).strip(),
            "workspace_path": str(system_prompt_report.get("workspaceDir", "")).strip(),
            "stop_reason": str(data.get("stopReason") or meta.get("stopReason") or "").strip(),
        }
        return response_text, artifacts

    async def execute(
        self,
        work_item: WorkItem,
        profile: ProfileConfig,
        context: ExecutionContext,
        rendered_prompt: str,
    ) -> AgentResult:
        prepared_prompt = self._prepare_prompt(rendered_prompt, context, work_item)
        try:
            command = self._build_command(profile, prepared_prompt)
        except ValueError as error:
            return AgentResult(
                work_item_id=work_item.id,
                profile=work_item.profile,
                agent=work_item.agent,
                mode=work_item.mode,
                status=TaskStatus.FAILED,
                summary=str(error),
            )

        if context.dry_run:
            return AgentResult(
                work_item_id=work_item.id,
                profile=work_item.profile,
                agent=work_item.agent,
                mode=work_item.mode,
                status=TaskStatus.SUCCEEDED,
                summary=f"Dry-run only. Planned OpenClaw command for {work_item.title}.",
                output=prepared_prompt,
                stdout=prepared_prompt,
                exit_code=0,
                command=command,
                artifacts={
                    "openclaw_agent_id": profile.openclaw_agent_id,
                    "openclaw_profile": profile.openclaw_profile,
                    "workspace_path": work_item.workspace_path or context.repo_path,
                    "openclaw_prepared_prompt": prepared_prompt,
                },
            )

        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=context.repo_path,
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
                summary=f"OpenClaw task {work_item.title} failed with exit code {process.returncode}.",
                output=error_output or output,
                stdout=output,
                stderr=error_output,
                exit_code=process.returncode,
                command=command,
                artifacts={"openclaw_agent_id": profile.openclaw_agent_id},
            )

        try:
            response_text, artifacts = self._parse_response_output(output)
        except (json.JSONDecodeError, ValueError) as error:
            return AgentResult(
                work_item_id=work_item.id,
                profile=work_item.profile,
                agent=work_item.agent,
                mode=work_item.mode,
                status=TaskStatus.FAILED,
                summary=f"OpenClaw task {work_item.title} returned invalid JSON: {error}",
                output=output,
                stdout=output,
                stderr=error_output,
                exit_code=process.returncode,
                command=command,
                artifacts={"openclaw_agent_id": profile.openclaw_agent_id},
            )

        control_signal = parse_control_output(response_text)
        status = control_signal.status or TaskStatus.SUCCEEDED
        cleaned_output = control_signal.cleaned_output or response_text
        blocked_reason = control_signal.block_reason
        artifacts["openclaw_agent_id"] = profile.openclaw_agent_id
        artifacts["openclaw_profile"] = profile.openclaw_profile
        artifacts["openclaw_prepared_prompt"] = prepared_prompt
        if blocked_reason:
            artifacts["blocked_reason"] = blocked_reason

        return AgentResult(
            work_item_id=work_item.id,
            profile=work_item.profile,
            agent=work_item.agent,
            mode=work_item.mode,
            status=status,
            summary=(
                f"OpenClaw task {work_item.title} blocked: {blocked_reason}"
                if status == TaskStatus.BLOCKED
                else f"OpenClaw task {work_item.title} finished successfully."
            ),
            output=cleaned_output,
            stdout=output,
            stderr=error_output,
            exit_code=process.returncode,
            command=command,
            artifacts=artifacts,
        )
