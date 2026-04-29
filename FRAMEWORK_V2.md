# OpenClaw v2 Framework

## 核心目标

`openclaw_v2/` 不是对 `openclaw.py` 的简单重写，而是把项目重构成“修改版方案四”的 Mission Control：

- 第一层：CLI / SDK 本地执行
- 第二层：GitHub / PR / Issue 异步执行
- 第三层：审阅与监督

v1 的关键词路由原型继续保留，但不再代表项目长期方向。

当前实现边界：

- 长期目标仍然是 OpenClaw 风格的统一总控
- 当前真正落地的控制层是 `main_v2.py` + `openclaw_v2/`
- `ExecutionMode.OPENCLAW` 只是已接入的一种执行路径，不等于仓库已经由外部 OpenClaw 完全接管
- `ExecutionMode.HERMES` 当前定位为本机监督 / 记录执行路径，不承担默认实现步骤

## 分层映射

### 1. Control Layer

- 入口：`main_v2.py`
- 职责：
  - 解析命令行参数
  - 选择 pipeline
  - 输出 preflight / result / artifacts 摘要
  - 输出 step 级 progress 与根因摘要

### 2. Orchestration Layer

- `planner.py`
- `orchestrator.py`
- `preflight.py`
- `worktree.py`

职责：

- 生成计划
- 按依赖执行
- 管理 run id、workspace、branch
- 先走 assignment 层，再解析具体受控 agent
- 处理 blocked / failed / skipped
- 汇总依赖结果，传给下游步骤

### 3. Execution Layer

- `executors/cli.py`
- `executors/hermes.py`
- `executors/openclaw.py`
- `executors/github.py`

职责：

- 统一执行接口
- 把本地 CLI、本机 OpenClaw、GitHub 协作接进同一条编排链
- 把 Hermes 这类本机 supervisor / recorder executor 接进同一条编排链
- 将 stdout / stderr / 结果结构化成 `AgentResult`

### 3.5 Managed-Agent Registry

- `managed_agents`
- `assignments`

职责：

- 维护受控 agent 清单
- 把逻辑角色映射到受控 agent
- 再由受控 agent 解析到具体 profile / executor
- 校验 `required_capabilities`
- 在 primary agent 不可用时按静态 `fallback` 回退
- 若 assignment 或 profile 无法解析，则把该 step 降成系统级 `blocked`
- 允许通过环境变量做静态覆盖，但这仍不是实时调度系统

### 4. Supervision Layer

- `review` step
- `artifacts.py`
- `preflight.py`

职责：

- 在实现后做审阅
- 保留 prompt、workspace manifest、result、summary
- 在 live 前做环境预检

## 数据流

```text
request
  -> build plan
  -> preflight
  -> prepare workspace
  -> render prompt
  -> execute step
  -> collect artifacts
  -> resolve dependency outcomes
  -> supervision / review
  -> publish / sync / dispatch
```

## 默认 pipeline

`mission_control_default`

1. `triage`
2. `implement`
3. `review`
4. `commit_changes`
5. `publish_branch`
6. `sync_issue`
7. `update_issue`
8. `draft_pr`
9. `dispatch_review`
10. `collect_review`

另有一条专门用于 GitHub bridge 排障的最小 pipeline：

`github_bridge_smoke`

1. `dispatch_review`
2. `collect_review`

它只跑 `dispatch_review -> collect_review`，不会经过 `commit_changes` 和 `publish_branch`。

另有一条 Hermes 监督变体：

`mission_control_hermes_supervised`

1. `triage`（Hermes）
2. `implement`（本地 CLI）
3. `review`（Hermes）
4. `commit_changes`
5. `publish_branch`
6. `sync_issue`
7. `record_summary`（Hermes）
8. `update_issue`
9. `draft_pr`
10. `dispatch_review`
11. `collect_review`

这条链用于让 Hermes 同时承担 supervisor / recorder，不承担 `implement`。

设计原则：

- 本地优先
- 审阅先于发布
- 发布之后才进入 GitHub 协作层
- 下游步骤必须消费上游结构化结果

## 状态模型

`TaskStatus`

- `planned`
- `running`
- `succeeded`
- `blocked`
- `failed`
- `skipped`

其中：

