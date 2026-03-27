#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import os
from typing import Any

from openclaw_v2 import HybridOrchestrator, load_app_config
from openclaw_v2.config import diagnose_app_config
from openclaw_v2.models import PreflightReport, TaskStatus


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="OpenClaw v2 hybrid orchestrator")
    parser.add_argument("--config", default="config_v2.yaml", help="Path to config file.")
    parser.add_argument("--pipeline", help="Override runtime.pipeline from config.")
    parser.add_argument("--repo-path", default=os.getcwd(), help="Repository path to operate on.")
    parser.add_argument("--request", help="Run one request non-interactively and exit.")
    parser.add_argument(
        "--steps",
        help="Comma-separated step ids to run. Dependencies are included automatically.",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Run in live mode. Overrides config.runtime.dry_run=false.",
    )
    parser.add_argument(
        "--list-steps",
        action="store_true",
        help="Print the effective step plan and exit.",
    )
    parser.add_argument(
        "--preflight-only",
        action="store_true",
        help="Run preflight checks for the selected plan and exit.",
    )
    parser.add_argument(
        "--list-managed-agents",
        action="store_true",
        help="Print managed-agent registry and effective assignments, then exit.",
    )
    parser.add_argument(
        "--diagnose-plan",
        action="store_true",
        help="Print detailed per-step resolution diagnostics for the selected plan, then exit.",
    )
    parser.add_argument(
        "--doctor-config",
        action="store_true",
        help="Validate config references across profiles, managed_agents, assignments, and pipelines, then exit.",
    )
    return parser.parse_args()


def _print_dependency_outcomes(artifacts: dict[str, Any]) -> None:
    dependency_outcomes = artifacts.get("dependency_outcomes")
    if not isinstance(dependency_outcomes, dict):
        return

    blocked = dependency_outcomes.get("blocked", [])
    failed = dependency_outcomes.get("failed", [])
    skipped = dependency_outcomes.get("skipped", [])
    noop_dependencies = artifacts.get("noop_dependencies", [])

    for item in blocked:
        dependency_id = item.get("id", "unknown")
        blocked_reason = item.get("blocked_reason") or item.get("summary", "")
        print(f"  blocked_dependency: {dependency_id} -> {blocked_reason}")

    for item in failed:
        dependency_id = item.get("id", "unknown")
        summary = item.get("summary", "")
        print(f"  failed_dependency: {dependency_id} -> {summary}")

    for item in skipped:
        dependency_id = item.get("id", "unknown")
        summary = item.get("summary", "")
        print(f"  skipped_dependency: {dependency_id} -> {summary}")

    for item in noop_dependencies:
        dependency_id = item.get("id", "unknown")
        summary = item.get("summary", "")
        print(f"  noop_dependency: {dependency_id} -> {summary}")


def _print_github_artifacts(artifacts: dict[str, Any]) -> None:
    keys = [
        "repo",
        "repo_source",
        "action",
        "source_branch",
        "issue_number",
        "issue_url",
        "pr_number",
        "pr_url",
        "workflow_name",
        "workflow_ref",
        "workflow_run_id",
        "workflow_run_url",
        "workflow_status",
        "workflow_conclusion",
        "workflow_head_branch",
        "workflow_run_attempt",
        "workflow_run_number",
        "workflow_poll_attempt_count",
        "workflow_job_count",
        "workflow_failed_job_count",
        "workflow_failed_jobs",
        "github_attempt_count",
        "github_retried",
        "github_label_fallback_used",
        "github_requested_labels",
        "github_ignored_labels",
        "github_failure_kind",
        "github_retryable",
        "github_recovery_hint",
        "github_error",
    ]
    printed = False
    for key in keys:
        value = artifacts.get(key)
        if key in artifacts and value is not None and value != "":
            if not printed:
                print("  github:")
                printed = True
            print(f"    {key}: {value}")


def _print_stderr(stderr: str) -> None:
    text = stderr.strip()
    if not text:
        return
    print("  stderr:")
    for line in text.splitlines()[:8]:
        print(f"    {line}")
    if len(text.splitlines()) > 8:
        print("    ...")


