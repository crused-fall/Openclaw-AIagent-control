#!/usr/bin/env python3
"""OpenClaw 演示模式 - 无需 API Keys"""
import asyncio
from dataclasses import dataclass
from enum import Enum
from typing import List, Dict, Any

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

class DemoAdapter:
    """演示适配器"""
    def __init__(self, agent_name: str):
        self.agent_name = agent_name

    async def execute(self, task: Task) -> Result:
        await asyncio.sleep(0.3)
        response = f"{self.agent_name} 回复: 我已收到您的请求「{task.content}」并进行了处理。"
        return Result(task.id, task.agent_type, response, True)

class OpenClawDemo:
    """演示版本"""
    def __init__(self):
        self.adapters = {
            AgentType.CLAUDE: DemoAdapter("Claude"),
            AgentType.GEMINI: DemoAdapter("Gemini"),
            AgentType.CODEX: DemoAdapter("GPT-4"),
        }
        self.routing_rules = [
            {"keywords": ["代码", "code", "编程", "bug"], "agent": "claude"},
            {"keywords": ["搜索", "search", "查找"], "agent": "gemini"},
            {"keywords": ["图片", "image", "视频"], "agent": "gemini"},
            {"keywords": ["分析", "优化"], "agent": "codex"},
        ]

    def decompose_task(self, user_input: str) -> List[Task]:
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

    async def process(self, user_input: str) -> Dict[str, Any]:
        tasks = self.decompose_task(user_input)
        print(f"  → 分配给 {len(tasks)} 个 Agent: {[t.agent_type.value for t in tasks]}")
        results = await asyncio.gather(*[self.adapters[t.agent_type].execute(t) for t in tasks])
        return {
            "success": all(r.success for r in results),
            "results": [{"agent": r.agent_type.value, "content": r.content} for r in results],
            "summary": "\n".join(r.content for r in results)
        }

async def main():
    print("=" * 60)
    print("OpenClaw 演示模式 (无需 API Keys)")
    print("=" * 60)
    print("\n这是一个演示版本，展示多 Agent 协作的工作流程")
    print("输入 'quit' 退出\n")

    claw = OpenClawDemo()

    while True:
        user_input = input("用户: ").strip()
        if user_input.lower() in ['quit', 'exit', 'q']:
            print("再见！")
            break
        if not user_input:
            continue

        print("\n处理中...")
        result = await claw.process(user_input)
        print("\n结果:")
        print(result['summary'])
        print("\n" + "-" * 60 + "\n")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n程序已中断")
