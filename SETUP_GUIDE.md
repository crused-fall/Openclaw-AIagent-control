# OpenClaw Setup Guide

本指南以“修改版方案四”为目标，说明如何把当前仓库跑成一个最小的 Mission Control。

## 1. 你要先理解两条入口

### v1 legacy

- 入口：`openclaw.py`
- 作用：验证多模型 API 路由

### v2 mission control

- 入口：`main_v2.py`
- 作用：验证 CLI / GitHub / supervision 分层编排

注意：当前真正的控制层仍是 `main_v2.py` + `openclaw_v2/`。
OpenClaw 已经接入执行层和受控 agent 体系，但还不是默认统一总控入口。

如果你准备继续做项目，请优先使用 v2。

## 2. 基础依赖

```bash
pip install -r requirements.txt
```

需要的 Python 包：

- `anthropic`
- `google-generativeai`
- `openai`
- `pyyaml`

如果当前 Python 环境没有 `pyyaml`，v2 也可以通过系统 Ruby 做配置加载 fallback，但仍建议装齐依赖。

## 3. v1 legacy 环境

```bash
export ANTHROPIC_API_KEY="your-key"
export GOOGLE_API_KEY="your-key"
export OPENAI_API_KEY="your-key"
```

验证：

```bash
python3 test_setup.py
python3 demo.py
python3 openclaw.py
```

## 4. v2 mission control 环境

### 本地 agent

至少准备：

- `claude`
- `gemini`（如果要把它纳入受控 agent 池）
- `codex`
- `cursor-agent`（如果要把 Cursor 纳入受控 agent 池）
- `git`
- `openclaw`（如果要验证本机 OpenClaw 接入）

建议先确认：

```bash
claude --version
gemini --version
codex --version
cursor-agent --version
git --version
```

### GitHub 层

```bash
export OPENCLAW_GITHUB_REPO="owner/repo"
gh auth login
```

并确保当前仓库有 `origin` remote。

### OpenClaw 本地接入

如果要走 `mission_control_openclaw_triage` 或 `mission_control_openclaw_default`，至少准备一个本地 OpenClaw agent：

```bash
openclaw agents list --json
openclaw agents add openclaw-control-ext \
  --workspace ~/.openclaw/workspaces/openclaw-aiagent-control \
  --non-interactive --json
export OPENCLAW_AGENT_ID="your-agent-id"
```

更稳的做法是为这个仓库单独建一个 agent，而不是复用个人 `main`。
更稳的 workspace 做法是放在仓库外，例如 `~/.openclaw/workspaces/openclaw-aiagent-control`。

注意：

- 不建议长期把 OpenClaw agent 的 workspace 直接指到仓库根目录
- 否则 OpenClaw 可能会在仓库里生成 `IDENTITY.md`、`SOUL.md`、`TOOLS.md`、`USER.md`、`HEARTBEAT.md` 这类运行态文件
- 当前版本会在 preflight 里对这种情况给出 warning
- 当前 OpenClaw executor 会显式传入 repo 绝对路径，并要求 agent 先读取 repo 内的 `AGENTS.md`
- 如果你的 `claude` 依赖自定义 `ANTHROPIC_BASE_URL` / `ANTHROPIC_AUTH_TOKEN`，默认 `claude_local` 会保留这些变量；`claude_local_isolated` 只作为显式备选

## 5. 推荐运行顺序

### 先理解 assignment 层

当前 v2 不再推荐把 step 直接理解成“Claude 步骤”或“Codex 步骤”。

正确理解是：

- step 只表达 `triage / implement / review` 这类逻辑角色
- 具体用哪个受控 agent，由 `config_v2.yaml` 的 `assignments + managed_agents` 决定
- `assignments` 还可以声明 `required_capabilities` 和 `fallback`
- 如果 assignment / profile 解析失败，这一步会在计划阶段直接变成 `blocked`，而不是让整个 planner 直接崩掉
- 如果要临时切换，也可以用环境变量覆盖，例如 `OPENCLAW_ASSIGN_TRIAGE_LOCAL`

