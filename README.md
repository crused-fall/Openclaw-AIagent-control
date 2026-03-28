# OpenClaw

OpenClaw 是一个多 AI agent 的 Mission Control。

项目目标不是简单聚合多个模型 API，而是把不同形态的 agent 接到同一个总控层里，并按“修改版方案四”编排：

1. CLI / SDK 本地执行层
2. GitHub / Issue / PR 异步协作层
3. 审阅与监督层

当前仓库同时保留两条实现线：

- `openclaw.py`: v1 legacy，基于模型 API 的并行路由原型
- `main_v2.py` + `openclaw_v2/`: 按修改版方案四演进的 Mission Control 框架

当前实现和目标方向需要分开看：

- 目标方向：让 OpenClaw 最终成为多 agent 的统一控制面
- 当前落地：真正的控制层仍然是 `main_v2.py` + `openclaw_v2/`
- 当前 OpenClaw 现状：已经接入执行层和受控 agent 体系，但还不是默认统一总控入口

## 方案四定位

方案来源见 `Solutions.md` 的“方案四：做混合式 Mission Control，分层接入”。

OpenClaw 当前选定的方向是：

- 目标上，用户最终只和 OpenClaw 交互
- 目标上，OpenClaw 最终负责拆任务、调度、留痕、重试和审阅
- Claude / Gemini / Codex / Cursor 这类工具只作为“受控 agent”
- step 需要什么能力，由 OpenClaw 的 `assignment -> managed_agent -> profile` 链决定，不由 agent 名称硬编码决定
- assignment 还可以声明 `required_capabilities` 和 `fallback`，用于静态选择和回退
- assignment / profile 解析失败不会再直接抛异常，而是会被降成可追踪的 `blocked` 步骤
- 优先使用 CLI / SDK
- 保留 GitHub 工作流的异步协作优势
- 当前版本不把 GUI 自动化放进主线实现
- 当前代码里，这个控制面仍由 `main_v2.py` + `openclaw_v2/` 承担，OpenClaw 本身只在变体 pipeline 和受控 agent 体系里接入

## 当前架构

```text
User
  -> Control Layer
     -> main_v2.py
  -> Orchestration Layer
     -> planner.py / orchestrator.py / preflight.py / worktree.py
     -> assignment layer / managed-agent registry
  -> Execution Layer
     -> CLIExecutor
     -> OpenClawExecutor
     -> GitHubWorkflowExecutor
  -> Supervision Layer
     -> review step / artifacts / preflight / run summaries
```

## 仓库结构

```text
openclaw.py               v1 legacy 原型
demo.py                   v1 演示模式
main_v2.py                v2 Mission Control 入口
config.yaml               v1 配置
config_v2.yaml            v2 配置
FRAMEWORK_V2.md           v2 架构说明
PROJECT_STATUS.md         当前阶段状态
SETUP_GUIDE.md            环境搭建与运行指南
Solutions.md              方案分析与长期路线
openclaw_v2/
  config.py               配置与环境展开
  models.py               数据模型与状态
  planner.py              pipeline 规划
  orchestrator.py         依赖调度与汇总
  preflight.py            预检
  worktree.py             独立工作区管理
  artifacts.py            运行产物落盘
  executors/
    cli.py                本地 CLI / SDK 执行层
    openclaw.py           本地 OpenClaw 执行层
    github.py             GitHub 工作流执行层
tests/
  ...
```

## 默认 pipeline

默认 pipeline 是 `mission_control_default`，目标是体现 CLI + GitHub 双引擎加监督层：

1. `triage`: 分析需求与仓库匹配度
2. `implement`: 在独立 worktree 中本地实现
3. `review`: 审阅实现结果，形成监督结论
4. `publish_branch`: 推送实现分支
5. `sync_issue`: 在 GitHub 建立异步跟踪
6. `update_issue`: 回写实施状态
7. `draft_pr`: 生成 Draft PR 描述
8. `dispatch_review`: 触发 GitHub review workflow
9. `collect_review`: 回流 GitHub review workflow 状态

另有两条 OpenClaw 变体 pipeline：

- `mission_control_openclaw_triage`：只把 `triage` 切到本机 `openclaw agent --local --json`
- `mission_control_openclaw_default`：把 `triage + review` 都切到 OpenClaw，本地 `implement` 和后续 GitHub 步骤保持不变（适用于 Claude 不可用时）
- 当前这样设计是为了先替换最容易受 Claude 环境影响的监督层，不把 gateway / ACP 问题一次性扩大
- OpenClaw executor 会显式把 repo 绝对路径传给 agent，并要求它先读取 repo 内的 `AGENTS.md`

另有一条 GitHub-only smoke pipeline：`github_bridge_smoke`