def _print_highlights(result) -> None:
    first_blocked = next(
        (
            item
            for item in result.results
            if item.status == TaskStatus.BLOCKED
            or item.artifacts.get("blocked_reason")
            or item.artifacts.get("planning_blocked_reason")
        ),
        None,
    )
    fallback_items = [
        item
        for item in result.results
        if item.artifacts.get("fallback_used") and item.artifacts.get("managed_agent")
    ]
    if not first_blocked and not fallback_items:
        return

    print("\nHighlights:")
    if first_blocked:
        blocked_reason = (
            first_blocked.artifacts.get("blocked_reason")
            or first_blocked.artifacts.get("planning_blocked_reason")
            or first_blocked.summary
        )
        print(f"- first_blocked: {first_blocked.work_item_id} -> {blocked_reason}")
    for item in fallback_items:
        print(
            f"- fallback_used: {item.work_item_id} -> "
            f"{item.artifacts.get('managed_agent', 'unknown')}"
        )


def _print_result(result) -> None:
    print(f"\nRun ID: {result.run_id}")
    print(f"Success: {result.success}")
    print(f"Artifacts: {result.artifacts_dir}")
    _print_highlights(result)
    print("\nPlan:")
    for item in result.plan:
        workspace = f" workspace={item.workspace_path}" if item.workspace_path else ""
        assignment = f" assignment={item.assignment}" if item.assignment else ""
        managed_agent = f" managed_agent={item.managed_agent}" if item.managed_agent else ""
        fallback = " fallback_used=true" if item.fallback_used else ""
        print(f"- {item.id} [{item.mode.value}/{item.agent.value}] {item.title}{assignment}{managed_agent}{fallback}{workspace}")
        if item.assignment_reason:
            print(f"  assignment_reason: {item.assignment_reason}")
        if item.planning_blocked_reason:
            print(f"  planning_blocked_reason: {item.planning_blocked_reason}")

    print("\nResults:")
    for item in result.results:
        print(f"- {item.work_item_id}: {item.status.value} -> {item.summary}")
        if item.artifacts.get("managed_agent"):
            trace = f"  managed_agent: {item.artifacts['managed_agent']}"
            if item.artifacts.get("assignment"):
                trace += f" assignment={item.artifacts['assignment']}"
            if item.artifacts.get("fallback_used"):
                trace += " fallback_used=true"
            print(trace)
        if item.artifacts.get("assignment_reason"):
            print(f"  assignment_reason: {item.artifacts['assignment_reason']}")
        if item.artifacts.get("planning_blocked_reason"):
            print(f"  planning_blocked_reason: {item.artifacts['planning_blocked_reason']}")
        blocked_reason = item.artifacts.get("blocked_reason")
        if blocked_reason:
            print(f"  blocked_reason: {blocked_reason}")
        if item.artifacts.get("cli_timed_out"):
            print("  cli_timed_out: true")
        if "cli_timeout_seconds" in item.artifacts:
            print(f"  cli_timeout_seconds: {item.artifacts['cli_timeout_seconds']}")
        if item.artifacts.get("noop_result"):
            print("  noop_result: true")
        if "workspace_has_changes" in item.artifacts:
            print(f"  workspace_has_changes: {item.artifacts['workspace_has_changes']}")
        if item.artifacts.get("workspace_changed_files"):
            print(f"  workspace_changed_files: {item.artifacts['workspace_changed_files']}")
        if item.artifacts.get("cli_failure_kind"):
            print(f"  cli_failure_kind: {item.artifacts['cli_failure_kind']}")
        if item.artifacts.get("cli_recovery_hint"):
            print(f"  cli_recovery_hint: {item.artifacts['cli_recovery_hint']}")
        _print_github_artifacts(item.artifacts)
        _print_dependency_outcomes(item.artifacts)
        if item.command:
            print(f"  command: {' '.join(item.command)}")
        if item.artifacts.get("workspace_path"):
            print(f"  workspace: {item.artifacts['workspace_path']}")
        if item.exit_code is not None:
            print(f"  exit_code: {item.exit_code}")
        _print_stderr(item.stderr)


