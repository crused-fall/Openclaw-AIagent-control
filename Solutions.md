# OpenClaw 多 Agent 总控方案分析

更新时间：2026-03-14

## 先用大白话说清楚：你想做的到底是什么

你现在的想法，不是单纯“调用几个大模型 API”。

你真正想做的是：

1. 做一个叫 `OpenClaw` 的总控台。
2. 它像一个项目经理一样，把任务分给不同 AI 编程助手。
3. 这些助手可能不是同一种形态：
   - 有的是终端工具，比如 Claude Code、Codex CLI。
   - 有的是 IDE/编辑器里的 Agent，比如 Copilot。
   - 有的是独立产品或独立工作台，比如 Antigravity 一类的 agent-first IDE。
4. 最后 `OpenClaw` 再把结果收回来，给人看、给人审核，甚至自动合并代码。

这件事是可行的，但有一个非常重要的区别：

- `模型 API 编排`：像今天项目里的 [openclaw.py](/Users/cfall/Documents/Programs/Openclaw-AIagent-control/openclaw.py) 这样，直接请求不同模型接口。
- `Agent 编排`：不是直接问模型，而是调度“会读代码、会改文件、会跑命令、会写 PR 的 AI 工具”。

你想做的，本质上是第二种。

## 先给结论

如果你是想做一个真正能落地的产品，而不是只做一个演示 Demo，那么最推荐的方向不是“像人一样点 app 界面”，而是：

`OpenClaw 作为上层总控 -> 优先接 CLI / SDK / MCP / ACP / GitHub 工作流 -> 只有在没有公开接口时才退回 GUI 自动化`

可以把它理解成：

- 最稳的办法：直接打电话给对方的“前台”。
- 次稳的办法：发标准邮件给对方。
- 最不稳的办法：偷偷趴在窗外看对方点了哪个按钮，再模仿去点。

GUI 自动化就属于第三种，能做，但很脆。

## 我查到的外部信息，说明这个方向确实有人在做

截至 2026-03-14，我查到的公开信息里，行业已经明显在往“多 Agent 总控台”这个方向走：

- OpenAI 在 2025-10-06 发布了 Codex SDK，说明 Codex 已经不仅是一个聊天模型，而是可以被嵌入工作流的 agent runtime。
- OpenAI 在 2026-02-02 发布了 Codex 桌面 app，明确把它描述为一个 “command center for agents”，支持多 agent 并行、worktree、长任务。
- GitHub 的 Agents on GitHub 页面已经把 Copilot、Claude、Codex 放到同一个“统一任务视图”里，说明“一个平台调多个 agent”是主流趋势，不是冷门想法。
- GitHub Copilot CLI 文档里明确写了 ACP（Agent Client Protocol），说明它可以作为 agent 被第三方工具接入。
- Google Antigravity 的官方入门文档也把它描述为 “Mission Control”，也就是“任务指挥中心”。
- 社区里已经出现很多围绕 Claude Code 子代理、工作树、MCP、并行协作的教程和经验分享。

这说明你的直觉是对的：未来不是“只用一个 AI”，而是“一个总控管多个 AI”。

但这不代表“最初想到的实现方法”就是最优解。

## 做这件事之前，必须先分清 4 种接入方式

### 1. 直接模型 API

意思是：
直接调用 OpenAI、Anthropic、Google 的接口，让它们返回文本。

优点：
- 最容易上手。
- 最容易自己完全掌控。

缺点：
- 你拿到的只是“回答”，不是完整 agent。
- 它不会天然帮你管文件、跑命令、做分支、产出 PR。

适合：
- 做最早期原型。
- 做问答型总控。

### 2. CLI / SDK 接入

意思是：
不是直接问模型，而是调用它们自己的命令行工具或 SDK。

比如可以理解成：
- 不是叫厨师“告诉我怎么做饭”
- 而是直接让厨师进厨房做饭

优点：
- 更接近真正 agent。
- 稳定性通常比点界面高。
- 更容易做自动化。

缺点：
- 不同工具的接法不统一。
- 需要处理权限、沙箱、日志、会话恢复。

适合：
- 真正要做产品。
- 真正想让多 agent 协作。

