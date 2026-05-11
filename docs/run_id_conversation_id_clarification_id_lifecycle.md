# run_id / conversation_id / clarification_id 生命周期与作用域详解

> 本文档详细解释企业经营分析系统中三个核心 ID 的设计理念、生命周期、作用域和使用场景。

---

## 一、概念速览

| ID | 中文名称 | 英文含义 | 粒度 | 生命周期 |
|----|---------|---------|------|---------|
| `conversation_id` | 会话ID | Conversation Identifier | 粗粒度（会话级） | 长 |
| `run_id` | 任务运行ID | Task Run Identifier | 细粒度（单次执行） | 中 |
| `clarification_id` | 澄清事件ID | Clarification Event Identifier | 事件级 | 短 |

---

## 二、为什么需要三个 ID？

### 2.1 问题背景

企业经营分析是一个复杂的交互系统：

1. **用户可能问多轮问题**：用户不会一次性把需求说清楚
2. **系统可能缺信息**：需要主动向用户澄清
3. **每次查询都是独立任务**：需要追踪每次执行
4. **同一会话可能有多个任务并行**：比如同时查询发电量和收入

### 2.2 设计目标

```
┌─────────────────────────────────────────────────────────────┐
│                      用户会话                               │
│  ┌───────────┐  ┌───────────┐  ┌───────────┐             │
│  │ 第1轮查询  │  │ 第2轮查询  │  │ 第3轮查询  │             │
│  │ run_001   │  │ run_002   │  │ run_003   │             │
│  └───────────┘  └───────────┘  └───────────┘             │
│                                                              │
│  ┌───────────┐                                              │
│  │ 澄清事件   │  ← 需要单独追踪                              │
│  │ clr_001   │                                              │
│  └───────────┘                                              │
└─────────────────────────────────────────────────────────────┘
                          ▲
                          │
                    conversation_id: conv_xxx
```

### 2.3 职责划分

| ID | 职责 | 不负责 |
|----|------|--------|
| `conversation_id` | 串联同一用户的多次交互 | 单次任务细节 |
| `run_id` | 追踪单次任务执行链路 | 跨任务上下文 |
| `clarification_id` | 记录澄清交互事件 | 任务执行状态 |

---

## 三、conversation_id（会话ID）

### 3.1 定义

`conversation_id` 是**会话级别**的唯一标识符，用于串联同一用户的多次交互。

### 3.2 生命周期

```
时间轴 ─────────────────────────────────────────────────────────────▶

创建时机                    存活期间                    销毁时机
   │                          │                          │
   ▼                          ▼                          ▼
┌─────────┐    ┌─────────────────────────────────┐    ┌─────────┐
│ 对话开始 │ ──▶ │ 多轮对话（任意时长）              │ ──▶ │ 对话结束 │
│         │    │                                 │    │         │
│ 用户问句 │    │  第1轮 ──▶  第2轮 ──▶  第3轮    │    │ 归档    │
│ 用户问句 │    │  run_001  run_002  run_003      │    │ 删除    │
│ 用户问句 │    │                                 │    │ 过期    │
└─────────┘    └─────────────────────────────────┘    └─────────┘

生命周期：长（可能持续数天到数月）
```

### 3.3 作用域

```
┌─────────────────────────────────────────────────────────────────────┐
│                         conversation_id: conv_xxx                    │
│                                                                      │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │  第1轮：查询发电量                                            │    │
│  │  run_id: run_001  ←── 属于这个会话                           │    │
│  │  status: succeeded                                           │    │
│  │  memory: last_metric="发电量", last_time_range="2024-03"     │    │
│  └─────────────────────────────────────────────────────────────┘    │
│                                                                      │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │  第2轮：和去年对比（复用上轮的指标和时间）                     │    │
│  │  run_id: run_002  ←── 属于这个会话                           │    │
│  │  status: succeeded                                           │    │
│  │  memory: last_metric="发电量", last_time_range="2024-03"     │    │
│  └─────────────────────────────────────────────────────────────┘    │
│                                                                      │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │  第3轮：看看收入（不指定时间，承接上轮时间）                   │    │
│  │  run_id: run_003  ←── 属于这个会话                           │    │
│  │  status: succeeded                                           │    │
│  └─────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────┘
```

