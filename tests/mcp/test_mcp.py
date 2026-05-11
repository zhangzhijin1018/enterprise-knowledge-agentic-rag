"""
MCP 模块测试

测试 MCP 协议、服务等功能
"""

import pytest


class TestMCPSchemas:
    """测试 MCP 协议数据结构"""

    def test_mcp_request_creation(self):
        """测试 MCPRequest 创建"""
        from core.tools.mcp import MCPRequest

        request = MCPRequest(
            method="execute_query",
            params={"sql": "SELECT * FROM test"},
        )

        assert request.method == "execute_query"
        assert request.params["sql"] == "SELECT * FROM test"

    def test_mcp_response_creation(self):
        """测试 MCPResponse 创建"""
        from core.tools.mcp import MCPResponse

        response = MCPResponse(
            success=True,
            result={"rows": [{"id": 1}]},
        )

        assert response.success is True
        assert len(response.result["rows"]) == 1

    def test_mcp_error(self):
        """测试 MCPError"""
        from core.tools.mcp import MCPError

        error = MCPError(
            code="INVALID_PARAMS",
            message="参数错误",
            detail={"field": "sql"},
        )

        assert error.code == "INVALID_PARAMS"
        assert error.detail["field"] == "sql"


class TestMCPServer:
    """测试 MCP Server"""

    def test_server_creation(self):
        """测试 Server 创建"""
        from core.tools.mcp import MCPServer

        server = MCPServer(
            name="test-mcp",
            version="1.0.0",
            description="测试 MCP 服务",
        )

        assert server.name == "test-mcp"
        assert server.version == "1.0.0"

    def test_tool_registration(self):
        """测试工具注册"""
        from core.tools.mcp import MCPServer

        server = MCPServer(name="test-mcp")

        @server.tool(
            name="test_tool",
            description="测试工具",
            input_schema={
                "type": "object",
                "properties": {
                    "param1": {"type": "string"},
                },
                "required": ["param1"],
            },
        )
        def test_tool(param1: str):
            return {"result": param1}

        tools = server.list_tools()
        assert len(tools) == 1
        assert tools[0].name == "test_tool"


class TestMCPClient:
    """测试 MCP Client"""

    def test_client_creation(self):
        """测试 Client 创建"""
        from core.tools.mcp import MCPClient

        client = MCPClient(
            base_url="http://localhost:5001",
            timeout=60,
        )

        assert client.base_url == "http://localhost:5001"
        assert client.timeout == 60
