# OpenClaw Working Memory

更新时间：2026-05-10

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
- `openclaw_v2/config.py`
- `openclaw_v2/webui/app.js`
- `openclaw_v2/executors/github.py`
- `openclaw_v2/executors/openclaw.py`
- `openclaw_v2/preflight.py`
- `openclaw_v2/orchestrator.py`
- `config_v2.yaml`
- `main_v2.py`
- `README.md`
- `tests/test_github_executor.py`
- `tests/test_web.py`
- `openclaw_v2/webui/index.html`
- `tests/test_webui_static.py`

## 最近进展

- 2026-05-06：`collect_review` 的 workflow 失败 / action_required / in-progress 状态现在会带出统一的 `github_failure_kind`、`github_retryable` 和 `github_recovery_hint`。
- 2026-05-06：GitHub review workflow 的恢复提示现在会回流到 run insights，并显示在 Web UI 的 bridge 文案、run summary、issue update 和 PR note 里。
- 2026-05-07：非 workflow 的 GitHub 失败现在也会汇总为 `github.latestFailure`，不再只靠 workflow 专属视图承载恢复提示。
- 2026-05-07：Web UI 的 Bridge state 和导出文案现在会优先显示最新 GitHub 失败的恢复路径，避免 `draft_pr` / `update_issue` / `dispatch_review` 失败被“pending”文案掩盖。
- 2026-05-07：GitHub bridge cards 现在即使拿不到 issue / PR / workflow 引用，也会为失败步骤保留 operator 卡片，并显示 step summary、failure kind 和 recovery hint。
- 2026-05-07：新增 `github_collect_review_resume` pipeline 和 `--workflow-run-ref`，可以直接回流一个已有 workflow run 的状态，不再额外触发 `dispatch_review`。
- 2026-05-07：`collect_review` resume 的 workflow run ref 现在会贯穿 plan、prompt、GitHub workflow_view 命令和 Web dashboard 任务提交。
- 2026-05-07：真实 live run `25504962543` 已验证 `github_collect_review_resume` 能直接收敛为 success。
- 2026-05-07：重新跑通 `github_collect_review_resume` live smoke，workflow run `25504962543` 仍然可直接收敛为 success。
- 2026-05-07：全量 Python 单测 221 项通过，`node --check openclaw_v2/webui/app.js` 通过。
- 2026-05-07：Web UI 的 Launch Pad 现在暴露 `workflow run ref` 输入，并会在 `github_collect_review_resume` 选中时把它带进 task payload 和 readiness gate，避免 resume 流程还要手动改请求体。
- 2026-05-07：Web UI 的 run compare 现在会显示左右 run 的最新 GitHub failure，以及 `latestFailureChanged` 差异，方便直接比较两次 run 的失败根因是否变化。
- 2026-05-07：Web UI 的 recent runs 列表现在也会显示每次 run 的最新 GitHub failure、失败摘要和 recovery 提示，不用先点进 run detail 或 compare 才能看出最近几次协作失败发生在哪里。
- 2026-05-07：Web UI 的 loaded run detail 和 artifact context 现在也会显示最新 GitHub failure 与 recovery，点开单次 run 后不再需要再切去 bridge 卡或复制文案才能看出当前协作阻塞点。
- 2026-05-07：真实 `github_bridge_smoke` live run 证明原来的 `collect_review` 轮询窗口太短；默认 polling 已从 12 秒提高到约 30 秒，并用真实 run `run-20260507T151929Z-5962a5` / workflow `25504962543` 验证同次 live run 可直接收敛为 success。
- 2026-05-08：Web UI run insights 新增 `usage` 聚合层，会从 `summary.json` 汇总 `openclaw_usage` / `openclaw_last_call_usage`，后续可以直接接到成本展示而不用改 summary 结构。
- 2026-05-08：Web UI 的 recent runs 和 run summary 现在也会显示 OpenClaw usage 汇总，token 量已经能直接在控制台里读出来，下一步可以再决定是否做金额换算或趋势图。
- 2026-05-08：Web UI 的 history compare 现在也会显示 OpenClaw usage delta，已经能直接看两次 run 的 token 消耗差异。
- 2026-05-08：Web UI 的 recent runs 现在也会显示相邻 run 的 OpenClaw usage trend，token 变化方向已经能在首页一眼看出来。
- 2026-05-08：Web UI 的 run summary / issue update / PR note copy 文本现在也会回流 OpenClaw usage 汇总，面板和桥接导出已经对齐。
- 2026-05-08：Preflight 现在会对 Claude-backed CLI profile 先跑 print-mode 探针；当前机器上的 live smoke 已因此在 triage 前直接暴露 `claude_local` 的认证/可用性问题，而不是等到后续 step 超时。
- 2026-05-08：Claude 预检失败提示现在会直接带出 `mission_control_openclaw_default` + `OPENCLAW_ASSIGN_IMPLEMENT_LOCAL=openclaw_builder` 的 OpenClaw fallback 路径，并补 triage 侧 `claude_router_isolated` 的隔离建议。
- 2026-05-08：在 `OPENCLAW_ASSIGN_IMPLEMENT_LOCAL=openclaw_builder` 下，`mission_control_openclaw_default` 已完整跑通 triage / implement / review live smoke，说明 OpenClaw 变体已经具备可用的本地闭环。
- 2026-05-09：当前机器上的 `mission_control_default --live` 仍会在 `claude_local` 认证超时处被挡住；后续 live 入口要继续显式切到 `mission_control_openclaw_default + OPENCLAW_ASSIGN_IMPLEMENT_LOCAL=openclaw_builder`，不要把默认主链误当成当前机器上的可用入口。
- 2026-05-09：即使 triage / review 改用 `claude_router_isolated`，当前机器上的 `claude_local_isolated` 也未登录；默认 live 仍不应再在 Claude 路径上继续耗时，实际可继续的入口还是 OpenClaw fallback。
- 2026-05-09：Claude CLI 的 isolated 失败提示现在也会直接指向 OpenClaw fallback，避免 triage / review 隔离看起来像还能单独救活默认 live。
- 2026-05-10：Web UI 的 readiness gate 和 health 面板现在会直接显示 preflight recovery hint，操作员不用再回到 CLI 日志里找 `mission_control_openclaw_default + OPENCLAW_ASSIGN_IMPLEMENT_LOCAL=openclaw_builder`。
- 2026-05-03：GitHub review workflow 的 conclusion 和 failed jobs 已回流到 Web UI 的 run summary、issue update 和 PR note 文案。
- 2026-05-03：GitHub review workflow failed jobs 的 run insights / UI helper / 回归测试已补齐，字符串形态的 failed jobs 也能正确显示。
- 2026-05-03：Web UI 健康面板在 channels 为空时保持 `warning`，不再误报 `passed`。
- 2026-05-03：Web UI 安全头已覆盖错误响应，不再只覆盖成功响应。

