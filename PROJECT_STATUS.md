# OpenClaw Project Status

更新时间：2026-05-01

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
- `--doctor-config` 已有 CLI 回归测试并合并到 main，锁定配置诊断路径不会误进入交互模式
- CLI 入口现在会把缺失的 `--config` 转成干净的 `SystemExit`，不再直接抛 traceback
- CLI 的 `_print_preflight()` 现在会把 `preflight.json` 在 exists/open 之间消失、变成不可读、或变成非对象 JSON 的情况安静降级，不再让 run 结束后的预检摘要打印把进程拖成 traceback
- 支持 `--web` 本地 Mission Control 控制台
- live 运行时会输出 step 级 progress

### Orchestration Layer

- 配置驱动 pipeline（已支持继承 / 覆盖 / remove_steps 组合）
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
- GitHub bridge 的 `repository_unavailable` / `workflow_missing` 失败分支已补上回归测试，和现有 auth / permission / reference / network 路径一起覆盖主要失败形态
- GitHub bridge 面板里的 repo / workflow 外链也已统一走 `safeExternalUrl`，避免把非 http(s) URL 直接挂到 `href`
- GitHub bridge 已支持显式配置的网络类自动重试
- GitHub repo 已支持显式开启的 `origin` fallback
- `gh issue create` 如果因为仓库里缺少 labels 失败，会自动去掉 labels 重试一次，并把被忽略的 labels 回写到结果
- GitHub bridge state 现在会同步写入 run summary、issue update 和 PR note，方便协作方直接看到最新桥接状态
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
- 本地 Web UI 已具备 readiness gate、run compare、artifact browser、health snapshot（含最近 preflight 摘要与来源）、GitHub bridge 总览状态卡和 housekeeping 入口
- Web UI 的健康面板在渠道数据为空时会保守显示 warning，不再误报 passed
- Web UI 的 repo/config 作用域已默认收紧到启动时绑定的仓库，避免页面层面对任意路径做历史清理和健康检查
- housekeeping 清理已改为校验 manifest 的 repo/worktree/branch 范围，防止 run 产物被篡改后越界删除其他仓库对象
- housekeeping 危险操作已要求当前 dashboard 会话携带服务端确认 token，降低绕过前端弹窗直接调用接口的风险
- Web UI 对 repo 内替代配置的支持已进一步收紧：允许调整 pipeline/assignment，但不允许改写 dashboard 绑定的 artifacts/worktrees roots
- Web UI 的安全头现在覆盖 4xx / 5xx 响应，未捕获异常会回落到干净的内部错误响应
- Web UI 的 artifact file 预览现在会拒绝逃逸 run 目录的路径，避免通过 `../` 之类的相对路径越界读取
- Web UI 的 history compare 接口现在会拒绝非 list / 非字符串项 / 非恰好两个 / 非不同 run 的 `runIds` 请求，避免比较入口静默接受歧义输入
- Web API 的 JSON 入口现在会把坏 JSON 统一转换成 `400 Invalid JSON body.`，不再让解析错误冒泡成 `500`
- Web UI 的 run history / recent runs 读取现在会把损坏、非对象、或嵌套 `plan/results` 形状异常的 run 元数据做保守降级处理；损坏的 `preflight.json` 会按缺失处理，避免浏览历史时炸出 `500`
- Web UI 的 health snapshot 现在会对 `openclaw health --json` 的 `channelOrder` / `channels` / `agents` / `defaultAgentId` 做保守解析，避免健康页被坏 payload 拖成 `500`
- Web UI 的 recent runs / cleanup manifest 读取现在也会跳过坏字节输入，避免 `summary.json` / workspace manifest 的编码错误拖垮页面
- Web UI 的 recent runs / history 读取现在能容忍 `summary.json` 在扫描或读取间消失，避免竞争条件把页面拖成 `500`
- Web UI 的 history / cleanup / prune 现在会复用请求内已解析的 config，不再在后台线程里二次打开配置文件；这样 config 在请求中途消失时，不会把已经开始的历史读取或清理拖成 `500`
- Web UI 的 history 文件列表和单文件读取现在也会容忍文件在 size/stat 阶段消失，避免 artifact browser 的竞态把页面拖成 `500`
- Web UI 的 recent runs / housekeeping prune 现在也会跳过在排序阶段消失的 run 目录，避免目录级竞态把页面拖成 `500`
- Web UI 的 history 详情页现在也会把 run 目录在更新时间戳阶段消失收敛成 404，避免目录级竞态冒成 `500`
- Web UI 的 recent runs 现在也会把 `preflight.json` 在读取时消失收敛成缺失预检，避免首页因为预检竞态冒成 `500`
- Web UI 的 cleanup manifest 读取现在也会跳过在读取时消失的 workspace manifest，避免 housekeeping 因竞态冒成 `500`
- Web UI 的 cleanup artifact 删除现在也会把 run 目录在删除时消失收敛成已缺失，不再把 housekeeping 因竞态拖成 `500`
- Web UI 的 artifact file 预览在 stat 消失时会保留原始大小，不再把截断文件误报成 limit 大小
- Web UI 的 cleanup artifact 删除在真实 OSError 下会返回 failure 记录，不再伪装成 skipped
- Web UI 的 history 文件枚举现在会把 artifact tree glob 失败收敛成空列表，不再把目录级竞态顶成 `404`
- Web UI 的 cleanup manifest 枚举现在会把 workspace glob 失败收敛成空列表，不再把 manifest 竞态顶成 `404`
- Hermes preflight 的 `.env` 读取现在也会把文件在 exists/open 之间消失收敛成空值，不再把 Hermes 前置检查拖成异常
- Hermes preflight 的 `config.yaml` 读取现在也会把文件在 exists/open 之间消失收敛成空配置，不再把 Hermes 前置检查拖成异常；这条也覆盖 PyYAML 和 Ruby fallback 解析路径
- 配置加载器的 Ruby fallback 现在会把“文件在读取时消失”统一成 `FileNotFoundError`，避免调用方把同一个竞态误报成 YAML 解析失败；判定依据是文件当前是否仍然存在，而不是 Ruby stderr 文本
- Web UI 的历史与概览里，`success` / `dry_run` 这类状态位现在只认真正的 JSON 布尔值，字符串值不再被误报为 `true`
- Web UI 的 history compare 现在会对 malformed `statusCounts` / `workflow` / `sessionCount` 做保守降级，避免比较摘要被坏字段拖垮
- Web UI 的 history compare 现在也会保守忽略非列表的 `plan/results`，避免摘要里的结构异常拖出 `500`
- Web UI 的 runtime snapshot / Hermes overview / GitHub overview 现在会把字符串型布尔和坏列表保守降级，避免配置快照误报
- Web API 的任务创建现在会拒绝非布尔的 `live`，避免字符串值误入 live 模式
- Web API 的任务创建现在会严格校验 `steps` 形状，避免非字符串列表项进入后台执行
- Web API 的任务创建现在会在入队前拒绝空请求文本和未知 step id，避免先返回 `202` 再异步失败
- Web UI 的 bootstrap 接口现在会把未知 pipeline override 直接拒绝为 `400`，不再让首页请求落成 `500`
- Web API 的 housekeeping cleanup / prune 现在会拒绝非布尔的 `removeWorktrees` / `removeArtifacts`，避免字符串值被误判为 `true`
- Web UI 的 history prune 接口现在会拒绝非整数 `keepLatest`，避免无效保留策略输入漏成 `500`
- Web API 的 history prune 现在也会拒绝布尔型 `keepLatest`，避免 `true` 被误当成 `1`
- Web API 的 history prune 现在还会拒绝负数 `keepLatest`，避免错误输入被静默钳成 `0` 后误删全部历史
- Web API 的 JSON 入口现在还会拒绝非对象 JSON body，避免数组 / 标量 payload 触发 handler 内部异常