### 3.4 核心数据：conversation_memory

会话记忆是 `conversation_id` 最重要的功能：

```python
class ConversationMemory(BaseModel):
    """会话记忆：存储跨轮次的上下文信息"""

    # 长期记忆：上次查询的指标、时间、组织范围
    last_metric: str | None = None          # "发电量"
    last_time_range: dict | None = None      # {"type": "absolute", "value": "2024-03"}
    last_org_scope: dict | None = None       # {"type": "region", "value": "XJ"}

    # 短期记忆：本轮查询的分组、对比等
    short_term_memory: dict | None = None    # {"last_group_by": "station", ...}

    # 会话状态
    last_route: str | None = None            # "analytics"
    last_status: str | None = None           # "succeeded"
```

### 3.5 使用场景

| 场景 | 代码示例 |
|-----|---------|
| 创建会话 | `conversation = repo.create(user_id="u_xxx")` |
| 查询会话 | `conversation = repo.get_conversation("conv_xxx")` |
| 更新记忆 | `repo.upsert_memory("conv_xxx", last_metric="发电量")` |
| 读取记忆 | `memory = repo.get_memory("conv_xxx")` |

### 3.6 多轮承接示例

**第1轮**：`"查询新疆区域2024年3月发电量"`

```python
# 系统处理
conversation_memory = {
    "last_metric": "发电量",
    "last_time_range": {"type": "absolute", "value": "2024-03"},
    "last_org_scope": {"type": "region", "value": "XJ"}
}
```

**第2轮**：`"和去年对比"`

```python
# 系统处理
# 复用 conversation_memory 中的指标、时间、组织
intent = {
    "metric": "发电量",           # 来自 memory
    "time_range": "2024-03",     # 来自 memory
    "org_scope": "XJ",           # 来自 memory
    "compare_target": "yoy"      # 新增：本轮指定
}
```

---

## 四、run_id（任务运行ID）

### 4.1 定义

`run_id` 是**任务执行级别**的唯一标识符，用于追踪单次任务从开始到结束的完整链路。

### 4.2 生命周期

```
时间轴 ─────────────────────────────────────────────────────────────▶

生成时机                    存活期间                              结束时机
   │                          │                                    │
   ▼                          ▼                                    ▼
┌─────────┐    ┌─────────────────────────────────────────┐    ┌─────────┐
│ entry   │ ──▶ │ 节点1 ──▶ 节点2 ──▶ 节点3 ──▶ ...     │ ──▶ │ finish  │
│ 节点    │    │                                         │    │ 节点    │
│         │    │ analytics_entry                         │    │         │
│ 创建    │    │ analytics_plan                          │    │ 更新状态 │
│ run_id  │    │ analytics_validate_slots                │    │ 持久化   │
│         │    │ analytics_build_sql                      │    │ 结果     │
└─────────┘    │ analytics_guard_sql                      │    └─────────┘
               │ analytics_execute_sql                    │
               │ analytics_summarize                      │
               │ analytics_finish                         │
               └─────────────────────────────────────────┘

生命周期：中（分钟级别，通常 < 5分钟）
```

### 4.3 作用域

