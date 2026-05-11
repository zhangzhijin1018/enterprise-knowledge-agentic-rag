# Agentic RAG 平台开发规范

## 1. 项目身份

**新疆能源集团知识与生产经营智能 Agent 平台**

```
Enterprise Knowledge Agentic RAG Platform
```

### 1.1 核心架构

```
"A2A 宏观调度 + LangGraph 微观执行" 混合架构

┌─────────────────────────────────────────────────────────────────┐
│                      API Gateway (FastAPI)                       │
└─────────────────────────────┬───────────────────────────────────┘
                              │ A2A over Redis Streams
┌─────────────────────────────▼───────────────────────────────────┐
│                   Supervisor Agent                               │
│  - 意图理解、任务路由                                            │
│  - 跨 Agent 协调                                                │
│  - 状态聚合                                                      │
└──────┬────────────────────┬────────────────────┬────────────────┘
       │ A2A               │ A2A               │ A2A
       ▼                   ▼                   ▼
┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│  RAG Agent   │    │ Analytics    │    │  Contract    │
│  (LangGraph) │    │ Agent        │    │  Agent       │
│              │    │ (LangGraph)  │    │  (LangGraph) │
└──────────────┘    └──────────────┘    └──────────────┘
```

### 1.2 三大子 Agent

| Agent | 职责 | 核心能力 |
|-------|------|----------|
| **RAG Agent** | 智能问答 | 集团制度、安全规程、设备检修、故障排查 RAG |
| **Analytics Agent** | 经营分析 | 自然语言 SQL、数据可视化、分析报告 |
| **Contract Agent** | 合同审查 | 条款抽取、风险识别、法务复核 |

---

## 2. 技术栈规范

### 2.1 宏观调度层（A2A）

```
消息总线：Redis Streams
协议：HTTP/JSON (A2A 风格)
服务化：每个 Agent 是独立 FastAPI 服务
```

**A2A 消息格式：**

```python
# Task Envelope
{
    "task_id": "task_xxx",
    "run_id": "run_xxx",
    "trace_id": "trace_xxx",
    "source_agent": "supervisor",
    "target_agent": "rag_agent",
    "task_type": "knowledge_qa",
    "input_payload": {
        "query": "...",
        "user_context": {...}
    }
}

# Result Contract
{
    "task_id": "task_xxx",
    "run_id": "run_xxx",
    "status": "succeeded|failed|waiting_review",
    "output_payload": {...},
    "error": {...}
}
```

### 2.2 微观执行层（LangGraph）

```
状态机：LangGraph StateGraph
模式：ReAct (Think -> Tool -> Reflect)
幂等保障：幂等键 + DB 状态单调推进
```

**State 设计原则：**

```python
class AgentState(TypedDict):
    # 链路追踪
    run_id: str
    trace_id: str
    conversation_id: str

    # 上下文
    user_context: UserContext
    query: str
    route: str

    # 执行状态（幂等推进）
    current_step: str
    step_status: str  # pending/running/completed/failed
    idempotency_key: str  # 幂等键

    # 结果
    retrieved_chunks: list[dict]
    tool_calls: list[dict]
    final_answer: str
    status: str
```

### 2.3 MCP 服务化

每个 MCP Server 是独立服务：

| MCP Server | 协议 | 用途 |
|------------|------|------|
| SQL MCP | HTTP | 只读查询、Schema 读取 |
| Document MCP | HTTP | 文档解析、Chunk 读取 |
| Report MCP | HTTP | 报告生成、导出 |
| RAG MCP | HTTP | 混合检索、重排序 |

### 2.4 服务部署

```
uvicorn apps.api.main:app --host 0.0.0.0 --port 8000  # API Gateway
uvicorn apps.agents.supervisor:app --port 8001        # Supervisor
uvicorn apps.agents.rag:app --port 8002               # RAG Agent
uvicorn apps.agents.analytics:app --port 8003         # Analytics Agent
uvicorn apps.agents.contract:app --port 8004           # Contract Agent
uvicorn apps.mcp.sql:app --port 8005                  # SQL MCP
uvicorn apps.mcp.document:app --port 8006             # Document MCP
```

---

## 3. 目录结构规范