- 只跑 `dispatch_review -> collect_review`
- 用来单独验证 GitHub review workflow 的触发和状态回流
- 适合在本地 `claude/codex` 环境不稳定时排除干扰

## 快速开始

### v2 Mission Control

1. 安装依赖

```bash
pip install -r requirements.txt
```

2. 准备本地 agent 与 GitHub 环境

```bash
export OPENCLAW_GITHUB_REPO="owner/repo"
gh auth login
```

需要时再准备：

- `claude`
- `gemini`
- `codex`
- `cursor-agent`
- `openclaw`

如果要验证本机 OpenClaw 接入，再额外准备：

```bash
openclaw agents add openclaw-control-ext \
  --workspace ~/.openclaw/workspaces/openclaw-aiagent-control \
  --non-interactive --json
export OPENCLAW_AGENT_ID="your-openclaw-agent-id"
```

推荐把 OpenClaw agent 的 workspace 放在仓库外，再把仓库绝对路径交给 executor。
不要长期把 workspace 直接指到 repo 根目录。

如果你的 `claude` 依赖自定义 `ANTHROPIC_BASE_URL` / `ANTHROPIC_AUTH_TOKEN`，当前默认 `claude_local` 会保留这些环境变量。
仓库里还提供了一个隔离版 `claude_local_isolated`，只在你需要显式绕过这两个变量时使用。

3. 预览 pipeline

```bash
python3 main_v2.py --list-steps
python3 main_v2.py --preflight-only --steps publish_branch,draft_pr
python3 main_v2.py --list-managed-agents
python3 main_v2.py --doctor-config
python3 main_v2.py --diagnose-plan --steps triage,implement
```

如果要临时改 agent 分配，不必改 pipeline step。本次运行前覆盖 assignment 即可，例如：

```bash
export OPENCLAW_ASSIGN_TRIAGE_LOCAL="gemini_researcher"
python3 main_v2.py --list-steps --steps triage
```

4. dry-run 执行

```bash
python3 main_v2.py --request "修复登录页报错" --steps triage,implement,review
```

如果你只想验证 GitHub review workflow，不想先经过本地 `triage/implement/review`：

```bash
python3 main_v2.py --pipeline github_bridge_smoke --request "smoke test github bridge" --steps collect_review
```

5. live 执行

```bash
python3 main_v2.py --live --request "修复登录页报错" --steps triage,implement,review
```

当前默认策略下，live 模式不会静默接受 fallback managed agent。
如果某一步只能靠 fallback 才能继续，live 会直接中止，并要求你显式检查 assignment 配置。
运行中会输出 `[progress] preflight:start`、`[progress] step:start ...` 这类进度行，避免长步骤看起来像卡住。
当前还启用了 `runtime.cli_command_timeout_seconds=180.0`，本地 `claude/codex` 长时间无响应时会明确超时失败，而不是无限挂住。
CLI 失败结果现在也会带 `cli_failure_kind` 和 `cli_recovery_hint`。如果默认 `triage` 卡在 Claude，可以优先试 `OPENCLAW_ASSIGN_TRIAGE_LOCAL=claude_router_isolated`，或者直接切到 `mission_control_openclaw_triage` / `mission_control_openclaw_default`。
`codex_local` 现在默认用 `codex exec --ephemeral`，尽量避开本机 `~/.codex/state_*.sqlite` 迁移冲突；如果仍然返回 `cli_failure_kind=usage_limit`，说明是 Codex 账号配额问题，不是项目编排问题。
如果 Codex 当前不可用，但你本机 OpenClaw agent 可写仓库，可以显式覆盖实现层：`OPENCLAW_ASSIGN_IMPLEMENT_LOCAL=openclaw_builder`。这样 `mission_control_openclaw_default` 会让 OpenClaw 承担 `implement`，而不是继续卡在 Codex。
这条 `openclaw_builder` 路径目前主要用于本地 `triage/implement/review`；如果实现结果没有导出可推送分支，`publish_branch` 现在会直接 `blocked`，而不是假装还能继续 GitHub 尾链。
如果 live 计划里包含隔离 CLI worktree，而仓库还有未提交改动，preflight 现在会直接拦下；这些 worktree 只基于已提交 `HEAD`，不会自动带上本地脏改动。
如果 `implement` 判断“请求已满足、无需改动”，结果会显式标成 no-op；后续 `publish_branch` 会因为没有可发布文件变化而跳过。

如果要直接做 GitHub bridge live 验证：

```bash
python3 main_v2.py --pipeline github_bridge_smoke --live \
  --request "smoke test github bridge" --steps collect_review
```

6. 验证 OpenClaw triage 接入

