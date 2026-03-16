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
- 已有 preflight 检查和 stdout/stderr artifacts
- 已有本地分支发布步骤，用于真正衔接 GitHub PR
- 已有 CLI 入口参数，支持 live 开关与按步骤子集执行
- 已有 live 护栏，默认只允许白名单步骤集合
- 已有交互入口 `main_v2.py`
- 默认 `dry_run: true`

## 入口参数

`main_v2.py` 当前支持：

- `--request "..."`：单次执行后退出
- `--steps a,b,c`：只执行指定步骤，并自动补齐依赖
- `--list-steps`：只输出有效计划
- `--preflight-only`：只输出预检结果
- `--live`：切换到 live 模式
- `--repo-path /path/to/repo`：指定仓库路径
- `--pipeline name`：切换 pipeline

## 建议试跑顺序

### 1. 查看计划

```bash
/usr/bin/python3 main_v2.py --list-steps --steps publish_branch
```

### 2. 查看预检

```bash
/usr/bin/python3 main_v2.py --preflight-only --steps publish_branch,draft_pr
```

### 3. 最小 dry-run

```bash
/usr/bin/python3 main_v2.py --request "修复登录页报错" --steps publish_branch
```

### 4. 最小 live

```bash
/usr/bin/python3 main_v2.py --live --request "修复登录页报错" --steps publish_branch
```

## live 护栏

默认 live 模式有两条限制：

1. 必须显式提供 `--steps`
2. 默认只允许这些步骤进入 live：
   - `triage`
   - `implement`
   - `publish_branch`

如果后面要放开更多真实执行步骤，可以修改 `config_v2.yaml` 里的 `runtime.allowed_live_steps`。

## 当前已知前提

如果要执行 GitHub 相关步骤，至少需要：

- `OPENCLAW_GITHUB_REPO` 已配置
- `gh auth login` 已完成且 token 有效
- 仓库存在 `origin` remote
- Claude / Codex CLI 在当前 shell 可用

默认 dry-run 的含义是：

- 会生成计划
- 会渲染 prompt
- 会拼装命令
- 会规划 worktree 路径
- 会把 plan / prompt / result 写入 artifacts
- 会把 CLI 任务分支传给下游 GitHub 步骤
- 会规划 worktree cleanup 命令
- 会在每轮执行前记录 preflight 报告
- 不会真的调用外部 CLI
- 不会真的创建 GitHub issue / PR

## 下一步建议

1. 先把最小 live 链路 `triage -> implement -> publish_branch` 实际跑通。
2. 修复 GitHub 环境后，再放开 `sync_issue / update_issue / draft_pr / dispatch_review` 的 live 白名单。
3. 为 GitHub executor 增加更细的响应解析和 `pr comment` 场景。
4. 在 live 模式下补齐异常中断后的 worktree 回收策略。
5. 增加 review / merge 审核阶段。
