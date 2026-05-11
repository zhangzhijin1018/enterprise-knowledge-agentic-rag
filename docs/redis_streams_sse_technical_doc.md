# Redis Streams SSE 进度推送技术文档

## 1. 概述

### 1.1 什么是 Redis Streams SSE

Redis Streams SSE 是一种基于 Redis Streams 的 Server-Sent Events (SSE) 实现，用于将服务端实时进度推送给客户端（如前端浏览器）。

### 1.2 为什么需要它

在企业级应用中，任务执行往往是异步的（如经营分析查询、文档处理、报告生成等）。客户端需要实时了解任务执行进度，传统方案有：

| 方案 | 原理 | 缺点 |
|------|------|------|
| **轮询** | 前端定时请求状态接口 | 服务器压力大、延迟高、浪费资源 |
| **WebSocket** | 双向通信 | 实现复杂、占用连接多 |
| **轮询 + 内存队列** | 前端轮询，服务端内存队列推送 | **无法跨进程、多 worker 部署** |
| **Redis Streams SSE** | 服务端推送 + Redis 中转 | ✅ 支持跨进程、低延迟、实现简单 |

### 1.3 本项目应用场景

- 经营分析任务执行进度推送
- 文档处理进度跟踪
- 报告生成状态通知
- 任何需要实时反馈的异步任务

---

## 2. 技术架构

### 2.1 整体数据流

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           Redis Streams SSE 数据流                            │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   ┌──────────────────┐                                                      │
│   │   Workflow 节点   │  (LangGraph Workflow / Celery Worker)                 │
│   │                  │                                                      │
│   │  1. 创建 run_id  │                                                      │
│   │  2. 执行各步骤   │                                                      │
│   │  3. 推送进度     │                                                      │
│   └────────┬─────────┘                                                      │
│            │                                                                │
│            │ XADD (发布消息)                                                │
│            ▼                                                                │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │                        Redis Streams                                 │   │
│   │                                                                       │   │
│   │   Key: sse:progress:{run_id}                                         │   │
│   │   Type: Stream                                                       │   │
│   │   消息格式:                                                          │   │
│   │   ┌─────────────────────────────────────────────────────────┐       │   │
│   │   │  event: "progress"                                        │       │   │
│   │   │  data: {"run_id": "xxx", "progress": 50, ...}            │       │   │
│   │   │  timestamp: 1704067200000                                  │       │   │
│   │   └─────────────────────────────────────────────────────────┘       │   │
│   │                                                                       │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│            │                                                                │
│            │ XREAD (订阅消费)                                               │
│            ▼                                                                │
│   ┌──────────────────┐                                                      │
│   │  SSE Endpoint    │  (FastAPI / API Server)                             │
│   │                  │                                                      │
│   │  GET /stream/xxx │                                                      │
│   └────────┬─────────┘                                                      │
│            │                                                                │
│            │ SSE (text/event-stream)                                        │
│            ▼                                                                │
│   ┌──────────────────┐                                                      │
│   │     浏览器        │                                                      │
│   │                  │                                                      │
│   │  EventSource API │                                                      │
│   └──────────────────┘                                                      │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 2.2 核心组件

| 组件 | 类名 | 职责 |
|------|------|------|
| 连接池管理器 | `RedisConnectionPool` | 管理 Redis 异步连接池，全局单例 |
| 发布器 | `RedisSSEPublisher` | 向 Redis Stream 发布进度消息 |
| 消费者 | `RedisSSEConsumer` | 从 Redis Stream 消费消息，转换为 SSE 格式 |
| 追踪器 | `RedisSSEProgressTracker` | 封装 Publisher，提供友好的步骤追踪接口 |

### 2.3 多 Worker 部署支持

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          多 Worker 部署架构                                  │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │                           Redis Cluster                              │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                                      ▲                                      │
│                                      │ XADD                                 │
│           ┌─────────────────────────┼─────────────────────────┐           │
│           │                         │                         │           │
│           ▼                         ▼                         ▼           │
│   ┌───────────────┐         ┌───────────────┐         ┌───────────────┐      │
│   │  Worker 1     │         │  Worker 2     │         │  API Server   │      │
│   │  (Celery)     │         │  (LangGraph)  │         │              │      │
│   │               │         │               │         │ SSE Stream   │      │
│   │ XADD 进度     │         │ XADD 进度     │         │ XREAD 消费   │      │
│   └───────────────┘         └───────────────┘         └───────────────┘      │
│                                                                              │
│   优势：                                                                    │
│   - Worker 和 API 可以是完全独立的进程/容器                                    │
│   - 支持水平扩展                                                             │
│   - 消息持久化，断线可重连                                                    │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Redis 数据结构

