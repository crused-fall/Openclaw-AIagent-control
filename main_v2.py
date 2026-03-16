#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import os

from openclaw_v2 import HybridOrchestrator, load_app_config


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
    return parser.parse_args()


def _print_result(result) -> None:
    print(f"\nRun ID: {result.run_id}")
    print(f"Success: {result.success}")
    print(f"Artifacts: {result.artifacts_dir}")
    print("\nPlan:")
    for item in result.plan:
        workspace = f" workspace={item.workspace_path}" if item.workspace_path else ""
        print(f"- {item.id} [{item.mode.value}/{item.agent.value}] {item.title}{workspace}")

    print("\nResults:")
    for item in result.results:
        print(f"- {item.work_item_id}: {item.status.value} -> {item.summary}")
        if item.command:
            print(f"  command: {' '.join(item.command)}")
        if item.artifacts.get("workspace_path"):
            print(f"  workspace: {item.artifacts['workspace_path']}")
        if item.exit_code is not None:
            print(f"  exit_code: {item.exit_code}")


def _print_plan(plan) -> None:
    print("\nPlan:")
    for item in plan:
        depends = f" depends_on={','.join(item.depends_on)}" if item.depends_on else ""
        print(f"- {item.id} [{item.mode.value}/{item.agent.value}] {item.title}{depends}")


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


async def _run_once(
    orchestrator: HybridOrchestrator,
    repo_path: str,
    user_input: str,
    selected_steps: list[str] | None,
) -> None:
    result = await orchestrator.run(user_input, repo_path, selected_steps=selected_steps)
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

    if args.live and not (args.list_steps or args.preflight_only):
        _validate_live_policy(
            orchestrator,
            selected_steps=selected_steps,
            require_step_selection=config.runtime.require_step_selection_for_live,
            allowed_live_steps=config.runtime.allowed_live_steps,
        )

    print("OpenClaw v2 已启动，输入 'quit' 退出")
    print(f"当前模式: {'dry-run' if config.runtime.dry_run else 'live'}")
    print(f"当前 pipeline: {config.runtime.pipeline}")
    print(f"当前仓库: {repo_path}")
    if selected_steps:
        print(f"当前 steps: {', '.join(selected_steps)}")
    print("")

    if args.list_steps or args.preflight_only:
        plan, report = await orchestrator.preflight(repo_path, selected_steps=selected_steps)
        _print_plan(plan)
        _print_preflight_report(report)
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
