# CLAUDE.md

This repository is evolving toward a modified scheme-four Mission Control architecture centered on CLI plus GitHub workflows.

## Project Overview

OpenClaw is a multi-agent orchestration project with two tracks:

- `openclaw.py`: legacy direct-model prototype
- `main_v2.py` + `openclaw_v2/`: layered Mission Control framework

The current target is:

1. CLI / SDK first
2. GitHub workflow second
3. review / supervision above both execution layers

## Key Modules

- `main_v2.py`
- `config_v2.yaml`
- `openclaw_v2/config.py`
- `openclaw_v2/models.py`
- `openclaw_v2/planner.py`
- `openclaw_v2/orchestrator.py`
- `openclaw_v2/preflight.py`
- `openclaw_v2/worktree.py`
- `openclaw_v2/executors/cli.py`
- `openclaw_v2/executors/openclaw.py`
- `openclaw_v2/executors/github.py`

## Current Expectations

- Keep v1 runnable, but do not treat it as the main architecture.
- Use `mission_control_default` as the main pipeline.
- Expect the default GitHub tail to include `dispatch_review` and `collect_review`.
- Preserve explicit `blocked` handling for request / repository mismatches.
- Treat `Claude / Gemini / Codex / Cursor / OpenClaw` as managed agents selected by `assignments`, not fixed step owners.
- Use `--diagnose-plan` and `--doctor-config` before changing assignment wiring.
- Keep the primary build focused on local CLI execution plus GitHub collaboration.

## Useful Commands

```bash
python3 main_v2.py --list-steps
python3 main_v2.py --list-managed-agents
python3 main_v2.py --diagnose-plan --steps triage,implement
python3 main_v2.py --doctor-config
python3 main_v2.py --preflight-only
python3 main_v2.py --request "修复登录页报错" --steps triage,implement,review
python3 main_v2.py --live --request "修复登录页报错" --steps triage,implement,review
```