```
enterprise-knowledge-agentic-rag/
├── apps/
│   ├── api/                      # API Gateway
│   │   ├── main.py
│   │   ├── deps.py
│   │   ├── routers/
│   │   └── schemas/
│   │
│   ├── agents/                   # Agent 服务
│   │   ├── supervisor/           # Supervisor Agent
│   │   │   ├── main.py
│   │   │   ├── router.py
│   │   │   └── routes.py
│   │   │
│   │   ├── rag/                  # RAG Agent
│   │   │   ├── main.py
│   │   │   ├── router.py
│   │   │   ├── workflow/         # LangGraph 微工作流
│   │   │   │   ├── graph.py
│   │   │   │   ├── nodes.py
│   │   │   │   ├── state.py
│   │   │   │   └── adapter.py
│   │   │   └── tools/            # Agent 专用工具
│   │   │
│   │   ├── analytics/            # Analytics Agent
│   │   │   ├── main.py
│   │   │   ├── router.py
│   │   │   ├── workflow/
│   │   │   └── tools/
│   │   │
│   │   └── contract/             # Contract Agent
│   │       ├── main.py
│   │       ├── router.py
│   │       ├── workflow/
│   │       └── tools/
│   │
│   ├── mcp/                      # MCP 服务
│   │   ├── sql/
│   │   │   ├── main.py
│   │   │   ├── router.py
│   │   │   └── contracts.py
│   │   │
│   │   ├── document/
│   │   │   ├── main.py
│   │   │   └── router.py
│   │   │
│   │   └── registry/             # MCP 注册中心
│   │       └── registry.py
│   │
│   └── worker/                   # Celery Worker
│
├── core/
│   ├── common/                    # 通用组件
│   │   ├── a2a/                  # A2A 协议实现
│   │   │   ├── envelope.py       # Task Envelope
│   │   │   ├── contract.py       # Result Contract
│   │   │   ├── dispatcher.py     # 任务分发器
│   │   │   └── consumer.py       # 任务消费者
│   │   │
│   │   ├── redis_streams/        # Redis Streams 封装
│   │   │   ├── producer.py
│   │   │   └── consumer.py
│   │   │
│   │   └── sse_progress.py       # SSE 进度推送
│   │
│   ├── agent/                     # Agent 核心
│   │   ├── supervisor/           # Supervisor 实现
│   │   │   ├── router.py         # 意图路由
│   │   │   ├── coordinator.py    # 任务协调
│   │   │   └── aggregator.py     # 结果聚合
│   │   │
│   │   └── contracts/            # Agent 契约
│   │       └── task_envelope.py
│   │
│   ├── rag/                      # RAG 核心
│   │   ├── retrieval/
│   │   │   ├── dense_retriever.py
│   │   │   ├── sparse_retriever.py
│   │   │   ├── hybrid_search.py
│   │   │   └── reranker.py
│   │   │
│   │   ├── retrieval_chain.py    # 检索链路
│   │   └── context_builder.py    # 上下文构建
│   │
│   ├── llm/                      # LLM 接入
│   │   └── gateway.py
│   │
│   ├── tools/                    # 工具抽象
│   │   ├── base.py               # Tool 基类
│   │   ├── registry.py           # Tool 注册
│   │   └── mcp_client.py         # MCP 客户端
│   │
│   └── observability/            # 可观测性
│       ├── trace.py
│       └── metrics.py
│
├── docs/                         # 文档
│   ├── ARCHITECTURE.md
│   ├── A2A_DESIGN.md
│   ├── LANGGRAPH_DESIGN.md
│   └── MCP_DESIGN.md
│
└── tests/
    ├── unit/
    ├── integration/
    └── e2e/
```

---

## 4. A2A 宏观调度规范

### 4.1 消息流

```
用户请求
    ↓
API Gateway (鉴权、路由)
    ↓
Supervisor (意图理解、任务分解)
    ↓ XADD task to Redis Stream
Redis Streams (task:{agent_type})
    ↓
目标 Agent Consumer (接收任务)
    ↓
LangGraph 微工作流 (执行)
    ↓
Result Contract (结果封装)
    ↓ XADD result to Redis Stream
Redis Streams (result:{task_id})
    ↓
Supervisor Consumer (结果收集)
    ↓
API Gateway (响应用户)
```

