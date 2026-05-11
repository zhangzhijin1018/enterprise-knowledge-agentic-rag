# 分布式 Agent 事件总线架构设计

## 1. 概述

本架构基于 **Redis Streams** 实现 **A2A 协议**的分布式消息总线，用于：

1. **多 Agent 进度推送**：各 Agent 服务可以将任务执行进度写入 Redis
2. **统一 SSE 订阅**：Supervisor 消费 Redis 事件，通过 SSE 推送给前端
3. **跨进程/跨服务通信**：Workflow 节点和 API 进程可以不在同一进程

```
┌─────────────────────────────────────────────────────────────────────────┐
│                                                                         │
│   ┌─────────────┐     XADD      ┌─────────────┐     XREAD     ┌──────┐│
│   │ Analytics   │──────────────►│   Redis     │──────────────►│  Sup ││
│   │   Agent     │               │   Streams   │               │  erv ││
│   └─────────────┘               └─────────────┘               │  iso ││
│           │                                                       │  r   │
│           │                                                       └──┬───┘│
│   ┌─────────────┐                                                  │   │
│   │ RAG Agent   │──────────────────────────────────────────────────┘   │
│   └─────────────┘                                                      │
│                                                                         │
│   ┌─────────────┐                                                      │
│   │ Contract    │──────────────────────────────────────────────────────┘
│   │   Agent     │                                                      │
│   └─────────────┘                                                      │
│                                                                         │
│                            SSE                                           │
│                             │                                           │
│                             ▼                                           │
│                        ┌────────────┐                                   │
│                        │   前端     │                                   │
│                        └────────────┘                                   │
└─────────────────────────────────────────────────────────────────────────┘
```

## 2. 核心组件

### 2.1 事件 Schema (`core/common/events/schema.py`)

统一的事件数据模型：

```python
@dataclass
class AgentEvent:
    run_id: str              # 任务运行 ID
    agent_name: str          # Agent 名称
    event_type: str         # 事件类型 (progress/completed/error/...)
    status: str              # 任务状态 (running/completed/failed)
    stage: str               # 当前阶段 (sql_build/summary_generate/...)
    progress: int           # 进度 0-100
    message: str             # 人类可读消息
    data: dict              # 业务数据 (SQL、结果、图表等)
    error: dict             # 错误信息
    trace_id: str           # 追踪 ID
    conversation_id: str     # 会话 ID
    timestamp: int          # 时间戳 (毫秒)
```

### 2.2 事件类型

| 类型 | 说明 |
|------|------|
| `connected` | 连接成功 |
| `started` | 任务开始 |
| `progress` | 进度更新 |
| `stage_started` | 阶段开始 |
| `stage_completed` | 阶段完成 |
| `summary_done` | 摘要生成完成 |
| `insight_done` | 洞察生成完成 |
| `chart_done` | 图表生成完成 |
| `report_done` | 报告生成完成 |
| `completed` | 任务完成 |
| `error` | 任务失败 |
| `heartbeat` | 心跳保活 |

### 2.3 阶段枚举

**Analytics Agent 阶段**：
- `sql_build` - 构建 SQL
- `sql_execute` - 执行查询
- `summary_generate` - 生成摘要
- `insight_generate` - 生成洞察
- `chart_generate` - 生成图表
- `report_generate` - 生成报告

**RAG Agent 阶段**：
- `query_rewrite` - 查询改写
- `retrieval` - 检索
- `rerank` - 重排序
- `context_build` - 构建上下文
- `answer_generate` - 生成答案

## 3. Producer 实现 (`core/common/events/producer.py`)

### 3.1 基本用法

```python
from core.common.events import AgentEventProducer, create_progress_event

# 创建生产者
producer = AgentEventProducer()
await producer.connect()

# 发布进度事件
await producer.publish_progress(
    run_id="run_abc123",
    agent_name="analytics-agent",
    stage="sql_build",
    progress=25,
    message="正在构建 SQL...",
)

# 发布完成事件
await producer.publish_complete(
    run_id="run_abc123",
    agent_name="analytics-agent",
    message="任务完成",
    answer="分析结果...",
)

await producer.close()
```

### 3.2 事件工厂函数

```python
from core.common.events import (
    create_progress_event,
    create_complete_event,
    create_error_event,
    create_analytics_summary_event,
    create_analytics_insight_event,
    create_analytics_chart_event,
    create_analytics_report_event,
)

# 创建摘要完成事件
event = create_analytics_summary_event(
    run_id="run_abc123",
    summary={"main_text": "本月发电量同比增长 15%..."},
)
await producer.publish(event)
```

## 4. Consumer 实现 (`core/common/events/consumer.py`)

### 4.1 SSE 流消费

```python
from core.common.events.consumer import sse_event_stream

# FastAPI 端点
@router.get("/stream/{run_id}")
async def stream_progress(run_id: str) -> StreamingResponse:
    return StreamingResponse(
        sse_event_stream(run_id),
        media_type="text/event-stream",
    )
```

### 4.2 事件消费

```python
from core.common.events import AgentEventConsumer

consumer = AgentEventConsumer()
async for message in consumer.consume(run_id="run_abc123"):
    # message 是 SSE 格式的 bytes
    yield message
```

## 5. Supervisor SSE 端点

### 5.1 流式进度端点

```
GET /api/v1/stream/{run_id}
```

### 5.2 前端订阅示例

