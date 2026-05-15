# OpenClaw Project Log

更新时间：2026-05-13

## 用途

这份文件用于归档 `Openclaw-AIagent-control` 之前已经做过的阶段工作，把原本分散在 `PROJECT_STATUS.md` 和 `PROJECT_MEMORY.md` 里的历史过程整理成长期日志。

当前三份项目跟踪文件的分工是：

- `PROJECT_STATUS.md`：当前完成度、稳定基线、阻塞项
- `PROJECT_MEMORY.md`：当前主线目标、目标文件、下一步工作记忆
- `PROJECT_LOG.md`：完整项目日志、阶段归档、历史验证记录

## 当前项目结论

- 项目主线已经明确切到 `main_v2.py` + `openclaw_v2/` 的 modified scheme-four Mission Control。
- `openclaw.py` 仍保留为 v1 legacy，但不再代表主线推进方向。
- GitHub tail-chain、Web UI control room、OpenClaw fallback live 路径、Hermes supervisor/recorder 这些关键子模块都已经做成可用基线。
- 当前最大的未完成项不是“再加新功能”，而是把默认 `mission_control_default` 的 live 可用性、GitHub 协作尾链复跑稳定性，以及最终角色边界收口到可发布状态。
- 当前机器上的默认 live 仍会被 `claude_local` 预检挡住；实际可继续的本地 live 入口仍是 `mission_control_openclaw_default + OPENCLAW_ASSIGN_IMPLEMENT_LOCAL=openclaw_builder`。

## 项目进展总览

> 这些百分比是按主线目标完成度估算，不是按提交数统计。

| 方向 | 估算进展 | 当前判断 |
| --- | ---: | --- |
| v2 Mission Control 主骨架 | 90% | 已经成为仓库主线，CLI / config / planner / orchestrator / artifacts 基本齐全 |
| 默认 pipeline 骨架 | 85% | `triage -> collect_review` 全链路已成形，dry-run / preflight / diagnose 能用 |
| GitHub 协作尾链 | 80% | issue / PR / review workflow / resume / recovery hint 已落地，但还缺更稳定的真实端到端复跑 |
| Web UI control room | 88% | 已能承担本地主控台职责，且安全/校验/历史/健康/usage 面较完整 |
| OpenClaw 本地接入 | 75% | fallback live 路径可用，但还不是默认统一总控入口 |
| Hermes supervisor + recorder | 70% | 角色边界已明确，监督/记录链可接入，但不承担 implement |
| 成本统计 / 自动 fallback / 更细 review-merge 阶段 | 35% | 仍是明确未完成区 |
| 整体项目完成度 | 78% | 已接近“几乎完成”，但还没到默认主链稳定可发布 |

## 阶段归档

### Phase 0：方向收敛与可行性判断（2026-03-14 ~ 2026-03-16）

这一阶段的核心不是实现功能，而是把项目方向从“多模型 API demo”收敛到“Mission Control 总控层”。

完成的关键动作：

- 明确 OpenClaw 需要以“修改版方案四”推进，而不是继续强化 v1 keyword router。
- 产出面向 CLI + GitHub + review/supervision 的可行性方案和框架草案。
- 确认 `main_v2.py` + `openclaw_v2/` 将成为真实主线。

### Phase 1：默认 pipeline 脊柱成形（2026-03-27 ~ 2026-04-02）

这一阶段把默认 pipeline 从概念拉到可执行骨架。

完成的关键动作：

- 引入 GitHub review workflow。
- 稳定默认 pipeline 的 noop / dirty worktree / missing labels / skipped publish 等分支。
- 明确加入 `commit_changes`，把“改动提交”从 publish 前置条件里拆成显式步骤。
- 使用 isolated worktree 承载 implement，避免污染仓库根目录。
- 补齐 publish blocked 条件：依赖分支缺失、变更未提交、base branch ahead of upstream 等。
- 保留 committed workspace metadata，为后续 publish / review / cleanup 提供追踪基础。

### Phase 2：OpenClaw / Hermes / 控制台主控面扩展（2026-04-16 ~ 2026-04-30）