### 3. GitHub / PR / Issue 工作流接入

意思是：
你不一定非要“控制 agent 本体”，也可以把任务交给 GitHub 上的 coding agent 工作流，让它通过 issue、PR、review 的形式做事。

优点：
- 很适合异步任务。
- 很适合多人协作。
- 可审计、可回滚、可追踪。

缺点：
- 响应速度没有本地 CLI 那么直接。
- 更偏工程流程，不像聊天那么即时。

适合：
- 团队开发。
- 后台排队执行。

### 4. GUI / RPA / 电脑操作自动化

意思是：
像人一样打开 app、切窗口、粘贴 prompt、点击发送、读取结果。

优点：
- 几乎所有产品理论上都能接。
- 不依赖官方是否开放 API。

缺点：
- 最脆弱。
- UI 一改就坏。
- 登录弹窗、权限弹窗、网络异常都可能卡死。
- 很难并行，很难恢复，很难调试。

适合：
- 临时兼容。
- 没接口时的兜底。
- 做演示视频。

## 方案一：把 OpenClaw 做成“CLI / SDK 总控器”

## 一句话解释

OpenClaw 不去点界面，而是像总调度台一样，直接调用 Claude Code、Codex、Copilot CLI 这类工具。

## 用小白也能懂的话解释

你可以把这件事想成一家装修公司：

- `OpenClaw` 是项目经理。
- `Claude Code` 是擅长读代码和规划的老师傅。
- `Codex` 是擅长长任务和并行推进的老师傅。
- `Copilot` 是擅长贴着 GitHub 和 PR 流程工作的老师傅。

现在最合理的做法，不是让项目经理跑到每个师傅面前盯着他按鼠标。

更合理的做法是：

- 项目经理给每个人发标准任务单。
- 每个人在自己的工位上干活。
- 干完以后把产出、日志、改动、失败原因交回来。

CLI / SDK 就是这个“标准任务单”。

## 它怎么工作

可以分成 6 步：

1. 用户说：`给这个项目加登录功能，并修掉首页报错`
2. OpenClaw 先拆任务：
   - 任务 A：分析项目结构
   - 任务 B：实现登录
   - 任务 C：定位首页报错
   - 任务 D：做一次 review
3. OpenClaw 给每个 agent 分配独立工作区
   - 最好是独立 `git worktree`
   - 避免几个 agent 同时改同一份文件互相打架
4. OpenClaw 用 CLI / SDK 发任务
5. 每个 agent 返回：
   - 对话结果
   - 改动文件
   - 命令日志
   - 测试结果
   - 提交建议
6. OpenClaw 汇总，并让“审稿 agent”或人类做最后确认

## 优点

- 最接近真正可落地的产品形态。
- 稳定性远高于 GUI 自动化。
- 容易做并行。
- 容易做日志、重试、限流、失败恢复。
- 后面扩展新 agent 更自然。

## 缺点

- 前期设计会比现在的 `openclaw.py` 复杂很多。
- 不同 agent 的能力并不完全统一。
- Copilot 和 Antigravity 的“完整程序化控制能力”未必和 Claude/Codex 一样开放。

## 难度

中等到偏高。

对小白来说，可以理解为：
不是“很难到做不了”，而是“需要先搭框架，再接一个个 agent”。

## 适合谁

- 想把项目做成长期产品的人。
- 想让系统真的能跑任务、改代码、留痕审计的人。

## 推荐程度

最高，最推荐。

## 实施建议

先按这个顺序做：

1. 先接 `Claude Code`
2. 再接 `Codex`
3. 再接 `Copilot`
4. `Antigravity` 最后再评估要不要接

原因很简单：

- Claude Code 和 Codex 更像“天然可编排 agent”
- Copilot 更像“依托 GitHub 和编辑器生态的 agent”
- Antigravity 本身就像另一个总控平台，把它当成“被总控对象”会有点绕

## 方案二：把 OpenClaw 做成“GitHub 任务中台”

## 一句话解释

OpenClaw 不直接操控每个 agent 的本地运行，而是把任务转成 GitHub issue、branch、PR、review 流程，让不同 agent 在 GitHub 工作流里接力完成。

## 用小白也能懂的话解释