### 4.2 幂等保障

```python
# 每个任务有唯一幂等键
idempotency_key = f"{run_id}:{current_step}:{retry_count}"

# DB 状态单调推进
if current_status in ["completed", "failed"]:
    raise IdempotencyError("Task already processed")

# 只在状态为 pending/running 时更新
update_task_run_status(run_id, new_status, idempotency_key)
```

### 4.3 Supervisor 职责

```python
class SupervisorAgent:
    """宏观调度职责"""

    async def route_task(self, query: str, user_context) -> TaskEnvelope:
        """1. 意图理解"""
        intent = await self.understand_intent(query)

        """2. 任务分解"""
        if intent.type == "knowledge_qa":
            return TaskEnvelope(
                target_agent="rag_agent",
                task_type="knowledge_qa"
            )
        elif intent.type == "data_analysis":
            return TaskEnvelope(
                target_agent="analytics_agent",
                task_type="data_analysis"
            )
        elif intent.type == "contract_review":
            return TaskEnvelope(
                target_agent="contract_agent",
                task_type="contract_review"
            )

        """3. 多 Agent 协作"""
        # 对于复杂任务，可能需要多个 Agent 协作
```

---

## 5. LangGraph 微观执行规范

### 5.1 RAG Agent 状态机

```
┌─────────────┐
│   START     │
└──────┬──────┘
       │ query
       ▼
┌─────────────┐
│  RETRIEVE   │ ← Think: 需要检索哪些知识库
└──────┬──────┘
       │ chunks
       ▼
┌─────────────┐
│   RERANK    │ ← Think: 哪些 chunk 最相关
└──────┬──────┘
       │ top_chunks
       ▼
┌─────────────┐
│   GENERATE  │ ← Think: 如何基于证据回答
└──────┬──────┘
       │ answer
       ▼
┌─────────────┐
│  EVALUATE   │ ← Reflect: 答案是否可信？
└──────┬──────┘
       │ decision
       ▼
   ┌───┴───┐
   │ good   │ → FINISH
   │ need_review │ → Human Review
   │ retry  │ → RETRIEVE
   └───┬───┘
```

### 5.2 Analytics Agent 状态机

```
┌─────────────┐
│   START     │
└──────┬──────┘
       │ query
       ▼
┌─────────────┐
│   PARSE     │ ← LLM 解析意图，提取 metric/time_range
└──────┬──────┘
       │ intent
       ▼
┌─────────────┐
│  VALIDATE   │ ← 槽位校验
└──────┬──────┘
       │ slots
       ▼
   ┌───┴───┐
   │complete│ → BUILD_SQL
   │missing │ → CLARIFY → 用户补充 → 回到 VALIDATE
   └───┬───┘
       │
       ▼
┌─────────────┐
│  BUILD_SQL  │ ← SQL 模板 + LLM 增强
└──────┬──────┘
       │ sql
       ▼
┌─────────────┐
│  GUARD_SQL  │ ← SQL 安全校验
└──────┬──────┘
       │ checked_sql
       ▼
┌─────────────┐
│ EXECUTE_SQL │ ← MCP 调用 SQL 查询
└──────┬──────┘
       │ result
       ▼
┌─────────────┐
│  SUMMARIZE  │ ← LLM 生成摘要/图表/报告
└──────┬──────┘
       │ final_answer
       ▼
┌─────────────┐
│   FINISH    │
└─────────────┘
```

### 5.3 Contract Agent 状态机

```
┌─────────────┐
│   START     │
└──────┬──────┘
       │ contract_file
       ▼
┌─────────────┐
│   PARSE     │ ← 合同解析、条款抽取
└──────┬──────┘
       │ clauses
       ▼
┌─────────────┐
│   COMPARE   │ ← 与标准模板对比
└──────┬──────┘
       │ diff
       ▼
┌─────────────┐
│  IDENTIFY   │ ← 风险识别、等级划分
└──────┬──────┘
       │ risks
       ▼
┌─────────────┐
│  EVALUATE   │ ← 风险评估
└──────┬──────┘
       │ decision
       ▼
   ┌───┴───┐
   │ low   │ → FINISH (通过)
   │medium │ → FINISH (带警告)
   │ high  │ → Human Review
   │critical│ → 拒绝自动通过
   └───┬───┘
       │
       ▼
┌─────────────┐
│   FINISH    │ ← 生成审查报告
└─────────────┘
```

