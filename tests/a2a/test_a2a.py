"""
A2A 模块测试

使用 python_a2a 库的标准化测试
"""

import pytest


class TestA2AIntegration:
    """测试 A2A 集成"""

    def test_python_a2a_import(self):
        """测试 python_a2a 导入"""
        from python_a2a import A2AServer, AgentCard, AgentSkill
        from python_a2a.models import Message, TextContent, MessageRole

        assert A2AServer is not None
        assert AgentCard is not None
        assert Message is not None

    def test_agent_card_creation(self):
        """测试 AgentCard 创建"""
        from python_a2a import AgentCard

        card = AgentCard(
            name="test-agent",
            description="Test Agent",
            url="http://localhost:6001",
            version="1.0.0",
        )

        assert card.name == "test-agent"
        assert card.url == "http://localhost:6001"

    def test_message_creation(self):
        """测试 Message 创建"""
        from python_a2a.models import Message, TextContent, MessageRole

        msg = Message(
            content=TextContent(text="Hello"),
            role=MessageRole.USER,
        )

        assert msg.role == MessageRole.USER
        assert msg.content.text == "Hello"


class TestSupervisorA2AClient:
    """测试 Supervisor A2A 客户端"""

    def test_client_initialization(self):
        """测试客户端初始化"""
        from apps.api.routers.supervisor import A2AClient

        client = A2AClient(namespace="test-ns")
        assert client.namespace == "test-ns"

    def test_get_agent_url(self):
        """测试获取 Agent URL"""
        from apps.api.routers.supervisor import A2AClient

        client = A2AClient(namespace="test")

        url = client.get_agent_url("rag-agent")
        assert "rag-agent" in url
        assert "6001" in url

        url = client.get_agent_url("analytics-agent")
        assert "analytics-agent" in url
        assert "6002" in url

    def test_list_agents(self):
        """测试列出 Agent"""
        from apps.api.routers.supervisor import A2AClient

        client = A2AClient()
        agents = list(client._agent_endpoints.keys())

        assert "rag-agent" in agents
        assert "analytics-agent" in agents
        assert "contract-agent" in agents
        assert "policy-agent" in agents