```
┌─────────────────────────────────────────────────────────────────────┐
│                         run_id: run_xxx                             │
│                                                                      │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │  节点执行链                                                  │    │
│  │                                                              │    │
│  │  analytics_entry ──▶ analytics_plan ──▶ analytics_validate  │    │
│  │                                                              │    │
│  │        │                                                    │    │
│  │        ▼                                                    │    │
│  │  ┌─────────────────┐                                        │    │
│  │  │ 校验通过        │  ┌─────────────────┐                   │    │
│  │  │ analytics_build │  │ 校验失败        │                   │    │
│  │  │ analytics_guard │  │ analytics_clarify│                   │    │
│  │  │ analytics_exec  │  │ 返回澄清        │                   │    │
│  │  │ analytics_sum   │  └─────────────────┘                   │    │
│  │  │ analytics_finish│                                       │    │
│  │  └─────────────────┘                                        │    │
│  └─────────────────────────────────────────────────────────────┘    │
│                                                                      │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │  关联数据                                                    │    │
│  │                                                              │    │
│  │  task_run ──── run_id ────▶ 当前执行状态                     │    │
│  │  slot_snapshot ──── run_id ────▶ 槽位快照                   │    │
│  │  analytics_result ──── run_id ────▶ 分析结果                 │    │
│  │  sql_audit ──── run_id ────▶ SQL审计记录                   │    │
│  │  clarification_event ──── run_id ────▶ 澄清事件              │    │
│  └─────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────┘
```

### 4.4 核心数据：task_run

```python
class TaskRun(BaseModel):
    """任务运行记录：追踪单次任务执行"""

    run_id: str                           # "run_001"
    conversation_id: str                   # "conv_xxx"
    task_type: str                         # "analytics"
    route: str                             # "business_analysis"

    # 状态流转
    status: str                            # pending/executing/succeeded/failed/awaiting_user_clarification
    sub_status: str                        # 具体子状态

    # 快照数据
    input_snapshot: dict | None = None      # 入参快照（query、output_mode等）
    output_snapshot: dict | None = None    # 出参快照（summary、chart等）
    context_snapshot: dict | None = None   # 上下文快照（intent、slots等）

    # 追踪信息
    trace_id: str                          # 链路追踪ID
    created_at: datetime                   # 创建时间
    updated_at: datetime                   # 更新时间
```

### 4.5 状态流转

```
                         ┌─────────────────────────────────────┐
                         │                                     │
                         ▼                                     │
┌─────────┐    ┌─────────────────┐    ┌─────────────────┐    │
│ pending │ ──▶│   executing     │ ──▶│   succeeded     │    │
│         │    │                 │    │                 │    │
│ 初始状态│    │  正在执行中      │    │  执行成功       │    │
└─────────┘    │                 │    └─────────────────┘    │
               └─────────────────┘             ▲               │
                         │                    │               │
                         │  ┌─────────────────┐              │
                         │  │   failed        │              │
                         │  │                 │              │
                         │  │  执行失败       │              │
                         │  └─────────────────┘              │
                         │                                     │
                         │  ┌─────────────────────────┐       │
                         └─▶│ awaiting_user_clarification │───┘
                            │                           │
                            │  等待用户澄清             │
                            └─────────────────────────┘
                                   │
                                   │ 用户回复
                                   ▼
                            ┌─────────────────┐
                            │  继续执行       │
                            │  (复用原run_id) │
                            └─────────────────┘
```

### 4.6 使用场景

| 场景 | 代码示例 |
|-----|---------|
| 创建 task_run | `task_run = repo.create_task_run(conversation_id="conv_xxx", ...)` |
| 更新状态 | `repo.update_task_run("run_xxx", status="succeeded")` |
| 持久化结果 | `repo.update_task_run("run_xxx", output_snapshot={...})` |
| 查询 run | `task_run = repo.get_task_run("run_xxx")` |

---

## 五、clarification_id（澄清事件ID）

### 5.1 定义

`clarification_id` 是**澄清交互级别**的唯一标识符，用于记录"系统怎么问、用户怎么答、解析出什么"。

### 5.2 生命周期