### 3.1 Stream Key 命名规则

```
sse:progress:{run_id}
```

示例：
- `sse:progress:run_abc123` - run_id 为 `run_abc123` 的任务进度 Stream

### 3.2 消息字段结构

每条 Redis Stream 消息包含以下字段：

| 字段名 | 类型 | 说明 | 示例 |
|--------|------|------|------|
| `event` | string | 事件类型 | `"progress"`, `"complete"`, `"error"` |
| `data` | string (JSON) | 事件数据 | `{"run_id": "xxx", "progress": 50}` |
| `timestamp` | string | 时间戳（毫秒） | `"1704067200000"` |

**XADD 具体示例：**

```python
# Key 格式
stream_key = f"sse:progress:{run_id}"  # 例如: "sse:progress:run_abc123"

# Value 格式（Hash 字段）
payload = {
    "event": "progress",                                        # 事件类型
    "data": '{"run_id": "run_abc123", "progress": 25}',       # JSON 字符串
    "timestamp": "1746234567890",                               # 时间戳
}

# 实际 XADD 调用
await self.redis.xadd(stream_key, payload)
```

### 3.3 消费机制详解

#### 3.3.1 有消息就立即取，没消息才等

Consumer 使用 `XREAD BLOCK` 阻塞等待，具体行为：

```python
messages = await self.redis.xread(
    {self.stream_key: self._last_message_id},  # 从上次位置开始读
    count=100,        # 一次最多取 100 条
    block=30000,      # 阻塞最多 30 秒（毫秒）
)

if not messages:
    # 超时了，没有新消息，发送心跳
    yield 心跳
    continue
else:
    # 有新消息，立即返回并处理
    for msg in messages:
        yield msg
```

**实际效果：**

| 场景 | Consumer 行为 |
|------|--------------|
| Workflow XADD 一条 | Consumer 马上读到（< 100ms） |
| XADD 后停了 30 秒没新消息 | Consumer 等 30 秒超时，发心跳，继续等 |
| 又 XADD 新消息 | Consumer 马上读到 |

**所以不是轮询，是阻塞等待：**
- Redis 端有新消息 → 立即唤醒 Consumer
- Redis 端没新消息 → 等 30 秒超时后发心跳

#### 3.3.2 为什么 count=100

`count=100` 不是限制每次只取一条，而是**设置批量读取上限**：

```python
# XREAD 返回格式
messages = [
    ("sse:progress:run_abc", [
        ("1706234567890-0", {"event": "progress", "data": "...", "timestamp": "..."}),
        ("1706234567891-0", {"event": "progress", "data": "...", "timestamp": "..."}),
        ...
    ])
]

# 内部用 for 循环逐条处理
for stream_key, message_list in messages:
    for message_id, fields in message_list:
        yield self._format_sse_event(...)  # 逐条 yield 给前端
```

**设置 count=100 的原因：**

1. **批量读取更高效**：一次网络往返取多条，减少 RPC 开销
2. **处理速度快**：如果推送很快，100 条可能一瞬间就处理完了
3. **避免频繁阻塞**：减少 `xread` 调用次数

**实际场景**：经营分析任务通常只有 5-10 条消息（connected + progress × 5 + complete），count=100 是上限，实际不会达到。

### 3.4 完整数据流时序图

```
时间线
─────────────────────────────────────────────────────────────────────────────────▶

1. 前端 POST /query
   │
   ▼
2. 后端创建 run_id，初始化 RedisSSEProgressTracker
   │
   ▼
3. Workflow 执行，每步调用 tracker.step()
   │
   ├──▶ XADD progress event ──▶ Redis Stream ──▶ XREAD 返回
   │
   ▼
4. LLM 生成完成，调用 tracker.publish_summary()
   │
   ├──▶ XADD summary_done event
   │
   ▼
5. 所有完成，调用 tracker.finish()
   │
   ├──▶ XADD complete event
   │
   ▼
6. 前端 GET /stream/{run_id}
   │
   ▼
7. RedisSSEConsumer XREAD BLOCK 阻塞等待
   │
   ◀──────────────────────────────────────── XREAD 立即返回所有事件
   │
   ▼
8. yield SSE 消息给前端
   │
   ▼
9. 前端收到 complete/error，关闭连接
```

**推送与消费的真实延迟**：< 100ms（几乎实时）

### 3.5 事件类型

