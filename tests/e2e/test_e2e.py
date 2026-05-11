"""
端到端测试

测试完整的用户请求链路
"""

import pytest


class TestSupervisorE2E:
    """Supervisor 端到端测试"""

    def test_intent_detection(self):
        """测试意图识别"""
        from core.agent.intent_detector import detect_intent, IntentType

        # 测试经营分析意图
        result = detect_intent("查询本月发电量")
        assert result.intent_type == IntentType.ANALYTICS_QUERY

        # 测试 RAG 意图
        result = detect_intent("安全生产注意事项有哪些")
        assert result.intent_type in [IntentType.RAG_QA, IntentType.SAFETY_QA]

        # 测试合同意图
        result = detect_intent("审查采购合同")
        assert result.intent_type == IntentType.CONTRACT_REVIEW

    def test_routing_decision(self):
        """测试路由决策"""
        from core.agent.intent_detector import detect_intent
        from core.agent.routing_engine import route_request

        # 测试经营分析路由
        intent = detect_intent("查询本月收入")
        route = route_request(intent)
        assert route.target.agent_name == "analytics-agent"

        # 测试 RAG 路由
        intent = detect_intent("如何申请年假")
        route = route_request(intent)
        assert route.target.agent_name == "rag-agent"


class TestConversationManagement:
    """对话管理测试"""

    def test_conversation_creation(self):
        """测试会话创建"""
        from core.agent.conversation_manager import ConversationManager

        manager = ConversationManager()
        conv = manager.create_conversation(
            conversation_id="test_001",
            user_id="user_001",
        )

        assert conv.conversation_id == "test_001"
        assert conv.user_id == "user_001"
        assert conv.status.value == "active"

    def test_add_message(self):
        """测试添加消息"""
        from core.agent.conversation_manager import ConversationManager

        manager = ConversationManager()
        conv = manager.create_conversation("test_001", "user_001")

        manager.add_user_message("test_001", "msg_001", "你好")
        manager.add_assistant_message("test_001", "msg_002", "你好，有什么可以帮您？")

        conv = manager.get_conversation("test_001")
        assert len(conv.messages) == 2
        assert conv.messages[0].role == "user"
        assert conv.messages[1].role == "assistant"

    def test_slot_update(self):
        """测试槽位更新"""
        from core.agent.conversation_manager import ConversationManager

        manager = ConversationManager()
        conv = manager.create_conversation("test_001", "user_001")

        manager.update_slots(
            "test_001",
            slots={"metric": "发电量", "time_range": "本月"},
        )

        conv = manager.get_conversation("test_001")
        assert conv.slots["metric"] == "发电量"
        assert "metric" not in conv.missing_slots


class TestIntegration:
    """集成测试"""

    def test_agent_endpoints(self):
        """测试 Agent 端点定义"""
        from core.agent.routing_engine import RoutingEngine

        engine = RoutingEngine()
        agents = engine.get_available_agents()

        # 验证所有 Agent 都已注册
        expected = ["rag-agent", "analytics-agent", "contract-agent", "policy-agent"]
        for agent in expected:
            assert agent in agents
