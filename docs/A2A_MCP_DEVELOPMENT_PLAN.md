# A2A + MCP 服务化开发规划

## 概述

本项目采用 **A2A (Agent to Agent)** + **MCP (Model Context Protocol)** 混合架构：

- **A2A**：Supervisor 总控 Agent 调度各业务 Agent
- **MCP**：计算密集型能力（SQL、Report）独立微服务化，与 Agent 紧耦合的能力（Parser）内置

---

## 架构总览

```
┌─────────────────────────────────────────────────────────────────────────┐
│                              用户请求                                      │
│                                  │                                        │
│                                  ▼                                        │
│                     ┌─────────────────────┐                             │
│                     │   Supervisor API     │                             │
│                     │     (总控入口)       │                             │
│                     └──────────┬──────────┘                             │
│                                │                                         │
│           ┌────────────────────┼────────────────────┐                   │
│           │                    │                    │                     │
│           ▼                    ▼                    ▼                     │
│   ┌───────────────┐  ┌───────────────┐  ┌───────────────┐             │
│   │   RAG Agent   │  │Analytics Agent│  │Contract Agent│             │
│   │  (A2A Client) │  │ (A2A Client)  │  │ (A2A Client) │             │
│   │ 内置 Parser   │  │  A2A → SQL MCP│  │ 内置 Parser   │             │
│   └───────────────┘  └───────────────┘  └───────────────┘             │
│                                                                          │
│           ┌─────────────────────────────────────────────────────┐       │
│           │                    A2A 网络层                          │       │
│           │              (HTTP/JSON + K8s DNS)                   │       │
│           └─────────────────────────────────────────────────────┘       │
│                                │                                         │
│         ┌──────────────────────┼──────────────────────┐                │
│         │                      │                      │                  │
│         ▼                      ▼                      ▼                   │
│  ┌─────────────┐        ┌─────────────┐        ┌─────────────┐          │
│  │  SQL MCP    │        │ Report MCP  │        │Enterprise   │          │
│  │  (微服务)   │        │  (微服务)   │        │API MCP      │          │
│  │  Port: 5001 │        │  Port: 5002 │        │  Port: 5003 │          │
│  └─────────────┘        └─────────────┘        └─────────────┘          │
│                                                                          │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │                      K8s 基础设施层                                  │  │
│  │  Service (负载均衡) │ DNS (服务发现) │ ConfigMap │ Ingress         │  │
│  └───────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## MCP 服务化决策表

| MCP 类型 | 服务化方式 | 端口 | 原因 |
|----------|------------|------|------|
| SQL MCP | **微服务** | 5001 | 计算密集、需要独立审计、可能被多 Agent 共用 |
| Report MCP | **微服务** | 5002 | LLM 调用独立、可扩展、需要状态管理 |
| Enterprise API MCP | **微服务** | 5003 | 对外接口、需要独立认证限流、多 Agent 共用 |
| Parser MCP | **内置库** | - | 与 Agent 紧耦合、轻量级、无状态、不需要复用 |
| File MCP | **内置库** | - | 本地文件系统调用、安全要求高、不暴露为服务 |

---

## Agent 端口分配

| Agent | 端口 | 说明 |
|-------|------|------|
| RAG Agent | 6001 | 知识库问答 |
| Analytics Agent | 6002 | 经营分析 |
| Contract Agent | 6003 | 合同审查 |
| Policy Agent | 6004 | 制度政策 |
| Supervisor | 8000 | 总控入口（API 端口） |

---

## MCP 服务端口分配

| MCP | 端口 | 说明 |
|-----|------|------|
| SQL MCP | 5001 | SQL 查询服务 |
| Report MCP | 5002 | 报告生成服务 |
| Enterprise API MCP | 5003 | 集团 API 服务 |

---

## 完整开发任务清单

### 第一阶段：基础设施层

| 序号 | 任务 | 状态 | 产出物 |
|------|------|------|--------|
| 1 | A2A 协议定义 | ✅ DONE | `core/tools/a2a/schemas.py` |
| 2 | K8sA2AClient | ✅ DONE | `core/tools/a2a/client.py` |
| 3 | Agent 基类 | ✅ DONE | `core/tools/a2a/base_agent.py` |
| 4 | MCP Gateway | ✅ DONE | `core/tools/mcp/gateway.py` |
| 5 | MCP Client | ✅ DONE | `core/tools/mcp/client.py` |
| 6 | MCP Server 框架 | ✅ DONE | `core/tools/mcp/server.py` |

### 第二阶段：MCP 服务层

| 序号 | 任务 | 状态 | 产出物 |
|------|------|------|--------|
| 7 | SQL MCP Server | ✅ DONE | `apps/mcp/sql_server.py` |
| 8 | Report MCP Server | ✅ DONE | `apps/mcp/report_server.py` |
| 9 | Parser MCP（内置） | ✅ DONE | `core/tools/local/parser.py` |
| 10 | Enterprise API MCP | ✅ DONE | `apps/mcp/enterprise_server.py` |

### 第三阶段：Agent 服务层

| 序号 | 任务 | 状态 | 产出物 |
|------|------|------|--------|
| 11 | RAG Agent | ✅ DONE | `apps/agents/rag_agent_server.py` |
| 12 | Analytics Agent | ✅ DONE | `apps/agents/analytics_agent_server.py` |
| 13 | Contract Agent | ✅ DONE | `apps/agents/contract_agent_server.py` |
| 14 | Policy Agent | ✅ DONE | `apps/agents/policy_agent_server.py` |

### 第四阶段：Supervisor 总控层

| 序号 | 任务 | 状态 | 产出物 |
|------|------|------|--------|
| 15 | 意图识别模块 | ✅ DONE | `core/agent/intent_detector.py` |
| 16 | 路由引擎 | ✅ DONE | `core/agent/routing_engine.py` |
| 17 | Supervisor API | ✅ DONE | `apps/api/routers/supervisor.py` |
| 18 | 多轮对话管理 | ✅ DONE | `core/agent/conversation_manager.py` |

### 第五阶段：第三方包改进

| 序号 | 任务 | 状态 | 产出物 |
|------|------|------|--------|
| 19 | python_a2a 封装 | TODO | `core/tools/a2a/wrapper.py` |
| 20 | LangGraph 封装 | TODO | `core/agent/langgraph_wrapper.py` |
| 21 | LLM Gateway 增强 | TODO | `core/llm/gateway.py` |

### 第六阶段：K8s 部署

| 序号 | 任务 | 状态 | 产出物 |
|------|------|------|--------|
| 22 | MCP K8s Deployment | TODO | `k8s/mcp/` |
| 23 | Agent K8s Deployment | TODO | `k8s/agents/` |
| 24 | Supervisor K8s | TODO | `k8s/supervisor/` |
| 25 | ConfigMap | TODO | `k8s/configmap.yaml` |
| 26 | Helm Chart | TODO | `helm/enterprise-agent/` |

### 第七阶段：测试与文档

| 序号 | 任务 | 状态 | 产出物 |
|------|------|------|--------|
| 27 | A2A 集成测试 | TODO | `tests/a2a/` |
| 28 | MCP 服务测试 | TODO | `tests/mcp/` |
| 29 | 端到端测试 | TODO | `tests/e2e/` |
| 30 | 文档 | TODO | `docs/A2A_MCP_ARCHITECTURE.md` |

---

## A2A 协议定义

### Task Envelope（任务包）

```python
class TaskEnvelope(BaseModel):
    task_id: str                      # 任务唯一 ID
    trace_id: str                     # 链路追踪 ID
    conversation_id: str               # 会话 ID
    source_agent: str                 # 来源 Agent
    target_agent: str                 # 目标 Agent
    intent: str                       # 意图类型
    message: Message                  # 消息内容
    context: dict                    # 上下文信息
    slot_snapshot: dict               # 槽位快照
    created_at: datetime             # 创建时间
    priority: str = "normal"          # 优先级
    timeout: int = 300               # 超时时间（秒）