| 事件类型 | 触发时机 | 说明 |
|----------|----------|------|
| `connected` | 客户端连接成功 | 通知前端 SSE 连接已建立 |
| `progress` | 每个步骤完成 | 推送当前进度百分比和步骤信息 |
| `heartbeat` | 每 30 秒 | 保活心跳，防止连接超时 |
| `complete` | 任务成功完成 | 推送最终结果 |
| `error` | 任务执行失败 | 推送错误信息 |

### 3.6 进度数据结构 (data 字段)

```json
{
  "run_id": "run_abc123",
  "status": "running",
  "current_step": "执行查询",
  "progress": 50,
  "step_key": "sql_execute",
  "steps": [
    {"key": "intent_parse", "label": "理解问题", "status": "completed"},
    {"key": "slot_validate", "label": "验证参数", "status": "completed"},
    {"key": "sql_execute", "label": "执行查询", "status": "running"},
    {"key": "generate_summary", "label": "生成摘要", "status": "pending"}
  ]
}
```

---

## 4. 性能优化

### 4.1 连接池管理

```python
# 全局单例连接池，避免每次操作创建/销毁连接
class RedisConnectionPool:
    _instance = None

    async def get_instance(self):
        if self._instance is None:
            async with self._lock:
                if self._instance is None:
                    self._instance = self()
                    await self._instance._initialize()
        return self._instance
```

**配置参数：**

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `redis_pool_max_connections` | 50 | 最大连接数 |
| `redis_socket_timeout` | 5.0s | Socket 超时 |
| `redis_socket_connect_timeout` | 5.0s | 连接超时 |

### 4.2 消息发布优化

```python
# 使用 XADD + MAXLEN ~ 近似裁剪，开销低
await self.redis.xadd(
    self.stream_key,
    payload,
    maxlen=self.max_stream_len,  # 最大消息数
    approximate=True,             # 近似裁剪（更高效）
)
```

**优势：**
- `MAXLEN ~` 是近似裁剪，不会精确计数，性能更好
- 避免 Redis Stream 无限增长导致内存泄漏

### 4.3 消息消费优化

```python
# XREAD BLOCK 阻塞等待，减少 CPU 占用
messages = await self.redis.xread(
    {self.stream_key: self._last_message_id},
    count=100,              # 批量读取，减少网络往返
    block=30000,            # 阻塞 30 秒
)
```

**优势：**
- `BLOCK` 参数让 Redis 在没有新消息时阻塞，而不是轮询
- `count=100` 一次读取多条消息，减少网络往返

### 4.4 性能对比

| 指标 | 轮询方案 | WebSocket | Redis Streams SSE |
|------|----------|-----------|-------------------|
| 实时性 | ❌ 延迟高 | ✅ 实时 | ✅ 实时 |
| 服务器压力 | ❌ 高 | 中 | ✅ 低 |
| 断线重连 | ❌ 不支持 | 支持 | ✅ 支持 |
| 跨进程 | ❌ 不支持 | ❌ 不支持 | ✅ 支持 |
| 实现复杂度 | 低 | 高 | 中 |

---

## 5. 内存与资源管理

### 5.1 消息数量限制

```python
# 每个 Stream 最多保留 100 条消息
redis_sse_max_stream_len: int = Field(
    default=100,
    description="Redis SSE Stream 最大消息数",
)
```

**设计原因：**
- 进度消息是临时数据，不需要永久保留
- 限制消息数量防止 Redis 内存无限增长

### 5.2 Stream TTL 自动清理

```python
# Stream TTL = 1 小时
redis_sse_stream_ttl_seconds: int = Field(
    default=3600,
    description="Redis SSE Stream TTL（秒）",
)
```

**清理机制：**
1. **主动清理**：任务完成后调用 `cleanup()` 删除 Stream
2. **TTL 兜底**：即使未主动清理，1 小时后 Redis 自动删除
3. **MAXLEN 限制**：Stream 超过 100 条时自动裁剪旧消息

### 5.3 内存预估

假设：
- 同时运行 1000 个任务
- 每个任务 10 条进度消息
- 每条消息约 500 字节

```
内存占用 ≈ 1000 × 10 × 500 = 5 MB
```

即使有 10000 个并发任务，内存占用也只有约 50 MB，完全可接受。

---

## 6. 使用方式

### 6.1 在 Workflow 中使用 Tracker