## 下一步候选

1. 继续稳定 `mission_control_default` 主链，优先做更多真实 GitHub run 验证，减少“本地成功但协作链路不可读”的情况。
2. Claude CLI 不可用时，优先把 live 路径切到已经验证过的 OpenClaw fallback，而不是继续把时间耗在默认 triage 超时上。
3. 基于 `mission_control_openclaw_default` 已跑通的结果，判断 OpenClaw 变体是否应该继续承担主力 live 基线，还是仅作为对照路径保留。
4. 继续收 GitHub bridge 的结果诊断和失败恢复，下一步优先考虑把默认主链的 `publish_branch -> draft_pr -> dispatch_review -> collect_review` 也做一次真实端到端验证，而不是只停留在 smoke pipeline。
5. 继续把 Web UI 作为本地主控台打磨，但避免把它做成独立产品面，而是服务 Mission Control 主线。
6. 在默认 pipeline 稳定前，不把 Hermes 扩到 `implement`，也不急着把 OpenClaw 提升为默认控制入口。

## 记录规则

- 只要出现实质性阶段推进，更新 `PROJECT_STATUS.md`。
- 只要当前焦点、目标文件或下一步判断变化，更新 `PROJECT_MEMORY.md`。
- 如果变更直接影响主线判断，两个文件都更新。