```
时间轴 ─────────────────────────────────────────────────────────────▶

生成时机                    存活期间                    结束时机
   │                          │                          │
   ▼                          ▼                          ▼
┌─────────┐    ┌─────────────────────────────────┐    ┌─────────┐
│ 触发    │ ──▶ │ 等待用户回复                     │ ──▶ │ resolved│
│ 澄清    │    │                                 │    │ expired │
│         │    │  用户可能：                      │    │cancelled│
│ 创建    │    │  - 立即回复                      │    └─────────┘
│ clr_id  │    │  - 稍后回复（数小时/数天后）      │
└─────────┘    │  - 不回复（过期）                  │
               └─────────────────────────────────┘

生命周期：短到中（取决于用户响应时间，可能数小时到数天）
```

### 5.3 作用域

```
┌─────────────────────────────────────────────────────────────────────┐
│                      clarification_id: clr_xxx                       │
│                                                                      │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │  澄清交互事件                                                │    │
│  │                                                              │    │
│  │  question_text: "你想查哪个指标？发电量、收入还是成本？"         │    │
│  │  target_slots: ["metric"]                                    │    │
│  │                                                              │    │
│  │  ┌─────────────────────────────────────────────────────┐    │    │
│  │  │  用户回复后（状态变为 resolved）                       │    │    │
│  │  │                                                      │    │    │
│  │  │  user_reply: "发电量"                               │    │    │
│  │  │  resolved_slots: {"metric": "发电量"}               │    │    │
│  │  │  resolved_at: "2026-05-02T18:00:00Z"               │    │    │
│  │  └─────────────────────────────────────────────────────┘    │    │
│  └─────────────────────────────────────────────────────────────┘    │
│                                                                      │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │  关联关系                                                    │    │
│  │                                                              │    │
│  │  clarification_event ──── run_id ────▶ 关联的任务            │    │
│  │  clarification_event ──── conv_id ────▶ 关联的会话          │    │
│  │  slot_snapshot ──── run_id ────▶ 关联的槽位快照             │    │
│  └─────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────┘
```

### 5.4 核心数据：clarification_event

```python
class ClarificationEvent(BaseModel):
    """澄清事件：记录系统追问和用户回复"""

    clarification_id: str                   # "clr_001"

    # 关联标识
    run_id: str                            # "run_xxx"
    conversation_id: str                   # "conv_xxx"

    # 澄清内容
    question_text: str                      # "你想查哪个指标？"
    target_slots: list[str]                # ["metric"]

    # 用户回复（回复后填充）
    user_reply: str | None = None          # "发电量"
    resolved_slots: dict | None = None    # {"metric": "发电量", ...}

    # 状态
    status: str                            # pending/resolved/expired/cancelled

    # 时间戳
    created_at: datetime
    resolved_at: datetime | None = None
```

### 5.5 状态流转

```
┌─────────┐
│ pending │  ←── 初始状态
└────┬────┘
     │
     │ 用户回复
     ▼
┌──────────┐
│ resolved │  ←── 澄清完成
└──────────┘

┌─────────┐
│ pending │
└────┬────┘
     │
     │ 超时/用户主动取消
     ▼
┌──────────┐
│ expired  │  ←── 过期
└──────────┘

┌─────────┐
│ pending │
└────┬────┘
     │
     │ 管理员取消
     ▼
┌───────────┐
│ cancelled │  ←── 取消
└───────────┘
```

### 5.6 使用场景

| 场景 | 代码示例 |
|-----|---------|
| 创建澄清事件 | `clr = repo.create_clarification_event(run_id="run_xxx", ...)` |
| 更新回复 | `repo.update_clarification_event("clr_xxx", user_reply="发电量", ...)` |
| 查询澄清 | `clr = repo.get_clarification_event("clr_xxx")` |

---

## 六、三者关系图

### 6.1 层级关系

```
┌─────────────────────────────────────────────────────────────────────┐
│                        conversation_id: conv_xxx                     │
│                        (会话层级 - 最外层)                            │
│                                                                      │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │  run_id: run_001                                             │  │
│  │  (任务层级 - 中间层)                                          │  │
│  │                                                              │  │
│  │  ┌─────────────────────────────────────────────────────┐   │  │
│  │  │  clarification_id: clr_001                            │   │  │
│  │  │  (事件层级 - 最内层)                                    │   │  │
│  │  └─────────────────────────────────────────────────────┘   │  │
│  └───────────────────────────────────────────────────────────────┘  │
│                                                                      │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │  run_id: run_002                                             │  │
│  │  (另一个独立任务)                                             │  │
│  └───────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
```