```python
from core.common.sse_progress import RedisSSEProgressTracker, get_redis_pool

async def analytics_workflow(run_id: str, query: str):
    """经营分析 Workflow 示例"""

    steps = [
        {"key": "intent_parse", "label": "理解问题"},
        {"key": "slot_validate", "label": "验证参数"},
        {"key": "sql_execute", "label": "执行查询"},
        {"key": "generate_summary", "label": "生成摘要"},
    ]

    # 使用上下文管理器，自动管理资源
    async with RedisSSEProgressTracker(run_id, steps=steps) as tracker:
        # 步骤 1：解析意图
        await tracker.step("intent_parse")
        intent = await parse_intent(query)

        # 步骤 2：验证参数
        await tracker.step("slot_validate")
        await validate_slots(intent)

        # 步骤 3：执行查询
        await tracker.step("sql_execute")
        result = await execute_sql(intent)

        # 步骤 4：生成摘要
        await tracker.step("generate_summary")
        summary = await generate_summary(result)

        # 完成
        await tracker.finish(result={
            "summary": summary,
            "data": result
        })
```

### 6.2 前端订阅进度

```javascript
const runId = "run_abc123";
const eventSource = new EventSource(`/api/v1/analytics/stream/${runId}`);

// 连接成功
eventSource.addEventListener('connected', (e) => {
    console.log('SSE 已连接:', JSON.parse(e.data));
});

// 进度更新
eventSource.addEventListener('progress', (e) => {
    const data = JSON.parse(e.data);
    updateProgressBar(data.progress);           // 更新进度条
    updateCurrentStep(data.current_step);       // 更新当前步骤
    updateStepsList(data.steps);                // 更新步骤列表
});

// 任务完成
eventSource.addEventListener('complete', (e) => {
    const data = JSON.parse(e.data);
    showResult(data.result);                    // 显示结果
    eventSource.close();                        // 关闭连接
});

// 任务失败
eventSource.addEventListener('error', (e) => {
    const data = JSON.parse(e.data);
    showError(data.message);                    // 显示错误
    eventSource.close();
});
```

---

## 7. 配置参数

所有配置项在 `core/config/settings.py` 中定义：

### 7.1 Redis 连接配置

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `redis_url` | `redis://localhost:6379/0` | Redis 连接地址 |
| `redis_pool_size` | 20 | 连接池大小 |
| `redis_pool_max_connections` | 50 | 最大连接数 |
| `redis_socket_timeout` | 5.0 | Socket 超时（秒） |
| `redis_socket_connect_timeout` | 5.0 | 连接超时（秒） |

### 7.2 SSE 推送配置

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `redis_sse_stream_prefix` | `sse:progress` | Stream Key 前缀 |
| `redis_sse_max_stream_len` | 100 | 单个 Stream 最大消息数 |
| `redis_sse_stream_ttl_seconds` | 3600 | Stream TTL（秒） |

---

## 8. 注意事项

### 8.1 生产环境必须项

1. **Redis 高可用**：使用 Redis Sentinel 或 Redis Cluster
2. **连接池配置**：根据并发量调整 `redis_pool_max_connections`
3. **监控告警**：监控 Redis 内存使用、连接数、Stream 长度

### 8.2 常见问题

| 问题 | 原因 | 解决方案 |
|------|------|----------|
| 前端收不到消息 | Redis 未启动 | 检查 Redis 服务 |
| Stream 不存在 | 任务已结束且已清理 | 确认任务是否完成 |
| 消息延迟高 | Redis 负载高 | 增加 Redis 配置或分片 |
| 内存增长快 | Stream 未清理 | 检查 MAXLEN 和 TTL 配置 |

### 8.3 安全建议

1. **权限控制**：Redis 设置密码，配置 `requirepass`
2. **网络隔离**：Redis 不暴露到公网
3. **SSE 认证**：前端连接 SSE 时携带 Token

---

## 9. 代码位置

| 文件 | 说明 |
|------|------|
| `core/common/sse_progress.py` | SSE 核心实现 |
| `core/config/settings.py` | 配置定义 |
| `apps/api/routers/analytics.py` | SSE Endpoint |
| `apps/api/deps.py` | 依赖注入 |

---

## 10. 未来优化方向

1. **Redis Cluster 支持**：水平扩展
2. **消息压缩**：大结果数据压缩传输
3. **消费者组**：支持多消费者订阅同一任务
4. **监控面板**：接入 Prometheus/Grafana
5. **消息持久化**：消息写入后支持回放

---

## 11. Redis Stream 底层原理

### 11.1 为什么需要了解底层原理

理解 Redis Stream 的底层实现有助于：
- 合理配置 MAXLEN 和 TTL
- 排查生产环境问题
- 优化性能和内存使用
- 设计更可靠的断线重连机制