---

## 6. MCP 服务化规范

### 6.1 MCP Server 结构

```python
# apps/mcp/sql/main.py
from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="SQL MCP Server")

class SQLQueryRequest(BaseModel):
    """SQL 查询请求"""
    sql: str
    data_source: str
    timeout_ms: int = 5000
    row_limit: int = 500

class SQLQueryResponse(BaseModel):
    """SQL 查询响应"""
    columns: list[str]
    rows: list[list]
    row_count: int
    latency_ms: float

@app.post("/execute", response_model=SQLQueryResponse)
async def execute_query(req: SQLQueryRequest):
    """执行只读 SQL 查询"""
    # 实现...
```

### 6.2 MCP Client 调用

```python
# core/tools/mcp_client.py
class MCPClient:
    def __init__(self, base_url: str, timeout: int = 30):
        self.base_url = base_url
        self.timeout = timeout

    async def call(self, endpoint: str, request: BaseModel) -> BaseModel:
        """统一 MCP 调用"""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}{endpoint}",
                json=request.model_dump(),
                timeout=self.timeout
            )
            return response.json()
```

---

## 7. 代码规范

### 7.1 中文注释要求

所有核心业务代码必须包含中文注释：

```python
class SupervisorAgent:
    """Supervisor Agent - 宏观任务调度器。

    职责：
    - 理解用户意图
    - 分解任务到子 Agent
    - 协调多 Agent 协作
    - 聚合最终结果
    """

    async def route_task(self, query: str) -> TaskEnvelope:
        """根据用户 query 路由到对应 Agent。

        Args:
            query: 用户自然语言查询

        Returns:
            TaskEnvelope: 包含目标 Agent 和任务参数的信封

        路由逻辑：
        - 包含"合同"、"风险"、"条款" → contract_agent
        - 包含"分析"、"统计"、"报表" → analytics_agent
        - 其他知识问答 → rag_agent
        """
```

### 7.2 状态机注释

```python
def _route_after_retrieve(state: AgentState) -> str:
    """根据检索结果决定后续走向。

    ReAct 的 Reflect 阶段：
    - 如果检索到足够证据 → GENERATE
    - 如果证据不足 → 重新 RETRIEVE（最多 3 次）
    - 如果多次检索仍不足 → 返回"知识库中未找到明确依据"
    """

    chunks = state.get("retrieved_chunks", [])
    retry_count = state.get("retry_count", 0)

    if len(chunks) >= 3:
        return "generate"
    elif retry_count < 3:
        return "retrieve"
    else:
        return "insufficient_evidence"
```

---

## 8. 开发流程

### 8.1 新增 Agent 流程

```bash
# 1. 创建 Agent 目录
mkdir -p apps/agents/{new_agent}
mkdir -p core/agent/{new_agent}

# 2. 实现 LangGraph 微工作流
# core/agent/new_agent/graph.py
# core/agent/new_agent/nodes.py
# core/agent/new_agent/state.py

# 3. 实现 Agent 服务
# apps/agents/new_agent/main.py
# apps/agents/new_agent/router.py

# 4. 注册到 Supervisor
# core/agent/supervisor/router.py

# 5. 编写测试
# tests/unit/test_new_agent.py
# tests/integration/test_new_agent_workflow.py
```

### 8.2 新增 MCP Server 流程

```bash
# 1. 创建 MCP 目录
mkdir -p apps/mcp/{new_mcp}

# 2. 实现 MCP 服务
# apps/mcp/new_mcp/main.py
# apps/mcp/new_mcp/router.py
# apps/mcp/new_mcp/contracts.py

# 3. 注册到 MCP Registry
# apps/mcp/registry/registry.py

# 4. Agent 中引入使用
# core/tools/mcp_client.py
```

---

## 9. 验证清单

新增功能后，确保：

- [ ] 代码可导入（无 ImportError）
- [ ] FastAPI 服务可启动（uvicorn 不报错）
- [ ] A2A 消息可正确分发
- [ ] LangGraph 状态机可正常流转
- [ ] MCP 调用可返回结果
- [ ] 中文注释完整
- [ ] 单元测试通过

