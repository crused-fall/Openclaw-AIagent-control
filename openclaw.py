import asyncio
import json
import os
import yaml
from typing import List, Dict, Any
from dataclasses import dataclass
from enum import Enum
from anthropic import AsyncAnthropic
import google.generativeai as genai
from openai import AsyncOpenAI

class AgentType(Enum):
    CLAUDE = "claude"
    GEMINI = "gemini"
    CODEX = "codex"

@dataclass
class Task:
    id: str
    content: str
    agent_type: AgentType
    priority: int = 0

@dataclass
class Result:
    task_id: str
    agent_type: AgentType
    content: str
    success: bool

class AgentAdapter:
    """适配器基类"""
    async def execute(self, task: Task) -> Result:
        raise NotImplementedError

class ClaudeAdapter(AgentAdapter):
    def __init__(self, api_key: str, model: str, max_tokens: int):
        self.client = AsyncAnthropic(api_key=api_key)
        self.model = model
        self.max_tokens = max_tokens

    async def execute(self, task: Task) -> Result:
        try:
            message = await self.client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                messages=[{"role": "user", "content": task.content}]
            )
            return Result(task.id, AgentType.CLAUDE, message.content[0].text, True)
        except Exception as e:
            return Result(task.id, AgentType.CLAUDE, f"Error: {str(e)}", False)

class GeminiAdapter(AgentAdapter):
    def __init__(self, api_key: str, model: str):
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel(model)

    async def execute(self, task: Task) -> Result:
        try:
            response = await asyncio.to_thread(
                self.model.generate_content, task.content
            )
            return Result(task.id, AgentType.GEMINI, response.text, True)
        except Exception as e:
            return Result(task.id, AgentType.GEMINI, f"Error: {str(e)}", False)

class CodexAdapter(AgentAdapter):
    def __init__(self, api_key: str, model: str):
        self.client = AsyncOpenAI(api_key=api_key)
        self.model = model

    async def execute(self, task: Task) -> Result:
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": task.content}]
            )
            return Result(task.id, AgentType.CODEX, response.choices[0].message.content, True)
        except Exception as e:
            return Result(task.id, AgentType.CODEX, f"Error: {str(e)}", False)

class OpenClaw:
    """主控 Agent"""
    def __init__(self, config_path: str = "config.yaml"):
        with open(config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)

        # 替换环境变量
        for agent_name, agent_config in config['agents'].items():
            if 'api_key' in agent_config and agent_config['api_key'].startswith('${'):
                env_var = agent_config['api_key'][2:-1]
                agent_config['api_key'] = os.getenv(env_var)

        self.config = config
        self.adapters = {
            AgentType.CLAUDE: ClaudeAdapter(
                config['agents']['claude']['api_key'],
                config['agents']['claude']['model'],
                config['agents']['claude']['max_tokens']
            ),
            AgentType.GEMINI: GeminiAdapter(
                config['agents']['gemini']['api_key'],
                config['agents']['gemini']['model']
            ),
            AgentType.CODEX: CodexAdapter(
                config['agents']['codex']['api_key'],
                config['agents']['codex']['model']
            ),
        }
        self.routing_rules = config.get('routing_rules', [])

    def decompose_task(self, user_input: str) -> List[Task]:
        """任务分解逻辑"""
        tasks = []
        task_id = 0

        for rule in self.routing_rules:
            if any(keyword in user_input for keyword in rule['keywords']):
                agent_type = AgentType(rule['agent'])
                tasks.append(Task(str(task_id), user_input, agent_type, task_id))
                task_id += 1

        if not tasks:
            tasks.append(Task("0", user_input, AgentType.CLAUDE, 0))

        return tasks

    async def execute_task(self, task: Task) -> Result:
        """执行单个任务"""
        adapter = self.adapters[task.agent_type]
        return await adapter.execute(task)

    async def process(self, user_input: str) -> Dict[str, Any]:
        """主处理流程"""
        tasks = self.decompose_task(user_input)
        results = await asyncio.gather(*[self.execute_task(t) for t in tasks], return_exceptions=True)

        processed_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                processed_results.append(Result(
                    tasks[i].id, tasks[i].agent_type, f"Error: {str(result)}", False
                ))
            else:
                processed_results.append(result)

        return self.merge_results(processed_results)

    def merge_results(self, results: List[Result]) -> Dict[str, Any]:
        """结果合并策略"""
        return {
            "success": all(r.success for r in results),
            "results": [{"agent": r.agent_type.value, "content": r.content} for r in results],
            "summary": "\n".join(r.content for r in results)
        }

async def main():
    try:
        claw = OpenClaw()
        print("OpenClaw 已启动，输入 'quit' 退出\n")

        while True:
            user_input = input("用户: ").strip()
            if user_input.lower() in ['quit', 'exit', 'q']:
                print("再见！")
                break

            if not user_input:
                continue

            print("\n处理中...\n")
            result = await claw.process(user_input)

            if result['success']:
                print("结果:")
                print(result['summary'])
            else:
                print("部分任务失败:")
                for r in result['results']:
                    if not r.get('success', True):
                        print(f"- {r['agent']}: {r['content']}")
            print("\n" + "-" * 50 + "\n")

    except KeyboardInterrupt:
        print("\n\n程序已中断")
    except Exception as e:
        print(f"错误: {str(e)}")

if __name__ == "__main__":
    asyncio.run(main())