def _print_plan(plan) -> None:
    print("\nPlan:")
    for item in plan:
        depends = f" depends_on={','.join(item.depends_on)}" if item.depends_on else ""
        assignment = f" assignment={item.assignment}" if item.assignment else ""
        managed_agent = f" managed_agent={item.managed_agent}" if item.managed_agent else ""
        fallback = " fallback_used=true" if item.fallback_used else ""
        print(f"- {item.id} [{item.mode.value}/{item.agent.value}] {item.title}{assignment}{managed_agent}{fallback}{depends}")
        if item.assignment_reason:
            print(f"  assignment_reason: {item.assignment_reason}")
        if item.planning_blocked_reason:
            print(f"  planning_blocked_reason: {item.planning_blocked_reason}")


def _print_plan_diagnostics(plan) -> None:
    print("\nPlan Diagnostics:")
    for item in plan:
        print(f"- {item.id}")
        print(f"  title: {item.title}")
        print(f"  mode: {item.mode.value}")
        print(f"  agent: {item.agent.value}")
        print(f"  profile: {item.profile or '-'}")
        if item.assignment:
            print(f"  assignment: {item.assignment}")
        if item.assignment_source:
            print(f"  assignment_source: {item.assignment_source}")
        if item.managed_agent:
            print(f"  managed_agent: {item.managed_agent}")
        if item.required_capabilities:
            print(f"  required_capabilities: {', '.join(item.required_capabilities)}")
        if item.assignment_candidates:
            print(f"  assignment_candidates: {', '.join(item.assignment_candidates)}")
        if item.assignment_attempts:
            print(f"  assignment_attempts: {'; '.join(item.assignment_attempts)}")
        if item.fallback_chain:
            print(f"  fallback_chain: {', '.join(item.fallback_chain)}")
        if item.fallback_used:
            print("  fallback_used: true")
        if item.depends_on:
            print(f"  depends_on: {', '.join(item.depends_on)}")
        if item.assignment_reason:
            print(f"  assignment_reason: {item.assignment_reason}")
        if item.planning_blocked_reason:
            print(f"  planning_blocked_reason: {item.planning_blocked_reason}")


def _print_managed_agents(config, plan) -> None:
    print("\nManaged Agents:")
    for name, item in sorted(config.managed_agents.items()):
        capabilities = ",".join(item.capabilities) if item.capabilities else "-"
        state = "enabled" if item.enabled else "disabled"
        print(
            f"- {name} [{item.kind.value}] profile={item.profile} manager={item.manager} "
            f"state={state} capabilities={capabilities}"
        )

    if config.assignments:
        print("\nAssignments:")
        for name, item in sorted(config.assignments.items()):
            fallback = f" fallback={','.join(item.fallback)}" if item.fallback else ""
            capabilities = (
                f" required_capabilities={','.join(item.required_capabilities)}"
                if item.required_capabilities
                else ""
            )
            print(f"- {name}: agent={item.agent} manager={item.manager}{capabilities}{fallback}")

    if plan:
        _print_plan(plan)


def _print_preflight(artifacts_dir: str) -> None:
    preflight_path = os.path.join(artifacts_dir, "metadata", "preflight.json")
    if not os.path.exists(preflight_path):
        return

    with open(preflight_path, "r", encoding="utf-8") as handle:
        report = json.load(handle)

    print("\nPreflight:")
    for check in report.get("checks", []):
        print(f"- {check['status']}: {check['name']} -> {check['message']}")


def _print_preflight_report(report) -> None:
    print("\nPreflight:")
    for check in report.checks:
        print(f"- {check.status.value}: {check.name} -> {check.message}")