---

## 10. 参考项目映射

### 10.1 RAG 参考项目 (`integrated_qa_system`)

| 原项目模块 | 可复用部分 | 你的项目落地 |
|-----------|-----------|-------------|
| `rag_qa/core/document_processor.py` | 文档处理流程 | `core/rag/processing/` |
| `rag_qa/core/vector_store.py` | Milvus 封装 | `core/rag/retrieval/` |
| `rag_qa/core/strategy_selector.py` | 检索策略 | `core/rag/retrieval_chain.py` |
| `rag_qa/core/query_classifier.py` | 查询分类 | `core/agent/supervisor/router.py` |
| `rag_qa/edu_text_spliter/` | 文本切分 | `core/rag/chunking/` |
| `rag_qa/edu_document_loaders/` | 多种文档加载器 | `core/rag/loaders/` |

### 10.2 SmartVoyage 参考项目 (`SmartVoyage`)

这是你提供的 A2A + MCP + Agent 参考项目，结构清晰，是学习服务化 Agent 架构的最佳模板。

#### 10.2.1 项目架构

```
SmartVoyage/
├── app.py                    # Streamlit 前端入口（Agent 网络 + 意图识别）
├── main.py                   # 主程序入口
├── main_prompts.py           # Prompt 模板管理
├── config.py                 # 配置管理
├── create_logger.py          # 日志创建
│
├── a2a_server/               # A2A Agent 服务
│   ├── weather_server.py     # 天气查询 Agent（核心示例）
│   ├── ticket_server.py      # 票务查询 Agent
│   └── order_server.py       # 票务订购 Agent
│
├── mcp_server/               # MCP 服务
│   ├── mcp_weather_server.py # 天气 MCP Server（FastMCP）
│   ├── mcp_ticket_server.py  # 票务 MCP Server
│   └── mcp_order_server.py  # 订单 MCP Server
│
├── utils/
│   ├── spider_weather.py     # 天气数据爬取
│   └── format.py             # 格式化工具
│
└── test/                     # 测试文件
```

#### 10.2.2 A2A 实现分析

**核心库**：`python-a2a`（标准 A2A 协议实现）

```python
from python_a2a import A2AServer, AgentCard, AgentSkill, run_server

# Agent 卡片定义
agent_card = AgentCard(
    name="WeatherQueryAssistant",
    description="基于LangChain提供天气查询服务的助手",
    url="http://localhost:5005",
    version="1.0.0",
    capabilities={"streaming": True, "memory": True},
    skills=[
        AgentSkill(
            name="execute weather query",
            description="执行天气查询，返回天气数据库结果",
            examples=["北京 2025-07-30 天气", "上海未来5天"]
        )
    ]
)

# A2A Server 实现
class WeatherQueryServer(A2AServer):
    def __init__(self):
        super().__init__(agent_card=agent_card)

    def handle_task(self, task):
        # 处理任务逻辑
        return task
```

**关键特性**：
- 继承 `A2AServer`，实现 `handle_task` 方法
- `AgentCard` 描述 Agent 能力和技能
- `run_server()` 启动 A2A 服务

#### 10.2.3 MCP 实现分析

**核心库**：`mcp` + `FastMCP`

```python
from mcp.server.fastmcp import FastMCP

# 创建 FastMCP 实例
weather_mcp = FastMCP(
    name="WeatherTools",
    instructions="天气查询工具，基于 weather_data 表。",
    host="127.0.0.1",
    port=8002
)

@weather_mcp.tool(name="query_weather", description="查询天气数据")
def query_weather(sql: str) -> str:
    return service.execute_query(sql)

# 启动 MCP 服务
weather_mcp.run(transport="streamable-http")
```

**MCP Client 调用**：

```python
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

async def get_weather(sql):
    async with streamablehttp_client("http://127.0.0.1:8002/mcp") as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool("query_weather", {"sql": sql})
            return result
```

#### 10.2.4 前端 + A2A 整合分析

**Streamlit 前端** (`app.py`)：

