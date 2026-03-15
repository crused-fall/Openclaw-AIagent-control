# OpenClaw v2 Framework

## 目标

把当前单文件原型升级为“CLI + GitHub 工作流”混合编排框架，同时保留现有 `openclaw.py` 作为旧入口。

## 新增结构

```text
openclaw_v2/
  __init__.py
  config.py
  models.py
  planner.py
  orchestrator.py
  executors/
    base.py
    cli.py
    github.py
main_v2.py
config_v2.yaml
```

## 分层说明

### 1. Planner

负责把一个用户请求展开成一条 pipeline。

当前版本不是智能拆分器，而是“配置驱动的任务流水线”：

- `triage`
- `implement`
- `sync_issue`
- `draft_pr`

后续可以再替换成更智能的动态拆解器。

### 2. Executor

执行器分两类：

- `CLIExecutor`
- `GitHubWorkflowExecutor`

这样做的目的，是把“本地快速执行”和“远程异步协作”同时保留下来。

### 3. Orchestrator

编排器负责：

- 按依赖调度任务
- 渲染 prompt
- 选择执行器
- 汇总结果
- 在上游失败时跳过下游任务

### 4. Config

所有接入信息都放到 `config_v2.yaml`：

- profile 决定“谁来执行”
- pipeline 决定“按什么顺序执行”

## 当前实现状态

当前是“可运行骨架”，不是“完整产品”：

- 已有统一数据模型
- 已有 CLI / GitHub 两类执行器
- 已有依赖驱动的编排器
- 已有 run artifacts 落盘
- 已有 CLI 任务独立 worktree 准备层
- 已有依赖分支到 GitHub PR / workflow 的上下文传递
- 已有 issue 跟进步骤和 worktree cleanup 生命周期
- 已有交互入口 `main_v2.py`
- 默认 `dry_run: true`

默认 dry-run 的含义是：

- 会生成计划
- 会渲染 prompt
- 会拼装命令
- 会规划 worktree 路径
- 会把 plan / prompt / result 写入 artifacts
- 会把 CLI 任务分支传给下游 GitHub 步骤
- 会规划 worktree cleanup 命令
- 不会真的调用外部 CLI
- 不会真的创建 GitHub issue / PR

## 下一步建议

1. 先把 Claude / Codex 的真实 CLI 命令参数确认下来。
2. 为 GitHub executor 增加 `issue comment`、`pr comment`、`workflow dispatch` 支持。
3. 在 live 模式下补齐 worktree 回收和异常清理。
4. 把 CLI stdout / stderr、GitHub 响应体写入 artifacts。
5. 增加 review / merge 审核阶段。
