# OpenClaw 完整安装和使用指南

本指南将带你一步一步完成 OpenClaw 的安装、配置和使用。

---

## 📋 前置要求

- Python 3.9 或更高版本
- pip（Python 包管理器）
- 至少一个 AI 服务的 API Key（Claude、Gemini 或 OpenAI）

---

## 🚀 第一步：安装依赖

### 1.1 克隆或下载项目

如果你还没有项目文件，请先获取项目代码。

### 1.2 进入项目目录

```bash
cd /path/to/Claude-basement
```

### 1.3 安装 Python 依赖包

```bash
pip install -r requirements.txt
```

**预期输出：** 你会看到一系列包被下载和安装，包括 `anthropic`、`google-generativeai`、`openai`、`pyyaml` 等。

**可能的问题：**
- 如果遇到权限错误，使用 `pip install --user -r requirements.txt`
- 如果 pip 版本过旧，先运行 `pip install --upgrade pip`

---

## 🔑 第二步：配置 API Keys

你需要至少一个 AI 服务的 API Key。以下是获取方式：

### 2.1 获取 API Keys

**Anthropic Claude:**
1. 访问 https://console.anthropic.com/
2. 注册/登录账号
3. 进入 API Keys 页面
4. 创建新的 API Key
5. 复制保存（只显示一次）

**Google Gemini:**
1. 访问 https://makersuite.google.com/app/apikey
2. 登录 Google 账号
3. 点击 "Create API Key"
4. 复制保存

**OpenAI:**
1. 访问 https://platform.openai.com/api-keys
2. 注册/登录账号
3. 点击 "Create new secret key"
4. 复制保存（只显示一次）

### 2.2 设置环境变量

**方式 A：临时设置（推荐用于测试）**

在终端中运行：

```bash
export ANTHROPIC_API_KEY="your-anthropic-key-here"
export GOOGLE_API_KEY="your-google-key-here"
export OPENAI_API_KEY="your-openai-key-here"
```

**注意：** 这种方式只在当前终端会话有效，关闭终端后需要重新设置。

**方式 B：永久设置（推荐用于长期使用）**

创建 `.env` 文件：

```bash
cp .env.example .env
```

编辑 `.env` 文件，填入你的 API Keys：

```bash
ANTHROPIC_API_KEY=sk-ant-xxxxxxxxxxxxx
GOOGLE_API_KEY=AIzaSyxxxxxxxxxxxxx
OPENAI_API_KEY=sk-xxxxxxxxxxxxx
```

然后在使用前加载环境变量：

```bash
source .env
```

或者将以下内容添加到 `~/.bashrc` 或 `~/.zshrc`：

```bash
export ANTHROPIC_API_KEY="your-key"
export GOOGLE_API_KEY="your-key"
export OPENAI_API_KEY="your-key"
```

---

## ✅ 第三步：验证安装

运行环境检查脚本：

```bash
python3 test_setup.py
```

**预期输出：**

```
OpenClaw 环境检查
==================================================

✓ 配置文件存在
✓ 所有依赖包已安装
✓ 所有环境变量已设置

==================================================
✓ 环境配置完成，可以运行: python openclaw.py
```

**如果出现错误：**
- `❌ 缺少依赖包` → 重新运行步骤 1.3
- `❌ 缺少环境变量` → 检查步骤 2.2 是否正确设置
- `❌ 找不到 config.yaml` → 确认你在正确的项目目录中

---

## 🎮 第四步：运行程序

### 4.1 演示模式（无需 API Keys）

如果你想先体验系统工作流程，可以运行演示模式：

```bash
python3 demo.py
```

**演示模式特点：**
- 不需要真实的 API Keys
- 模拟多 Agent 协作流程
- 返回模拟响应

**示例交互：**

```
用户: 帮我写一段 Python 代码
  → 分配给 1 个 Agent: ['claude']

结果:
Claude 回复: 我已收到您的请求「帮我写一段 Python 代码」并进行了处理。
```

### 4.2 真实 API 模式

使用真实的 AI 服务：

```bash
python3 openclaw.py
```

或使用启动脚本（会自动检查环境变量）：

