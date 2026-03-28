# AGENTS.md

This repository is no longer just a multi-model demo. Its main direction is a modified scheme-four Mission Control architecture built around CLI plus GitHub workflows.

## Project Overview

OpenClaw orchestrates multiple AI agents through layered execution:

- CLI / SDK local execution
- GitHub async collaboration
- review / supervision

The repository still contains a legacy v1 prototype in `openclaw.py`, but active work should treat `main_v2.py` and `openclaw_v2/` as the primary path.

## Architecture

### v1 legacy

- `openclaw.py`
- direct model API routing
- keyword-based task decomposition

### v2 mission control

- `main_v2.py`: control layer entrypoint
- `config_v2.yaml`: profiles / managed_agents / assignments / pipelines
- `planner.py`: pipeline planning
- `orchestrator.py`: dependency scheduling and result merging
- `executors/cli.py`: local agent layer
- `executors/openclaw.py`: local OpenClaw layer
- `executors/github.py`: GitHub layer
- `preflight.py`: supervision and environment checks
- `worktree.py`: isolated workspace management

## Default Pipeline

The default pipeline is `mission_control_default`:

- `triage`
- `implement`
- `review`
- `commit_changes`
- `publish_branch`
- `sync_issue`
- `update_issue`
- `draft_pr`
- `dispatch_review`
- `collect_review`

## Development Commands

```bash
pip install -r requirements.txt

python3 main_v2.py --list-steps
python3 main_v2.py --list-managed-agents
python3 main_v2.py --diagnose-plan --steps triage,implement
python3 main_v2.py --doctor-config
python3 main_v2.py --preflight-only --steps review,commit_changes,publish_branch
python3 main_v2.py --request "修复登录页报错" --steps triage,implement,review
python3 main_v2.py --live --request "修复登录页报错" --steps triage,implement,review
```

Legacy commands still exist:

```bash
python3 demo.py
python3 openclaw.py
python3 test_setup.py
```

## Working Rules

- Preserve `openclaw.py` as legacy unless explicitly asked to remove it.
- Prefer improving `openclaw_v2/` rather than extending the v1 keyword router.
- Treat blocked requests as first-class outcomes, not generic failures.
- Treat controlled agents as registry entries, not hard-coded step owners.
- Prefer diagnosing `assignment -> managed_agent -> profile` resolution before changing pipeline structure.
- Live mode should not silently rely on fallback managed agents unless config explicitly opts in.
- Keep the main architecture centered on local CLI execution plus GitHub workflow collaboration.