```python
from python_a2a import AgentNetwork, Message, TextContent, MessageRole, Task

# 初始化 Agent 网络
network = AgentNetwork(name="Travel Assistant Network")
network.add("WeatherQueryAssistant", "http://localhost:5005")

# 意图识别
intents, user_queries, follow_up = intent_agent(prompt)

# A2A 调用
for intent in intents:
    if intent == "weather":
        agent = network.get_agent("WeatherQueryAssistant")
        message = Message(content=TextContent(text=chat_history), role=MessageRole.USER)
        task = Task(id="task-" + str(uuid.uuid4()), message=message.to_dict())
        raw_response = asyncio.run(agent.send_task_async(task))
```

#### 10.2.5 可复用设计模式

| 模式 | SmartVoyage 实现 | 你的项目落地 |
|------|------------------|-------------|
| **A2A Server** | 继承 `A2AServer` | `core/tools/a2a/` 已有，但可简化 |
| **MCP Server** | FastMCP + tool decorator | `core/tools/mcp/` 已有，但可迁移到 FastMCP |
| **意图路由** | LLM 识别 + 意图分发 | `core/agent/supervisor/` |
| **Agent Card** | 描述能力 + skills | `core/tools/a2a/contracts/models.py` |
| **Prompt 模板** | 分离管理 | `core/agent/workflows/*/prompts.py` |

#### 10.2.6 推荐迁移到你的项目

**1. MCP 服务迁移到 FastMCP**

当前你的项目用自定义 MCP，建议迁移到 FastMCP：

```python
# apps/mcp/sql/main.py - 使用 FastMCP
from mcp.server.fastmcp import FastMCP

sql_mcp = FastMCP(name="SQLTools", host="0.0.0.0", port=8005)

@sql_mcp.tool(name="execute_readonly_query", description="执行只读SQL查询")
async def execute_query(req: SQLQueryRequest) -> SQLQueryResponse:
    # 实现...
    return result

# 启动
sql_mcp.run(transport="streamable-http")
```

**2. A2A Server 迁移到 python-a2a**

当前你的项目用自定义 TaskEnvelope，建议迁移到 python-a2a：

```python
# apps/agents/rag/main.py - 使用 python-a2a
from python_a2a import A2AServer, AgentCard, run_server

rag_agent_card = AgentCard(
    name="RAGAgent",
    description="提供智能问答服务",
    url="http://localhost:8002",
    skills=[
        AgentSkill(
            name="knowledge_qa",
            description="基于知识库的问答",
            examples=["集团差旅报销标准是什么？"]
        )
    ]
)

class RAGAgentServer(A2AServer):
    def handle_task(self, task):
        # 处理任务
        return task
```

**3. 意图识别模式复用**

```python
# main_prompts.py 中的意图识别模式
intent_prompt = ChatPromptTemplate.from_template("""
识别意图：{intents}
可支持：['policy_qa', 'safety_qa', 'equipment_qa', 'contract_review', 'business_analysis']
""")

# 你的项目可以复用这个模式
```

### 10.3 当前项目 A2A/MCP 实现 (`enterprise-knowledge-agentic-rag`)

| 模块 | 文件 | 说明 |
|------|------|------|
| **A2A 契约** | `core/tools/a2a/contracts/models.py` | TaskEnvelope、ResultContract、AgentCardRef |
| **A2A 网关** | `core/tools/a2a/gateway/a2a_gateway.py` | 本地委托 + 远端委托占位 |
| **Supervisor** | `core/agent/supervisor/supervisor_service.py` | 宏观调度服务 |
| **SQL MCP** | `core/tools/mcp/sql_mcp_server.py` | 只读查询、健康检查 |
| **Report MCP** | `core/tools/mcp/report_mcp_server.py` | 报告生成 |
| **LangGraph Analytics** | `core/agent/workflows/analytics/` | 经营分析 9 节点工作流 |

### 10.3 可直接复用的架构模式

#### A2A 宏观调度模式
```python
# core/tools/a2a/contracts/models.py 核心模型
class TaskEnvelope(BaseModel):
    task_id: str
    run_id: str
    trace_id: str
    source_agent: str
    target_agent: str
    task_type: str
    input_payload: dict

class ResultContract(BaseModel):
    task_id: str
    run_id: str
    status: str  # succeeded/failed/waiting_review
    output_payload: dict
    error: dict | None
```