### 11.2 底层数据结构：Radix Tree（基数树）

Redis Stream 底层使用 **Radix Tree**（压缩前缀树）存储消息，而不是普通的 List 或 Hash。

```
┌─────────────────────────────────────────────────────────────────┐
│                        Radix Tree 内存结构                         │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│                        [root]                                   │
│                          │                                       │
│              ┌───────────┴───────────┐                          │
│              ▼                       ▼                          │
│          [node1]                  [node2]                       │
│          "1700-"                  "1701-"                        │
│          │                         │                            │
│     ┌────┴────┐                ┌────┴────┐                      │
│     ▼         ▼                ▼         ▼                      │
│  [msg1]   [msg2]           [msg3]    [msg4]                      │
│  1700-0   1700-1           1701-0    1701-1                    │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘

为什么用 Radix Tree？
├── 消息 ID 有共同前缀（如 1700-0, 1700-1 共享 "1700-"）
├── 节省内存：相同前缀只存储一次
├── 范围查询高效：找 > 1700-0 的所有消息只需遍历相关节点
└── 适合日志类场景：按时间顺序、追加写入
```

### 11.3 消息 ID 格式详解

```
格式：<millisecondsTime>-<sequenceNumber>

示例：
1704067200000-0    ← 第一条（该毫秒的第 1 条）
1704067200000-1    ← 第二条（该毫秒的第 2 条）
1704067200000-999  ← 第 1000 条（该毫秒的第 1000 条）
1704067200001-0    ← 下一秒的第 1 条
```

| 组成部分 | 说明 | 范围 |
|---------|------|------|
| `millisecondsTime` | Redis 节点的本地时间戳（毫秒） | 0 - 2^48 |
| `sequenceNumber` | 该毫秒内的序号 | 0 - 2^32-1 |

**ID 排序规则**：先比较时间戳，再比较序号

```
1704067200000-0   ← 最旧
1704067200000-1
1704067200001-0   ← 时间戳相同但序号+1
1704067200002-0   ← 时间戳+1
1704067201000-0   ← 最新
```

**ID 设计优势**：
- **单调递增**：新消息 ID 永远大于旧消息 ID
- **时间有序**：ID 隐含时间信息
- **唯一性**：同一毫秒内多条消息通过序号区分
- **断点续传基础**：通过记录已读 ID 实现精准续传

### 11.4 Stream Key 内部结构

执行 `XADD mystream * field1 value1` 后，Redis 内部结构为：

```
┌─────────────────────────────────────────────────────────────────┐
│  Key: "mystream"                                                │
│  Type: stream                                                    │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Radix Tree (压缩前缀树)                                          │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  root                                                      │   │
│  │   │                                                        │   │
│  │   ├── [1704067200000] ──▶ [entry(0)] ──▶ [entry(1)]      │   │
│  │   │                        msg1             msg2            │   │
│  │   │                                                        │   │
│  │   └── [1704067200001] ──▶ [entry(0)]                      │   │
│  │                            msg3                             │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                  │
│  Consumer Groups (消费者组) - 可选                                 │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  group "processors"                                        │   │
│  │   ├── consumer "c1": pending [msg1, msg2]                 │   │
│  │   └── consumer "c2": pending [msg3]                       │   │
│  │                                                          │   │
│  │  last-delivered-id: 1704067200001-0                      │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                  │
│  Stream Metadata                                                │
│  ├─ length: 3                    (消息总数)                      │
│  ├─ radix-tree-keys: 2          (Radix Tree 节点数)             │
│  ├─ last-generated-id: 1704067200001-0                          │
│  └─ first-entry-id: 1704067200000-0                            │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

**每个 Entry（消息）内部结构**：

```
┌─────────────────────────────────────────┐
│  Entry ID: 1704067200000-0               │
├─────────────────────────────────────────┤
│  field: "event"     │ value: "progress"  │
│  field: "data"      │ value: "{...}"     │
│  field: "timestamp" │ value: "17040672.."│
└─────────────────────────────────────────┘
         ↓
   Redis Hash 结构存储字段
