from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone

from .artifacts import ArtifactStore
from .config import AppConfig, resolve_runtime_path
from .executors import CLIExecutor, GitHubWorkflowExecutor
from .models import AgentResult, CheckStatus, ExecutionContext, ExecutionMode, RunResult, TaskStatus, WorkItem
from .planner import PipelinePlanner
from .preflight import PreflightRunner
from .worktree import WorktreeManager


class HybridOrchestrator:
    """Hybrid CLI + GitHub workflow orchestrator."""

    def __init__(self, config: AppConfig):
        self.config = config
        self.planner = PipelinePlanner(config)
        self.artifact_store = ArtifactStore()
        self.worktree_manager = WorktreeManager()
        self.preflight_runner = PreflightRunner(config)
        self.executors = {
            ExecutionMode.CLI: CLIExecutor(config),
            ExecutionMode.GITHUB: GitHubWorkflowExecutor(config),
        }

    @staticmethod
    def _make_run_id() -> str:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        return f"run-{timestamp}"

    def build_plan(self, selected_steps: list[str] | None = None) -> list[WorkItem]:
        return self.planner.build_plan(selected_steps=selected_steps)

    async def preflight(
        self,
        repo_path: str,
        selected_steps: list[str] | None = None,
    ):
        plan = self.build_plan(selected_steps=selected_steps)
        report = await self.preflight_runner.run(repo_path, plan)
        return plan, report

    @staticmethod
    def _dependency_summary(work_item: WorkItem, completed: dict[str, AgentResult]) -> str:
        if not work_item.depends_on:
            return ""

        lines = ["", "Dependency summaries:"]
        for dependency_id in work_item.depends_on:
            result = completed[dependency_id]
            lines.append(f"- {dependency_id}: {result.summary}")
            if result.output:
                lines.append(result.output)
        return "\n".join(lines).strip()

    @staticmethod
    def _collect_dependency_values(
        work_item: WorkItem,
        completed: dict[str, AgentResult],
    ) -> dict[str, str]:
        branches: list[str] = []
        issue_refs: list[str] = []
        pr_refs: list[str] = []
        source_branches: list[str] = []

        for dependency_id in work_item.depends_on:
            result = completed[dependency_id]
            branch = str(result.artifacts.get("branch_name", "")).strip()
            exports_branch = bool(result.artifacts.get("exports_branch", False))
            if branch and exports_branch:
                branches.append(branch)

            source_branch = str(result.artifacts.get("source_branch", "")).strip()
            if source_branch:
                source_branches.append(source_branch)

            issue_ref = str(
                result.artifacts.get("issue_number")
                or result.artifacts.get("issue_url")
                or ""
            ).strip()
            if issue_ref:
                issue_refs.append(issue_ref)

            pr_ref = str(
                result.artifacts.get("pr_number")
                or result.artifacts.get("pr_url")
                or ""
            ).strip()
            if pr_ref:
                pr_refs.append(pr_ref)

        return {
            "primary_branch_name": branches[0] if branches else "",
            "dependency_branches": ", ".join(branches),
            "source_branch": source_branches[0] if source_branches else (branches[0] if branches else ""),
            "primary_issue_ref": issue_refs[0] if issue_refs else "",
            "primary_pr_ref": pr_refs[0] if pr_refs else "",
        }

    def _render_prompt(
        self,
        work_item: WorkItem,
        context: ExecutionContext,
        completed: dict[str, AgentResult],
    ) -> str:
        dependency_summaries = self._dependency_summary(work_item, completed)
        dependency_values = self._collect_dependency_values(work_item, completed)
        values = {
            "run_id": context.run_id,
            "user_request": context.user_request,
            "repo_path": context.repo_path,
            "artifacts_dir": context.artifacts_dir,
            "workspace_path": work_item.workspace_path or context.repo_path,
            "branch_name": work_item.branch_name,
            "dependency_summaries": dependency_summaries,
            **dependency_values,
        }
        return work_item.prompt_template.format(**values).strip()

    async def _execute_ready_items(
        self,
        ready_items: list[WorkItem],
        context: ExecutionContext,
        completed: dict[str, AgentResult],
    ) -> list[AgentResult]:
        immediate_results: list[AgentResult] = []
        tasks = []
        for work_item in ready_items:
            try:
                work_item.metadata.update(self._collect_dependency_values(work_item, completed))
                await self.worktree_manager.prepare(work_item, context)
                self.artifact_store.write_workspace_manifest(context, work_item)
                profile = self.config.profiles[work_item.profile]
                rendered_prompt = self._render_prompt(work_item, context, completed)
                prompt_path = self.artifact_store.write_prompt(context, work_item, rendered_prompt)
                executor = self.executors[work_item.mode]
                work_item.status = TaskStatus.RUNNING
                work_item.metadata["prompt_path"] = prompt_path
                tasks.append(executor.execute(work_item, profile, context, rendered_prompt))
            except Exception as error:
                work_item.status = TaskStatus.FAILED
                immediate_results.append(
                    AgentResult(
                        work_item_id=work_item.id,
                        profile=work_item.profile,
                        agent=work_item.agent,
                        mode=work_item.mode,
                        status=TaskStatus.FAILED,
                        summary=f"Preparation failed for {work_item.title}: {error}",
                        artifacts={
                            "workspace_path": work_item.workspace_path,
                            "branch_name": work_item.branch_name,
                        },
                    )
                )
        if tasks:
            immediate_results.extend(await asyncio.gather(*tasks))
        return immediate_results

    async def run(
        self,
        user_request: str,
        repo_path: str,
        selected_steps: list[str] | None = None,
    ) -> RunResult:
        plan = self.build_plan(selected_steps=selected_steps)
        run_id = self._make_run_id()
        artifacts_root = resolve_runtime_path(repo_path, self.config.runtime.artifacts_dir)
        worktrees_root = resolve_runtime_path(repo_path, self.config.runtime.worktrees_dir)
        context = ExecutionContext(
            run_id=run_id,
            user_request=user_request,
            repo_path=repo_path,
            dry_run=self.config.runtime.dry_run,
            artifacts_dir=os.path.join(artifacts_root, run_id),
            worktrees_dir=os.path.join(worktrees_root, run_id),
        )
        self.artifact_store.initialize_run(context, plan)
        preflight_report = await self.preflight_runner.run(repo_path, plan)
        self.artifact_store.write_preflight_report(context, preflight_report)

        pending = {item.id: item for item in plan}
        completed: dict[str, AgentResult] = {}
        ordered_results: list[AgentResult] = []

        if not preflight_report.ok and not self.config.runtime.dry_run:
            for item in plan:
                item.status = TaskStatus.SKIPPED
                result = AgentResult(
                    work_item_id=item.id,
                    profile=item.profile,
                    agent=item.agent,
                    mode=item.mode,
                    status=TaskStatus.SKIPPED,
                    summary="Skipped because preflight checks failed.",
                    artifacts={"preflight_failed": True},
                )
                self.artifact_store.write_result(context, result)
                ordered_results.append(result)
            run_result = RunResult(
                run_id=context.run_id,
                plan=plan,
                results=ordered_results,
                success=False,
                artifacts_dir=context.artifacts_dir,
            )
            self.artifact_store.write_run_summary(run_result)
            return run_result

        while pending:
            ready_items = [
                item
                for item in pending.values()
                if all(
                    dependency_id in completed and completed[dependency_id].success
                    for dependency_id in item.depends_on
                )
            ]
            if not ready_items:
                blocked_results = []
                for item in pending.values():
                    item.status = TaskStatus.SKIPPED
                    result = AgentResult(
                        work_item_id=item.id,
                        profile=item.profile,
                        agent=item.agent,
                        mode=item.mode,
                        status=TaskStatus.SKIPPED,
                        summary="Skipped because one or more dependencies failed.",
                        artifacts={
                            "workspace_path": item.workspace_path,
                            "branch_name": item.branch_name,
                        },
                    )
                    self.artifact_store.write_result(context, result)
                    blocked_results.append(result)
                ordered_results.extend(blocked_results)
                break

            batch_results = await self._execute_ready_items(ready_items, context, completed)
            for result in batch_results:
                result.artifacts.setdefault(
                    "prompt_path",
                    pending[result.work_item_id].metadata.get("prompt_path", ""),
                )
                self.artifact_store.write_result(context, result)
                completed[result.work_item_id] = result
                ordered_results.append(result)
                pending[result.work_item_id].status = result.status
                pending.pop(result.work_item_id, None)

        run_result = RunResult(
            run_id=context.run_id,
            plan=plan,
            results=ordered_results,
            success=all(result.success for result in ordered_results if result.status != TaskStatus.SKIPPED),
            artifacts_dir=context.artifacts_dir,
        )
        await self.worktree_manager.cleanup(
            plan,
            context,
            cleanup_enabled=self.config.runtime.cleanup_worktrees,
            retain_failed_worktrees=self.config.runtime.retain_failed_worktrees,
            run_success=run_result.success,
        )
        for work_item in plan:
            self.artifact_store.write_workspace_manifest(context, work_item)
        self.artifact_store.write_run_summary(run_result)
        return run_result
