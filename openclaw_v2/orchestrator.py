from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from typing import Callable

from .artifacts import ArtifactStore
from .config import AppConfig, resolve_runtime_path
from .executors import CLIExecutor, GitHubWorkflowExecutor, OpenClawExecutor
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
            ExecutionMode.OPENCLAW: OpenClawExecutor(config),
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
        workflow_refs: list[str] = []
        source_branches: list[str] = []

        for dependency_id in work_item.depends_on:
            result = completed.get(dependency_id)
            if result is None:
                continue
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

            workflow_ref = str(
                result.artifacts.get("workflow_run_id")
                or result.artifacts.get("workflow_run_url")
                or ""
            ).strip()
            if workflow_ref:
                workflow_refs.append(workflow_ref)

        return {
            "primary_branch_name": branches[0] if branches else (source_branches[0] if source_branches else ""),
            "dependency_branches": ", ".join(branches),
            "source_branch": source_branches[0] if source_branches else (branches[0] if branches else ""),
            "primary_issue_ref": issue_refs[0] if issue_refs else "",
            "primary_pr_ref": pr_refs[0] if pr_refs else "",
            "primary_workflow_run_ref": workflow_refs[0] if workflow_refs else "",
        }

    @staticmethod
    def _dependency_outcomes(
        work_item: WorkItem,
        completed: dict[str, AgentResult],
    ) -> dict[str, list[dict[str, str]]]:
        blocked: list[dict[str, str]] = []
        failed: list[dict[str, str]] = []
        skipped: list[dict[str, str]] = []

        for dependency_id in work_item.depends_on:
            if dependency_id not in completed:
                continue

            result = completed[dependency_id]
            entry = {
                "id": dependency_id,
                "status": result.status.value,
                "summary": result.summary,
            }
            blocked_reason = str(result.artifacts.get("blocked_reason", "")).strip()
            if blocked_reason:
                entry["blocked_reason"] = blocked_reason

            if result.status == TaskStatus.BLOCKED:
                blocked.append(entry)
            elif result.status == TaskStatus.FAILED:
                failed.append(entry)
            elif result.status == TaskStatus.SKIPPED:
                skipped.append(entry)

        return {
            "blocked": blocked,
            "failed": failed,
            "skipped": skipped,
        }

    @classmethod
    def _blocked_summary(cls, work_item: WorkItem, completed: dict[str, AgentResult]) -> str:
        dependency_outcomes = cls._dependency_outcomes(work_item, completed)
        blocked = dependency_outcomes["blocked"]
        failed = dependency_outcomes["failed"]
        skipped = dependency_outcomes["skipped"]

        if blocked:
            if len(blocked) == 1:
                dependency = blocked[0]
                blocked_reason = dependency.get("blocked_reason", "")
                if blocked_reason:
                    return f"Skipped because dependency {dependency['id']} was blocked: {blocked_reason}"
                return f"Skipped because dependency {dependency['id']} was blocked and needs clarification."
            blocked_ids = ", ".join(item["id"] for item in blocked)
            return f"Skipped because dependencies were blocked and need clarification: {blocked_ids}"

        if failed:
            if len(failed) == 1:
                dependency = failed[0]
                return f"Skipped because dependency {dependency['id']} failed: {dependency['summary']}"
            failed_ids = ", ".join(item["id"] for item in failed)
            return f"Skipped because dependencies failed: {failed_ids}"

        if skipped:
            if len(skipped) == 1:
                dependency = skipped[0]
                return f"Skipped because dependency {dependency['id']} was skipped: {dependency['summary']}"
            skipped_ids = ", ".join(item["id"] for item in skipped)
            return f"Skipped because dependencies were skipped: {skipped_ids}"

        return "Skipped because one or more dependencies did not succeed."

    @staticmethod
    def _noop_dependencies(
        work_item: WorkItem,
        completed: dict[str, AgentResult],
    ) -> list[dict[str, str]]:
        noops: list[dict[str, str]] = []
        for dependency_id in work_item.depends_on:
            result = completed.get(dependency_id)
            if result is None or not result.artifacts.get("noop_result"):
                continue
            noops.append(
                {
                    "id": dependency_id,
                    "summary": result.summary,
                }
            )
        return noops

    @classmethod
    def _noop_summary(cls, work_item: WorkItem, completed: dict[str, AgentResult]) -> str:
        noops = cls._noop_dependencies(work_item, completed)
        if not noops:
            return ""
        if len(noops) == 1:
            dependency = noops[0]
            return f"Skipped because dependency {dependency['id']} produced no file changes."
        noop_ids = ", ".join(item["id"] for item in noops)
        return f"Skipped because dependencies produced no file changes: {noop_ids}"

    @staticmethod
    def _allow_noop_skipped_dependencies(work_item: WorkItem) -> set[str]:
        configured = work_item.metadata.get("allow_noop_skipped_dependencies", [])
        if not isinstance(configured, list):
            return set()
        return {str(item).strip() for item in configured if str(item).strip()}

    @classmethod
    def _required_dependency_branch_reason(
        cls,
        work_item: WorkItem,
        completed: dict[str, AgentResult],
    ) -> str:
        if not bool(work_item.metadata.get("requires_dependency_branch", False)):
            return ""
        dependency_values = cls._collect_dependency_values(work_item, completed)
        if str(dependency_values.get("source_branch", "")).strip():
            return ""
        if str(dependency_values.get("primary_branch_name", "")).strip():
            return ""
        return (
            f"Step {work_item.title} requires an exported dependency branch, "
            "but no dependency produced one."
        )

    @classmethod
    def _dependency_is_satisfied(
        cls,
        work_item: WorkItem,
        dependency_id: str,
        completed: dict[str, AgentResult],
    ) -> bool:
        result = completed.get(dependency_id)
        if result is None:
            return False
        if result.success:
            return True
        allowed_noop_dependencies = cls._allow_noop_skipped_dependencies(work_item)
        return (
            dependency_id in allowed_noop_dependencies
            and result.status == TaskStatus.SKIPPED
            and bool(result.artifacts.get("noop_dependencies"))
        )

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

    @staticmethod
    def _trace_artifacts(work_item: WorkItem) -> dict[str, object]:
        artifacts: dict[str, object] = {
            "assignment": work_item.assignment,
            "assignment_source": work_item.assignment_source,
            "managed_agent": work_item.managed_agent,
            "assignment_reason": work_item.assignment_reason,
            "fallback_used": work_item.fallback_used,
            "fallback_chain": work_item.fallback_chain,
            "required_capabilities": work_item.required_capabilities,
            "assignment_candidates": work_item.assignment_candidates,
            "assignment_attempts": work_item.assignment_attempts,
            "planning_blocked_reason": work_item.planning_blocked_reason,
        }
        return {key: value for key, value in artifacts.items() if value not in ("", [], False)}

    @staticmethod
    def _emit_progress(
        progress_callback: Callable[[str], None] | None,
        message: str,
    ) -> None:
        if progress_callback is not None:
            progress_callback(message)

    async def _execute_ready_items(
        self,
        ready_items: list[WorkItem],
        context: ExecutionContext,
        completed: dict[str, AgentResult],
        progress_callback: Callable[[str], None] | None = None,
    ) -> list[AgentResult]:
        immediate_results: list[AgentResult] = []
        tasks = []
        for work_item in ready_items:
            if work_item.planning_blocked_reason:
                work_item.status = TaskStatus.BLOCKED
                immediate_results.append(
                    AgentResult(
                        work_item_id=work_item.id,
                        profile=work_item.profile,
                        agent=work_item.agent,
                        mode=work_item.mode,
                        status=TaskStatus.BLOCKED,
                        summary=(
                            f"Step {work_item.title} was blocked before execution: "
                            f"{work_item.planning_blocked_reason}"
                        ),
                        artifacts={
                            "blocked_reason": work_item.planning_blocked_reason,
                            "workspace_path": work_item.workspace_path,
                            "branch_name": work_item.branch_name,
                            **self._trace_artifacts(work_item),
                        },
                    )
                )
                self._emit_progress(
                    progress_callback,
                    f"step:block {work_item.id} -> {work_item.planning_blocked_reason}",
                )
                continue
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
                self._emit_progress(
                    progress_callback,
                    (
                        f"step:start {work_item.id} "
                        f"[{work_item.mode.value}/{work_item.agent.value}] "
                        f"workspace={work_item.workspace_path or context.repo_path}"
                    ),
                )
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
                            **self._trace_artifacts(work_item),
                        },
                    )
                )
                self._emit_progress(
                    progress_callback,
                    f"step:fail {work_item.id} -> Preparation failed: {error}",
                )
        if tasks:
            immediate_results.extend(await asyncio.gather(*tasks))
        return immediate_results

    async def run(
        self,
        user_request: str,
        repo_path: str,
        selected_steps: list[str] | None = None,
        progress_callback: Callable[[str], None] | None = None,
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
        self._emit_progress(progress_callback, "preflight:start")
        preflight_report = await self.preflight_runner.run(repo_path, plan)
        self._emit_progress(
            progress_callback,
            f"preflight:{'ok' if preflight_report.ok else 'failed'}",
        )
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
                    artifacts={"preflight_failed": True, **self._trace_artifacts(item)},
                )
                self.artifact_store.write_result(context, result)
                ordered_results.append(result)
                self._emit_progress(
                    progress_callback,
                    f"step:skip {item.id} -> preflight checks failed",
                )
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
            noop_blocked_items = [
                item
                for item in pending.values()
                if bool(item.metadata.get("requires_workspace_changes", False))
                and self._noop_dependencies(item, completed)
            ]
            if noop_blocked_items:
                skipped_results = []
                for item in noop_blocked_items:
                    item.status = TaskStatus.SKIPPED
                    result = AgentResult(
                        work_item_id=item.id,
                        profile=item.profile,
                        agent=item.agent,
                        mode=item.mode,
                        status=TaskStatus.SKIPPED,
                        summary=self._noop_summary(item, completed),
                        artifacts={
                            "workspace_path": item.workspace_path,
                            "branch_name": item.branch_name,
                            **self._collect_dependency_values(item, completed),
                            "noop_dependencies": self._noop_dependencies(item, completed),
                            **self._trace_artifacts(item),
                        },
                    )
                    self.artifact_store.write_result(context, result)
                    completed[item.id] = result
                    skipped_results.append(result)
                    pending.pop(item.id, None)
                    self._emit_progress(
                        progress_callback,
                        f"step:skip {item.id} -> dependency produced no file changes",
                    )
                ordered_results.extend(skipped_results)
                continue

            branch_blocked_items = [
                item
                for item in pending.values()
                if all(
                    self._dependency_is_satisfied(item, dependency_id, completed)
                    for dependency_id in item.depends_on
                )
                and self._required_dependency_branch_reason(item, completed)
            ]
            if branch_blocked_items:
                blocked_results = []
                for item in branch_blocked_items:
                    blocked_reason = self._required_dependency_branch_reason(item, completed)
                    item.status = TaskStatus.BLOCKED
                    result = AgentResult(
                        work_item_id=item.id,
                        profile=item.profile,
                        agent=item.agent,
                        mode=item.mode,
                        status=TaskStatus.BLOCKED,
                        summary=f"Blocked because {blocked_reason}",
                        artifacts={
                            "workspace_path": item.workspace_path,
                            "branch_name": item.branch_name,
                            "blocked_reason": blocked_reason,
                            "dependency_outcomes": self._dependency_outcomes(item, completed),
                            **self._trace_artifacts(item),
                        },
                    )
                    self.artifact_store.write_result(context, result)
                    completed[item.id] = result
                    blocked_results.append(result)
                    pending.pop(item.id, None)
                    self._emit_progress(
                        progress_callback,
                        f"step:block {item.id} -> {blocked_reason}",
                    )
                ordered_results.extend(blocked_results)
                continue

            ready_items = [
                item
                for item in pending.values()
                if all(
                    self._dependency_is_satisfied(item, dependency_id, completed)
                    for dependency_id in item.depends_on
                )
            ]
            if not ready_items:
                blocked_results = []
                for item in list(pending.values()):
                    item.status = TaskStatus.SKIPPED
                    result = AgentResult(
                        work_item_id=item.id,
                        profile=item.profile,
                        agent=item.agent,
                        mode=item.mode,
                        status=TaskStatus.SKIPPED,
                        summary=self._blocked_summary(item, completed),
                        artifacts={
                            "workspace_path": item.workspace_path,
                            "branch_name": item.branch_name,
                            "dependency_outcomes": self._dependency_outcomes(item, completed),
                            **self._trace_artifacts(item),
                        },
                    )
                    self.artifact_store.write_result(context, result)
                    completed[item.id] = result
                    blocked_results.append(result)
                    pending.pop(item.id, None)
                ordered_results.extend(blocked_results)
                break

            batch_results = await self._execute_ready_items(
                ready_items,
                context,
                completed,
                progress_callback=progress_callback,
            )
            for result in batch_results:
                result.artifacts.update(self._trace_artifacts(pending[result.work_item_id]))
                result.artifacts.setdefault(
                    "prompt_path",
                    pending[result.work_item_id].metadata.get("prompt_path", ""),
                )
                self.artifact_store.write_result(context, result)
                completed[result.work_item_id] = result
                ordered_results.append(result)
                pending[result.work_item_id].status = result.status
                self._emit_progress(
                    progress_callback,
                    f"step:done {result.work_item_id} -> {result.status.value}",
                )
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
            run_has_failures=any(result.status == TaskStatus.FAILED for result in ordered_results),
        )
        for work_item in plan:
            self.artifact_store.write_workspace_manifest(context, work_item)
        self.artifact_store.write_run_summary(run_result)
        return run_result