- `blocked` 表示请求或环境暂时不能安全继续，但不是执行错误
- `failed` 表示步骤执行出错
- `skipped` 表示因为 preflight、blocked 或失败依赖而未执行

## preflight 的作用

preflight 是修改版方案四里监督层的一部分，不是附加脚本。

当前负责检查：

- git 仓库有效性
- planning blocked steps
- 需要的命令是否存在
- OpenClaw agent 是否存在
- `origin` remote 是否存在
- GitHub repo 配置是否完整
- `gh auth` 是否可用

## worktree 策略

本地执行层默认使用独立 worktree。

目的：

- 防止多个 agent 在同一工作区互相覆盖
- 给每个任务独立分支和 artifacts
- 让 review / publish / GitHub 步骤可以消费同一条实现分支

当前分支命名采用扁平格式，避免 git ref 的 file/dir 冲突。

## 配置设计

`config_v2.yaml` 分五部分：

- `runtime`: pipeline、dry-run、artifacts、live 护栏
- `github`: repo、base branch、默认 labels
- `profiles`: 执行端点
- `managed_agents`: 受控 agent 注册表
- `assignments`: 逻辑角色到受控 agent 的映射
- `pipelines`: 步骤顺序和 prompt 模板

## 当前边界

已经完成：

- step 到 agent 的 assignment 分配层
- managed-agent registry
- assignment capability / fallback 规则
- CLI / OpenClaw / GitHub 三种执行 mode
- 统一 artifacts 落盘
- blocked 信号解析
- review 监督步骤
- live 白名单和 preflight
- live 默认禁止 fallback managed agent 静默进入执行
- OpenClaw triage 变体 pipeline

当前新增边界：

- `mission_control_openclaw_triage` 只把 `triage` 切到 OpenClaw，本地实现和 GitHub 步骤不变
- `mission_control_openclaw_default` 把 `triage + review` 都切到 OpenClaw，适合 Claude 当前不可用时继续跑主线
- `Claude / Gemini / Codex / Cursor` 在设计上都只作为受控 agent，不再在 pipeline 里直接写死职能
- OpenClaw executor 会把 repo 绝对路径和 repo 内 `AGENTS.md` 显式 handoff 给 agent
- 推荐使用仓库外的独立 OpenClaw workspace；只有 workspace 指到 repo 内部时才视为风险
- gateway / ACP 暂不作为主链依赖
- GitHub 当前仍是 `gh` bridge，而不是 native coding agent 编排
- GitHub 缺少 issue / PR / branch 引用时会被降成 `blocked`，CLI 会直接打印 GitHub artifact 摘要
- GitHub bridge 的失败会分类为 auth / repository / workflow / reference / network / unknown，并保留 retryability、恢复提示和原始 stderr
- `gh issue create` 如果只是因为仓库里还没有预设 labels 失败，会自动去掉 labels 重试一次，并把 `github_label_fallback_used` / `github_ignored_labels` 落到 artifacts
- `implement` 为 no-op 时，`publish_branch` 会跳过；如果 `sync_issue` 已经先建了 issue，`update_issue` 仍可继续做 issue 收尾，而 PR / workflow 尾链继续跳过
- `workflow_dispatch` 会在 preflight 检查本地 `.github/workflows/<workflow_name>` 是否存在
- GitHub bridge 的自动重试当前只对可重试失败生效，并且默认关闭，需要通过 runtime 配置显式开启
- GitHub repo 默认允许从 `origin` remote 推导；如果 `github.repo` 已配置，则仍优先使用显式配置
- `dispatch_review` 之后现在有 `collect_review`，用于把 workflow run 的状态、结论和 run 引用回流到 artifacts
- `collect_review` 还会提取 failed jobs 摘要，避免 review workflow 失败时只剩一个笼统 conclusion
- `collect_review` 现在还支持短轮询等待，适合处理 workflow 刚 dispatch 后短时间内仍是 `queued` 的情况

尚未完成：

- OpenClaw 成为默认统一总控入口
- 跨层 fallback 策略的自动切换
- 更细粒度的任务拆分器
- 成本与重试策略

## 建议运行顺序

```bash
python3 main_v2.py --list-steps
python3 main_v2.py --preflight-only --steps review,publish_branch
python3 main_v2.py --request "修复登录页报错" --steps triage,implement,review
python3 main_v2.py --live --request "修复登录页报错" --steps triage,implement,review
```
