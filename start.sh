#!/bin/bash

echo "OpenClaw 启动脚本"
echo "================="
echo ""

# 检查环境变量
missing_vars=()
[ -z "$ANTHROPIC_API_KEY" ] && missing_vars+=("ANTHROPIC_API_KEY")
[ -z "$GOOGLE_API_KEY" ] && missing_vars+=("GOOGLE_API_KEY")
[ -z "$OPENAI_API_KEY" ] && missing_vars+=("OPENAI_API_KEY")

if [ ${#missing_vars[@]} -ne 0 ]; then
    echo "❌ 缺少环境变量: ${missing_vars[*]}"
    echo ""
    echo "请先设置环境变量:"
    for var in "${missing_vars[@]}"; do
        echo "  export $var='your-key-here'"
    done
    echo ""
    echo "或者创建 .env 文件并使用 source .env"
    exit 1
fi

echo "✓ 环境变量已设置"
echo ""
echo "启动 OpenClaw..."
echo ""

python3 openclaw.py
