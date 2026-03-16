# OpenClaw - 多 AI 协作系统

多 Agent 协作架构，支持 Claude、Gemini、GPT-4 并行处理任务。

## 架构

```
用户请求 → OpenClaw (主控) → 任务分解 → 并行执行 → 结果整合 → 返回
                                    ↓
                        ┌───────────┼───────────┐
                        ↓           ↓           ↓
                    Claude      Gemini      GPT-4
```

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置 API Keys

```bash
export ANTHROPIC_API_KEY="your-anthropic-key"
export GOOGLE_API_KEY="your-google-key"
export OPENAI_API_KEY="your-openai-key"
```

或创建 `.env` 文件（参考 `.env.example`）：

```bash
cp .env.example .env
# 编辑 .env 填入你的 API keys
```

### 3. 运行

```bash
# 方式 1: 演示模式（无需 API Keys）
python3 demo.py

# 方式 2: 真实 API 模式（需要 API Keys）
python3 openclaw.py

# 方式 3: 使用启动脚本（会检查环境变量）
./start.sh

# 方式 4: 测试环境配置
python3 test_setup.py
```

## v2 混合编排框架

仓库里还有一套新的 v2 骨架，入口是 `main_v2.py`，目标是把本地 CLI agent、GitHub 工作流、独立 worktree 和 artifacts 串成一条可控执行链。

### v2 常用命令

```bash
# 查看有效计划，会自动补齐依赖
/usr/bin/python3 main_v2.py --list-steps --steps publish_branch

# 只做预检，不执行任务
/usr/bin/python3 main_v2.py --preflight-only --steps publish_branch,draft_pr

# dry-run 执行最小链路
/usr/bin/python3 main_v2.py --request "修复登录页报错" --steps publish_branch

# live 模式默认只允许白名单步骤
/usr/bin/python3 main_v2.py --live --request "修复登录页报错" --steps publish_branch
```

### v2 额外环境要求

- `OPENCLAW_GITHUB_REPO=owner/repo`
- `gh auth login`
- `git remote origin` 已配置

更详细的结构说明见 `FRAMEWORK_V2.md`。

## 使用示例

```
用户: 帮我写一段 Python 代码实现快速排序

用户: 搜索最新的 AI 技术趋势

用户: 分析这段代码的性能瓶颈
```

输入 `quit`、`exit` 或 `q` 退出程序。

## 核心组件

- **OpenClaw**: 主控 Agent，负责任务分解和结果整���
- **ClaudeAdapter**: Anthropic Claude API 适配器
- **GeminiAdapter**: Google Gemini API 适配器
- **CodexAdapter**: OpenAI GPT-4 API 适配器
- **Task/Result**: 数据模型

## 配置说明

编辑 `config.yaml` 自定义：

- 模型参数（model、max_tokens）
- 路由规则（关键词匹配）

## 特性

- ✅ 真实 API 集成（Claude、Gemini、GPT-4）
- ✅ 基于关键词的智能任务路由
- ✅ 并行执行多个 Agent
- ✅ 错误处理和异常捕获
- ✅ 交互式命令行界面