### 6.2 数据关联

```
┌─────────────────────────────────────────────────────────────────────┐
│                         数据库表关联                                  │
│                                                                      │
│  ┌──────────────────┐         ┌──────────────────┐                │
│  │ conversations     │         │ task_runs         │                │
│  │                  │         │                  │                │
│  │ conv_id (PK)     │──┐      │ run_id (PK)      │──┐             │
│  │ user_id          │  │      │ conv_id (FK)     │◀─┘             │
│  │ created_at       │  │      │ task_type        │                │
│  │ ...              │  │      │ status           │                │
│  └──────────────────┘  │      └──────────────────┘                │
│         │               │             │                           │
│         │               │             │                           │
│         ▼               │             ▼                           │
│  ┌──────────────────┐   │      ┌──────────────────┐                │
│  │ messages         │   │      │ clarification_   │                │
│  │                  │   │      │ events           │                │
│  │ conv_id (FK)     │◀──┘      │                  │                │
│  │ message_type     │          │ clr_id (PK)     │                │
│  │ content          │          │ run_id (FK)     │◀─┐            │
│  │ ...              │          │ question_text    │  │            │
│  └──────────────────┘          │ status          │  │            │
│                                └──────────────────┘  │            │
│                                                    │            │
│  ┌──────────────────┐                              │            │
│  │ slot_snapshots   │                              │            │
│  │                  │                              │            │
│  │ run_id (FK)      │◀─────────────────────────────┘            │
│  │ metric           │                                              │
│  │ time_range       │                                              │
│  │ org_scope        │                                              │
│  └──────────────────┘                                              │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 七、完整交互示例

### 7.1 场景：用户需要澄清的完整流程

**第1步：用户首次问句（缺指标）**

```
用户: "帮我看一下新疆区域上个月的情况"
```

**第2步：系统处理 - 创建会话和任务**

```python
# 1. 创建/获取会话
conversation = conversation_repository.get_or_create(
    user_id="u_xxx",
    conversation_id=None  # 首次为空
)
# conversation_id: "conv_001"

# 2. 创建任务
task_run = task_run_repository.create_task_run(
    conversation_id="conv_001",
    task_type="analytics",
    route="business_analysis"
)
# run_id: "run_001"
# status: "executing"

# 3. 解析意图 - 发现缺 metric
intent = parser.parse("帮我看一下新疆区域上个月的情况")
# intent.metric: None (缺失)
# intent.need_clarification: True
```

**第3步：系统处理 - 触发澄清**

```python
# 4. 创建澄清事件
clarification = task_run_repository.create_clarification_event(
    run_id="run_001",
    conversation_id="conv_001",
    question_text="你想查看哪个经营指标？例如：发电量、收入、成本、利润。",
    target_slots=["metric"]
)
# clarification_id: "clr_001"
# status: "pending"

# 5. 创建槽位快照
slot_snapshot = task_run_repository.create_slot_snapshot(
    run_id="run_001",
    task_type="analytics",
    org_scope={"type": "region", "value": "XJ"},
    time_range={"type": "relative", "value": "last_month"},
    metric=None  # 缺失
)
# slot_snapshot_id: "slot_001"

# 6. 更新任务状态
task_run_repository.update_task_run(
    "run_001",
    status="awaiting_user_clarification",
    sub_status="awaiting_slot_fill"
)

