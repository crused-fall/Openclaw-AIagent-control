from __future__ import annotations

import json
import os
from dataclasses import asdict, is_dataclass
from enum import Enum
from typing import Any

from .models import AgentResult, ExecutionContext, PreflightReport, RunResult, WorkItem


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


class ArtifactStore:
    def __init__(self) -> None:
        self.prompts_dir_name = "prompts"
        self.results_dir_name = "results"
        self.metadata_dir_name = "metadata"
        self.workspaces_dir_name = "workspaces"
        self.logs_dir_name = "logs"

    def initialize_run(self, context: ExecutionContext, plan: list[WorkItem]) -> None:
        os.makedirs(context.artifacts_dir, exist_ok=True)
        os.makedirs(self._path(context, self.prompts_dir_name), exist_ok=True)
        os.makedirs(self._path(context, self.results_dir_name), exist_ok=True)
        os.makedirs(self._path(context, self.metadata_dir_name), exist_ok=True)
        os.makedirs(self._path(context, self.workspaces_dir_name), exist_ok=True)
        os.makedirs(self._path(context, self.logs_dir_name), exist_ok=True)

        self._write_json(self._path(context, "context.json"), context)
        self._write_json(self._path(context, "plan.json"), plan)

    def write_prompt(self, context: ExecutionContext, work_item: WorkItem, prompt: str) -> str:
        prompt_path = self._path(context, self.prompts_dir_name, f"{work_item.id}.txt")
        with open(prompt_path, "w", encoding="utf-8") as handle:
            handle.write(prompt)
            handle.write("\n")
        return prompt_path

    def write_workspace_manifest(self, context: ExecutionContext, work_item: WorkItem) -> str:
        payload = {
            "work_item_id": work_item.id,
            "workspace_path": work_item.workspace_path,
            "branch_name": work_item.branch_name,
            "mode": work_item.mode,
            "agent": work_item.agent,
            "metadata": work_item.metadata,
        }
        workspace_path = self._path(context, self.workspaces_dir_name, f"{work_item.id}.json")
        self._write_json(workspace_path, payload)
        return workspace_path

    def write_result(self, context: ExecutionContext, result: AgentResult) -> str:
        if result.stdout:
            stdout_path = self._path(context, self.logs_dir_name, f"{result.work_item_id}.stdout.txt")
            self._write_text(stdout_path, result.stdout)
            result.artifacts["stdout_path"] = stdout_path
        if result.stderr:
            stderr_path = self._path(context, self.logs_dir_name, f"{result.work_item_id}.stderr.txt")
            self._write_text(stderr_path, result.stderr)
            result.artifacts["stderr_path"] = stderr_path
        result_path = self._path(context, self.results_dir_name, f"{result.work_item_id}.json")
        self._write_json(result_path, result)
        return result_path

    def write_preflight_report(self, context: ExecutionContext, report: PreflightReport) -> str:
        report_path = self._path(context, self.metadata_dir_name, "preflight.json")
        self._write_json(report_path, report)
        return report_path

    def write_run_summary(self, run_result: RunResult) -> str:
        summary_path = os.path.join(run_result.artifacts_dir, "summary.json")
        self._write_json(summary_path, run_result)
        return summary_path

    @staticmethod
    def _path(context: ExecutionContext, *parts: str) -> str:
        return os.path.join(context.artifacts_dir, *parts)

    def _write_json(self, path: str, payload: Any) -> None:
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(_json_ready(payload), handle, ensure_ascii=False, indent=2)
            handle.write("\n")

    @staticmethod
    def _write_text(path: str, payload: str) -> None:
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(payload)
            if not payload.endswith("\n"):
                handle.write("\n")
