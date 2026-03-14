# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

OpenClaw is a multi-AI collaboration system that orchestrates multiple AI agents (Claude, Gemini, Codex) to handle user requests in parallel. The main controller decomposes tasks based on keywords and routes them to appropriate agents, then merges results.

## Architecture

- **OpenClaw**: Main controller class that handles task decomposition, parallel execution, and result merging
- **AgentAdapter**: Base class for AI service adapters (ClaudeAdapter, GeminiAdapter, CodexAdapter)
- **Task/Result**: Data models using dataclasses for task representation and execution results
- **AgentType**: Enum defining available agent types

The system uses asyncio for concurrent task execution with `asyncio.gather()` for parallel agent calls.

## Development Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run demo mode (no API keys needed)
python3 demo.py

# Run with real APIs (requires API keys)
python3 openclaw.py

# Use startup script with environment check
./start.sh

# Test environment setup
python3 test_setup.py

# Set required environment variables
export ANTHROPIC_API_KEY="your-key"
export GOOGLE_API_KEY="your-key"
export OPENAI_API_KEY="your-key"
```

## Configuration

`config.yaml` defines:
- Agent configurations (API keys via environment variables, models, parameters)
- Routing rules with keyword-based task assignment
- Model specifications: claude-sonnet-4-6, gemini-2.0-flash-exp, gpt-4

## Current Implementation Status

The adapters currently use mock implementations with `asyncio.sleep()`. Real API integration is marked with TODO comments in:
- `ClaudeAdapter.execute()` - line 33
- `GeminiAdapter.execute()` - line 39
- `CodexAdapter.execute()` - line 45

## Task Routing Logic

Tasks are assigned based on keyword matching in `decompose_task()`:
- "代码"/"code"/"编程"/"bug" → Claude
- "搜索"/"search"/"查找" → Gemini
- "图片"/"image"/"视频" → Gemini
- "分析"/"优化" → Codex
- Default fallback → Claude