```javascript
const runId = "run_abc123";
const eventSource = new EventSource(`/api/v1/stream/${runId}`);

// 进度更新
eventSource.addEventListener('progress', (e) => {
    const data = JSON.parse(e.data);
    console.log(`进度: ${data.progress}% - ${data.message}`);
    updateProgressBar(data.progress);
});

// 摘要完成
eventSource.addEventListener('summary_done', (e) => {
    const data = JSON.parse(e.data);
    displaySummary(data.data.summary);
});

// 洞察完成
eventSource.addEventListener('insight_done', (e) => {
    const data = JSON.parse(e.data);
    displayInsights(data.data.insights);
});

// 图表完成
eventSource.addEventListener('chart_done', (e) => {
    const data = JSON.parse(e.data);
    renderChart(data.data.chart);
});

// 任务完成
eventSource.addEventListener('completed', (e) => {
    const data = JSON.parse(e.data);
    console.log("任务完成:", data);
    eventSource.close();
});

// 错误处理
eventSource.addEventListener('error', (e) => {
    const data = JSON.parse(e.data);
    console.error("错误:", data.message);
    eventSource.close();
});
```

## 6. Redis 数据结构

### 6.1 Stream Key 格式

```
events:{run_id}
```

示例：
- `events:run_abc123`
- `events:run_def456`

### 6.2 Stream 消息结构

```json
{
    "event": "{\"run_id\": \"run_abc123\", \"agent_name\": \"analytics-agent\", ...}",
    "timestamp": "1704067200000"
}
```

### 6.3 配置参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `MAX_STREAM_LENGTH` | 200 | Stream 最大消息数 |
| `STREAM_TTL_SECONDS` | 7200 | Stream TTL (2小时) |
| `HEARTBEAT_INTERVAL` | 30 | 心跳间隔 (秒) |
| `READ_BLOCK_MS` | 5000 | XREAD 阻塞时间 (毫秒) |

## 7. 多 Agent 并行推送

所有 Agent 服务共享同一个 Redis Stream 前缀，前端只需订阅一个端点：

```
前端: /api/v1/stream/{run_id}
  │
  │ SSE
  ▼
Supervisor (统一消费 Redis)
  │
  │ Redis Streams
  ▼
┌─────────────────────────────────────┐
│         events:{run_id}             │
│                                     │
│  ┌─────────┐  ┌─────────┐  ┌─────┐│
│  │Analytics│  │   RAG   │  │Conct ││
│  │  Agent  │  │  Agent  │  │Agent ││
│  └────┬────┘  └────┬────┘  └──┬──┘│
│       │            │           │   │
└───────┼────────────┼───────────┼───┘
        │            │           │
        └────────────┴───────────┘
              XADD (写入)
```

## 8. 与原有 SSE 实现的区别

| 特性 | 原实现 (`core/common/sse_progress.py`) | 新实现 (`core/common/events/`) |
|------|----------------------------------------|--------------------------------|
| 适用范围 | Analytics 专用 | 通用，所有 Agent 共用 |
| 事件格式 | 分散 | 统一 `AgentEvent` Schema |
| 多 Agent 支持 | 不支持 | 支持 |
| 模块化 | 内嵌 | 独立模块 |
| 依赖 | 依赖 Service | 独立，可复用 |

## 9. 文件结构

```
core/common/events/
├── __init__.py           # 模块导出
├── schema.py             # 事件数据模型
├── producer.py            # Redis Producer (写入)
└── consumer.py            # Redis Consumer + SSE (消费)
```

## 10. 使用建议

### 10.1 在 Agent 中集成

```python
from core.common.events import AgentEventProducer, create_progress_event

class MyAgent:
    def __init__(self):
        self._producer = AgentEventProducer()

    async def process(self, run_id: str):
        await self._producer.connect()

        # 开始
        await self._producer.publish_progress(
            run_id=run_id,
            agent_name="my-agent",
            stage="step1",
            progress=25,
            message="执行步骤1...",
        )

        # ... 业务逻辑 ...

        # 完成
        await self._producer.publish_complete(
            run_id=run_id,
            agent_name="my-agent",
            result={"answer": "..."},
        )
```

### 10.2 前端轮询兼容

如果某些场景不支持 SSE，可以使用轮询：

```python
@router.get("/stream/{run_id}/progress")
async def get_progress_status(run_id: str) -> dict:
    """获取任务进度状态（非 SSE）"""
    from core.common.events.consumer import AgentEventConsumer

    consumer = AgentEventConsumer()
    stream_key = f"events:{run_id}"

    try:
        await consumer.connect()
        exists = await consumer.client.exists(stream_key)
        if not exists:
            return {"run_id": run_id, "exists": False}

        messages = await consumer.client.xrange(stream_key, count=1)
        if messages:
            _, fields = messages[0]
            return {"run_id": run_id, "exists": True, "has_events": True}

        return {"run_id": run_id, "exists": True, "has_events": False}
    finally:
        await consumer.close()
```

## 11. 监控与运维

### 11.1 查看活跃 Stream

```bash
redis-cli KEYS "events:*"
```

### 11.2 查看 Stream 内容

```bash
redis-cli XREAD COUNT 10 STREAMS events:run_abc123 0
```

### 11.3 清理过期 Stream

Stream 设置了 TTL，会自动过期删除。也可以手动清理：

```python
await producer.cleanup(run_id="run_abc123")
```

## 12. 注意事项

1. **连接管理**：Producer/Consumer 使用后应调用 `close()`
2. **异常处理**：生产者和消费者都需要处理 Redis 连接异常
3. **断线重连**：SSE Consumer 从位置 0 开始读取，支持前端断线重连
4. **内存限制**：MAXLEN ~ 限制消息数量，防止 Redis 内存泄漏