```bash
OPENCLAW_AGENT_ID=your-openclaw-agent-id python3 main_v2.py \
  --pipeline mission_control_openclaw_triage \
  --preflight-only --steps triage
```

### v1 legacy 原型

```bash
python3 demo.py
python3 openclaw.py
./start.sh
python3 test_setup.py
```

## 当前状态

当前仓库已经不再把 `openclaw.py` 视为最终目标，而是把它当作早期原型保留。

v2 已具备：

- 配置驱动 pipeline
- assignment 驱动的受控 agent 分配
- managed-agent registry
- assignment capability / fallback 规则
- assignment failure -> system blocked step
- CLI / OpenClaw / GitHub 三种执行接口
- preflight 预检
- worktree 隔离
- artifacts 落盘
- blocked / failed / skipped 状态区分
- review 监督步骤
- step 级 progress 输出
- config doctor / plan diagnostics

v2 已验证：

- `mission_control_openclaw_triage` 能通过 orchestrator 调起本机 `openclaw agent --local --json`
- OpenClaw 的 `payloads/sessionId/model/usage/workspace` 已能落盘到 run artifacts
- 已验证“仓库外 workspace + repo 绝对路径 handoff”可工作；只有 workspace 指到 repo 内部时才会 warning
- 已验证可以通过 assignment override 在不改 pipeline 的情况下，把 `triage` 临时切到 `gemini_researcher`
- 已验证 preflight 和 `--list-managed-agents` 会显示 managed agent、required_capabilities 和 fallback 信息
- 已验证 assignment 解析失败会落成 `blocked` 结果，并把根因一路透传到下游 `skipped`
- 已验证 `--diagnose-plan` 可以直接打印 step 的 assignment 候选、尝试链和 blocked 根因
- 已验证 `dispatch_review -> collect_review` 可以把 workflow run 引用回流到后续 GitHub follow-up step
- `collect_review` 现在还能回流 workflow status / conclusion，以及失败 job 摘要
- `collect_review` 现在支持短轮询等待；如果 workflow 很快完成，同一次 live run 就能直接拿到最终状态
- GitHub bridge 现在会稳定回流 issue / PR / workflow run 引用，便于下游步骤继续消费
- GitHub 步骤在 CLI 结果里会直接打印 `github:` 摘要，包含 repo、action、issue / PR / workflow refs
- GitHub bridge 失败时会区分 `auth / repository / workflow / reference / network / unknown`，并保留 `blocked_reason`、`github_error`、`github_retryable` 和 `github_recovery_hint`
- 例如，如果 `gh workflow run` 返回 403 'Resource not accessible by personal access token'，可以改用 `gh auth login --web` 重新认证，或确保 token 具有 `repo` 和 `workflow` scope（使用 `gh auth refresh -h github.com -s repo,workflow`；在 headless 环境中，可使用 `gh auth login --with-token` 作为 `--web` 的替代方式）。
- `gh issue create` 如果因为仓库里缺少预设 labels 而失败，现在会自动去掉 labels 重试一次，并把被忽略的 labels 回写到结果 artifacts
- 如果 `implement` 是 no-op 但前面已经成功 `sync_issue`，`update_issue` 现在仍可继续执行，用来把“无需代码改动”的终态回写到已有 issue；PR / workflow 尾链仍会保持跳过
- `workflow_dispatch` 会在 preflight 检查本地 `.github/workflows/<workflow_name>` 是否存在，避免缺文件时到 live 阶段才失败
- GitHub bridge 已支持可配置的网络类自动重试；默认关闭，需要显式设置 `runtime.github_retry_attempts > 1`
- GitHub repo 现在默认允许从 `git remote origin` 推导；如果你显式配置了 `github.repo`，则以配置值为准
- 已验证 live 路径会先打印 `preflight/start/done` 级别的 progress，而不是整段静默
- `--doctor-config` 现在也会检查 GitHub runtime retry 配置和 GitHub profile action / workflow 配置是否自洽

v2 仍未完成：

- OpenClaw 尚未成为默认统一总控入口
- `Gemini` 和 `Cursor` 还没有进入默认 assignment
- GitHub 仍是 `gh issue/pr/workflow` 桥接层，不是 native agent 接入
- GitHub bridge 已开始做失败分类，但仍不是 native agent 编排
- GitHub 层更深的结果解析与恢复策略
- 统一成本统计
- 长任务调度与超时重试

## 文档导航

- `Solutions.md`: 为什么最后要走方案四
- `FRAMEWORK_V2.md`: v2 的结构和模块职责
- `SETUP_GUIDE.md`: 环境搭建和运行方式
- `PROJECT_STATUS.md`: 当前阶段做到了什么、还缺什么