```bash
./start.sh
```

**首次运行输出：**

```
OpenClaw 已启动，输入 'quit' 退出

用户:
```

---

## 💬 第五步：使用系统

### 5.1 基本使用

在提示符后输入你的请求，系统会自动分配给合适的 Agent 处理。

**示例 1：代码相关请求**

```
用户: 帮我写一段 Python 快速排序代码

处理中...

结果:
[Claude 的详细代码实现]
```

**示例 2：搜索相关请求**

```
用户: 搜索最新的 AI 技术趋势

处理中...

结果:
[Gemini 的搜索结果]
```

**示例 3：分析相关请求**

```
用户: 分析这段代码的性能瓶颈

处理中...

结果:
[GPT-4 的分析结果]
```

### 5.2 多 Agent 协作

如果你的请求包含多个关键词，系统会同时调用多个 Agent：

```
用户: 帮我写代码并搜索相关文档

处理中...

结果:
Claude 回复: [代码实现]
Gemini 回复: [文档搜索结果]
```

### 5.3 退出程序

输入以下任一命令退出：
- `quit`
- `exit`
- `q`

或按 `Ctrl+C` 强制退出。

---

## ⚙️ 第六步：自定义配置

### 6.1 修改路由规则

编辑 `config.yaml` 文件：

```yaml
routing_rules:
  - keywords: ["代码", "code", "编程", "bug"]
    agent: claude
  - keywords: ["搜索", "search", "查找"]
    agent: gemini
  - keywords: ["分析", "优化"]
    agent: codex
```

**添加新规则：**

```yaml
  - keywords: ["翻译", "translate"]
    agent: gemini
```

### 6.2 修改模型参数

在 `config.yaml` 中调整：

```yaml
agents:
  claude:
    model: claude-sonnet-4-6
    max_tokens: 4096  # 增加到 8192 以获得更长的响应
```

---

## 🔧 故障排除

### 问题 1：API Key 无效

**错误信息：** `Error: Invalid API key`

**解决方案：**
1. 检查 API Key 是否正确复制（没有多余空格）
2. 确认 API Key 没有过期
3. 验证账户是否有足够的配额

### 问题 2：网络连接失败

**错误信息：** `Error: Connection timeout`

**解决方案：**
1. 检查网络连接
2. 如果在中国大陆，可能需要配置代理
3. 尝试使用 VPN

### 问题 3：依赖包冲突

**错误信息：** `ImportError` 或版本冲突

**解决方案：**
```bash
# 创建虚拟环境
python3 -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 问题 4：Python 版本过低

**错误信息：** `SyntaxError` 或不支持的特性

**解决方案：**
```bash
# 检查 Python 版本
python3 --version

# 如果低于 3.9，请升级 Python
```

---

## 📚 进阶使用

### 使用特定 Agent

修改 `openclaw.py` 中的 `decompose_task` 方法，强制使用特定 Agent：

```python
def decompose_task(self, user_input: str) -> List[Task]:
    # 强制使用 Claude
    return [Task("0", user_input, AgentType.CLAUDE, 0)]
```

### 添加日志记录

在 `openclaw.py` 开头添加：

```python
import logging
logging.basicConfig(level=logging.INFO)
```

### 批量处理

创建一个包含多个请求的文件 `requests.txt`，然后：

```bash
while IFS= read -r line; do
    echo "$line" | python3 openclaw.py
done < requests.txt
```

---

## 🎯 快速参考

| 命令 | 用途 |
|------|------|
| `python3 demo.py` | 演示模式（无需 API Keys） |
| `python3 openclaw.py` | 真实 API 模式 |
| `./start.sh` | 带环境检查的启动 |
| `python3 test_setup.py` | 验证环境配置 |
| `quit` / `exit` / `q` | 退出程序 |

---

## 📞 获取帮助

- 查看 `README.md` 了解项目概述
- 查看 `CLAUDE.md` 了解架构细节
- 查看 `PROJECT_STATUS.md` 了解项目状态
- 遇到问题请检查本文档的"故障排除"部分

---

**祝使用愉快！** 🎉