这一阶段把项目从“只会跑 pipeline”推进到“可观察、可监督、可切换 agent 变体”的状态。

完成的关键动作：

- 澄清 `github_bridge_smoke` 的边界，避免把 smoke pipeline 误当成完整主链。
- 引入 Hermes `supervisor + recorder` 变体 pipeline，明确它不接 implement。
- 建立 Web UI control room，把 CLI / GitHub / health / run history / housekeeping 集中到一个本地入口。
- 为 `doctor-config` 加回归测试，锁定配置诊断不会误入交互路径。
- 开始系统性收 GitHub bridge 链接和 Web UI 输入/输出的安全问题。

### Phase 3：Web / API / race hardening（2026-04-29 ~ 2026-05-03）

这一阶段的主题是“让控制台和历史读取在坏输入、坏 JSON、坏编码、目录消失、文件消失时仍然稳住”。

完成的关键动作：

- 补齐 Web API JSON 输入校验：对象体、布尔值、整数、非负数、合法 steps、非空请求。
- 收紧 repo/config/runtime scope，避免 Web UI 对任意路径做越界清理、历史枚举和健康检查。
- housekeeping 增加 manifest 范围校验和 confirmation token。
- 大量处理 run/history/cleanup/compare/preflight/config/worktree 的 race 条件。
- 安全头覆盖到错误响应；artifact path escape、history compare 输入、cleanup 竞态都补了回归保护。

### Phase 4：GitHub review 恢复链路与 reviewer-facing 输出（2026-05-06 ~ 2026-05-07）

这一阶段把 GitHub tail-chain 从“能跑”推进到“失败时能读懂、稍后能恢复、UI 和导出文案语义一致”。

完成的关键动作：

- `collect_review` failed / action_required / in_progress 会统一生成 `github_failure_kind`、`github_retryable`、`github_recovery_hint`。
- 非 workflow GitHub 失败也会汇总到 `github.latestFailure`。
- Web UI compare / recent runs / run detail / bridge copy 会统一显示最新 GitHub failure 和 recovery。
- 新增 `github_collect_review_resume` pipeline 和 `--workflow-run-ref`。
- Web UI Launch Pad 新增 workflow run ref 输入。
- 增加 `collect_review` polling 窗口，并用真实 smoke 验证可以在同一次 live run 内收敛到 success。

### Phase 5：usage 可视化、默认 live blocker 诊断与 OpenClaw fallback 固化（2026-05-08 ~ 2026-05-12）

这一阶段的主题是两件事：

1. 把 OpenClaw usage 从结果 JSON 提升到控制台里的可读信息。
2. 把默认 live 的 Claude blocker 和可用 fallback 路径解释清楚。

完成的关键动作：

- Web UI recent runs / run summary / history compare / bridge copy 增加 OpenClaw usage 汇总。
- 新增 Token Stats 面板，只读 token breakdown，不做 cost 估算。
- preflight 先做 Claude print-mode 探针，在 triage 前暴露不可用状态。
- recovery hint 统一指向 `mission_control_openclaw_default + OPENCLAW_ASSIGN_IMPLEMENT_LOCAL=openclaw_builder`。
- README 和状态文档持续记录 fallback live smoke、no-op tail-chain 行为、当前默认 live blocker。

## 当前可用基线（2026-05-13 存档快照）

### 已经可用

- `main_v2.py` 已是统一控制入口。
- `config_v2.yaml` + planner/orchestrator/preflight/worktree/artifacts 已形成完整骨架。
- 默认 pipeline `mission_control_default` 的 step 结构已经固定。
- GitHub tail-chain 已支持 issue / PR / review workflow / resume / recovery hint / failed jobs 摘要。
- Web UI control room 已可承担本地主控台职责。
- `mission_control_openclaw_default + OPENCLAW_ASSIGN_IMPLEMENT_LOCAL=openclaw_builder` 已验证为当前机器上的可用 live fallback。
- Hermes 已稳定在 `supervisor + recorder` 角色，不参与 implement。

### 当前阻塞