示例：

```bash
OPENCLAW_ASSIGN_TRIAGE_LOCAL=gemini_researcher python3 main_v2.py --list-steps --steps triage
```

如需查看当前受控 agent 注册表：

```bash
python3 main_v2.py --list-managed-agents
python3 main_v2.py --doctor-config
```

如需直接诊断 step 是怎么解析到具体 managed agent 的：

```bash
python3 main_v2.py --diagnose-plan --steps triage,implement
python3 main_v2.py --diagnose-plan --steps collect_review
```

### 第一步：只看计划

```bash
python3 main_v2.py --list-steps
python3 main_v2.py --list-steps --steps review,publish_branch
```

### 第二步：只看预检

```bash
python3 main_v2.py --preflight-only
python3 main_v2.py --preflight-only --steps draft_pr,dispatch_review
```

如果你计划跑 `dispatch_review`，当前 preflight 还会检查本地是否存在
`.github/workflows/openclaw-review.yml`。缺失时 dry-run 会 warning，live 会直接失败。
如果你计划跑 `collect_review`，它会依赖 `dispatch_review` 先产出 workflow run id 或 URL。
成功接通后，`collect_review` 会把 workflow status / conclusion 和 failed jobs 摘要回流到结果 artifacts。
当前默认还会对 `workflow_view` 做一个很短的轮询等待，配置项是
`runtime.github_workflow_view_poll_attempts` 和 `runtime.github_workflow_view_poll_interval_seconds`。
如果你只想单独验证 GitHub review workflow，而不想先经过本地 `triage/implement/review`，可以改用 `github_bridge_smoke` pipeline。

### 第三步：dry-run

```bash
python3 main_v2.py --request "修复登录页报错" --steps triage,implement,review
```

### 第四步：live

```bash
python3 main_v2.py --live --request "修复登录页报错" --steps triage,implement,review
```

注意：当前默认 live 策略下，如果某一步已经静态解析到 fallback managed agent，live 会直接中止。
要允许这种行为，需要显式把 `runtime.allow_fallback_in_live` 设为 `true`。
另外，live 运行中会先输出 `[progress] preflight:start`、`[progress] step:start ...` 之类的进度行。
当前默认还启用了 `runtime.cli_command_timeout_seconds=180.0`，本地 CLI 长时间无响应时会明确超时退出。
如果 GitHub bridge 失败，CLI 还会直接打印 `stderr`、`github_failure_kind`、`github_retryable` 和 `github_recovery_hint`。
如果 `gh workflow run` 返回 403 `Resource not accessible by personal access token`，优先改用 `gh auth login --web` 重新认证，或执行 `gh auth refresh -h github.com -s repo,workflow`；在 headless 环境中，可用 `gh auth login --with-token` 作为 `--web` 的替代方式。
如果 `gh issue create` 只是因为仓库里还没有预设 labels 失败，系统现在会自动去掉 labels 重试一次，并在结果里打印 `github_label_fallback_used` 和 `github_ignored_labels`。
如果本地 CLI 失败，结果里也会直接打印 `cli_failure_kind` 和 `cli_recovery_hint`。默认 `triage` 卡在 Claude 时，优先试 `OPENCLAW_ASSIGN_TRIAGE_LOCAL=claude_router_isolated`；如果想整体绕过 Claude 的前后监督步骤，直接改用 `mission_control_openclaw_default`；如果只想替换 `triage`，用 `mission_control_openclaw_triage`。
`codex_local` 现在默认带 `--ephemeral`，用于降低本机 `~/.codex` 状态库迁移冲突对 live run 的影响；如果结果里出现 `cli_failure_kind=usage_limit`，则需要等待 Codex 配额恢复或提升账号额度。
如果 Codex 当前不可用，但你本机 OpenClaw agent 已具备仓库写权限，也可以临时绕过 Codex：`OPENCLAW_ASSIGN_IMPLEMENT_LOCAL=openclaw_builder`。这会把 `implement` 这一步显式切到 `openclaw_local`，而不改变默认 pipeline 结构。
这条 `openclaw_builder` 路径当前更适合本地 `triage/implement/review` 校验；如果实现结果没有导出可推送分支，`publish_branch` 现在会明确 `blocked`，不会再误继续到 GitHub 尾链。
当前主线已经补了显式的 `commit_changes` 步骤：只有当实现工作区里的改动被提交为干净 commit 后，`publish_branch` 才会继续；如果提交后工作区仍不干净，链路会继续明确 `blocked`。
如果 live 计划里包含隔离 CLI worktree，而仓库仍有未提交改动，preflight 现在会直接失败；这些 worktree 只基于已提交 `HEAD`，不会自动带上本地改动。
如果 `implement` 最终判断“请求已满足、无需改动”，结果会被显式标成 no-op，后续 `publish_branch` 会因为没有可发布文件变化而跳过。
如果这时前面已经成功 `sync_issue`，`update_issue` 现在仍会继续，把“无需代码改动”的结果回写到现有 issue；但 `draft_pr / dispatch_review / collect_review` 仍会保持跳过。
如果你希望网络类 GitHub 失败自动重试，可以把 `runtime.github_retry_attempts` 调到大于 `1`，并用 `runtime.github_retry_backoff_seconds` 控制间隔；默认是关闭的。
当前默认已经允许在没填 `github.repo` 时从 `git remote origin` 推导仓库；如果你想固定目标仓库，可以显式设置 `github.repo` 或 `OPENCLAW_GITHUB_REPO`。
`--doctor-config` 现在还会检查这些 GitHub runtime 配置和 GitHub profile action / workflow 配置是否自洽。

