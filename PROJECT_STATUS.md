# OpenClaw Project Status

更新时间：2026-05-13

## 当前记录入口

- `PROJECT_STATUS.md`：当前完成度、稳定基线、阻塞项
- `PROJECT_MEMORY.md`：当前主线目标、目标文件、下一步工作记忆
- `PROJECT_LOG.md`：完整项目日志与历史归档

## 项目完成度快照

> 这些百分比是按主线目标估算，不是按提交量统计。

| 方向 | 估算进展 | 当前状态 | 说明 |
| --- | ---: | --- | --- |
| v2 Mission Control 主骨架 | 90% | 稳定 | `main_v2.py` + `openclaw_v2/` 已成为真实主线 |
| 默认 pipeline 骨架 | 85% | 稳定但未完全收口 | `triage -> collect_review` 结构完整，dry-run / preflight / diagnose 能用 |
| GitHub 协作尾链 | 80% | 可用 | issue / PR / review workflow / resume / recovery hint 已落地 |
| Web UI control room | 88% | 可用 | 已覆盖 launch / history / compare / health / bridge / housekeeping / token stats |
| OpenClaw 本地接入 | 75% | 可用但非默认 | fallback live 路径可跑，尚未成为默认总控入口 |
| Hermes supervisor + recorder | 70% | 可用但受限 | triage / review / record_summary 可接，明确不承担 implement |
| 成本统计 / 自动 fallback / 更细 review-merge 阶段 | 35% | 未完成 | 属于当前主要剩余工作 |
| 整体项目完成度 | 78% | 接近收口 | 已接近“几乎完成”，但还没到默认主链稳定可发布 |

## 当前主线判断

- 项目已经从“多模型 API demo”转成“以 CLI + GitHub workflow 为中心的 Mission Control”。
- `openclaw.py` 仍保留，但只代表 v1 legacy；主线实现已经是 `main_v2.py` + `openclaw_v2/`。
- 当前最重要的不是再扩新 agent，而是把默认 `mission_control_default` 的 live 稳定性、GitHub 协作尾链复跑性和角色边界收口清楚。
- OpenClaw 当前已经是可靠 fallback 执行器，但还不是默认统一总控入口。

## 当前稳定基线

### 已完成并可复用的能力

- `main_v2.py` 统一入口、`--doctor-config`、`--diagnose-plan`、`--preflight-only`、`--web`
- assignment / managed-agent / capability / fallback 解析链
- `commit_changes` 显式 stage + implement worktree / branch 复用
- GitHub issue / PR / workflow / review workflow / resume / recovery hint 回流
- Web UI control room：launch pad、readiness gate、health、recent runs、history compare、GitHub bridge、housekeeping、token stats
- Web / history / cleanup / config / preflight / worktree 的大规模 race hardening
- Hermes `supervisor + recorder` 变体 pipeline
- OpenClaw fallback live 入口：`mission_control_openclaw_default + OPENCLAW_ASSIGN_IMPLEMENT_LOCAL=openclaw_builder`

### 当前机器上的已知事实

- `mission_control_default --live` 仍会在 `claude_local` 预检处被挡住。
- 当前可继续的本地 live 入口仍是 OpenClaw fallback，而不是默认 Claude 路径。
- `github_collect_review_resume` 与 `github_bridge_smoke` 已有真实成功记录。

## 当前阻塞项

1. 默认 `mission_control_default --live` 还没有在当前机器上形成稳定可复跑的完整闭环。
2. GitHub 协作尾链虽然已经可用，但还需要更多真实 end-to-end 验证来证明“失败可解释、恢复可继续、重复运行不飘”。
3. OpenClaw 与 Hermes 的最终角色边界虽然大方向已定，但“OpenClaw 何时升级成默认总控入口”还未决。
4. 成本统计、自动 fallback、更细 review / merge 审核阶段仍未完成。

## 已归档的阶段性工作

下列历史过程已经转存到 `PROJECT_LOG.md`，不再继续堆在当前状态文件里：

- 2026-03-14 ~ 2026-03-16：方向收敛和 v2 可行性判断
- 2026-03-27 ~ 2026-04-02：默认 pipeline 脊柱、worktree、commit/publish 约束
- 2026-04-16 ~ 2026-04-30：OpenClaw / Hermes / Web UI control room 扩展
- 2026-04-29 ~ 2026-05-03：Web / API / race / scope / safety hardening
- 2026-05-06 ~ 2026-05-07：GitHub recovery / resume / reviewer-facing 输出
- 2026-05-08 ~ 2026-05-12：usage 面板、Token Stats、Claude blocker 与 OpenClaw fallback 记录

## 下一阶段验收线

项目要进入“接近完成”的收口状态，至少还需要满足三条：

1. 默认 pipeline 能稳定复跑，或明确宣布 OpenClaw fallback 成为当前机器上的默认可运行入口。
2. GitHub 尾链在真实 workflow / issue / PR / review 场景下继续验证，且失败结果对人可读、可恢复。
3. Web UI 继续作为真实运营控制台，而不是只停留在演示面。