- 当前机器上的 `mission_control_default --live` 仍会被 `claude_local` 预检超时或未认证挡住。
- 默认主链还没有被证明能在当前机器上稳定重复跑完完整 live tail-chain。
- OpenClaw 还没有被提升成默认统一总控入口。
- 成本统计、跨层自动 fallback、细化 review/merge 阶段仍未完成。

## 关键验证记录归档

- 2026-05-07：真实 `github_bridge_smoke` live run 证明 `collect_review` 轮询窗口需要加长；随后同一条链路已验证能直接收敛为 success。
- 2026-05-07：`github_collect_review_resume` 已用真实 workflow run `25504962543` 验证成功。
- 2026-05-07：全量 Python 单测 221 项通过，`node --check openclaw_v2/webui/app.js` 通过。
- 2026-05-08：`mission_control_openclaw_default + OPENCLAW_ASSIGN_IMPLEMENT_LOCAL=openclaw_builder` 已完整跑通 triage / implement / review live smoke。
- 2026-05-11：PR #13 对应的 `openclaw-review.yml` 在 head `400ad43` 上成功完成，workflow run `25643659466` 证明当前 review smoke 仍可用。
- 2026-05-11 ~ 2026-05-12：多次 fallback/no-op smoke 进一步确认：默认 live 仍被 Claude preflight 挡住，但 OpenClaw fallback 仍是当前机器上的可继续入口。

## 完整 Git 历史日志（按提交时间正序）