如果当前 live 总是被本地 `claude/codex` 环境挡住，可以先单独做 GitHub smoke test：

```bash
python3 main_v2.py --pipeline github_bridge_smoke --preflight-only --steps collect_review
python3 main_v2.py --pipeline github_bridge_smoke --live --request "smoke test github bridge" --steps collect_review
```

### 第五步：走完整链路

```bash
python3 main_v2.py --live --request "修复登录页报错" --steps publish_branch,draft_pr
```

### 第六步：验证 OpenClaw 接入

```bash
OPENCLAW_AGENT_ID="openclaw-control-ext" \
python3 main_v2.py --pipeline mission_control_openclaw_triage --preflight-only --steps triage
```

```bash
OPENCLAW_AGENT_ID="openclaw-control-ext" \
python3 main_v2.py --live --pipeline mission_control_openclaw_triage --steps triage \
  --request "概括这个仓库的主入口"
```

如果你想在 Claude 当前不可用时继续跑主线，可以改成：

```bash
OPENCLAW_AGENT_ID="openclaw-control-ext" \
python3 main_v2.py --pipeline mission_control_openclaw_default --preflight-only --steps triage,implement,review
```

## 6. 结果怎么查看

每次 v2 运行都会落盘到：

```text
.openclaw/runs/<run-id>/
```

主要文件：

- `context.json`
- `plan.json`
- `summary.json`
- `prompts/*.txt`
- `results/*.json`
- `workspaces/*.json`
- `logs/*.stdout.txt`
- `metadata/preflight.json`

## 7. 常见问题

### `PyYAML` 缺失

先装：

```bash
pip install pyyaml
```

如果暂时没装，v2 会尝试用系统 Ruby 加载 YAML。

### `git worktree` 建分支失败

先确认当前环境允许写 `.git/refs/heads`。

如果是在受限沙箱里运行，live 模式可能需要额外权限。

### 请求和仓库不匹配

这是预期路径的一部分。

当前 v2 会把这种情况标记为：

- `triage: blocked`
- 下游实现步骤 `skipped`

这正是修改版方案四里监督层应该做的事情。
