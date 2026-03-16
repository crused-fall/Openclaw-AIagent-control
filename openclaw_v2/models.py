from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class AgentType(str, Enum):
    CLAUDE = "claude"
    CODEX = "codex"
    COPILOT = "copilot"
    ANTIGRAVITY = "antigravity"
    SYSTEM = "system"


class ExecutionMode(str, Enum):
    CLI = "cli"
    GITHUB = "github"


class TaskStatus(str, Enum):
    PLANNED = "planned"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
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