# 7. 更新会话记忆
conversation_repository.upsert_memory(
    "conv_001",
    last_org_scope={"type": "region", "value": "XJ"},
    last_time_range={"type": "relative", "value": "last_month"}
)
```

**第4步：返回澄清响应给用户**

```json
{
    "success": true,
    "meta": {
        "conversation_id": "conv_001",
        "run_id": "run_001",
        "status": "awaiting_user_clarification"
    },
    "data": {
        "clarification": {
            "clarification_id": "clr_001",
            "question": "你想查看哪个经营指标？例如：发电量、收入、成本、利润。",
            "target_slots": ["metric"]
        }
    }
}
```

---

**第5步：用户回复澄清**

```
用户: "看发电量"
```

**第6步：系统处理 - 用户回复**

```python
# 1. 查询澄清事件
clarification = task_run_repository.get_clarification_event("clr_001")
# clarification_id: "clr_001"
# status: "pending"
# target_slots: ["metric"]

# 2. 解析用户回复
resolved_slots = parser.parse_slot_fill(
    user_reply="看发电量",
    target_slots=["metric"]
)
# resolved_slots: {"metric": "发电量", "metric_code": "generation"}

# 3. 更新澄清事件
task_run_repository.update_clarification_event(
    "clr_001",
    user_reply="看发电量",
    resolved_slots=resolved_slots,
    status="resolved",
    resolved_at=datetime.now()
)

# 4. 更新槽位快照
task_run_repository.update_slot_snapshot(
    "slot_001",
    metric="发电量",
    metric_code="generation"
)

# 5. 更新任务状态
task_run_repository.update_task_run(
    "run_001",
    status="executing",
    sub_status="resuming_after_clarification"
)
```

**第7步：系统处理 - 恢复执行**

```python
# 1. 恢复状态（复用原 run_id）
state = {
    "run_id": "run_001",              # 复用原 run_id
    "conversation_id": "conv_001",    # 复用原 conversation_id
    "trace_id": "tr_xxx",            # 复用原 trace_id
    "intent": {
        "metric": "发电量",           # 合并后的意图
        "metric_code": "generation",
        "org_scope": {"type": "region", "value": "XJ"},
        "time_range": {"type": "relative", "value": "last_month"}
    },
    "resume_from_clarification": True  # 标记为从澄清恢复
}

# 2. 继续执行（跳过 analytics_entry 中的新建逻辑）
# 直接进入 analytics_build_sql
```

**第8步：执行查询并返回结果**

```python
# 1. 构建 SQL
sql = sql_builder.build(intent)

# 2. 执行 SQL
result = sql_gateway.execute(sql)

# 3. 生成摘要
summary = summarizer.generate(result)

# 4. 更新任务状态
task_run_repository.update_task_run(
    "run_001",
    status="succeeded",
    output_snapshot={
        "summary": summary,
        "row_count": result.row_count
    }
)

# 5. 更新会话记忆
conversation_repository.upsert_memory(
    "conv_001",
    last_metric="发电量",
    last_metric_code="generation"
)
```

**第9步：返回成功响应给用户**

```json
{
    "success": true,
    "meta": {
        "conversation_id": "conv_001",
        "run_id": "run_001",
        "clarification_id": "clr_001",
        "status": "succeeded"
    },
    "data": {
        "summary": "上个月，新疆区域的发电量为 12345.67 万千瓦时。"
    }
}
```

---

## 八、API 调用对照表

### 8.1 首次请求（无 conversation_id）

```python
POST /api/v1/analytics/query

Request:
{
    "query": "查询新疆区域2024年3月发电量"
}

Response:
{
    "success": true,
    "meta": {
        "conversation_id": "conv_001",
        "run_id": "run_001",
        "trace_id": "tr_001",
        "status": "succeeded"
    },
    "data": {
        "summary": "..."
    }
}
```

### 8.2 继续请求（带 conversation_id）

```python
POST /api/v1/analytics/query

Request:
{
    "query": "和去年对比",
    "conversation_id": "conv_001"  # 带上会话ID，承接上下文
}

