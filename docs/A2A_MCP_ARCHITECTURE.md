# =============================================================================
# A2A + MCP 服务化开发规划
# =============================================================================

## 概述

本项目采用 **A2A (Agent to Agent)** + **MCP (Model Context Protocol)** 混合架构：

- **A2A**：使用 `python_a2a` 库实现标准化 Agent 间通信
- **MCP**：计算密集型能力（SQL、Report）独立微服务化

## 技术选型

| 组件 | 技术 | 说明 |
|------|------|------|
| A2A 协议 | python_a2a | Google A2A 协议的 Python 实现 |
| Agent 基类 | A2AServer | python_a2a 提供的标准服务器 |
| Supervisor 调用 | 自定义 A2AClient | 直接 HTTP 调用，不依赖 AgentNetwork |

---

## 架构总览

```
┌─────────────────────────────────────────────────────────────────────────┐
│                              用户请求                                      │
│                                  │                                        │
│                                  ▼                                        │
│                     ┌─────────────────────┐                             │
│                     │   Supervisor API    │                             │
│                     │     (Port: 8000)   │                             │
│                     └──────────┬──────────┘                             │
│                                │                                         │
│           ┌────────────────────┼────────────────────┐                   │
│           │                    │                    │                     │
│           ▼                    ▼                    ▼                     │
│   ┌───────────────┐  ┌───────────────┐  ┌───────────────┐             │
│   │   RAG Agent  │  │Analytics     │  │Contract     │             │
│   │  (python_a2a)│  │(python_a2a) │  │(python_a2a) │             │
│   │  Port: 6001  │  │ Port: 6002  │  │ Port: 6003  │             │
│   └───────────────┘  └───────┬───────┘  └───────────────┘             │
│                              │                                         │
│                              │ A2A / MCP                               │
│                              ▼                                         │
│   ┌─────────────┐   ┌─────────────┐   ┌─────────────┐               │
│   │  SQL MCP   │   │Report MCP  │   │Enterprise  │               │
│   │ (Port:5001)│   │(Port:5002)│   │API (5003) │               │
│   └─────────────┘   └─────────────┘   └─────────────┘               │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 端口分配

### Agent 服务（python_a2a）

| Agent | 端口 | 说明 |
|-------|------|------|
| RAG Agent | 6001 | 知识库问答 |
| Analytics Agent | 6002 | 经营分析 |
| Contract Agent | 6003 | 合同审查 |
| Policy Agent | 6004 | 制度政策 |

### MCP 服务

| 服务 | 端口 | 说明 |
|------|------|------|
| SQL MCP | 5001 | SQL 查询服务 |
| Report MCP | 5002 | 报告生成服务 |
| Enterprise API MCP | 5003 | 集团 API 服务 |

### 入口服务

| 服务 | 端口 | 说明 |
|------|------|------|
| Supervisor | 8000 | 总控入口 |

---

## 代码示例

### Agent 实现（RAG Agent）

```python
from python_a2a import A2AServer, AgentCard, AgentSkill
from python_a2a.models import Message, TextContent, MessageRole

class RAGAgentServer(A2AServer):
    """RAG Agent - 使用 python_a2a 标准实现"""
    
    name = "rag-agent"
    version = "1.0.0"
    description = "RAG 知识库问答 Agent"
    
    def __init__(self):
        agent_card = AgentCard(
            name=self.name,
            description=self.description,
            url="http://0.0.0.0:6001",
            version=self.version,
            skills=[
                AgentSkill(id="rag_qa", name="RAG问答", description="...")
            ],
        )
        super().__init__(agent_card=agent_card, message_handler=self.handle_message)
    
    def handle_message(self, message: Message) -> Message:
        # 处理业务逻辑
        query = message.content.text
        answer = self.rag_chain.answer(query)
        
        return Message(
            content=TextContent(text=answer),
            role=MessageRole.AGENT,
            parent_message_id=message.message_id,
        )

# 启动服务
server = RAGAgentServer()
run_server(server, host="0.0.0.0", port=6001)
```

### Supervisor 调用

```python
import httpx

class A2AClient:
    """Supervisor 使用的 A2A 客户端"""
    
    def __init__(self, namespace="enterprise-agent"):
        self._endpoints = {
            "rag-agent": f"http://rag-agent-svc.{namespace}.svc.cluster.local:6001",
            "analytics-agent": f"http://analytics-agent-svc.{namespace}.svc.cluster.local:6002",
        }
    
    async def send_task(self, agent_name: str, message: str, **kwargs) -> dict:
        url = self._endpoints[agent_name]
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{url}/a2a/v1/tasks/send",
                json={"message": {"content": {"text": message}}, **kwargs}
            )
            return response.json()
```

---

## 启动方式

### 本地开发

```bash
# 启动 MCP 服务
uvicorn apps.mcp.sql_server:app --host 0.0.0.0 --port 5001

# 启动 Agent 服务
uvicorn apps.agents.rag_agent_server:app --host 0.0.0.0 --port 6001
uvicorn apps.agents.analytics_agent_server:app --host 0.0.0.0 --port 6002
uvicorn apps.agents.contract_agent_server:app --host 0.0.0.0 --port 6003
uvicorn apps.agents.policy_agent_server:app --host 0.0.0.0 --port 6004

# 启动 Supervisor
uvicorn apps.api.routers.supervisor:app --host 0.0.0.0 --port 8000
```

### K8s 部署

```bash
# 部署所有服务
./k8s/deploy.sh

# 查看服务状态
kubectl get svc -n enterprise-agent
```

---

## 文件结构

```
enterprise-knowledge-agentic-rag/
├── core/
│   └── tools/
│       └── a2a/                    # A2A 协议（基于 python_a2a）
│           └── __init__.py          # 重新导出 python_a2a
├── apps/
│   ├── mcp/                        # MCP 微服务
│   │   ├── sql_server.py           # Port: 5001
│   │   ├── report_server.py        # Port: 5002
│   │   └── enterprise_server.py    # Port: 5003
│   ├── agents/                     # Agent 服务（python_a2a）
│   │   ├── rag_agent_server.py     # Port: 6001
│   │   ├── analytics_agent_server.py # Port: 6002
│   │   ├── contract_agent_server.py # Port: 6003
│   │   └── policy_agent_server.py   # Port: 6004
│   └── api/
│       └── routers/
│           └── supervisor.py        # Port: 8000
├── k8s/                            # K8s 部署配置
└── tests/                          # 测试
```

---

## 依赖

```txt
# pyproject.toml
python-a2a>=0.5.0
```

---

## 更新记录

| 日期 | 更新内容 |
|------|----------|
| 2026-05-03 | 重构为使用 python_a2a 标准库 |
| 2026-05-03 | Supervisor 改用自研 A2AClient（不用 AgentNetwork） |