```

### Result Contract（结果契约）

```python
class ResultContract(BaseModel):
    task_id: str                      # 任务 ID
    trace_id: str                     # 链路追踪 ID
    conversation_id: str              # 会话 ID
    status: str                       # succeeded / failed / partial
    result: dict                      # 执行结果
    error: dict | None                # 错误信息
    artifacts: list[Artifact]         # 产物列表
    updated_at: datetime              # 更新时间
```

---

## K8s 服务发现机制

### DNS 格式

```
http://<service-name>.<namespace>.svc.cluster.local
```

### 环境变量覆盖

```
# 优先级：环境变量 > K8s DNS
RAG_AGENT_URL=http://rag-agent-svc.default.svc.cluster.local:6001
SQL_MCP_URL=http://sql-mcp-svc.default.svc.cluster.local:5001
```

### K8sA2AClient 配置

```python
class K8sA2AClient:
    def __init__(
        self,
        namespace: str = "default",
        default_timeout: int = 300
    ):
        self.namespace = namespace
        self.default_timeout = default_timeout
        self._agent_urls = {}

    def register_agent(self, agent_name: str, service_name: str, port: int = 80):
        """注册 Agent，自动解析 K8s DNS 地址"""
        env_key = f"{agent_name.upper()}_URL"
        if env_key in os.environ:
            url = os.environ[env_key]
        else:
            url = f"http://{service_name}.{self.namespace}.svc.cluster.local:{port}"
        self._agent_urls[agent_name] = url

    async def send_task(self, agent_name: str, task: TaskEnvelope) -> ResultContract:
        """发送任务到指定 Agent"""
        ...

    async def send_task_stream(self, agent_name: str, task: TaskEnvelope):
        """发送任务并获取流式响应（SSE）"""
        ...
```

---

## 执行顺序

```
阶段一（基础设施）
    │
    ├─ 1. A2A 协议定义
    ├─ 2. K8sA2AClient
    ├─ 3. Agent 基类
    ├─ 4. MCP Gateway
    ├─ 5. MCP Client
    └─ 6. MCP Server 框架
              │
              ▼