```

### 11.5 核心命令详解

#### 11.5.1 XADD - 添加消息

```bash
XADD mystream MAXLEN ~ 100 * field1 value1 field2 value2
```

| 参数 | 含义 |
|------|------|
| `mystream` | Stream 名称 |
| `MAXLEN ~ 100` | 近似裁剪，最多保留 100 条 |
| `*` | 自动生成 ID（使用当前时间戳） |
| `1704067200000-0` | 指定 ID（比 `*` 更精确控制） |
| `field value` | 键值对数据 |

**执行过程**：
```
1. 生成消息 ID（时间戳-序号）
2. 将 field-value 存入 Radix Tree 节点
3. 检查是否需要裁剪（MAXLEN）
4. 返回消息 ID
```

#### 11.5.2 XREAD - 读取消息

```bash
XREAD BLOCK 30000 STREAMS mystream "1704067200000-0"
```

| 参数 | 含义 |
|------|------|
| `STREAMS mystream` | 要读取的 Stream |
| `"1704067200000-0"` | 起始 ID（**从此 ID 之后开始读**，不包含该 ID） |
| `BLOCK 30000` | 阻塞等待 30 秒（毫秒） |
| `COUNT 100` | 最多返回 100 条 |

**返回格式**：
```python
[
    ("mystream", [
        ("1704067200001-0", {"field1": "value1", "field2": "value2"}),
        ("1704067200002-0", {"field1": "value1", "field2": "value2"}),
    ])
]
```

#### 11.5.3 XRANGE - 范围查询

```bash
# 查询指定范围的消息
XRANGE mystream 1704067200000-0 1704067200100-0 COUNT 10

# 查询所有消息
XRANGE mystream - +

# - 表示最小 ID，+ 表示最大 ID
```

#### 11.5.4 XLEN - 获取长度

```bash
XLEN mystream
# 返回：42
```

#### 11.5.5 XINFO - 查看 Stream 信息

```bash
XINFO STREAM mystream FULL
```

```bash
 1) length                    # 消息数量
 2) (integer) 42
 3) radix-tree-keys          # Radix Tree 节点数
 4) (integer) 2
 5) radix-tree-nodes         # Radix Tree 节点总数
 6) (integer) 5
 7) last-generated-id        # 最后生成的消息 ID
 8) "1704067200041-0"
 9) first-entry             # 第一条消息
10) 1) "1704067200000-0"
    2) 1) "field"
       2) "value"
11) last-entry              # 最后一条消息
12) 1) "1704067200041-0"
    2) 1) "field"
       2) "value"
13) consumer-groups         # 消费者组数量
14) (integer) 1
```

### 11.6 MAXLEN 裁剪原理

#### 11.6.1 精确裁剪 vs 近似裁剪

```bash
# 精确裁剪：保证正好 100 条（可能有性能开销）
XADD mystream MAXLEN 100 * field value

# 近似裁剪：大约 100 条（性能更好）
XADD mystream MAXLEN ~ 100 * field value
```

#### 11.6.2 近似裁剪内部机制

```
┌─────────────────────────────────────────────────────────────────┐
│                     近似裁剪内部机制                               │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Redis Stream 内部按 16 的倍数组织节点：                          │
│                                                                  │
│  节点: [node_0]  ─▶  16 条消息                                    │
│  节点: [node_1]  ─▶  16 条消息  ─▶  节点满后删除整个 node_0      │
│  节点: [node_2]  ─▶  16 条消息                                    │
│  ...                                                             │
│                                                                  │
│  删除时：                                                          │
│  当 node_1 满了添加新消息，Redis 删除 node_0（一次性删 16 条）     │
│  结果：实际可能保留 100-115 条，而不是精确的 100 条                │
│                                                                  │
│  优点：O(1) 时间复杂度，不需要遍历所有消息                          │
│  缺点：可能多保留一些消息                                          │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

#### 11.6.3 MINID 裁剪（更灵活的方案）

```bash
# 删除 ID 小于指定值的所有消息
XTRIM mystream MINID 1704067200000-0

# 等价于：只保留 ID >= 1704067200000-0 的消息
```

### 11.7 Consumer Group（消费者组）

Consumer Group 是 Stream 最强大的特性之一，**项目当前未使用，但了解它有助于后续扩展**：

#### 11.7.1 基本概念

```bash
# 创建消费者组（从 Stream 开头开始消费）
XGROUP CREATE mystream group1 0

# 创建消费者组（从指定 ID 开始消费）
XGROUP CREATE mystream group2 1704067200000-0

# 消费者读取消息
XREADGROUP GROUP group1 c1 COUNT 10 STREAMS mystream ">"
# ">" 表示只读取新消息，不读取历史消息
```

#### 11.7.2 Consumer Group 工作原理