Response:
{
    "success": true,
    "meta": {
        "conversation_id": "conv_001",
        "run_id": "run_002",  # 新 run_id，但属于同一会话
        "trace_id": "tr_002",
        "status": "succeeded"
    },
    "data": {
        "summary": "..."
    }
}
```

### 8.3 澄清请求（系统返回澄清）

```python
POST /api/v1/analytics/query

Request:
{
    "query": "帮我看一下新疆区域上个月的情况",
    "conversation_id": "conv_001"
}

Response:
{
    "success": true,
    "meta": {
        "conversation_id": "conv_001",
        "run_id": "run_003",
        "status": "awaiting_user_clarification"
    },
    "data": {
        "clarification": {
            "clarification_id": "clr_001",
            "question": "你想查看哪个经营指标？",
            "target_slots": ["metric"]
        }
    }
}
```

### 8.4 澄清回复（带 clarification_id）

```python
POST /api/v1/analytics/clarification/reply

Request:
{
    "clarification_id": "clr_001",
    "reply": "发电量"
}

Response:
{
    "success": true,
    "meta": {
        "conversation_id": "conv_001",
        "run_id": "run_003",  # 复用原 run_id
        "clarification_id": "clr_001",
        "status": "succeeded"
    },
    "data": {
        "summary": "上个月，新疆区域的发电量为 12345.67 万千瓦时。"
    }
}
```

---

## 九、ID 生成规则

### 9.1 前缀规则

| ID 类型 | 前缀 | 示例 |
|--------|------|------|
| conversation_id | `conv_` | `conv_001`, `conv_abc123` |
| run_id | `run_` | `run_001`, `run_xyz789` |
| clarification_id | `clr_` | `clr_001`, `clr_def456` |

### 9.2 生成方式

```python
import uuid

def generate_id(prefix: str) -> str:
    """生成带前缀的唯一ID"""
    unique_part = uuid.uuid4().hex[:12]
    return f"{prefix}{unique_part}"

# 使用
conversation_id = generate_id("conv_")  # "conv_a1b2c3d4e5f6"
run_id = generate_id("run_")           # "run_f6e5d4c3b2a1"
clarification_id = generate_id("clr_")  # "clr_123456789abc"
```

---

## 十、常见问题

### Q1: 为什么 clarification 复用 run_id 而不是新建？

**A**: 澄清不是新任务，而是原任务的"中断-恢复"。复用 `run_id` 可以：
1. 保持审计链路连贯
2. 关联同一任务的不同阶段
3. 便于追溯完整执行历史

### Q2: 一个会话可以同时有多个 pending 的澄清吗？

**A**: 不建议。系统设计为每次任务只会有一个活跃澄清。如果用户发起新任务，原有澄清应标记为 `cancelled`。

### Q3: clarification 过期后怎么办？

**A**:
1. 标记 `clarification.status = "expired"`
2. 原任务 `task_run.status` 保持 `awaiting_user_clarification` 或改为 `failed`
3. 用户如需继续，需重新发起问句

### Q4: run_id 和 trace_id 的区别？

| ID | 用途 | 粒度 | 层级 |
|----|------|------|------|
| run_id | 业务任务追踪 | 单次执行 | 业务层 |
| trace_id | 全链路追踪 | 整个请求链 | 技术层 |

`trace_id` 用于分布式追踪系统（如 OpenTelemetry），`run_id` 用于业务逻辑追踪。

---

## 十一、总结

| ID | 一句话总结 | 生命周期 | 核心职责 |
|----|-----------|---------|---------|
| `conversation_id` | 串联同一用户的多次对话 | 长 | 多轮上下文承接 |
| `run_id` | 追踪单次任务执行 | 中 | 任务状态与结果 |
| `clarification_id` | 记录澄清交互事件 | 短 | 澄清问答追溯 |

理解这三个 ID 的关系，是掌握企业经营分析系统架构的关键。

---

**文档版本**: v1.0
**最后更新**: 2026-05-02
**适用模块**: 经营分析 Agent、Clarification Service、Conversation Service