```text
2026-03-14 46755f2 Provide OpenClaw feasibility plan
2026-03-15 068cb93 构建CLI与GitHub框架草案指南
2026-03-16 505e173 Assess Openclaw v2 changes
2026-03-27 b5586ba Add OpenClaw review workflow
2026-03-27 7c1c782 WIP: stabilize openclaw default pipeline
2026-03-27 0235fd8 Handle noop implement results and dirty worktree preflight
2026-03-27 488fa54 Handle missing GitHub labels gracefully
2026-03-27 c08cbbc Allow noop issue follow-up after skipped publish
2026-03-28 2311070 Guard noop dependency value collection
2026-03-28 c7a4140 Add orchestrator regression for noop OpenClaw issue follow-up
2026-03-28 b9c3212 Use ephemeral Codex runs and surface usage limits
2026-03-28 a94fcd0 Add OpenClaw implement fallback and noop detection
2026-03-28 7447fde Block publish when no dependency branch is exported
2026-03-28 8c880a3 Document headless GitHub auth fallback
2026-03-28 cc5cfec Block publish when dependency changes are uncommitted
2026-03-28 c66f7f2 Add explicit commit_changes pipeline stage
2026-03-28 6ec3b3b Use isolated worktrees for OpenClaw implement steps
2026-03-28 125d15b Preserve OpenClaw branch artifacts in dry-run
2026-04-02 a1b5115 Track committed workspace metadata
2026-04-02 7b88e75 Clarify review prompts for isolated worktrees
2026-04-02 085ff27 Block live publish when base branch is ahead of upstream
2026-04-16 ab2ace5 Clarify github_bridge_smoke scope
2026-04-29 2dce486 Add Hermes supervisor and recorder pipeline (#9)
2026-04-29 98b104a Build Hermes-aware Mission Control control room (#10)
2026-04-29 45e31cf Add doctor-config CLI regression test (#11)
2026-04-29 b2343f9 Harden GitHub bridge links and coverage
2026-04-29 ae34795 Add history file path escape regression
2026-04-29 76c3e4a Add history compare input regression
2026-04-30 d24611f Handle invalid JSON in web API handlers
2026-04-30 b62288a Validate prune keepLatest input
2026-04-30 45dde83 Require object JSON bodies in web API
2026-05-01 f7c4f6b Harden dashboard input validation
2026-05-01 fe49d4d Tighten web task input validation
2026-05-01 17a0d17 Validate dashboard requests before queueing
2026-05-01 07b44cc Tighten history compare input validation
2026-05-01 e84bbae Harden run history JSON handling
2026-05-01 01eb7b5 Reject negative history prune limits
2026-05-01 6446d38 Harden run metadata shape handling
2026-05-01 eced709 Harden health snapshot parsing
2026-05-01 a7d298a Skip bad bytes in run metadata readers
2026-05-02 7f8bf31 Harden run metadata race handling
2026-05-02 27c4269 Harden history compare summaries
2026-05-02 d27b29a Harden web race handling
2026-05-02 06f872a Harden cleanup artifact races
2026-05-02 690d2bd Document cleanup artifact race hardening
2026-05-02 ae62bf9 Address review comments on web races
2026-05-02 01a5e89 Harden artifact enumeration races
2026-05-02 0d73ee9 Harden Hermes preflight env loading
2026-05-02 8bc9eb1 Harden Hermes preflight config races
2026-05-02 12aceec Harden Hermes preflight fallback config races
2026-05-03 594b3a7 Harden config loader fallback races
2026-05-03 113210b Harden startup config disappearance handling
2026-05-03 8b0d905 Harden web config race handling
2026-05-03 ec3df0d Harden CLI preflight report races
2026-05-03 07f96e2 Harden CLI preflight report shapes
2026-05-03 12ab877 Harden worktree cleanup races
2026-05-03 d5811a1 Harden worktree cleanup branch races
2026-05-03 34be4f7 Harden Hermes runtime probe races
2026-05-03 3e5cab3 Merge pull request #12 from crused-fall/codex/harden-web-race-handling
2026-05-03 a315b64 Add Hermes role regression coverage
2026-05-03 e30ec2a Harden GitHub review workflow summaries
2026-05-03 072d64e Track project memory and target files
2026-05-06 f167d2f Propagate review workflow recovery hints
2026-05-07 d6142a6 Unify GitHub bridge failure recovery view
2026-05-07 b797966 Surface GitHub failure operators in compare UI
2026-05-07 10d70bf Expose GitHub failure state in recent runs
2026-05-07 1a0b44e Surface GitHub failure in run detail
2026-05-07 701d478 Extend GitHub review poll window
2026-05-07 cbbb88c Add collect_review resume pipeline
2026-05-07 72c3d58 Add workflow run ref control to Web UI
2026-05-07 6870e74 Record resume smoke and verification status
2026-05-08 74d4851 Add OpenClaw usage summaries to Web UI
2026-05-08 d703175 Add OpenClaw usage trend to recent runs
2026-05-08 3608c0f Include OpenClaw usage in bridge copy text
2026-05-08 58e391e Add Claude CLI preflight probe
2026-05-08 7da06c6 Record OpenClaw live smoke success
2026-05-08 e2aaa32 Clarify OpenClaw default implement override
2026-05-08 f4f25d8 Add Claude preflight recovery hint
2026-05-08 06c45ec Add OpenClaw fallback hint to README
2026-05-09 343b525 Record current live fallback status
2026-05-09 f5cdb19 Record claude_local_isolated live fallback result
2026-05-09 30e90f9 Clarify Claude isolated fallback diagnostics
2026-05-09 add9507 Record isolated Claude fallback diagnostics
2026-05-09 4ddd12e Clarify Claude isolated fallback guidance
2026-05-10 a0ede8d Surface preflight recovery hints in Web UI
2026-05-11 ac70fa6 Surface preflight recovery hints in copy surfaces
2026-05-11 88b8afd Record review workflow validation
2026-05-11 5c240e3 Record latest review run for PR 13
2026-05-11 37bbdcf Record fresh live smoke results
2026-05-11 1d2d1a2 Record fallback tail-chain smoke outcome
2026-05-11 400ad43 Clarify fallback smoke no-op behavior
2026-05-11 bca3a03 Record latest smoke clarification
2026-05-11 3b745a0 Record latest fallback smoke facts
2026-05-12 d17d0a4 Record latest no-op smoke in docs
2026-05-12 d4f88ae Record latest default pipeline blocker
2026-05-12 3440cd0 Record latest override smoke success
2026-05-12 cc636f7 Revert "Record latest override smoke success"
2026-05-12 17c4792 feat: add token stats panel to web ui
2026-05-12 8b1af4b docs: record token stats panel
```