```
┌─────────────────────────────────────────────────────────────────┐
│                    Consumer Group 工作原理                         │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Stream: mystream                                                │
│  ┌────┬────┬────┬────┬────┬────┬────┬────┐                   │
│  │ M1 │ M2 │ M3 │ M4 │ M5 │ M6 │ M7 │ M8 │  ← 消息            │
│  └────┴────┴────┴────┴────┴────┴────┴────┘                      │
│                                                                  │
│  Consumer Group: "processors"                                     │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │  Consumer c1: [M1, M2]        ← 待 ACK 的消息               │ │
│  │  Consumer c2: [M3, M4]                                      │ │
│  │  Consumer c3: []                                            │ │
│  │                                                              │ │
│  │  last-delivered: M4                                         │ │
│  └────────────────────────────────────────────────────────────┘ │
│                                                                  │
│  工作流程：                                                        │
│  1. XREADGROUP ">" → 读取新消息（不包含已分配的）                   │
│  2. 消息自动分配给消费者（轮询或空闲最少）                           │
│  3. 消费者处理完成后 XACK → 消息从 PEL 删除                        │
│  4. 如果消费者崩溃，未 ACK 的消息会被重新分配                       │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

#### 11.7.3 PEL（Pending Entries List）

每个消费者有一个 PEL，记录"已读取但未 ACK"的消息：

```
消费者 c1 的 PEL：
┌────────────────────────────────────────┐
│  message ID     │  delivery time  │ cnt │
├────────────────┼─────────────────┼─────┤
│  1704067200-0  │  1704067220000  │  3  │  ← 已投递3次，仍失败
│  1704067200-1  │  1704067221000  │  1  │  ← 已投递1次
└────────────────────────────────────────┘
           ↓
   XACK 1704067200-0  → 从 PEL 删除
           ↓
   下次 XREADGROUP 时，这条消息可以被其他消费者读取
```

### 11.8 断线重连原理

#### 11.8.1 项目中的实现方式

项目通过记录 `_last_message_id` 实现断点续传：

```python
# 初始化：最后消息 ID 为 "0"（从头开始）
self._last_message_id = "0"

# 主循环：每次 XREAD 时传入上次读取的位置
messages = await self.redis.xread(
    {self.stream_key: self._last_message_id},  # ← 从这个 ID 之后开始读
    count=100,
    block=self.heartbeat_interval * 1000,
)

for stream_key, message_list in messages:
    for message_id, fields in message_list:
        # 处理完每条消息后，更新位置
        self._last_message_id = message_id  # ← 更新为当前消息 ID
```

#### 11.8.2 完整断线重连流程

```
时间线：
───────────────────────────────────────────────────────────────────────────────▶

消息1 ─▶ 消息2 ─▶ 消息3 ─▶ 消息4 ─▶ 消息5 ─▶ 消息6 ─▶ ...
   ✅         ✅         ↑
                      断线了！
                      
重连后：
                      
_last_message_id = "2"（已读到最后一条）  ←────────────────┐
                                                                  │
XREAD {stream: "2"}  ────────────────────────────────▶ 从消息3开始读 ✅
                                                                  │
_last_message_id = "5"（更新为最后已读）  ────────────────────────┘
```

#### 11.8.3 XREAD 的 ID 语义

| `_last_message_id` | XREAD 行为 |
|-------------------|-----------|
| `"0"` | 从第一条消息开始读 |
| `"2"` | **从第三条开始读**（跳过消息1、2） |
| `"5"` | 从第六条开始读（跳过消息1-5） |

**注意**：XREAD 的语义是"从指定 ID **之后**开始读"，不包含该 ID。

#### 11.8.4 被裁剪消息的处理

如果消费者读到消息3后断线，期间消息1、2被 MAXLEN 裁剪删除了，重连后：

```
情况：
- 消息1、2 已被 MAXLEN 删除
- _last_message_id = "2"
- 重连时 XREAD {stream: "2"}

