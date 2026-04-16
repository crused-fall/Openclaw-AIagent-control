from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import re
from typing import Any


class AgentType(str, Enum):
    CLAUDE = "claude"
    GEMINI = "gemini"
    CODEX = "codex"
    CURSOR = "cursor"
    OPENCLAW = "openclaw"
    HERMES = "hermes"
    COPILOT = "copilot"
    ANTIGRAVITY = "antigravity"
    SYSTEM = "system"


class ExecutionMode(str, Enum):
    CLI = "cli"
    GITHUB = "github"
    OPENCLAW = "openclaw"
    HERMES = "hermes"
    SYSTEM = "system"


class TaskStatus(str, Enum):
    PLANNED = "planned"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    BLOCKED = "blocked"
    FAILED = "failed"
    SKIPPED = "skipped"


class CheckStatus(str, Enum):
    PASSED = "passed"
    WARNING = "warning"
    FAILED = "failed"


@dataclass
class WorkItem:
    id: str
    title: str
    profile: str
    agent: AgentType
    mode: ExecutionMode
    prompt_template: str
    assignment: str = ""
    assignment_source: str = ""
    managed_agent: str = ""
    assignment_reason: str = ""
    fallback_used: bool = False
    fallback_chain: list[str] = field(default_factory=list)
    required_capabilities: list[str] = field(default_factory=list)
    assignment_candidates: list[str] = field(default_factory=list)
    assignment_attempts: list[str] = field(default_factory=list)
    planning_blocked_reason: str = ""
    depends_on: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    status: TaskStatus = TaskStatus.PLANNED
    workspace_path: str = ""
    branch_name: str = ""


@dataclass
class ExecutionContext:
    run_id: str
    user_request: str
    repo_path: str
    dry_run: bool
    artifacts_dir: str
    worktrees_dir: str


@dataclass
class AgentResult:
    work_item_id: str
    profile: str
    agent: AgentType
    mode: ExecutionMode
    status: TaskStatus
    summary: str
    output: str = ""
    stdout: str = ""
    stderr: str = ""
    exit_code: int | None = None
    command: list[str] = field(default_factory=list)
    artifacts: dict[str, Any] = field(default_factory=dict)

    @property
    def success(self) -> bool:
        return self.status == TaskStatus.SUCCEEDED


@dataclass
class RunResult:
    run_id: str
    plan: list[WorkItem]
    results: list[AgentResult]
    success: bool
    artifacts_dir: str = ""


@dataclass
class PreflightCheck:
    name: str
    status: CheckStatus
    message: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class PreflightReport:
    checks: list[PreflightCheck]

    @property
    def ok(self) -> bool:
        return all(check.status != CheckStatus.FAILED for check in self.checks)


@dataclass
class ControlSignal:
    status: TaskStatus | None = None
    block_reason: str = ""
    cleaned_output: str = ""


def parse_control_output(output: str) -> ControlSignal:
    status: TaskStatus | None = None
    block_reason = ""
    cleaned_lines: list[str] = []
    marker_pattern = re.compile(r"OPENCLAW_(STATUS|BLOCK_REASON)\s*:\s*(.+)", re.IGNORECASE)

    for line in output.splitlines():
        normalized_line = line.strip().strip("*`")
        match = marker_pattern.search(normalized_line)
        if not match:
            cleaned_lines.append(line)
            continue

        key = match.group(1).upper()
        value = match.group(2).strip().strip("*`")
        if key == "STATUS":
            normalized = value.lower()
            if normalized == "ready":
                status = TaskStatus.SUCCEEDED
            elif normalized == "blocked":
                status = TaskStatus.BLOCKED
        elif key == "BLOCK_REASON" and value:
            block_reason = value

    cleaned_output = "\n".join(cleaned_lines).strip()
    if status == TaskStatus.BLOCKED and not block_reason:
        block_reason = next((line.strip() for line in cleaned_lines if line.strip()), "")
    return ControlSignal(
        status=status,
        block_reason=block_reason,
        cleaned_output=cleaned_output,
    )
