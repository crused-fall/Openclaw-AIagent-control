#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import os

from openclaw_v2 import HybridOrchestrator, load_app_config


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


async def main() -> None:
    config = load_app_config("config_v2.yaml")
    orchestrator = HybridOrchestrator(config)

    print("OpenClaw v2 已启动，输入 'quit' 退出")
    print(f"当前模式: {'dry-run' if config.runtime.dry_run else 'live'}")
    print(f"当前 pipeline: {config.runtime.pipeline}\n")

    while True:
        user_input = input("用户: ").strip()
        if user_input.lower() in {"quit", "exit", "q"}:
            print("再见！")
            return

        if not user_input:
            continue

        result = await orchestrator.run(user_input, os.getcwd())
        _print_result(result)
        print("\n" + "-" * 60 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
