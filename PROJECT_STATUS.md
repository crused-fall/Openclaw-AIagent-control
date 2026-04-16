# OpenClaw Project Status

更新时间：2026-03-28

## 当前阶段

项目已经从“多模型 API 路由原型”进入“修改版方案四 Mission Control 骨架”阶段。

这意味着：

- `openclaw.py` 仍可运行，但只代表 v1 legacy
- 核心演进方向已经转向 `main_v2.py` + `openclaw_v2/`
- OpenClaw 已进入执行层与受控 agent 体系，但还没有成为默认统一总控入口

## 已完成

### Control Layer

- `main_v2.py` 已可作为统一入口
- 支持 `--steps`、`--request`、`--live`、`--preflight-only`
- 支持 `--list-managed-agents`、`--doctor-config`、`--diagnose-plan`
- live 运行时会输出 step 级 progress

### Orchestration Layer

- 配置驱动 pipeline
- assignment 分配层
- managed-agent registry
- capability / fallback 解析
- assignment failure -> blocked policy
- 依赖调度
- worktree 隔离
- artifacts 落盘
- blocked / failed / skipped 区分

### Execution Layer

- CLI 执行层
- OpenClaw 本地执行层
- GitHub 执行层
- 受控 agent 池：Claude / Gemini / Codex / Cursor / OpenClaw
- GitHub issue / PR / workflow run refs 回流
- `dispatch_review -> collect_review` workflow 状态回流已落地
- `collect_review` 已支持 failed jobs 摘要回流
- 新增 `github_bridge_smoke` pipeline，可绕过本地 `triage/implement/review` 单独验证 GitHub review workflow
- `collect_review` 已支持短轮询等待，减少 workflow 刚触发时立即返回 `queued` 的手工重跑
- 本地 CLI executor 已有超时护栏，`claude/codex` 长时间无响应时不会再无限挂住 run
- GitHub 步骤 CLI 会打印 `github:` 摘要
- GitHub bridge 的失败会分类为 auth / repository / workflow / reference / network / unknown
- GitHub 失败结果会保留 `stderr`、retryability 和恢复提示
- GitHub bridge 已支持显式配置的网络类自动重试
- GitHub repo 已支持显式开启的 `origin` fallback
- `gh issue create` 如果因为仓库里缺少 labels 失败，会自动去掉 labels 重试一次，并把被忽略的 labels 回写到结果
- `implement` 为 no-op 且 `sync_issue` 已成功时，`update_issue` 现在允许继续执行 issue 收尾；PR / workflow 尾链仍保持跳过
- 主线已新增显式 `commit_changes` 步骤，用于在 `review` 后、`publish_branch` 前提交实现工作区里的改动
- `commit_changes` 会复用实现步骤的 workspace 和分支，而不是回落到仓库根目录
- `commit_changes` 现在会保留提交前的变更文件列表，并明确记录 `changes_committed` / `head_commit`
- 只有当改动被提交为干净 commit 后，`publish_branch` 才会继续；否则继续明确 `blocked`

### Supervision Layer

- preflight
- review step
- run summary
- blocked 原因透传
- `first_blocked` 根因摘要

## 部分完成

- 任务拆分仍然是静态 pipeline，不是智能动态 planner
- OpenClaw 接入骨架已落地，但目前只安全接到 `triage` 变体 pipeline
- OpenClaw 已验证“仓库外 workspace + repo 绝对路径 handoff”可运行，当前已有 `mission_control_openclaw_triage` 和 `mission_control_openclaw_default` 两条变体 pipeline
- Hermes 已作为本机 `supervisor + recorder` 接入，新增 `mission_control_hermes_supervised` 变体 pipeline，但不承担 `implement`
- `Gemini` 和 `Cursor` 已进入受控 agent 注册表，但还没进入默认 assignment
- 当前 fallback 仍是静态配置回退，不是实时在线调度
- live 模式下已默认禁止 fallback managed agent 静默执行
- GitHub 当前仍是 `gh` bridge，不是 native agent / MCP 编排
- GitHub 缺少 issue / PR / branch 引用时会被标记为 `blocked`
- `workflow_dispatch` 已会在 preflight 检查本地 workflow 文件是否存在
- GitHub 自动重试默认仍是关闭状态
- GitHub repo 的 `origin` fallback 当前默认已开启
- `doctor-config` 已覆盖 GitHub runtime retry 和 GitHub profile action / workflow 配置
- 真实正向 live 闭环仍取决于外部 agent 环境是否可用，例如 Claude/Codex/OpenClaw/GitHub 权限与配额

## 未完成

- OpenClaw 成为默认统一总控入口
- 成本统计
- 跨层自动 fallback
- 更细的 review / merge 审核阶段

## 建议优先级

1. 继续稳定默认 `mission_control_default` pipeline
2. 决定 OpenClaw 什么时候从变体执行器升级成默认控制入口
3. 决定哪些 step 默认由 Claude / Codex 继续承担，哪些开始尝试切到 Gemini / Cursor / OpenClaw
4. 继续补 GitHub bridge 的结果诊断、review 透传和失败恢复
5. 再考虑动态 planner、fallback 和成本控制