阶段二（MCP 服务）
    │
    ├─ 7. SQL MCP Server
    ├─ 8. Report MCP Server
    └─ 10. Enterprise API MCP
              │
              ▼
阶段三（Agent 服务）
    │
    ├─ 11. RAG Agent
    ├─ 12. Analytics Agent
    ├─ 13. Contract Agent
    └─ 14. Policy Agent
              │
              ▼
阶段四（Supervisor）
    │
    ├─ 15. 意图识别
    ├─ 16. 路由引擎
    ├─ 17. Supervisor API
    └─ 18. 多轮对话
              │
              ▼
阶段五（第三方包改进）
    │
    ├─ 19. python_a2a 封装
    ├─ 20. LangGraph 封装
    └─ 21. LLM Gateway 增强
              │
              ▼
阶段六（K8s 部署）
    │
    └─ 22-26. 部署配置
              │
              ▼
阶段七（测试）
    │
    └─ 27-30. 测试与文档
```

---

## 开发规范

### 代码组织

```
enterprise-knowledge-agentic-rag/
├── core/
│   ├── tools/
│   │   ├── a2a/                    # A2A 协议实现
│   │   │   ├── schemas.py          # A2A 数据结构
│   │   │   ├── client.py          # K8sA2AClient
│   │   │   ├── base_agent.py      # Agent 基类
│   │   │   └── wrapper.py         # python_a2a 封装
│   │   ├── mcp/                    # MCP 协议实现
│   │   │   ├── gateway.py         # MCP Gateway
│   │   │   ├── client.py         # MCP Client
│   │   │   └── server.py         # MCP Server 框架
│   │   └── local/
│   │       └── parser.py         # 内置 Parser
│   ├── agent/
│   │   ├── intent_detector.py     # 意图识别
│   │   ├── router.py              # 路由引擎
│   │   └── conversation_manager.py # 多轮对话
│   └── llm/
│       └── gateway.py             # LLM Gateway
├── apps/
│   ├── agents/                     # Agent 服务
│   │   ├── rag_agent.py
│   │   ├── analytics_agent.py
│   │   ├── contract_agent.py
│   │   └── policy_agent.py
│   ├── mcp/                        # MCP 微服务
│   │   ├── sql_mcp_server.py
│   │   ├── report_mcp_server.py
│   │   └── enterprise_mcp_server.py
│   └── api/
│       └── routers/
│           └── supervisor.py      # Supervisor API
├── k8s/
│   ├── mcp/
│   ├── agents/
│   └── supervisor/
└── helm/
    └── enterprise-agent/
```

### 命名规范

- Agent 服务：`xxx-agent`（如 `rag-agent`）
- MCP 服务：`xxx-mcp`（如 `sql-mcp`）
- K8s Service：`xxx-svc`（如 `rag-agent-svc`）

### 通信协议

- Agent 之间：A2A HTTP/JSON
- Agent 调用 MCP：A2A HTTP/JSON
- 流式响应：SSE（Server-Sent Events）

---

## 更新记录

| 日期 | 更新内容 |
|------|----------|
| 2026-05-03 | 初始创建规划文档 |
| 2026-05-03 | 完成阶段一（基础设施层）：A2A 协议、K8sA2AClient、Agent 基类、MCP Gateway/Client/Server |
| 2026-05-03 | 完成阶段二（MCP 服务层）：SQL MCP Server、Report MCP Server、Enterprise API MCP Server |
| 2026-05-03 | 完成阶段三（Agent 服务层）：RAG/Analytics/Contract/Policy Agent HTTP Server |
| 2026-05-03 | 完成阶段四（Supervisor 总控层）：意图识别、路由引擎、Supervisor API、多轮对话管理 |

---

## 已完成文件清单

### A2A 模块 (`core/tools/a2a/`)

```
core/tools/a2a/
├── __init__.py       # 模块导出
├── schemas.py         # A2A 协议数据结构
├── client.py         # K8sA2AClient
└── base_agent.py     # Agent 基类
```

### MCP 模块 (`core/tools/mcp/`)

```
core/tools/mcp/
├── __init__.py       # 模块导出
├── schemas.py        # MCP 协议数据结构
├── gateway.py        # MCP Gateway
├── client.py         # MCP Client
└── server.py         # MCP Server 框架
```

### MCP 服务 (`apps/mcp/`)

```
apps/mcp/
├── sql_server.py              # SQL MCP HTTP Server (Port: 5001)
├── report_server.py           # Report MCP HTTP Server (Port: 5002)
└── enterprise_server.py       # Enterprise API MCP HTTP Server (Port: 5003)
```

### Agent 服务 (`apps/agents/`)

```
apps/agents/
├── rag_agent_server.py        # RAG Agent HTTP Server (Port: 6001)
├── analytics_agent_server.py   # Analytics Agent HTTP Server (Port: 6002)
├── contract_agent_server.py   # Contract Agent HTTP Server (Port: 6003)
└── policy_agent_server.py     # Policy Agent HTTP Server (Port: 6004)
```
