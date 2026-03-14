#!/usr/bin/env python3
"""测试 OpenClaw 配置是否正确"""
import os
import sys

def check_env_vars():
    """检查环境变量"""
    required_vars = ['ANTHROPIC_API_KEY', 'GOOGLE_API_KEY', 'OPENAI_API_KEY']
    missing = []

    for var in required_vars:
        if not os.getenv(var):
            missing.append(var)

    if missing:
        print(f"❌ 缺少环境变量: {', '.join(missing)}")
        print("\n请设置环境变量:")
        for var in missing:
            print(f"  export {var}='your-key-here'")
        return False

    print("✓ 所有环境变量已设置")
    return True

def check_imports():
    """检查依赖包"""
    try:
        import anthropic
        import google.generativeai
        import openai
        import yaml
        print("✓ 所有依赖包已安装")
        return True
    except ImportError as e:
        print(f"❌ 缺少依赖包: {e}")
        print("\n请运行: pip install -r requirements.txt")
        return False

def check_config():
    """检查配置文件"""
    if not os.path.exists('config.yaml'):
        print("❌ 找不到 config.yaml")
        return False
    print("✓ 配置文件存在")
    return True

if __name__ == '__main__':
    print("OpenClaw 环境检查\n" + "="*50 + "\n")

    checks = [
        check_config(),
        check_imports(),
        check_env_vars()
    ]

    print("\n" + "="*50)
    if all(checks):
        print("✓ 环境配置完成，可以运行: python openclaw.py")
        sys.exit(0)
    else:
        print("❌ 请修复上述问题后重试")
        sys.exit(1)