还是用装修比喻：

方案一像项目经理直接站在工地调度。

方案二像项目经理用“施工单系统”管理大家：

- 创建工单
- 指派负责人
- 提交照片
- 填写进度
- 最后验收签字

GitHub 在这里就像“施工管理平台”。

## 它怎么工作

1. OpenClaw 接到需求
2. 自动创建 issue，写清楚需求
3. 给不同任务打标签
4. 指派给不同 agent 或不同工作流
5. agent 在后台完成修改，提交 PR
6. OpenClaw 自动汇总 review 结果
7. 人类最后点击 merge

## 优点

- 非常适合团队协作。
- 每一步都能追踪。
- 很适合长任务和异步任务。
- 容易和现有开发流程结合。
- 更适合企业级落地。

## 缺点

- 没有“马上聊天马上动手”那么丝滑。
- 对个人小项目来说，流程可能显得重。
- 本地 IDE 体验不如直接 CLI 协作自然。

## 难度

中等。

虽然听起来很“企业”，但工程上反而比 GUI 自动化更稳。

## 适合谁

- 想做“后台自动干活”的系统。
- 想让 agent 输出 PR 而不是直接改主分支。
- 想要安全、可审计、多人可协作。

## 推荐程度

很高，尤其适合第二阶段。

## 最适合的定位

把它当成：

- `OpenClaw 的后台异步引擎`

而不是唯一入口。

最好的组合通常是：

- 前台：CLI / Chat / Web 控制台
- 后台：GitHub issue / PR 执行流

## 方案三：把 OpenClaw 做成“桌面自动化总控”

## 一句话解释

OpenClaw 通过电脑自动化的方式，像真人一样去操作 Claude、Copilot、Antigravity、Codex 的 app 或网页界面。

## 用小白也能懂的话解释

这就像你雇了一个机器人秘书：

- 会切窗口
- 会复制粘贴
- 会点发送按钮
- 会截图
- 会读屏幕

听起来很酷，而且最接近你最初的设想。

## 它怎么工作

1. OpenClaw 打开目标 app
2. 切到指定工作区
3. 把 prompt 输进去
4. 点击发送
5. 等待结果出现
6. 把结果抄回来
7. 如果需要，再把代码 diff 或文字摘要交给下一个 agent

## 优点

- 最符合“像操控 app 一样调度 AI”的想象。
- 如果某个工具没有 API、没有 CLI，这招理论上还能试。
- 很容易做出看起来很震撼的 Demo。

## 缺点

- 特别脆弱。
- 界面一改就容易失效。
- 多窗口并行很难。
- 需要处理：
  - 登录态
  - 焦点丢失
  - 弹窗
  - 权限确认
  - OCR 识别错误
  - 窗口位置变化
- 调试成本很高。
- 出错后很难恢复到正确状态。

## 难度

表面简单，实际很高。

这类方案最容易让新手产生一种错觉：
“我都能控制鼠标键盘了，那就离成功很近了。”

其实常常相反。

最难的不是“点一下按钮”，而是：

- 点完以后怎么确认系统真的进入了正确状态
- 失败以后怎么恢复
- 同时控制 3 到 5 个 agent 时如何不串台

## 适合谁

- 想快速做概念验证 Demo 的人。
- 想兼容暂时没有开放接口的产品。
- 愿意接受“今天能跑，明天可能坏”的维护现实。

## 推荐程度

低到中。

可以做，但不建议作为主架构。

## 最好的使用方式

只把 GUI 自动化做成一层“兜底适配器”：

- 有 CLI / SDK 时，绝不用 GUI
- 没 CLI / SDK 时，才退回 GUI

## 方案四：做“混合式 Mission Control”，分层接入

## 一句话解释

这是最完整、最像产品的方案：

OpenClaw 不是只用一种方式接全部 agent，而是分层：

- 第一层：CLI / SDK
- 第二层：GitHub / PR / Issue 工作流
- 第三层：GUI 自动化兜底

## 用小白也能懂的话解释

这就像你在管理一个跨城市施工项目，不能只靠一种沟通方式。

- 能打电话的，就打电话
- 能发工单的，就发工单
- 两种都不行，才派人亲自跑过去

