# OpenClaw Working Memory

更新时间：2026-05-13

## 主目标

- 把项目稳定为以 `main_v2.py` + `openclaw_v2/` 为主线的 modified scheme-four Mission Control。
- 持续稳定默认 `mission_control_default` pipeline，而不是只维护演示型变体路径。
- 保持 Hermes 只承担 `supervisor + recorder`，不接 `implement`。
- 逐步把 OpenClaw 从变体执行器推进到更接近默认控制入口的位置，但前提是默认 pipeline 足够稳定。

## 当前主线

- 继续稳定 GitHub bridge 的结果诊断、review 透传、失败恢复和 reviewer-facing 输出。
- 继续稳定本地 Web UI control room 的安全边界、可观测性和 run/history/health 协作体验。
- 继续校准 `config_v2.yaml` 中的 pipeline、assignment、managed agent 和 preflight 约束。
- 继续把默认主链和 OpenClaw fallback 的角色边界记录清楚，避免误把当前 fallback 成功当成默认主链已经完成。

## 当前目标文件

- `PROJECT_STATUS.md`
- `PROJECT_MEMORY.md`
- `PROJECT_LOG.md`
- `config_v2.yaml`
- `main_v2.py`
- `README.md`
- `openclaw_v2/web.py`
- `openclaw_v2/config.py`
- `openclaw_v2/preflight.py`
- `openclaw_v2/orchestrator.py`
- `openclaw_v2/executors/github.py`
- `openclaw_v2/executors/openclaw.py`
- `openclaw_v2/webui/index.html`
- `openclaw_v2/webui/app.js`
- `tests/test_github_executor.py`
- `tests/test_web.py`
- `tests/test_webui_static.py`

## 本次归档结果

- 历史阶段过程已从当前状态文件里抽离，集中归档到 `PROJECT_LOG.md`。
- `PROJECT_STATUS.md` 已收敛回“完成度 + 稳定基线 + 阻塞项”。
- `PROJECT_MEMORY.md` 只保留当前主线目标、目标文件和下一步判断，不再承担完整历史日志职责。

## 当前关键事实

- 当前机器上的 `mission_control_default --live` 仍会被 `claude_local` 预检挡住。
- 当前机器上的可继续 live 入口仍是 `mission_control_openclaw_default + OPENCLAW_ASSIGN_IMPLEMENT_LOCAL=openclaw_builder`。
- `github_collect_review_resume`、`github_bridge_smoke`、Web UI Token Stats、GitHub recovery surfaces 都已经进入“已做完并应保持稳定”的归档区域。
- 后续新增工作不应再把 `PROJECT_STATUS.md` / `PROJECT_MEMORY.md` 堆成长流水账；阶段事实优先沉到 `PROJECT_LOG.md`。

## 下一步候选

1. 继续做默认 `mission_control_default` 的真实 live 验证，判断它在当前机器上究竟是“待修复默认入口”还是“需要正式让位给 OpenClaw fallback”。
2. 继续做 GitHub 尾链的真实 end-to-end 验证，尤其是 `publish_branch -> draft_pr -> dispatch_review -> collect_review` 的重复运行稳定性。
3. 若默认主链短期内仍受 Claude 环境限制，就把 OpenClaw fallback 的 operator 语义、文档和 UI 提示进一步固定下来。
4. 在默认 pipeline 稳定前，不扩 Hermes 到 `implement`，也不急着把 OpenClaw 命名上提前升级成已经完成的默认总控。

## 记录规则

- 只要出现实质性阶段推进，更新 `PROJECT_STATUS.md`。
- 只要当前焦点、目标文件或下一步判断变化，更新 `PROJECT_MEMORY.md`。
- 只要需要保留完整历史过程、验证序列或阶段归档，更新 `PROJECT_LOG.md`。
- 如果变更直接影响主线判断，三个文件可以一起更新，但 `PROJECT_STATUS.md` / `PROJECT_MEMORY.md` 不再堆长流水账。