## 部分完成

- 任务拆分仍然以配置驱动 pipeline 为主，已经支持 pipeline 继承 / 覆盖 / remove_steps 组合，planner 也已开始按依赖关系排序，但还不是智能动态 planner
- OpenClaw 接入骨架已落地，但目前只安全接到 `triage` 变体 pipeline
- OpenClaw 已验证“仓库外 workspace + repo 绝对路径 handoff”可运行，当前已有 `mission_control_openclaw_triage` 和 `mission_control_openclaw_default` 两条变体 pipeline
- Hermes 已作为本机 `supervisor + recorder` 接入，新增 `mission_control_hermes_supervised` 变体 pipeline，但不承担 `implement`
- 当前分支上的 Web UI control room 已把 CLI / GitHub / Hermes / OpenClaw 的运行态集中到一个本地面板里
- `Gemini` 和 `Cursor` 已进入受控 agent 注册表，但还没进入默认 assignment
- 当前 fallback 仍是静态配置回退，不是实时在线调度
- live 模式下已默认禁止 fallback managed agent 静默执行
- GitHub 当前仍是 `gh` bridge，不是 native agent / MCP 编排
- GitHub 缺少 issue / PR / branch 引用时会被标记为 `blocked`
- `workflow_dispatch` 已会在 preflight 检查本地 workflow 文件是否存在
- GitHub 自动重试默认仍是关闭状态
- GitHub repo 的 `origin` fallback 当前默认已开启
- `doctor-config` 已覆盖 GitHub runtime retry、GitHub profile action / workflow 配置，以及 pipeline 依赖引用 / 循环校验
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
5. 再考虑真正的动态 planner、fallback 和成本控制