def _validate_live_policy(
    orchestrator: HybridOrchestrator,
    selected_steps: list[str] | None,
    require_step_selection: bool,
    allow_fallback_in_live: bool,
    allowed_live_steps: list[str],
) -> None:
    if require_step_selection and not selected_steps:
        raise SystemExit(
            "Live mode requires --steps. "
            "Example: --live --steps triage,implement,publish_branch --request '...'"
        )

    effective_plan = orchestrator.build_plan(selected_steps=selected_steps)
    allowed_set = set(allowed_live_steps)
    disallowed = [item.id for item in effective_plan if item.id not in allowed_set]
    if disallowed:
        raise SystemExit(
            "Live mode blocked by allowed_live_steps policy. "
            f"Disallowed steps: {', '.join(disallowed)}. "
            f"Allowed steps: {', '.join(allowed_live_steps)}"
        )

    if not allow_fallback_in_live:
        fallback_items = [item for item in effective_plan if item.fallback_used]
        if fallback_items:
            details = ", ".join(
                f"{item.id} -> {item.managed_agent or 'unknown'}"
                for item in fallback_items
            )
            raise SystemExit(
                "Live mode blocked because one or more steps resolved through fallback managed agents. "
                f"Steps: {details}. "
                "Review the assignment registry or set runtime.allow_fallback_in_live=true to opt in."
            )


async def _run_once(
    orchestrator: HybridOrchestrator,
    repo_path: str,
    user_input: str,
    selected_steps: list[str] | None,
) -> None:
    result = await orchestrator.run(
        user_input,
        repo_path,
        selected_steps=selected_steps,
        progress_callback=lambda message: print(f"[progress] {message}", flush=True),
    )
    _print_preflight(result.artifacts_dir)
    _print_result(result)
    print("\n" + "-" * 60 + "\n")


async def main() -> None:
    args = _parse_args()
    config = load_app_config(args.config)
    if args.pipeline:
        config.runtime.pipeline = args.pipeline
    if args.live:
        config.runtime.dry_run = False

    orchestrator = HybridOrchestrator(config)
    selected_steps = [step.strip() for step in args.steps.split(",") if step.strip()] if args.steps else None
    repo_path = os.path.abspath(args.repo_path)
    is_inspection_mode = any(
        [
            args.list_steps,
            args.preflight_only,
            args.list_managed_agents,
            args.diagnose_plan,
            args.doctor_config,
        ]
    )

    if args.live and not (args.list_steps or args.preflight_only):
        _validate_live_policy(
            orchestrator,
            selected_steps=selected_steps,
            require_step_selection=config.runtime.require_step_selection_for_live,
            allow_fallback_in_live=config.runtime.allow_fallback_in_live,
            allowed_live_steps=config.runtime.allowed_live_steps,
        )

    if not is_inspection_mode:
        print("OpenClaw v2 已启动，输入 'quit' 退出")
        print(f"当前模式: {'dry-run' if config.runtime.dry_run else 'live'}")
        print(f"当前 pipeline: {config.runtime.pipeline}")
        print(f"当前仓库: {repo_path}")
        if selected_steps:
            print(f"当前 steps: {', '.join(selected_steps)}")
        print("")

    if args.doctor_config:
        _print_preflight_report(PreflightReport(checks=diagnose_app_config(config)))
        return

    if args.list_steps or args.preflight_only or args.diagnose_plan:
        plan, report = await orchestrator.preflight(repo_path, selected_steps=selected_steps)
        if args.diagnose_plan:
            _print_plan_diagnostics(plan)
        else:
            _print_plan(plan)
        if args.preflight_only or args.diagnose_plan:
            _print_preflight_report(report)
        return

    if args.list_managed_agents:
        plan = orchestrator.build_plan(selected_steps=selected_steps)
        _print_managed_agents(config, plan)
        return

    if args.request:
        await _run_once(orchestrator, repo_path, args.request, selected_steps)
        return

    while True:
        user_input = input("用户: ").strip()
        if user_input.lower() in {"quit", "exit", "q"}:
            print("再见！")
            return

        if not user_input:
            continue

        await _run_once(orchestrator, repo_path, user_input, selected_steps)


if __name__ == "__main__":
    asyncio.run(main())