如果你只保留第三种，会很累。
如果你只保留第一种，又会丢掉少数没有开放接口的对象。

所以最合理的办法，不是选一个，而是分层。

## 它怎么工作

### 控制层

用户只和 OpenClaw 对话。

### 编排层

OpenClaw 负责：

- 拆任务
- 排优先级
- 记录上下文
- 分配 agent
- 收集结果
- 判断是否需要重试

### 执行层

按优先级选择接入方式：

1. 先试 CLI / SDK
2. 不行就走 GitHub 工作流
3. 还不行再走 GUI 自动化

### 监督层

最后再由：

- 人工审核
- 或一个“审阅 agent”

统一把关。

## 优点

- 兼顾稳定性和兼容性。
- 最适合以后不断加新 agent。
- 不会把系统绑定死在某一家产品的界面上。
- 方便做权限控制、成本控制、失败重试。

## 缺点

- 架构设计最复杂。
- 前期要先想清楚统一接口。
- 需要做更多状态管理。

## 难度

高。

但这是“前期难，后期轻松”的难。

而 GUI-only 方案通常是“前期看起来快，后期越来越痛苦”的难。

## 适合谁

- 真想把 OpenClaw 做成自己的长期核心项目。
- 希望以后能接更多 agent，而不只是今天这 4 个。

## 推荐程度

如果你准备长期做，最高。

如果你准备先出原型，先做方案一，再逐步升级到方案四。

## 四个方案的横向对比

| 方案 | 核心思路 | 稳定性 | 开发速度 | 维护成本 | 是否适合长期产品 | 是否适合小白起步 |
| --- | --- | --- | --- | --- | --- | --- |
| 方案一 | CLI / SDK 总控 | 高 | 中 | 中 | 很适合 | 适合 |
| 方案二 | GitHub 任务中台 | 高 | 中 | 低到中 | 很适合 | 适合 |
| 方案三 | GUI 自动化总控 | 低 | 看起来快 | 很高 | 不太适合 | 不太适合 |
| 方案四 | 混合式 Mission Control | 很高 | 中到慢 | 中 | 最适合 | 先别直接从这里起步 |

## 如果你是编程小白，我会怎么建议你走

不要一上来就做最酷的那版。

最容易成功的路线是：

### 第一步：先做方案一的最小版本

先只接 2 个对象：

- Claude Code
- Codex

先别急着接 4 个。

目标不是“接得多”，而是“真的能稳定派活并拿回结果”。

先做到这几件事：

1. OpenClaw 能创建任务
2. OpenClaw 能给不同 agent 分独立目录
3. OpenClaw 能记录谁做了什么
4. OpenClaw 能拿回结果并显示

### 第二步：加上 Git 工作区隔离

这一步很重要。

如果多个 agent 在同一个目录里乱改文件，就像 3 个人同时拿一支笔写同一张纸，很容易打架。

你要做的是给每个 agent 一张自己的草稿纸。

这在工程里通常就是：

- `git worktree`
- 独立分支
- 或独立临时目录

### 第三步：再接 Copilot 相关流程

Copilot 更适合放到：

- GitHub PR
- Copilot CLI
- Copilot Agent / ACP

而不是强行当成本地窗口来点来点去。

### 第四步：最后才考虑 GUI 自动化

这一步不是不用做。

而是它应该是：

- 备胎
- 兼容层
- 演示层

不是发动机本体。

## 对你点名的 4 个对象，分别怎么判断

## 1. Claude Code

判断：
非常值得优先接。

原因：

- 更接近“本地 agent”
- 适合代码理解、执行命令、工作流自动化
- 社区里围绕子代理、MCP、工作树的实践很多

建议定位：

- `主力本地执行 agent`

## 2. Codex

判断：
非常值得优先接。

原因：

- 官方已经在推动 SDK、CLI、桌面 app、云任务一体化
- 很适合长任务、多任务、独立工作区

建议定位：

- `主力长任务 agent`
- `后台并行 agent`

## 3. GitHub Copilot

判断：
值得接，但最好别把重点放在“操作它的 UI”上。

原因：

