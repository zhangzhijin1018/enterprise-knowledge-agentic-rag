#!/usr/bin/env python3
"""测试 DeepSeek API 连接"""

import sys
import os

# 加载 .env 文件
from dotenv import load_dotenv
load_dotenv()

sys.path.insert(0, "/Users/zhangzhijin/study/黑马学习/agent/enterprise-knowledge-agentic-rag")

def test_deepseek_connection():
    """测试 DeepSeek API 连接"""
    from core.llm import OpenAICompatibleLLMGateway
    from core.llm.models import LLMMessage

    # 从环境变量读取配置
    base_url = os.getenv("LLM_BASE_URL", "https://api.deepseek.com/v1")
    api_key = os.getenv("LLM_API_KEY", "")
    model_name = os.getenv("LLM_MODEL_NAME", "deepseek-v4-flash")
    timeout = int(os.getenv("LLM_TIMEOUT_SECONDS", "60"))

    print("=" * 60)
    print("DeepSeek API 配置测试")
    print("=" * 60)

    print(f"\n配置信息:")
    print(f"  LLM Base URL: {base_url}")
    print(f"  LLM API Key: {api_key[:15]}..." if api_key else "  LLM API Key: 未配置")
    print(f"  LLM Model: {model_name}")
    print(f"  LLM Timeout: {timeout}s")

    if not api_key:
        print("\n错误: LLM_API_KEY 未配置!")
        return False

    # 创建设置对象（模拟）
    class TestSettings:
        llm_base_url = base_url
        llm_api_key = api_key
        llm_model_name = model_name
        llm_timeout_seconds = timeout
        llm_provider = "deepseek"

    settings = TestSettings()

    # 创建 Gateway
    gateway = OpenAICompatibleLLMGateway(settings=settings)

    # 测试调用
    print("\n正在测试调用...")
    try:
        response = gateway.chat(
            messages=[
                LLMMessage(role="system", content="你是一个专业的助手。"),
                LLMMessage(role="user", content="请用一句话介绍自己"),
            ],
            model=model_name,
        )

        print(f"\n调用成功!")
        print(f"模型: {response.model}")
        print(f"响应:\n{response.content}")

        if response.usage:
            print(f"\nToken 使用:")
            print(f"  Prompt: {response.usage.get('prompt_tokens', 'N/A')}")
            print(f"  Completion: {response.usage.get('completion_tokens', 'N/A')}")
            print(f"  Total: {response.usage.get('total_tokens', 'N/A')}")

        return True

    except Exception as e:
        print(f"\n调用失败: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_llm_content_generator():
    """测试 LLM 内容生成器"""
    print("\n" + "=" * 60)
    print("测试 LLM Content Generator")
    print("=" * 60)

    try:
        from core.analytics.llm_content_generator import LLMContentGenerator
        from core.llm import OpenAICompatibleLLMGateway
        from core.llm.models import LLMMessage

        # 从环境变量读取配置
        base_url = os.getenv("LLM_BASE_URL", "https://api.deepseek.com/v1")
        api_key = os.getenv("LLM_API_KEY", "")
        model_name = os.getenv("LLM_MODEL_NAME", "deepseek-v4-flash")

        class TestSettings:
            llm_base_url = base_url
            llm_api_key = api_key
            llm_model_name = model_name
            llm_timeout_seconds = 60
            llm_provider = "deepseek"

        settings = TestSettings()
        gateway = OpenAICompatibleLLMGateway(settings=settings)

        generator = LLMContentGenerator(
            llm_gateway=gateway,
            model=model_name,
            temperature=0.7,
        )

        # 测试数据
        slots = {
            "metric": "发电量",
            "time_range": {"label": "2024年3月"},
            "org_scope": {"value": "新疆区域"},
            "compare_target": "yoy",
            "group_by": "station",
        }

        rows = [
            {"station": "哈密站", "current_value": 12345, "compare_value": 11000},
            {"station": "吐鲁番站", "current_value": 9876, "compare_value": 9000},
            {"station": "克拉玛依站", "current_value": 7654, "compare_value": 7000},
        ]

        print("\n正在生成摘要...")
        result = generator.generate_all(
            original_query="查询新疆区域2024年3月发电量，和去年对比",
            slots=slots,
            rows=rows,
            columns=["station", "current_value", "compare_value"],
            row_count=3,
        )

        print(f"\n生成成功!")
        print(f"\n摘要:\n{result['summary']['main_text']}")

        print(f"\n洞察:")
        for insight in result['insights']['insights']:
            print(f"  [{insight['type']}] {insight['title']}: {insight['summary']}")

        print(f"\n图表描述:\n{result['chart_desc']['description']}")

        return True

    except Exception as e:
        print(f"\n生成失败: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    # 测试 1: DeepSeek 连接
    success1 = test_deepseek_connection()

    if success1:
        # 测试 2: 内容生成
        success2 = test_llm_content_generator()
    else:
        print("\n由于连接测试失败，跳过内容生成测试")
        success2 = False

    print("\n" + "=" * 60)
    print("测试结果汇总")
    print("=" * 60)
    print(f"DeepSeek 连接测试: {'通过' if success1 else '失败'}")
    print(f"内容生成测试: {'通过' if success2 else '失败'}")