#### LangGraph 节点模式
```python
# core/agent/workflows/analytics/nodes.py
class AnalyticsWorkflowNodes:
    async def analytics_entry(self, state: dict) -> dict:
        """入口节点 - 校验 query、创建会话"""

    async def analytics_plan(self, state: dict) -> dict:
        """规划节点 - LLM 解析意图"""

    async def analytics_build_sql(self, state: dict) -> dict:
        """SQL 构建节点"""

    async def analytics_execute_sql(self, state: dict) -> dict:
        """SQL 执行节点 - 调用 MCP"""
```

#### MCP Server 模式
```python
# core/tools/mcp/sql_mcp_server.py
class SQLMCPServer:
    def execute_readonly_query(self, request: SQLReadQueryRequest) -> SQLReadQueryResponse:
        """执行只读 SQL 查询"""
        # 1. 参数校验
        # 2. SQL 安全检查
        # 3. 执行查询
        # 4. 结果脱敏
        # 5. 返回结果
```

### 10.4 参考项目 → 你的项目映射表

| 功能 | 参考来源 | 落地位置 |
|------|----------|----------|
| A2A 协议 | `core/tools/a2a/` | 直接复用 |
| MCP Server | `core/tools/mcp/` | 直接复用 + 扩展 |
| LangGraph 工作流 | `core/agent/workflows/analytics/` | 模板参考 |
| **文档解析** | `core/tools/local/parser.py` | ✅ 已完整，比参考项目更好 |
| **OCR** | `core/tools/local/ocr.py` | ✅ 已完整，支持 PaddleOCR + PP-Structure |
| **文档切片** | `core/services/document_parse_service.py` | ✅ 已完整 |
| **向量入库** | `core/services/document_ingestion_service.py` | ✅ 已完整 |
| RAG 检索 | `core/services/retrieval_service.py` | 待完善：Hybrid Search + Rerank |
| 合同审查 | SmartVoyage 模式 + 全新设计 | 待开发 |

---

## 11. 完整项目开发指南

### 11.1 重要更新

**2026-05-03 更新**：项目文档处理能力已超过参考项目，无需从 integrated_qa_system 复用！

| 模块 | 状态 | 说明 |
|------|------|------|
| **文档解析** | ✅ 完整 | `parser.py` (748行) + OCR (369行) |
| **文档切片** | ✅ 完整 | `document_parse_service.py` |
| **向量入库** | ✅ 完整 | `document_ingestion_service.py` |
| **Analytics Agent** | ✅ 完整 | 9节点 LangGraph |
| **A2A/MCP** | ✅ 基础 | TaskEnvelope + 简单实现 |
| **RAG 检索** | 🔲 待完善 | 需要 Hybrid Search + Rerank |
| **RAG Agent** | ❌ 待开发 | 需要新建 |
| **合同审查 Agent** | ❌ 待开发 | 需要全新设计 |

### 11.2 完整开发规划

请参考 `docs/PROJECT_COMPLETE_DEVELOPMENT_GUIDE.md` 获取：
- 完整开发阶段划分（7个阶段）
- 每个阶段的详细代码模板
- 完整的文件清单
- 接续开发指南

### 11.3 快速开始

```bash
# 1. 安装依赖
cd /Users/zhangzhijin/study/黑马学习/agent/enterprise-knowledge-agentic-rag
pip install -e .

# 2. 启动后端服务
uvicorn apps.api.main:app --reload --port 8000

# 3. 启动 Celery Worker
celery -A apps.worker.celery_app worker --loglevel=info
```

### 11.4 开发顺序建议

| 顺序 | 阶段 | 核心文件 | 依赖 |
|------|------|----------|------|
| 1 | RAG 检索链路 | `core/rag/retrieval/` | vectorstore, embedding |
| 2 | RAG Agent | `core/agent/workflows/rag/` | 阶段1 |
| 3 | 合同审查 Agent | `core/contracts/` | parser (已有) |
| 4 | A2A Redis Streams | `core/common/a2a/` | 现有A2A |
| 5 | Human Review | `core/review/` | 阶段2,3 |
| 6 | 前端页面 | `apps/web/` | 阶段1-5 |
| 7 | Evaluation | `core/evaluation/` | 阶段1-3 |