- 它更强的地方在 GitHub 和 VS Code 生态里
- 很适合 issue、PR、review、后台任务
- 官方已经在讲 ACP 和统一 agent 视图

建议定位：

- `GitHub 流程 agent`
- `代码 review / PR 驱动 agent`

## 4. Antigravity

判断：
可以研究，但不建议一开始就把它当主接入对象。

原因：

- 它本身就像另一个“任务指挥中心”
- 公开、稳定、适合程序化接入的能力目前没有前面几者那么清晰
- 如果你去“总控另一个总控”，架构上会有点绕

建议定位：

- `实验性接入`
- `可选扩展对象`

## 最终建议：我会怎么选

### 如果你的目标是“尽快做出能跑的原型”

选：

- 方案一为主
- 方案二为辅

也就是：

- 本地先接 Claude Code + Codex
- 后台逐步接 GitHub / Copilot 工作流

### 如果你的目标是“最贴近最初脑洞，做一个很酷的演示”

选：

- 方案三做 Demo
- 但心里要清楚它不是最终架构

### 如果你的目标是“把 OpenClaw 做成长期产品”

选：

- 先从方案一起步
- 最终升级到方案四

这是我最推荐的路线。

## 我最推荐的一条落地路线

### 阶段 1：最小可用版

- OpenClaw 只支持任务创建、任务分发、日志记录、结果汇总
- 只接 Claude Code 和 Codex
- 每个任务一个独立工作目录

### 阶段 2：工程化

- 加任务状态机
- 加超时和重试
- 加成本统计
- 加 review agent
- 加 Git worktree

### 阶段 3：接 GitHub 工作流

- issue 创建
- PR 生成
- review 汇总
- Copilot 相关流程接入

### 阶段 4：补 GUI 兼容层

- 只在没有公开接口时使用
- 单独做一个 `GuiAutomationAdapter`
- 不要让主流程依赖它

## 参考资料

### 官方资料

- OpenAI: [Codex is now generally available](https://openai.com/index/codex-now-generally-available/)
- OpenAI: [Introducing the Codex app](https://openai.com/index/introducing-the-codex-app/)
- Anthropic: [Claude Agent SDK / Headless](https://platform.claude.com/docs/en/agent-sdk/headless)
- GitHub Docs: [About GitHub Copilot CLI](https://docs.github.com/en/copilot/concepts/agents/copilot-cli/about-copilot-cli)
- GitHub: [Agents on GitHub](https://github.com/features/copilot/agents)
- Google Blog: [Gemini 3 / Antigravity 相关发布](https://blog.google/products-and-platforms/products/gemini/gemini-3/)
- Google Codelab: [Getting Started with Google Antigravity](https://codelabs.developers.google.com/getting-started-google-antigravity)

### 社区与案例

- GitHub: [Rover](https://github.com/endorhq/rover)
- GitHub: [CCManager](https://github.com/kbwo/ccmanager)
- GitHub: [Commander](https://github.com/autohandai/commander)
- Bilibili: [ClaudeCode 子代理(sub agents)详解 + 使用案例](https://www.bilibili.com/video/BV19n4ZzMEuJ/)
- Bilibili: [Google Antigravity IDE 初体验](https://www.bilibili.com/video/BV14ryEBVE1S/)
- Bilibili: [OpenAI「Codex」详细完整实践教程](https://www.bilibili.com/video/BV1VqYNzuEqv/)
- 知乎专栏: [GitHub Agent HQ正式发布，构建开放智能体生态](https://zhuanlan.zhihu.com/p/1971897932623111771)
- Stack Overflow: [Copilot Agent Not Using My MCP Extensions in VS Code – Any Fix?](https://stackoverflow.com/questions/79656359/copilot-agent-not-using-my-mcp-extensions-in-vs-code-any-fix)
- Stack Overflow: [Does Vscode Copilot extension in Agent mode only works with Claude?](https://stackoverflow.com/questions/79581068/does-vscode-copilot-extension-in-agent-mode-only-works-with-claude)

### 关于小红书搜索结果的说明

我在 2026-03-14 搜过小红书相关结果，但公开可索引内容里没有找到足够高相关、足够稳定、足够适合作为技术判断依据的帖子，所以没有把它作为主要参考来源。