结果：
Redis 仍然从消息3开始读，不会报错
原因：Stream ID 是单调递增的，Redis 通过 ID 定位，不依赖物理存储
```

### 11.9 Stream vs 其他数据结构对比

| 特性 | List | Pub/Sub | Stream |
|------|------|---------|--------|
| 消息持久化 | ✅ | ❌ | ✅ |
| 断点续传 | ❌ | ❌ | ✅ |
| 消费者组 | ❌ | ❌ | ✅ |
| 消息自动删除 | LPOP 后删除 | 无状态 | 可配置 MAXLEN/TTL |
| 范围查询 | LPUSH/LRANGE | ❌ | ✅ XRANGE |
| 确认机制 | ❌ | ❌ | ✅ XACK |
| 内存模型 | Linked List | PubSub Channels | Radix Tree |

### 11.10 项目中的 Stream 使用总结

项目中的使用是**简化版（无消费者组）**：

```
┌─────────────────────────────────────────────────────────────────┐
│              项目中的 Stream 使用方式                             │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  发布者（Publisher）：                                            │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │  XADD sse:progress:run_abc MAXLEN ~ 100 *                 │ │
│  │      event="progress"                                     │ │
│  │      data='{"run_id": "...", "progress": 50}'             │ │
│  │      timestamp="1704067200000"                              │ │
│  └─────────────────────────────────────────────────────────────┘ │
│                                                                  │
│  消费者（Consumer）：                                             │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │  XREAD BLOCK 30000 {sse:progress:run_abc: "0"}           │ │
│  │                                                          │ │
│  │  while True:                                             │ │
│  │      if timeout: send heartbeat                           │ │
│  │      if messages: yield to SSE endpoint                  │ │
│  └─────────────────────────────────────────────────────────────┘ │
│                                                                  │
│  特点：                                                          │
│  ✅ 无消费者组，所有消费者都能看到所有消息                           │
│  ✅ 自己记录 _last_message_id 实现断点续传                         │
│  ✅ 单消费者场景，不需要 ACK 机制                                  │
│                                                                  │
│  未来扩展方向：                                                   │
│  - Consumer Group：支持多前端同时订阅同一任务进度                   │
│  - XACK：确保消息被正确处理后再删除                                │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### 11.11 常用调试命令

```bash
# 1. 添加几条消息测试
XADD mystream * field1 value1
XADD mystream * field2 value2
XADD mystream * field3 value3

# 2. 查看所有消息
XRANGE mystream - +

# 3. 从指定 ID 之后读取
XREAD STREAMS mystream "1704067200000-1"

# 4. 查看 Stream 信息
XINFO STREAM mystream FULL

# 5. 近似裁剪测试
XADD mystream MAXLEN ~ 2 * test test
XLEN mystream  # 应该接近 2-3 条

# 6. 创建消费者组
XGROUP CREATE mystream mygroup 0
XREADGROUP GROUP mygroup consumer1 STREAMS mystream ">"

# 7. 确认消息
XACK mystream mygroup 1704067200000-0

# 8. 查看消费者组信息
XINFO GROUPS mystream

# 9. 查看消费者信息
XINFO CONSUMERS mystream mygroup

# 10. 清理
DEL mystream
```

---

## 12. 常见问题解答

### Q1: 消费完消息就没了吗？

**不是！** 与 List 的 `LPOP` 不同，Stream 的 `XREAD` 只是读取消息，消息仍然保留在 Stream 中。

```
List 的 LPOP：消息被取出后就消失了
Stream 的 XREAD：消息只是被读取，保留在 Stream 中
```

这就是 Stream 支持**断线重连**的根本原因。

### Q2: 超过 MAXLEN 后会删除哪条消息？

**删除最旧的消息**。Redis 会自动删除 ID 最小的消息，保留最新的。

```
时间线：
─────────────────────────────────────────────────────────────────────▶

消息1 ─▶ 消息2 ─▶ ... ─▶ 消息99 ─▶ 消息100 ─▶ 消息101 ─▶ 消息102
                              ↑
                              删除最旧的 ←─ 自动裁剪
```

### Q3: Consumer Group 和普通 XREAD 的区别？

| 特性 | XREAD | XREADGROUP (Consumer Group) |
|------|-------|------------------------------|
| 多消费者 | 所有消费者看到所有消息 | 消息分配给不同消费者，不重复 |
| 消息确认 | 无需确认 | 需要 XACK 确认 |
| 崩溃恢复 | 自己记录位置 | 未 ACK 消息自动重新分配 |
| 适用场景 | SSE 推送（单消费者） | 任务队列（多消费者） |

### Q4: MAXLEN ~ 和 MAXLEN 精确的区别？

| 模式 | 行为 | 性能 | 实际条数 |
|------|------|------|----------|
| `MAXLEN 100` | 精确保留 100 条 | 较慢（每次精确计数） | 精确 100 条 |
| `MAXLEN ~ 100` | 近似保留 100 条 | 较快（分组删除） | 约 100-115 条 |

项目使用近似模式，因为：
1. 性能更好（O(1) 复杂度）
2. 进度消息不需要精确数量
3. 误差在可接受范围内

---

*文档版本：v1.1*
*更新时间：2026-05-03*
*新增章节：第 11 章 Redis Stream 底层原理、第 12 章常见问题解答*
