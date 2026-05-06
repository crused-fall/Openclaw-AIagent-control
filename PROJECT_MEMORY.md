# OpenClaw Working Memory

更新时间：2026-05-06

## 主目标

- 把项目稳定为以 `main_v2.py` + `openclaw_v2/` 为主线的 modified scheme-four Mission Control。
- 持续稳定默认 `mission_control_default` pipeline，而不是只维护演示型变体路径。
- 保持 Hermes 只承担 `supervisor + recorder`，不接 `implement`。
- 逐步把 OpenClaw 从变体执行器推进到更接近默认控制入口的位置，但前提是默认 pipeline 足够稳定。

## 当前主线

- 稳定 GitHub bridge 的结果诊断、review 透传、失败恢复和 reviewer-facing 输出。
- 稳定本地 Web UI control room 的安全边界、可观测性和 run/history/health 协作体验。
- 持续校准 `config_v2.yaml` 中的 pipeline、assignment、managed agent 和 preflight 约束。

## 当前目标文件

- `PROJECT_STATUS.md`
- `PROJECT_MEMORY.md`
- `config_v2.yaml`
- `main_v2.py`
- `openclaw_v2/web.py`
- `openclaw_v2/webui/app.js`
- `openclaw_v2/executors/github.py`
- `openclaw_v2/executors/openclaw.py`
- `openclaw_v2/preflight.py`
- `openclaw_v2/orchestrator.py`
- `tests/test_github_executor.py`
- `tests/test_web.py`
- `tests/test_webui_static.py`

## 最近进展

- 2026-05-06：`collect_review` 的 workflow 失败 / action_required / in-progress 状态现在会带出统一的 `github_failure_kind`、`github_retryable` 和 `github_recovery_hint`。
- 2026-05-06：GitHub review workflow 的恢复提示现在会回流到 run insights，并显示在 Web UI 的 bridge 文案、run summary、issue update 和 PR note 里。
- 2026-05-03：GitHub review workflow 的 conclusion 和 failed jobs 已回流到 Web UI 的 run summary、issue update 和 PR note 文案。
- 2026-05-03：GitHub review workflow failed jobs 的 run insights / UI helper / 回归测试已补齐，字符串形态的 failed jobs 也能正确显示。
- 2026-05-03：Web UI 健康面板在 channels 为空时保持 `warning`，不再误报 `passed`。
- 2026-05-03：Web UI 安全头已覆盖错误响应，不再只覆盖成功响应。

## 下一步候选

1. 继续收 GitHub bridge 的 review 结果诊断和失败恢复，尤其是把 workflow failure 与 CLI-level GitHub failure 的恢复路径继续统一。
2. 继续稳定 `mission_control_default` 主链，减少“本地成功但协作链路不可读”的情况。
3. 继续把 Web UI 作为本地主控台打磨，但避免把它做成独立产品面，而是服务 Mission Control 主线。
4. 在默认 pipeline 稳定前，不把 Hermes 扩到 `implement`，也不急着把 OpenClaw 提升为默认控制入口。

## 记录规则

- 只要出现实质性阶段推进，更新 `PROJECT_STATUS.md`。
- 只要当前焦点、目标文件或下一步判断变化，更新 `PROJECT_MEMORY.md`。
- 如果变更直接影响主线判断，两个文件都更新。
