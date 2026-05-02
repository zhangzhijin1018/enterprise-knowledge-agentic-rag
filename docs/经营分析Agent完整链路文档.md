# 经营分析 Agent 完整链路文档

> **版本**：v2 链路收敛版
> **更新时间**：2026-05-02
> **状态**：生产级实现

---

## 一、文档概述

### 1.1 文档目的

本文档详细说明经营分析 Agent 的完整执行链路，包括：
- 用户问句到最终结果的全流程
- 每个节点的输入输出
- LangGraph 状态机执行机制
- Supervisor 层职责
- 状态持久化与上下文承接
- 澄清判断逻辑
- Prompt 提示词设计

### 1.2 核心链路架构

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                                    Supervisor 层                                     │
│  ┌─────────────┐    ┌─────────────────┐    ┌────────────────┐    ┌──────────────┐ │
│  │ 接收请求    │ -> │ 解析目标专家    │ -> │ 构造 TaskEnvelope │ -> │ 委托执行     │ │
│  └─────────────┘    └─────────────────┘    └────────────────┘    └──────────────┘ │
└─────────────────────────────────────────────────────────────────────────────────────┘
                                        │
                                        ▼
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                                  Analytics 层                                         │
│                                                                                      │
│  ┌──────────────────────────────────────────────────────────────────────────────┐   │
│  │                         LangGraph StateGraph                                  │   │
│  │                                                                              │   │
│  │  ┌──────────────┐    ┌────────────┐    ┌──────────────┐    ┌────────────┐  │   │
│  │  │analytics_    │ -> │ analytics_ │ -> │  analytics_  │ -> │analytics_  │  │   │
│  │  │entry         │    │ plan       │    │validate_slots│    │clarify    │  │   │
│  │  └──────────────┘    └────────────┘    └──────────────┘    └────────────┘  │   │
│  │                                                          │                   │   │
│  │                                                          │ (if need         │   │
│  │                                                          │  clarification)  │   │
│  │  ┌────────────┐    ┌────────────┐    ┌────────────┐    └────────────┐    │   │
│  │  │analytics_  │ <- │analytics_  │ <- │analytics_  │ <- │analytics_   │    │   │
│  │  │finish      │    │summarize   │    │execute_sql │    │guard_sql   │    │   │
│  │  └────────────┘    └────────────┘    └────────────┘    └────────────┘    │   │
│  │                                                    │                        │   │
│  │                                                    │ (if valid)            │   │
│  │  ┌──────────────┐    ┌────────────┐    ┌────────────┐                     │   │
│  │  │analytics_   │ -> │ LLM        │ -> │ Analytics  │                     │   │
│  │  │build_sql    │    │Analytics   │    │Intent      │                     │   │
│  │  └──────────────┘    │IntentParser│    │Validator   │                     │   │
│  │                       └────────────┘    └────────────┘                     │   │
│  └──────────────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────────────┘
                                        │
                                        ▼
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                                  SQL 执行层                                          │
│  ┌────────────────┐    ┌────────────────┐    ┌────────────────┐                 │
│  │ SQL Builder    │ -> │ SQL Guard      │ -> │ SQL Gateway    │ -> Result        │
│  └────────────────┘    └────────────────┘    └────────────────┘                 │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 二、用户问句完整流程

### 2.1 流程概览

```
用户问句
    │
    ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│ Step 1: Supervisor 接收请求                                                   │
│ - 解析 task_type = "business_analysis"                                        │
│ - 构造 TaskEnvelope                                                          │
│ - 生成 run_id / trace_id                                                      │
│ - 调用 DelegationController.dispatch()                                        │
└──────────────────────────────────────────────────────────────────────────────┘
    │
    ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│ Step 2: AnalyticsWorkflowAdapter.execute_query()                              │
│ - 调用 AnalyticsLangGraphWorkflow.invoke()                                   │
│ - 传入 query / user_context / conversation_id 等                             │
└──────────────────────────────────────────────────────────────────────────────┘
    │
    ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│ Step 3: LangGraph StateGraph 执行                                            │
│                                                                              │
│ 节点执行顺序：                                                               │
│ analytics_entry -> analytics_plan -> analytics_validate_slots                 │
│                                          │                                   │
│                     ┌───────────────────┼───────────────────┐               │
│                     ▼                   ▼                   ▼               │
│               analytics_clarify    analytics_build_sql    (fail)           │
│                     │                   │                                   │
│                     │                   ▼                                   │
│                     │            analytics_guard_sql                         │
│                     │                   │                                   │
│                     │                   ▼                                   │
│                     │            analytics_execute_sql                       │
│                     │                   │                                   │
│                     │                   ▼                                   │
│                     │            analytics_summarize                         │
│                     │                   │                                   │
│                     │                   ▼                                   │
│                     └───────► analytics_finish ◄──────┘                     │
│                                                                              │
└──────────────────────────────────────────────────────────────────────────────┘
    │
    ▼
最终响应
```

---

## 三、节点详解

### 3.1 analytics_entry（入口节点）

**文件位置**：`core/agent/workflows/analytics/nodes.py`

**职责**：
- 校验 query 非空
- 标准化 output_mode
- 创建/读取 conversation
- 记录用户消息
- 准备 conversation memory

**输入**（state 初始状态）：
```python
{
    "query": "查询新疆区域2024年3月发电量",
    "user_context": UserContext(...),
    "conversation_id": None,
    "output_mode": "lite",
    "need_sql_explain": False,
    "run_id": None,
    "trace_id": None,
    "parent_task_id": None,
    "recovered_plan": None,
    "resume_from_clarification": False,
    "existing_task_run": None,
}
```

**输出**（更新后的 state）：
```python
{
    # 标准化后的字段
    "query": "查询新疆区域2024年3月发电量",  # 去空格
    "output_mode": "lite",  # 标准化为 lite/standard/full

    # 新增字段
    "conversation": {...},  # 会话对象
    "conversation_id": "conv_xxx",
    "conversation_memory": {...},  # 多轮上下文

    # 状态机字段
    "workflow_stage": "analytics_entry",
    "workflow_outcome": "continue",
    "clarification_needed": False,
    "review_required": False,

    # 重试/降级字段
    "retry_count": 0,
    "retry_history": [],
    "degraded": False,
    "degraded_features": [],

    # ReAct 字段（默认不使用）
    "react_used": False,
    "react_steps": [],
    "react_stopped_reason": "",
    "react_fallback_used": False,
}
```

**代码片段**：
```python
def analytics_entry(self, state: dict) -> dict:
    """工作流入口节点。"""

    query = (state.get("query") or "").strip()
    if not query:
        raise AppException(
            error_code=error_codes.ANALYTICS_QUERY_FAILED,
            message="经营分析问题不能为空",
            status_code=400,
        )

    output_mode = self.analytics_service._normalize_output_mode(state.get("output_mode") or "lite")

    # 创建或获取会话
    conversation = self.analytics_service._get_or_create_conversation(
        conversation_id=state.get("conversation_id"),
        query=query,
        user_context=user_context,
    )

    # 获取会话记忆（用于多轮上下文）
    memory = self.analytics_service.conversation_repository.get_memory(conversation["conversation_id"])

    # 记录用户消息
    self.analytics_service.conversation_repository.add_message(
        conversation_id=conversation["conversation_id"],
        role="user",
        message_type="analytics_query",
        content=query,
        related_run_id=None,
        structured_content={"output_mode": output_mode},
    )

    # 更新 state
    state["conversation"] = conversation
    state["conversation_id"] = conversation["conversation_id"]
    state["conversation_memory"] = memory
    state["workflow_stage"] = AnalyticsWorkflowStage.ANALYTICS_ENTRY

    return state
```

---

### 3.2 analytics_plan（规划节点）

**文件位置**：`core/agent/workflows/analytics/nodes.py`

**职责**：
- 调用 `LLMAnalyticsIntentParser` 解析用户意图
- 生成结构化 `AnalyticsIntent`
- 将 `AnalyticsIntent` 转换为兼容的 `AnalyticsPlan`
- 记录 planning_source

**输入**（state）：
```python
{
    "query": "查询新疆区域2024年3月发电量",
    "conversation_memory": {...},  # 多轮上下文
    "trace_id": "tr_xxx",
    "run_id": "run_xxx",
    # ... 来自 analytics_entry 的字段
}
```

**处理流程**：

```
┌─────────────────────────────────────────────────────────────┐
│                    analytics_plan 节点                        │
│                                                              │
│  ┌───────────────┐                                          │
│  │ recovered_    │                                          │
│  │ plan != None? │                                          │
│  └───────┬───────┘                                          │
│          │                                                  │
│    ┌─────┴─────┐                                           │
│    ▼           ▼                                           │
│   Yes         No                                            │
│    │           │                                           │
│    ▼           ▼                                           │
│  _plan_to    intent_parser.parse()                         │
│  _intent()   (LLMAnalyticsIntentParser)                    │
│    │           │                                           │
│    │           ▼                                           │
│    │    ┌────────────┐                                     │
│    │    │ Parser     │                                     │
│    │    │ Result     │                                     │
│    │    └─────┬──────┘                                     │
│    │          │                                            │
│    │          ▼                                            │
│    │    ┌────────────┐                                     │
│    │    │ Analytics  │                                     │
│    │    │ Intent     │                                     │
│    │    └─────┬──────┘                                     │
│    │          │                                            │
│    └──────┬───┘                                            │
│           ▼                                                │
│    ┌────────────┐                                         │
│    │ _intent_to │                                         │
│    │ _plan()    │  # 转换为兼容的 AnalyticsPlan           │
│    └─────┬──────┘                                         │
│          │                                                │
│          ▼                                                │
│    state["plan"] = AnalyticsPlan                          │
│    state["intent"] = AnalyticsIntent                      │
│    state["planning_source"] = "llm_parser" | "rule_fallback"│
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

**输出**（更新后的 state）：
```python
{
    # 新增 AnalyticsIntent（核心意图结构）
    "intent": AnalyticsIntent(
        task_type="analytics_query",
        complexity=ComplexityType.SIMPLE,
        planning_mode=PlanningMode.DIRECT,
        analysis_intent=AnalysisIntentType.SIMPLE_QUERY,
        metric=MetricIntent(
            raw_text="发电量",
            metric_code="generation",
            metric_name="发电量",
            confidence=0.95
        ),
        time_range=TimeRangeIntent(
            raw_text="2024年3月",
            type=TimeRangeType.ABSOLUTE,
            value="2024-03",
            start="2024-03-01",
            end="2024-03-31",
            confidence=0.95
        ),
        org_scope=OrgScopeIntent(...),
        group_by=None,
        compare_target=CompareTarget.NONE,
        confidence=IntentConfidence(
            overall=0.9,
            metric=0.95,
            time_range=0.95,
            org_scope=0.9
        ),
        need_clarification=False,
        missing_fields=[],
        ambiguous_fields=[]
    ),

    # 兼容的旧版 AnalyticsPlan
    "plan": AnalyticsPlan(
        intent="business_analysis",
        slots={
            "metric": "发电量",
            "time_range": {...},
            "org_scope": {...}
        },
        is_executable=True,
        planning_source="llm_parser",
        confidence=0.9
    ),

    # 规划来源
    "planning_source": "llm_parser",  # 或 "rule_fallback"

    # 状态
    "workflow_stage": "analytics_plan",
    "workflow_outcome": "continue"
}
```

**关键代码**：
```python
def analytics_plan(self, state: dict) -> dict:
    """规划节点（新版统一主链路）。"""

    if state.get("recovered_plan") is not None:
        # 恢复场景：直接使用已恢复的 plan 转换为 intent
        plan = state["recovered_plan"]
        intent = self._plan_to_intent(plan)
    else:
        # 正常场景：调用 LLM 解析意图
        parser_result = self.intent_parser.parse(
            query=state["query"],
            conversation_memory=state.get("conversation_memory"),
            trace_id=state.get("trace_id"),
            run_id=state.get("run_id"),
        )

        intent = parser_result.intent
        state["planning_source"] = parser_result.planning_source

        # 将 AnalyticsIntent 转换为旧版 AnalyticsPlan（兼容保留）
        plan = self._intent_to_plan(intent)

    state["plan"] = plan
    state["intent"] = intent
    state["workflow_stage"] = AnalyticsWorkflowStage.ANALYTICS_PLAN

    return state
```

---

### 3.3 LLMAnalyticsIntentParser（意图解析器）

**文件位置**：`core/analytics/intent/parser.py`

**职责**：
- 接收用户 query、conversation context
- 调用 LLM 生成结构化 `AnalyticsIntent`
- 不生成 SQL、不更新 task_run、不调用 SQL Gateway
- 内置 fallback 机制

**输入**：
```python
{
    "query": "查询新疆区域2024年3月发电量",
    "conversation_memory": {
        "last_metric": "发电量",
        "last_time_range": {"label": "2024年2月"},
        "short_term_memory": {
            "last_group_by": None,
            "last_compare_target": None
        }
    }
}
```

**处理流程**：

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    LLMAnalyticsIntentParser.parse()                      │
│                                                                          │
│  ┌─────────────┐                                                        │
│  │ _call_llm() │                                                        │
│  └──────┬──────┘                                                        │
│         │                                                               │
│         ▼                                                               │
│  ┌──────────────────┐                                                  │
│  │ PromptRegistry    │                                                  │
│  │ .load()           │  # 加载 intent_parser_system.j2                 │
│  └─────────┬─────────┘                                                  │
│            │                                                            │
│            ▼                                                            │
│  ┌──────────────────┐                                                  │
│  │ PromptRenderer    │                                                  │
│  │ .render()         │  # 渲染 intent_parser_user.j2                  │
│  │ - query           │                                                  │
│  │ - conversation_   │                                                  │
│  │   memory          │                                                  │
│  │ - metric_catalog  │                                                  │
│  │ - schema_registry │                                                  │
│  └─────────┬─────────┘                                                  │
│            │                                                            │
│            ▼                                                            │
│  ┌──────────────────┐                                                  │
│  │ LLMGateway        │                                                  │
│  │ .structured_output│  # 调用 LLM，输出 AnalyticsIntent               │
│  └─────────┬─────────┘                                                  │
│            │                                                            │
│            ▼                                                            │
│  ┌──────────────────┐                                                  │
│  │ IntentParser      │                                                  │
│  │ OutputValidator   │  # 校验输出：禁止 SQL 字段等                    │
│  └─────────┬─────────┘                                                  │
│            │                                                            │
│            ▼                                                            │
│  ┌──────────────────┐                                                  │
│  │ IntentParserResult│                                                  │
│  │ - intent         │                                                  │
│  │ - planning_source│                                                  │
│  │ - latency_ms     │                                                  │
│  └──────────────────┘                                                  │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

**输出**：
```python
IntentParserResult(
    intent=AnalyticsIntent(
        task_type="analytics_query",
        complexity=ComplexityType.SIMPLE,
        planning_mode=PlanningMode.DIRECT,
        # ... 其他字段
    ),
    planning_source="llm_parser",
    latency_ms=1234.5,
    success=True
)
```

**Fallback 机制**：
```python
def parse(self, query: str, conversation_memory: dict | None = None, ...) -> IntentParserResult:
    try:
        intent = self._call_llm(query, conversation_memory)
        return IntentParserResult(intent=intent, success=True, ...)
    except Exception as exc:
        # LLM 失败时回退到规则解析
        return IntentParserResult(
            intent=self._create_fallback_intent(query, conversation_memory),
            planning_source="rule_fallback",
            success=False,
            error_message=str(exc)
        )
```

---

### 3.4 analytics_validate_slots（槽位校验节点）

**文件位置**：`core/agent/workflows/analytics/nodes.py`

**职责**：
- 创建 task_run
- 保存 slot_snapshot
- 调用 `AnalyticsIntentValidator` 校验
- 根据校验结果决定后续走向

**输入**（state）：
```python
{
    "intent": AnalyticsIntent(...),
    "plan": AnalyticsPlan(...),
    "conversation": {...},
    "user_context": UserContext(...),
    # ... 其他字段
}
```

**处理流程**：

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                   analytics_validate_slots 节点                               │
│                                                                              │
│  ┌──────────────────┐                                                       │
│  │ intent_validator  │                                                       │
│  │ .validate()       │                                                       │
│  └────────┬─────────┘                                                       │
│           │                                                                 │
│           ▼                                                                 │
│  ┌──────────────────┐                                                       │
│  │ IntentValidation  │                                                       │
│  │ Result           │                                                       │
│  │ - valid          │                                                       │
│  │ - need_          │                                                       │
│  │   clarification  │                                                       │
│  │ - missing_fields │                                                       │
│  │ - ambiguous_     │                                                       │
│  │   fields         │                                                       │
│  │ - errors         │                                                       │
│  └────────┬─────────┘                                                       │
│           │                                                                 │
│           ▼                                                                 │
│  ┌──────────────────┐     ┌──────────────────┐     ┌──────────────────┐   │
│  │ valid=True       │     │ need_clarification│     │ valid=False且    │   │
│  │ 且 is_executable │     │ =True            │     │ need_clarification│   │
│  │ =True            │     │                  │     │ =False           │   │
│  └────────┬─────────┘     └────────┬─────────┘     └────────┬─────────┘   │
│           │                       │                       │              │
│           ▼                       ▼                       ▼              │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐      │
│  │ workflow_outcome  │  │ workflow_outcome │  │ workflow_outcome  │      │
│  │ = CONTINUE       │  │ = CLARIFY        │  │ = FAIL           │      │
│  │ next_step =      │  │ next_step =      │  │                  │      │
│  │ analytics_build  │  │ analytics_clarify│  │                  │      │
│  │ _sql             │  │                  │  │                  │      │
│  └──────────────────┘  └──────────────────┘  └──────────────────┘      │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

**输出**（更新后的 state）：
```python
{
    # 校验结果
    "intent_validation_result": {
        "valid": True,
        "need_clarification": False,
        "missing_fields": [],
        "ambiguous_fields": [],
        "clarification_question": None,
        "errors": [],
        "sanitized_intent": AnalyticsIntent(...)
    },

    # Task Run（已创建）
    "task_run": {
        "run_id": "run_xxx",
        "trace_id": "tr_xxx",
        "conversation_id": "conv_xxx",
        "status": "executing",
        "sub_status": "planning_query"
    },

    # 状态机决策
    "workflow_stage": "analytics_validate_slots",
    "workflow_outcome": "continue",  # 或 "clarify" / "fail"
    "next_step": "analytics_build_sql",  # 或 "analytics_clarify"
    "clarification_needed": False
}
```

---

### 3.5 AnalyticsIntentValidator（意图校验器）

**文件位置**：`core/analytics/intent/validator.py`

**职责**：
- 校验 LLM 输出的 `AnalyticsIntent`
- 是意图进入 SQL Builder 的硬边界

**校验规则表**：

| 规则 | 校验内容 | 不通过结果 |
|-----|---------|-----------|
| SQL 字段禁止 | 检测 raw_sql、generated_sql、sql 等 | invalid |
| metric_code 存在 | 必须在指标目录中 | invalid |
| time_range 置信度 | >= 0.5 | clarify |
| group_by 白名单 | region/station/month/year 等 | invalid |
| compare_target 枚举 | none/yoy/mom | invalid |
| analysis_intent 枚举 | 枚举值 | invalid |
| top_n 范围 | 1-50 | invalid |
| overall 置信度 | >= 0.85 可执行，< 0.65 澄清 | clarify |
| 核心槽位缺失 | metric/time_range 为空 | clarify |
| 歧义字段 | ambiguous_fields 非空 且 overall < 0.85 | clarify |
| decomposed 必需 | required_queries 不能为空 | invalid |
| decline_attribution 必需 | yoy 时需要 yoy_baseline | invalid |

**置信度阈值**：
```python
OVERALL_THRESHOLD_HIGH = 0.85  # >= 0.85 可执行
OVERALL_THRESHOLD_LOW = 0.65   # < 0.65 必须澄清
CORE_FIELD_THRESHOLD = 0.6     # 核心字段低于此值需澄清
```

**代码片段**：
```python
def validate(self, intent: AnalyticsIntent, user_context: UserContext | None = None) -> IntentValidationResult:
    errors: list[str] = []

    # 1. SQL 字段检查
    if self._has_sql_fields(intent.model_dump()):
        return IntentValidationResult(
            valid=False,
            need_clarification=False,
            errors=["LLM 输出包含 SQL 相关字段，Validator 拒绝执行。"]
        )

    # 2. 指标校验
    metric_errors = self._validate_metric(intent.metric)
    errors.extend(metric_errors)

    # 3. 时间范围校验
    time_range_errors = self._validate_time_range(intent.time_range)
    errors.extend(time_range_errors)

    # 4. group_by 白名单校验
    group_by_errors = self._validate_group_by(intent.group_by)
    errors.extend(group_by_errors)

    # 5. top_n 范围校验
    top_n_errors = self._validate_top_n(intent.top_n)
    errors.extend(top_n_errors)

    # 6. required_queries 校验
    required_queries_errors = self._validate_required_queries(...)
    errors.extend(required_queries_errors)

    # 7. 置信度和槽位校验
    confidence_errors, need_clarification, missing_fields, ambiguous_fields, clarification_question = (
        self._validate_confidence_and_slots(...)
    )
    errors.extend(confidence_errors)

    # 8. 生成澄清问题
    if metric_errors or need_clarification:
        clarification_question = clarification_question or self._generate_clarification_question(...)

    is_valid = len(errors) == 0 and not need_clarification

    return IntentValidationResult(
        valid=is_valid,
        need_clarification=need_clarification,
        missing_fields=missing_fields,
        ambiguous_fields=ambiguous_fields,
        clarification_question=clarification_question if need_clarification else None,
        errors=errors,
        sanitized_intent=intent if is_valid else None
    )
```

---

### 3.6 analytics_clarify（澄清节点）

**文件位置**：`core/agent/workflows/analytics/nodes.py`

**职责**：
- 生成结构化 clarification 响应
- 创建 clarification_event
- 暂停 workflow，等待用户补充

**触发条件**：
- `intent_validation_result.need_clarification == True`
- 核心槽位（metric/time_range）缺失
- 指标存在歧义
- 置信度过低

**输入澄清示例**：

| 用户问句 | 缺失字段 | 澄清问题 |
|---------|---------|---------|
| "帮我看一下新疆区域上个月的情况" | metric | "你想查看哪个经营指标？例如：发电量、收入、成本、利润。" |
| "查询新疆区域发电量" | time_range | "你想查看哪个时间范围的指标？例如：本月、上个月、2024年3月。" |
| "新疆最近电量咋样" | ambiguous_fields | "你说的「电量」想看哪个口径？例如：发电量、上网电量、售电量。" |

**输出**：
```python
{
    "final_response": {
        "data": {
            "need_clarification": True,
            "question": "你想查看哪个经营指标？例如：发电量、收入、成本、利润。",
            "target_slots": ["metric"],
            "suggested_options": ["发电量", "收入", "成本", "利润"]
        },
        "meta": {
            "status": "awaiting_user_clarification",
            "conversation_id": "conv_xxx",
            "run_id": "run_xxx"
        }
    },
    "workflow_stage": "analytics_clarify",
    "workflow_outcome": "clarify",
    "clarification_needed": True
}
```

---

### 3.7 analytics_build_sql（SQL 构建节点）

**文件位置**：`core/agent/workflows/analytics/nodes.py`

**职责**：
- 根据 validated intent 构建 SQL
- 权限检查
- 数据源检查

**输入**：
```python
{
    "plan": AnalyticsPlan(
        slots={
            "metric": "发电量",
            "time_range": {"type": "absolute", "value": "2024-03", ...},
            "org_scope": {"type": "region", "name": "新疆区域", ...}
        }
    ),
    "user_context": UserContext(...),
    "task_run": {...}
}
```

**处理流程**：
```
1. 获取指标定义
   metric_definition = _get_cached_metric("发电量")

2. 获取数据源定义
   data_source_definition = schema_registry.get_data_source("bi_warehouse")

3. 获取表定义
   table_definition = schema_registry.get_table_definition(
       table_name=metric_definition.table_name
   )

4. 权限检查
   permission_check_result = _assert_metric_permission(...)

5. 构建 SQL
   sql_bundle = sql_builder.build(
       plan.slots,
       department_code=user_context.department_code
   )
```

**输出**：
```python
{
    "metric_definition": MetricDefinition(...),
    "data_source_definition": DataSourceDefinition(...),
    "table_definition": TableDefinition(...),
    "permission_check_result": {...},
    "data_scope_result": {...},
    "sql_bundle": {
        "generated_sql": "SELECT region, SUM(generation) as total_generation FROM ...",
        "data_source": "bi_warehouse",
        "metric_scope": ["generation"],
        "builder_metadata": {...}
    },
    "workflow_stage": "analytics_build_sql",
    "workflow_outcome": "continue"
}
```

---

### 3.8 analytics_guard_sql（SQL 安全校验节点）

**文件位置**：`core/agent/workflows/analytics/nodes.py`

**职责**：
- SQL 只读校验
- 白名单表检查
- DDL/DML 禁止
- 权限过滤
- LIMIT 限制

**校验项**：
```python
SQLGuard 校验规则：
├── 1. 只读校验：必须是 SELECT
├── 2. 白名单表：必须在 allowed_tables 中
├── 3. DDL 禁止：不能有 DROP/ALTER/CREATE/TRUNCATE
├── 4. DML 禁止：不能有 INSERT/UPDATE/DELETE
├── 5. 权限过滤：department_filter_column = user.department_code
├── 6. LIMIT 限制：最大 1000 行
├── 7. 敏感字段：检查字段级权限
└── 8. 超时限制：最大 30 秒
```

**输入**：
```python
{
    "sql_bundle": {
        "generated_sql": "SELECT region, SUM(generation) FROM ..."
    },
    "table_definition": TableDefinition(...),
    "user_context": UserContext(...)
}
```

**输出（校验通过）**：
```python
{
    "guard_result": SQLGuardResult(
        is_safe=True,
        checked_sql="SELECT region, SUM(generation) FROM ... LIMIT 1000",
        blocked_reason=None,
        governance_detail={...}
    ),
    "workflow_stage": "analytics_guard_sql"
}
```

**输出（校验失败）**：
```python
# 抛出 AppException
AppException(
    error_code=error_codes.SQL_GUARD_BLOCKED,
    message="SQL 安全检查未通过",
    detail={"blocked_reason": "包含禁止的 DDL 语句: DROP"}
)
```

---

### 3.9 analytics_execute_sql（SQL 执行节点）

**文件位置**：`core/agent/workflows/analytics/nodes.py`

**职责**：
- 调用 SQL Gateway 执行只读查询
- 记录 SQL Audit
- 结果脱敏

**输入**：
```python
{
    "sql_bundle": {...},
    "guard_result": SQLGuardResult(...),
    "task_run": {...},
    "user_context": {...}
}
```

**处理流程**：
```
1. 执行 SQL
   execution_result = sql_gateway.execute_readonly_query(
       SQLReadQueryRequest(
           data_source="bi_warehouse",
           sql="SELECT region, SUM(generation) FROM ...",
           timeout_ms=3000,
           row_limit=500
       )
   )

2. 记录审计
   audit_record = sql_audit_repository.create_audit(...)

3. 数据脱敏
   masking_result = data_masking_service.apply(
       rows=execution_result.rows,
       columns=execution_result.columns,
       visible_fields=...,
       sensitive_fields=...,
       user_permissions=user_context.permissions
   )
```

**输出**：
```python
{
    "execution_result": {
        "rows": [{"region": "新疆", "total_generation": 12345.67}, ...],
        "columns": ["region", "total_generation"],
        "row_count": 10,
        "latency_ms": 234,
        "data_source": "bi_warehouse",
        "db_type": "postgresql"
    },
    "audit_record": {...},
    "masking_result": DataMaskingResult(...),
    "workflow_stage": "analytics_execute_sql"
}
```

---

### 3.10 analytics_summarize（结果总结节点）

**文件位置**：`core/agent/workflows/analytics/nodes.py`

**职责**：
- 生成文本摘要
- 按 output_mode 生成 chart/insight/report
- 构造统一 AnalyticsResult

**output_mode 说明**：
| 模式 | summary | chart_spec | insight_cards | report_blocks |
|-----|---------|------------|---------------|---------------|
| lite | ✓ | - | - | - |
| standard | ✓ | ✓ | ✓ | - |
| full | ✓ | ✓ | ✓ | ✓ |

**输入**：
```python
{
    "output_mode": "standard",
    "execution_result": {...},
    "masking_result": {...},
    "audit_record": {...},
    "sql_bundle": {...},
    "guard_result": {...},
    "permission_check_result": {...},
    "need_sql_explain": False
}
```

**输出**：
```python
{
    "analytics_result": AnalyticsResult(
        run_id="run_xxx",
        trace_id="tr_xxx",
        summary="2024年3月，新疆区域发电量为12345.67万千瓦时，环比上月增长5.2%。",
        sql_preview="SELECT region, SUM(generation) FROM ...",
        chart_spec={...},
        insight_cards=[...],
        report_blocks=[],
        governance_decision={...},
        timing_breakdown={...}
    ),
    "workflow_stage": "analytics_summarize"
}
```

---

### 3.11 analytics_finish（结束节点）

**文件位置**：`core/agent/workflows/analytics/nodes.py`

**职责**：
- 写入 task_run 轻快照
- 保存 heavy result
- 记录 assistant 消息
- 更新 conversation memory
- 返回最终响应

**输出**：
```python
{
    "final_response": {
        "data": {
            # lite 模式
            "summary": "2024年3月，新疆区域发电量为12345.67万千瓦时，环比上月增长5.2%。",
            "sql_preview": "SELECT region, SUM(generation) FROM ...",
            "row_count": 10,
            "trace_id": "tr_xxx"
            # standard/full 模式会增加 chart/insight/report
        },
        "meta": {
            "status": "succeeded",
            "sub_status": "explaining_result",
            "conversation_id": "conv_xxx",
            "run_id": "run_xxx",
            "degraded": False,
            "degraded_features": []
        }
    },
    "workflow_stage": "analytics_finish",
    "workflow_outcome": "finish"
}
```

---

## 四、LangGraph 执行机制

### 4.1 Graph 构建

**文件位置**：`core/agent/workflows/analytics/graph.py`

```python
class AnalyticsLangGraphWorkflow:
    def _build_graph(self):
        graph = StateGraph(AnalyticsWorkflowState)

        # 添加节点
        graph.add_node("analytics_entry", self.nodes.analytics_entry)
        graph.add_node("analytics_plan", self.nodes.analytics_plan)
        graph.add_node("analytics_validate_slots", self.nodes.analytics_validate_slots)
        graph.add_node("analytics_clarify", self.nodes.analytics_clarify)
        graph.add_node("analytics_build_sql", self.nodes.analytics_build_sql)
        graph.add_node("analytics_guard_sql", self.nodes.analytics_guard_sql)
        graph.add_node("analytics_execute_sql", self.nodes.analytics_execute_sql)
        graph.add_node("analytics_summarize", self.nodes.analytics_summarize)
        graph.add_node("analytics_finish", self.nodes.analytics_finish)

        # 设置入口
        graph.set_entry_point("analytics_entry")

        # 添加边
        graph.add_edge("analytics_entry", "analytics_plan")
        graph.add_edge("analytics_plan", "analytics_validate_slots")

        # 条件边（validate -> clarify 或 validate -> build_sql）
        graph.add_conditional_edges(
            "analytics_validate_slots",
            _route_after_validation,
            {
                "analytics_clarify": "analytics_clarify",
                "analytics_build_sql": "analytics_build_sql",
            },
        )

        graph.add_edge("analytics_clarify", "analytics_finish")
        graph.add_edge("analytics_build_sql", "analytics_guard_sql")
        graph.add_edge("analytics_guard_sql", "analytics_execute_sql")
        graph.add_edge("analytics_execute_sql", "analytics_summarize")
        graph.add_edge("analytics_summarize", "analytics_finish")
        graph.add_edge("analytics_finish", END)

        return graph.compile()
```

### 4.2 条件路由函数

```python
def _route_after_validation(state: AnalyticsWorkflowState) -> str:
    """根据槽位校验结果决定后续走向。"""
    return state.get("next_step", "analytics_build_sql")
```

### 4.3 状态流转图

```
                    ┌─────────────────────────────────────────┐
                    │                                         │
                    ▼                                         │
┌─────────────┐  ┌────────────┐  ┌──────────────────────┐     │
│ analytics   │─▶│ analytics  │─▶│ analytics_validate  │     │
│ _entry      │  │ _plan      │  │ _slots               │     │
└─────────────┘  └────────────┘  └──────────┬───────────┘     │
                                             │                  │
                        ┌────────────────────┼────────────────┐│
                        ▼                    ▼                ▼│
                 ┌────────────┐       ┌────────────┐    ┌───────────┐
                 │ analytics  │       │ analytics  │    │ analytics │
                 │ _clarify   │       │ _build_sql │    │ _fail     │
                 └─────┬──────┘       └─────┬──────┘    └───────────┘
                       │                    │                  ▲
                       │                    ▼                  │
                       │             ┌────────────┐            │
                       │             │ analytics  │            │
                       │             │ _guard_sql │            │
                       │             └─────┬──────┘            │
                       │                   │                   │
                       │                   ▼                   │
                       │             ┌────────────┐            │
                       │             │ analytics  │            │
                       │             │ _execute_  │            │
                       │             │ sql         │            │
                       │             └─────┬──────┘            │
                       │                   │                   │
                       │                   ▼                   │
                       │             ┌────────────┐            │
                       │             │ analytics  │            │
                       │             │ _summarize │            │
                       │             └─────┬──────┘            │
                       │                   │                   │
                       └───────▶  ┌────────────┐ ◀────────────┘
                                  │ analytics  │
                                  │ _finish    │
                                  └────────────┘
```

---

## 五、Supervisor 层职责

### 5.1 Supervisor 位置

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              API 层                                         │
│                         /api/v1/chat                                       │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                          Supervisor 层                                       │
│                                                                              │
│  SupervisorService.handle_request()                                          │
│       │                                                                     │
│       ▼                                                                     │
│  DelegationController                                                        │
│       │                                                                     │
│       ▼                                                                     │
│  ┌────────────────────────────────────────────────────────────────────┐     │
│  │                    TaskEnvelope                                    │     │
│  │  - run_id: sup_xxx                                                 │     │
│  │  - trace_id: tr_xxx                                                │     │
│  │  - task_type: "business_analysis"                                 │     │
│  │  - input_payload: {query, user_context, ...}                      │     │
│  └────────────────────────────────────────────────────────────────────┘     │
│       │                                                                     │
│       ▼                                                                     │
│  ┌────────────────────────────────────────────────────────────────────┐     │
│  │              DelegationTarget                                       │     │
│  │  - agent_card: AgentCardRef(analytics_expert, local)               │     │
│  └────────────────────────────────────────────────────────────────────┘     │
│       │                                                                     │
│       ▼                                                                     │
│  ┌────────────────────────────────────────────────────────────────────┐     │
│  │              Local Handler / A2A Ready                            │     │
│  │  - AnalyticsWorkflowAdapter.as_local_handler()                     │     │
│  └────────────────────────────────────────────────────────────────────┘     │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                          Analytics 层                                        │
│                     LangGraph StateGraph                                    │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 5.2 Supervisor 职责清单

| 职责 | 说明 | 代码位置 |
|-----|------|---------|
| 接收请求 | 接收 API 层的业务请求 | `supervisor_service.py` |
| 解析目标专家 | 根据 task_type 解析目标 Agent | `delegation_controller.py` |
| 构造 TaskEnvelope | 生成统一的跨专家协议 | `delegation_controller.py` |
| 生成 run_id/trace_id | 贯穿整个链路的唯一标识 | `delegation_controller.py` |
| 委托执行 | 调用 local handler 或 A2A 远程 | `delegation_controller.py` |
| 汇总结果 | 统一 ResultContract 返回 | `supervisor_service.py` |

### 5.3 不在 Supervisor 层的职责

- **不在 Supervisor 层**：理解用户问句
- **不在 Supervisor 层**：生成 SQL
- **不在 Supervisor 层**：判断是否澄清
- **不在 Supervisor 层**：执行数据分析

---

## 六、状态持久化

### 6.1 持久化层级

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          微观状态（不持久化）                                │
│                                                                              │
│  AnalyticsWorkflowState（只存在于 workflow 执行期间）                        │
│  ├── intent: AnalyticsIntent                                                │
│  ├── plan: AnalyticsPlan                                                    │
│  ├── sql_bundle: dict                                                       │
│  ├── execution_result: dict                                                │
│  └── masking_result: dict                                                  │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                          业务状态（持久化）                                  │
│                                                                              │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐              │
│  │ task_run        │  │ slot_snapshot   │  │ clarification_ │              │
│  │                 │  │                 │  │ event          │              │
│  │ - run_id        │  │ - run_id        │  │ - event_id     │              │
│  │ - input_snapshot│  │ - slots         │  │ - run_id       │              │
│  │ - output_snapshot│ │ - created_at    │  │ - question     │              │
│  └─────────────────┘  └─────────────────┘  └─────────────────┘              │
│                                                                              │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐              │
│  │ conversation    │  │ sql_audit      │  │ analytics_     │              │
│  │                 │  │                 │  │ result_repository│             │
│  │ - messages      │  │ - run_id        │  │                 │              │
│  │ - memory        │  │ - sql          │  │ - heavy_result │              │
│  └─────────────────┘  │ - audit        │  └─────────────────┘              │
│                       └─────────────────┘                                   │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 6.2 task_run 持久化时机

| 时机 | 内容 | 位置 |
|-----|------|------|
| analytics_validate_slots | input_snapshot | `create_task_run()` |
| analytics_build_sql | context_snapshot (slots, planning_source, confidence) | `update_task_run()` |
| analytics_execute_sql | status = executing | `update_task_run()` |
| analytics_finish | output_snapshot, status = succeeded | `update_task_run()` |

### 6.3 slot_snapshot 持久化时机

```python
# analytics_validate_slots 节点
self.analytics_service.task_run_repository.create_slot_snapshot(
    run_id=task_run["run_id"],
    task_type="analytics",
    **self.analytics_service.snapshot_builder.build_slot_snapshot_payload(plan=plan)
)
```

### 6.4 clarification_event 持久化时机

```python
# analytics_service._build_clarification_response()
clarification_event = self.clarification_event_repository.create_clarification_event(
    run_id=task_run["run_id"],
    conversation_id=conversation["conversation_id"],
    question=clarification_question,
    target_slots=clarification_target_slots,
    suggested_options=clarification_suggested_options,
    status="pending_user_response"
)
```

---

## 七、上下文承接

### 7.1 多轮对话上下文

```
用户第1轮：
  "查询发电量"

用户第2轮：
  "看新疆区域的"  # 系统会自动承接"发电量"
                  # 从 conversation_memory 读取 last_metric

用户第3轮：
  "和去年对比呢"  # 系统会承接 last_metric, last_time_range
                  # 自动添加 compare_target="yoy"
```

### 7.2 conversation_memory 结构

```python
{
    "conversation_id": "conv_xxx",
    "messages": [
        {"role": "user", "content": "查询发电量", "timestamp": "..."},
        {"role": "assistant", "content": "2024年3月发电量是...", "timestamp": "..."}
    ],
    "last_metric": "发电量",
    "last_time_range": {"label": "2024年3月", "type": "absolute"},
    "last_org_scope": None,
    "short_term_memory": {
        "last_analytics_run_id": "run_xxx",
        "last_group_by": None,
        "last_compare_target": None,
        "last_top_n": None
    }
}
```

### 7.3 clarification 恢复

```
用户问句1：
  "帮我看一下新疆区域上个月的情况"

系统响应（clarification）：
  {"question": "你想查看哪个经营指标？", "target_slots": ["metric"]}

用户问句2（补充）：
  "发电量"

系统处理：
  1. 读取 slot_snapshot (新疆区域 + 上个月)
  2. 合并用户补充 (发电量)
  3. 重新构造 AnalyticsIntent
  4. 重新进入 Validator
  5. 校验通过后继续执行
```

---

## 八、澄清判断逻辑

### 8.1 澄清触发条件

| 条件 | 判断逻辑 | 代码位置 |
|-----|---------|---------|
| metric 缺失 | `intent.metric is None or confidence.metric < 0.6` | validator.py |
| time_range 缺失 | `intent.time_range is None or confidence.time_range < 0.6` | validator.py |
| overall 置信度过低 | `confidence.overall < 0.65` | validator.py |
| 指标歧义 | `intent.ambiguous_fields 非空 and confidence.overall < 0.85` | validator.py |
| LLM 输出 need_clarification | `intent.need_clarification == True` | validator.py |

### 8.2 澄清判断流程图

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    Validator.validate()                                  │
│                                                                          │
│  ┌─────────────┐                                                        │
│  │ SQL 字段检查 │                                                        │
│  └──────┬──────┘                                                        │
│         │                                                               │
│         ▼                                                               │
│  ┌─────────────┐     ┌─────────────┐                                    │
│  │ 校验 metric │────▶│ metric 有效?│                                    │
│  └──────┬──────┘     └──────┬──────┘                                    │
│         │                    │否                                         │
│         │                    ▼                                           │
│         │            missing_fields += "metric"                          │
│         │            need_clarification = True                            │
│         │否                                                               │
│         ▼                                                               │
│  ┌─────────────┐     ┌─────────────┐                                    │
│  │ 校验 time   │────▶│ time 有效?  │                                    │
│  │ _range      │     └──────┬──────┘                                    │
│  └──────┬──────┘            │否                                         │
│         │                    ▼                                           │
│         │            missing_fields += "time_range"                      │
│         │            need_clarification = True                           │
│         │                                                               │
│         ▼                                                               │
│  ┌─────────────┐     ┌─────────────┐                                    │
│  │ 校验        │────▶│ overall <   │                                    │
│  │ confidence  │     │ 0.65?       │                                    │
│  └──────┬──────┘     └──────┬──────┘                                    │
│         │                    │是                                         │
│         │                    ▼                                           │
│         │            need_clarification = True                           │
│         │                                                               │
│         ▼                                                               │
│  ┌─────────────┐     ┌─────────────┐                                    │
│  │ ambiguous   │────▶│ ambiguous_  │                                    │
│  │ _fields     │     │ fields 非空  │                                    │
│  │ 检查        │     │ 且 overall  │                                    │
│  └─────────────┘     │ < 0.85?     │                                    │
│                      └──────┬──────┘                                    │
│                             │是                                         │
│                             ▼                                           │
│                     need_clarification = True                           │
│                                                                          │
│         ┌──────────────────────────────────────────┐                     │
│         │                                          │                     │
│         ▼                                          ▼                     │
│  ┌─────────────┐                           ┌─────────────┐              │
│  │ need_clarif-│                           │ valid =     │              │
│  │ ication=True│                           │ False       │              │
│  │             │                           │             │              │
│  │ 继续判断    │                           │ errors 非空 │              │
│  └─────────────┘                           └─────────────┘              │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 九、Prompt 提示词设计

### 9.1 System Prompt (intent_parser_system.j2)

**文件位置**：`core/prompts/templates/analytics/intent_parser_system.j2`

**核心约束**：
```
1. 不生成 SQL：只输出结构化意图
2. 不猜测数据库结构
3. 置信度评估
4. 歧义处理
5. 缺失检测
```

**关键段落**：
```jinja2
## 核心原则

1. **不生成 SQL**：你只输出结构化意图，不允许生成任何 SQL 语句
2. **不猜测数据库结构**：不输出表名、字段名等数据库元信息
3. **置信度评估**：对每个字段给出置信度评估
4. **歧义处理**：当信息不明确或存在多种可能时，设置 ambiguous_fields 并提供候选
5. **缺失检测**：当关键信息缺失时，设置 missing_fields 和 need_clarification=true
```

### 9.2 User Prompt (intent_parser_user.j2)

**文件位置**：`core/prompts/templates/analytics/intent_parser_user.j2`

**渲染变量**：
```python
{
    "query": "查询新疆区域2024年3月发电量",
    "conversation_memory": {...},
    "metric_catalog_summary": "## 可用指标目录\n- 发电量（代码：generation）\n- 收入（代码：revenue）",
    "schema_registry_summary": "支持分组维度：region（区域）、station（电站）\n支持对比目标：yoy（同比）、mom（环比）",
    "user_context_summary": "默认角色：employee"
}
```

### 9.3 典型场景的 Prompt 输出

#### 场景1：简单查询
```
输入：查询新疆区域2024年3月发电量

LLM 输出：
{
  "task_type": "analytics_query",
  "complexity": "simple",
  "planning_mode": "direct",
  "analysis_intent": "simple_query",
  "metric": {
    "raw_text": "发电量",
    "metric_code": "generation",
    "metric_name": "发电量",
    "confidence": 0.95
  },
  "time_range": {
    "raw_text": "2024年3月",
    "type": "absolute",
    "value": "2024-03",
    "confidence": 0.95
  },
  "org_scope": {
    "raw_text": "新疆区域",
    "type": "region",
    "confidence": 0.9
  },
  "confidence": {"overall": 0.9, "metric": 0.95, "time_range": 0.95},
  "need_clarification": false,
  "missing_fields": [],
  "ambiguous_fields": []
}
```

#### 场景2：缺指标
```
输入：帮我看一下新疆区域上个月的情况

LLM 输出：
{
  "task_type": "analytics_query",
  "complexity": "simple",
  "planning_mode": "clarification",
  "metric": null,
  "confidence": {"overall": 0.5, "metric": 0.1},
  "need_clarification": true,
  "clarification_question": "你想查看哪个经营指标？例如：发电量、收入、成本、利润。",
  "missing_fields": ["metric"]
}
```

#### 场景3：指标歧义
```
输入：新疆最近电量咋样

LLM 输出：
{
  "task_type": "analytics_query",
  "complexity": "simple",
  "planning_mode": "clarification",
  "metric": {
    "raw_text": "电量",
    "confidence": 0.4,
    "candidates": [
      {"metric_code": "generation", "metric_name": "发电量", "confidence": 0.4},
      {"metric_code": "online", "metric_name": "上网电量", "confidence": 0.3},
      {"metric_code": "sales", "metric_name": "售电量", "confidence": 0.3}
    ]
  },
  "confidence": {"overall": 0.55, "metric": 0.4},
  "need_clarification": true,
  "clarification_question": "你说的「电量」想看哪个口径？例如：发电量、上网电量、售电量。",
  "ambiguous_fields": ["metric"]
}
```

#### 场景4：复杂同比拖累分析
```
输入：分析新疆区域近三个月发电量下降的原因，并和去年同期对比，看哪些电站拖累最大

LLM 输出：
{
  "task_type": "analytics_query",
  "complexity": "complex",
  "planning_mode": "decomposed",
  "analysis_intent": "decline_attribution",
  "metric": {
    "raw_text": "发电量",
    "metric_code": "generation",
    "confidence": 0.95
  },
  "time_range": {
    "raw_text": "近三个月",
    "type": "relative",
    "confidence": 0.9
  },
  "org_scope": {
    "raw_text": "新疆区域",
    "type": "region",
    "confidence": 0.9
  },
  "group_by": "station",
  "compare_target": "yoy",
  "top_n": 10,
  "required_queries": [
    {
      "query_name": "current",
      "purpose": "查询当前周期各电站发电量",
      "metric_code": "generation",
      "period_role": "current",
      "group_by": "station"
    },
    {
      "query_name": "yoy_baseline",
      "purpose": "查询去年同期各电站发电量",
      "metric_code": "generation",
      "period_role": "yoy_baseline",
      "group_by": "station"
    }
  ],
  "confidence": {"overall": 0.92},
  "need_clarification": false,
  "missing_fields": [],
  "ambiguous_fields": []
}
```

---

## 十、用户问句所有可能情况

### 10.1 情况分类表

| 情况 | 用户问句示例 | complexity | planning_mode | need_clarification | 后续节点 |
|-----|-------------|------------|---------------|-------------------|---------|
| 简单明确 | "查询新疆区域2024年3月发电量" | simple | direct | false | build_sql |
| 缺指标 | "帮我看一下新疆区域上个月的情况" | simple | clarification | true | clarify |
| 缺时间 | "查询新疆区域发电量" | simple | clarification | true | clarify |
| 指标歧义 | "新疆最近电量咋样" | simple | clarification | true | clarify |
| 复杂查询 | "分析新疆区域近三个月发电量下降的原因" | complex | decomposed | false | build_sql |
| SQL 注入 | "发电量; DROP TABLE metrics;" | - | - | - | fail (validator 拒绝) |
| 无效 SQL | "SELECT * FROM metrics" | - | - | - | fail (guard 拒绝) |
| 越权查询 | "查询全公司利润" | simple | clarification | true | clarify (权限不足) |

### 10.2 各情况详细流程

#### 10.2.1 简单明确查询
```
用户：查询新疆区域2024年3月发电量

流程：
analytics_entry
    │ query: "查询新疆区域2024年3月发电量"
    ▼
analytics_plan
    │ intent_parser.parse()
    │ intent.complexity = "simple"
    │ intent.planning_mode = "direct"
    ▼
analytics_validate_slots
    │ validator.validate()
    │ valid = True
    │ need_clarification = False
    ▼
analytics_build_sql
    │ sql_builder.build()
    │ generated_sql: "SELECT region, SUM(generation) ..."
    ▼
analytics_guard_sql
    │ sql_guard.validate()
    │ is_safe = True
    ▼
analytics_execute_sql
    │ sql_gateway.execute()
    │ rows: [{"region": "新疆", "total": 12345}]
    ▼
analytics_summarize
    │ summary: "2024年3月，新疆区域发电量为12345万千瓦时"
    ▼
analytics_finish
    │ final_response
```

#### 10.2.2 缺指标澄清
```
用户：帮我看一下新疆区域上个月的情况

流程：
analytics_entry
    │ query: "帮我看一下新疆区域上个月的情况"
    ▼
analytics_plan
    │ intent_parser.parse()
    │ intent.metric = null
    │ intent.need_clarification = True
    ▼
analytics_validate_slots
    │ validator.validate()
    │ valid = True
    │ need_clarification = True
    │ missing_fields = ["metric"]
    │ clarification_question = "你想查看哪个经营指标？..."
    ▼
analytics_clarify
    │ 返回澄清响应
    │ {
    │   "need_clarification": True,
    │   "question": "你想查看哪个经营指标？...",
    │   "target_slots": ["metric"],
    │   "suggested_options": ["发电量", "收入", ...]
    │ }
    ▼
analytics_finish
    │ status = "awaiting_user_clarification"

用户补充：发电量

恢复流程：
resume_from_slots()
    │ recovered_plan.slots["metric"] = "发电量"
    ▼
analytics_plan
    │ intent = _plan_to_intent(recovered_plan)
    ▼
analytics_validate_slots
    │ validator.validate()
    │ valid = True
    ▼
analytics_build_sql
    ▼
... (继续正常流程)
```

#### 10.2.3 指标歧义澄清
```
用户：新疆最近电量咋样

流程：
analytics_entry
    ▼
analytics_plan
    │ intent.metric.candidates = [
    │   {metric_code: "generation", name: "发电量"},
    │   {metric_code: "online", name: "上网电量"},
    │   {metric_code: "sales", name: "售电量"}
    │ ]
    │ intent.ambiguous_fields = ["metric"]
    │ intent.need_clarification = True
    ▼
analytics_validate_slots
    │ validator.validate()
    │ valid = True
    │ need_clarification = True
    │ ambiguous_fields = ["metric"]
    ▼
analytics_clarify
    │ 返回澄清响应
    │ {
    │   "question": "你说的「电量」想看哪个口径？...",
    │   "suggested_options": ["发电量", "上网电量", "售电量"]
    │ }
    ▼
analytics_finish
```

#### 10.2.4 复杂同比分析
```
用户：分析新疆区域近三个月发电量下降的原因，并和去年同期对比，看哪些电站拖累最大

流程：
analytics_entry
    ▼
analytics_plan
    │ intent.complexity = "complex"
    │ intent.planning_mode = "decomposed"
    │ intent.analysis_intent = "decline_attribution"
    │ intent.compare_target = "yoy"
    │ intent.required_queries = [
    │   {query_name: "current", period_role: "current"},
    │   {query_name: "yoy_baseline", period_role: "yoy_baseline"}
    │ ]
    ▼
analytics_validate_slots
    │ validator.validate()
    │ valid = True (required_queries 非空 且 包含 yoy_baseline)
    ▼
analytics_build_sql
    │ # 需要处理多个子查询
    │ sql_bundle = {
    │   "generated_sql": "WITH current AS (...), yoy AS (...) SELECT ...",
    │   "metric_scope": ["generation"]
    │ }
    ▼
analytics_guard_sql
    ▼
analytics_execute_sql
    │ execution_result.rows = [
    │   {station: "电站A", current: 1000, yoy: 1200, decline: 200},
    │   {station: "电站B", current: 800, yoy: 900, decline: 100}
    │ ]
    ▼
analytics_summarize
    │ summary: "近三个月发电量下降，拖累最大的是电站A（下降200万千瓦时）"
    ▼
analytics_finish
```

#### 10.2.5 SQL 注入被拒绝
```
用户：查询发电量 DROP TABLE metrics;

流程：
analytics_entry
    ▼
analytics_plan
    │ intent.metric = MetricIntent(...)
    │ intent.planning_mode = "direct"
    ▼
analytics_validate_slots
    │ validator.validate()
    │ valid = True (intent 中无 SQL)
    ▼
analytics_build_sql
    │ sql_builder.build()
    │ generated_sql = "SELECT ... FROM metrics WHERE ..."  # 正常 SQL
    ▼
analytics_guard_sql
    │ sql_guard.validate()
    │ # 检测到 DROP TABLE
    │ is_safe = False
    │ blocked_reason = "检测到禁止的 DDL 语句: DROP"
    ▼
analytics_finish (异常)
    │ AppException: SQL_GUARD_BLOCKED
```

#### 10.2.6 LLM 错误输出 SQL 被拒绝
```
模拟 LLM 错误输出：
{
  "task_type": "analytics_query",
  "metric": {...},
  "raw_sql": "SELECT * FROM users"  # 错误：LLM 生成了 SQL
}

流程：
analytics_entry
    ▼
analytics_plan
    │ intent_parser.parse()
    │ intent.raw_sql = "SELECT * FROM users"  # 来自 LLM 错误输出
    ▼
analytics_validate_slots
    │ validator.validate()
    │ _has_sql_fields(intent_dict) = True
    │ valid = False
    │ errors = ["LLM 输出包含 SQL 相关字段，Validator 拒绝执行。"]
    ▼
# 直接失败，不进入 SQL Builder
```

---

## 十一、完整链路时序图

```
用户           Supervisor        Adapter          Graph           Nodes           SQL层
 │                 │                │               │               │               │
 │──POST /chat────▶│                │               │               │               │
 │                 │──handle_request()──▶│         │               │               │
 │                 │                │               │               │               │
 │                 │                │──invoke()────▶│               │               │
 │                 │                │               │──compiled────▶│               │
 │                 │                │               │.invoke(state)  │               │
 │                 │                │               │               │               │
 │                 │                │               │◀──analytics_entry──▶│          │
 │                 │                │               │               │               │
 │                 │                │               │◀──analytics_plan──▶│           │
 │                 │                │               │               │               │
 │                 │                │               │               │──LLM解析──▶│         │
 │                 │                │               │               │◀──Intent───│         │
 │                 │                │               │               │               │
 │                 │                │               │◀──analytics_validate──▶│      │
 │                 │                │               │               │               │
 │                 │                │               │               │──Validator──▶│       │
 │                 │                │               │               │◀──Result────│       │
 │                 │                │               │               │               │
 │                 │                │               │◀──analytics_build_sql──▶│       │
 │                 │                │               │               │               │
 │                 │                │               │               │──SQLBuilder──▶│      │
 │                 │                │               │               │◀──SQLBundle──│      │
 │                 │                │               │               │               │
 │                 │                │               │◀──analytics_guard_sql──▶│      │
 │                 │                │               │               │               │
 │                 │                │               │               │──SQLGuard──▶│       │
 │                 │                │               │               │◀──Safe──────│       │
 │                 │                │               │               │               │
 │                 │                │               │◀──analytics_execute_sql──▶│   │
 │                 │                │               │               │               │
 │                 │                │               │               │──SQLGateway──▶│     │
 │                 │                │               │               │◀──Result────│       │
 │                 │                │               │               │               │
 │                 │                │               │◀──analytics_summarize──▶│       │
 │                 │                │               │               │               │
 │                 │                │               │◀──analytics_finish──▶│        │
 │                 │                │               │               │               │
 │                 │◀──final_response──────────────│               │               │
 │◀──HTTP 200─────│                │               │               │               │
```

---

## 十二、关键代码文件索引

| 功能 | 文件路径 |
|-----|---------|
| LangGraph 主入口 | `core/agent/workflows/analytics/graph.py` |
| 节点实现 | `core/agent/workflows/analytics/nodes.py` |
| 状态定义 | `core/agent/workflows/analytics/state.py` |
| 适配器 | `core/agent/workflows/analytics/adapter.py` |
| Supervisor | `core/agent/supervisor/supervisor_service.py` |
| 委托控制 | `core/agent/supervisor/delegation_controller.py` |
| 意图解析器 | `core/analytics/intent/parser.py` |
| 意图校验器 | `core/analytics/intent/validator.py` |
| 意图结构 | `core/analytics/intent/schema.py` |
| **新版 SQL Builder（基于 Intent）** | `core/agent/control_plane/intent_sql_builder.py` |
| **分析结果模型** | `core/analytics/analytics_result_model.py` |
| **结果仓库** | `core/repositories/analytics_result_repository.py` |
| System Prompt | `core/prompts/templates/analytics/intent_parser_system.j2` |
| User Prompt | `core/prompts/templates/analytics/intent_parser_user.j2` |
| Prompt 目录 | `core/prompts/catalog.py` |
| AnalyticsService | `core/services/analytics_service.py` |
| AnalyticsPlan | `core/agent/control_plane/analytics_planner.py` |
| SQL Builder（旧版） | `core/agent/control_plane/sql_builder.py` |
| SQL Guard | `core/agent/control_plane/sql_guard.py` |
| SQL Gateway | `core/tools/sql/sql_gateway.py` |

---

## 十三、新增组件说明

### 13.1 AnalyticsIntentSQLBuilder

**文件位置**：`core/agent/control_plane/intent_sql_builder.py`

**职责**：
- 直接接收经过 Validator 校验后的 `AnalyticsIntent`
- 生成 `simple` 和 `complex` 两种模式的 SQL
- 所有 SQL 字段、表、group_by 都来自 intent 和 schema registry

**关键方法**：

```python
class AnalyticsIntentSQLBuilder:
    def build(self, intent: AnalyticsIntent, *, department_code: str | None = None) -> dict:
        """根据 AnalyticsIntent 构造 SQL。"""

    def _build_simple_sql(self, intent: AnalyticsIntent, ...) -> dict:
        """构造简单查询 SQL（direct 模式）。"""

    def _build_complex_sql(self, intent: AnalyticsIntent, ...) -> dict:
        """构造复杂查询 SQL（decomposed 模式）。"""

    def _parse_time_range(self, intent: AnalyticsIntent) -> dict:
        """解析时间范围，转换为 SQL Builder 需要的格式。"""

    def _parse_org_scope(self, intent: AnalyticsIntent, table_definition) -> dict | None:
        """解析组织范围。"""
```

### 13.2 AnalyticsResult

**文件位置**：`core/analytics/analytics_result_model.py`

**职责**：
- 作为经营分析工作流最终输出的结构化结果对象
- 承载查询结果、摘要、图表、洞察、报告等完整输出

**关键方法**：

```python
class AnalyticsResult(BaseModel):
    def to_lite_view(self) -> dict:
        """转换为 lite 视图（只返回摘要）。"""

    def to_standard_view(self) -> dict:
        """转换为 standard 视图（返回摘要+图表+洞察）。"""

    def to_full_view(self) -> dict:
        """转换为 full 视图（返回完整信息）。"""

    def to_heavy_result(self) -> dict:
        """转换为重结果（用于持久化）。"""

    def to_lightweight_snapshot(self) -> dict:
        """转换为轻量快照（用于 task_run.output_snapshot）。"""
```

### 13.3 analytics_result_repository

**文件位置**：`core/repositories/analytics_result_repository.py`

**职责**：
- 持久化经营分析的重量结果（表格、图表、洞察、报告等）
- 当前阶段使用内存存储

### 13.4 analytics_build_sql 节点改造

**文件位置**：`core/agent/workflows/analytics/nodes.py`

**改造内容**：
- 优先使用 `state["intent"]` 生成 SQL
- 如果 intent 中缺少必要信息，回退到 `plan.slots`
- 支持 `simple` 和 `complex` 两种模式

```python
def analytics_build_sql(self, state: dict) -> dict:
    """SQL 构造节点（新版适配 AnalyticsIntent）。"""

    # 优先使用 intent 生成 SQL
    if intent is not None:
        return self._build_sql_from_intent(intent, plan, user_context, task_run)
    else:
        # 回退到旧的 plan.slots 方式
        return self._build_sql_from_slots(plan, user_context, task_run)
```

---

## 十五、新增组件说明

### 15.1 AnalyticsRepairController

SQL 执行失败时的意图修复控制器。

**文件路径**: `core/agent/workflows/analytics/repair_controller.py`

**核心功能**:
- 错误分类：超时、无数据、语法错误等
- LLM 驱动的意图修复
- 完整重新规划能力

**修复策略**:
| 策略 | 说明 |
|-----|------|
| relax_time_range | 放宽时间范围（精确日期→月/季度） |
| simplify_group_by | 简化分组维度（电站→区域） |
| reduce_top_n | 减少返回行数上限 |
| remove_compare | 移除同比/环比分析 |
| request_clarification | 需要用户澄清 |

**Prompt 模板**:
- `analytics/repair_system.j2`
- `analytics/repair_user.j2`
- `analytics/repair_replan_system.j2`
- `analytics/repair_replan_user.j2`

### 15.2 RequiredQueriesExecutor

复杂分析 required_queries 执行器。

**文件路径**: `core/agent/control_plane/required_queries_executor.py`

**核心功能**:
- 解析 required_queries，识别主查询和基准查询
- 执行多个子查询
- 组合结果，生成同比/环比分析

**输出结构**:
```python
@dataclass
class CombinedExecutionResult:
    main_result: QueryExecutionResult | None
    baseline_results: list[QueryExecutionResult]
    combined_rows: list[dict]
    summary: dict
    all_success: bool
```

### 15.3 WorkflowCheckpointManager

LangGraph Checkpoint 管理器。

**文件路径**: `core/agent/workflows/analytics/checkpoint.py`

**核心功能**:
- 工作流状态保存和恢复
- 支持 Memory/File/Postgres 多种存储
- 节点级 Checkpoint

**使用方式**:
```python
manager = create_checkpoint_manager(enabled=True)
manager.start_checkpoint("thread_123", initial_state)
manager.save_checkpoint(state)
restored = manager.restore_checkpoint("thread_123")
```

---

## 十六、测试覆盖

### 16.1 测试文件清单

| 文件 | 测试类型 | 场景数 |
|-----|---------|--------|
| `tests/unit/core/analytics/test_intent.py` | 单元测试 | 17 |
| `tests/agent/test_analytics_langgraph_workflow.py` | 工作流测试 | 3 |
| `tests/agent/test_analytics_integration.py` | 集成测试 | 12 |
| `tests/agent/test_analytics_e2e.py` | 端到端测试 | 10 |
| `tests/agent/test_analytics_repair.py` | 修复控制器测试 | 10 |
| `tests/agent/test_required_queries_executor.py` | 执行器测试 | 6 |
| `tests/agent/test_analytics_checkpoint.py` | Checkpoint 测试 | 18 |
| `tests/agent/test_analytics_performance.py` | 性能测试 | 7 |

**总计**: 83 个测试用例

### 16.2 测试场景覆盖

| 场景 | 测试用例 |
|-----|---------|
| 简单明确查询 | `test_simple_clear_query` |
| 缺指标澄清 | `test_missing_metric_clarification` |
| 缺时间范围澄清 | `test_missing_time_range_clarification` |
| 指标歧义澄清 | `test_ambiguous_metric_clarification` |
| 复杂同比分析 | `test_complex_yoy_analysis` |
| SQL 注入防护 | `test_sql_injection_protection` |
| LLM 输出 SQL 拒绝 | `test_llm_sql_field_rejection` |
| 澄清恢复执行 | `test_clarification_resume` |
| 置信度阈值校验 | `test_validator_confidence_threshold` |
| group_by 白名单 | `test_validator_group_by_whitelist` |
| required_queries 校验 | `test_decomposed_requires_required_queries` |
| decline_attribution 校验 | `test_decline_attribution_requires_yoy_baseline` |

---

## 十七、版本说明

| 版本 | 日期 | 变更内容 |
|-----|------|---------|
| v1 | 2026-04 | 初始实现，规则 Planner + Slot Fallback + ReAct 分流 |
| v2 | 2026-05-02 | 链路收敛：统一 LLMAnalyticsIntentParser + AnalyticsIntentValidator |
| v2.1 | 2026-05-02 | 新增 AnalyticsIntentSQLBuilder、AnalyticsResult、analytics_result_repository |
|| v3 | 2026-05-02 | 新增 RepairController、RequiredQueriesExecutor、CheckpointManager、完整测试覆盖 |

---

## 十八、典型问句完整链路（新手友好版）

> **阅读说明**：本章节用 5 个典型问句贯穿全文，每个问句都从"前端调什么接口"开始，逐步讲解整个流程。
> 每个步骤都包含：**输入什么 → 输出什么 → 什么时候读写上下文 → 持久化什么**。

### 18.1 问句分类概览

| 问句 | 覆盖场景 | 流程特点 |
|-----|---------|---------|
| "查询新疆区域2024年3月发电量" | 简单查询 | 完整流程，无中断 |
| "帮我看一下新疆区域上个月的情况" | 缺指标 | 触发澄清，用户补充后恢复 |
| "新疆最近电量咋样" | 指标歧义 | 触发澄清，用户选择后继续 |
| "分析近三个月发电量下降原因，和去年对比" | 复杂分析 | 并行查询多子SQL |
| "对比聚乙烯销量和发电量" | 跨数据源 | 并行查询不同数据源 |

---

### 18.2 简单查询：查询新疆区域2024年3月发电量

**问句**：`"查询新疆区域2024年3月发电量"`

---

#### 第一步：前端调接口

**接口**：`POST /api/v1/analytics/query`

**请求参数**：
```python
{
    "query": "查询新疆区域2024年3月发电量",  # 用户问句
    "output_mode": "standard",                   # 输出模式：lite/standard/full
    "need_sql_explain": False,                   # 是否需要返回SQL说明
    "conversation_id": None,                     # 会话ID，首次为空
    "user_context": {
        "user_id": "u_xxx",                     # 用户ID
        "department_code": "XJ",                 # 部门代码，用于数据权限过滤
        "role": "employee"                       # 角色：employee/manager/admin
    }
}
```

**响应（同步模式）**：
```python
{
    "success": True,
    "data": {
        "run_id": "run_xxx",                    # 本次运行ID，用于追踪
        "trace_id": "tr_xxx",                    # 链路追踪ID
        "status": "succeeded",                   # 最终状态
        "conversation_id": "conv_xxx",           # 会话ID，后续请求带上

        # lite 模式只返回 summary
        "summary": "2024年3月，新疆区域发电量为12345.67万千瓦时",

        # standard/full 模式额外返回
        "chart_spec": {...},                     # 图表配置
        "insight_cards": [...],                  # 洞察卡片
        "report_blocks": [...],                  # 报告块（仅full模式）
        "sql_preview": "SELECT region, SUM(generation)...",  # SQL预览
        "row_count": 5                           # 结果行数
    },
    "meta": {
        "latency_ms": 1234,                      # 总耗时
        "timing_breakdown": {                    # 各阶段耗时
            "intent_parse_ms": 234,
            "sql_execute_ms": 567,
            "summarize_ms": 123
        }
    }
}
```

---

#### 第二步：入口节点（analytics_entry）

**文件位置**：`core/agent/workflows/analytics/nodes.py`

**职责**：校验问句、创建会话、读取上下文

**输入（state初始状态）**：
```python
{
    "query": "查询新疆区域2024年3月发电量",      # 用户原始问句
    "output_mode": "standard",                    # 输出模式
    "conversation_id": None,                    # 首次为空
    "user_context": {...},                      # 用户上下文
    "run_id": None,                            # 初始为空
    "trace_id": None                           # 初始为空
}
```

**输出（更新后的state）**：
```python
{
    # 标准化后的问句
    "query": "查询新疆区域2024年3月发电量",      # 去除首尾空格

    # 会话信息（新建或读取）
    "conversation_id": "conv_xxx",              # 会话ID
    "conversation": {...},                      # 会话完整对象

    # 多轮上下文（从历史会话读取）
    "conversation_memory": {
        "last_metric": None,                    # 上轮查询的指标
        "last_time_range": None,                # 上轮查询的时间
        "last_org_scope": None,                 # 上轮查询的组织范围
        "short_term_memory": {
            "last_group_by": None,
            "last_compare_target": None,
            "last_top_n": None
        }
    },

    # 工作流状态
    "workflow_stage": "analytics_entry",         # 当前阶段
    "workflow_outcome": "continue"               # 继续执行
}
```

**什么时候读取上下文**：
- 进入 `analytics_entry` 节点时
- 调用 `conversation_repository.get_memory(conversation_id)` 获取历史上下文

**什么时候写入上下文**：
- 当前问句执行成功后，更新 `conversation_memory`

---

#### 第三步：规划节点（analytics_plan）

**职责**：调用 LLM 解析用户意图，生成结构化 AnalyticsIntent

**输入（state）**：
```python
{
    "query": "查询新疆区域2024年3月发电量",
    "conversation_memory": {...},                # 第二步读取的上下文
    "trace_id": "tr_xxx",
    "run_id": "run_xxx"
}
```

**传给 LLM 的数据结构（动态渲染到 prompt）**：

```python
# 渲染变量 1：用户问句
"query": "查询新疆区域2024年3月发电量"

# 渲染变量 2：会话上下文（用于指代消解）
"conversation_memory": {
    "last_metric": None,                        # 上轮没查指标，本次无法承接
    "last_time_range": None,                    # 上轮没查时间
    "last_org_scope": None
}

# 渲染变量 3：指标目录（告诉 LLM 可以查什么）
"metric_catalog_summary": """
## 可用指标目录
- 发电量（代码：generation）→ 电厂/电站发电量，单位：万千瓦时
- 上网电量（代码：online_generation）→ 上网电量
- 收入（代码：revenue）→ 发电收入
- 成本（代码：cost）→ 发电成本
- 利润（代码：profit）→ 利润
- 售电量（代码：sales）→ 售电量
"""

# 渲染变量 4：schema信息（告诉 LLM 可以按什么维度分组）
"schema_registry_summary": """
## 支持分组维度
- region：区域（新疆区域、甘肃区域...）
- station：电站（各电站名称）
- month：月份
- year：年份

## 支持对比目标
- yoy：同比（与去年同期对比）
- mom：环比（与上月对比）
"""
```

**LLM 返回的 JSON（每个字段中文注释）**：

```python
LLM_OUTPUT = {
    "task_type": "analytics_query",            # 任务类型：分析查询
    "complexity": "simple",                     # 复杂度：simple/simple_decomposed/complex
    "planning_mode": "direct",                 # 规划模式：direct(直接生成SQL)/decomposed(分解多SQL)
    "analysis_intent": "simple_query",         # 分析意图：simple_query/decline_attribution/...
    "metric": {                                # 指标信息
        "raw_text": "发电量",                  # 用户原文
        "metric_code": "generation",            # 指标代码（与目录匹配）
        "metric_name": "发电量",                # 指标名称
        "confidence": 0.95                     # 指标识别置信度
    },
    "time_range": {                           # 时间范围
        "raw_text": "2024年3月",               # 用户原文
        "type": "absolute",                    # 类型：absolute(绝对时间)/relative(相对时间)
        "value": "2024-03",                    # 标准化值
        "start": "2024-03-01",                # 开始日期
        "end": "2024-03-31",                  # 结束日期
        "confidence": 0.95                     # 时间识别置信度
    },
    "org_scope": {                            # 组织范围
        "raw_text": "新疆区域",                # 用户原文
        "type": "region",                      # 类型：region(区域)/station(电站)/company(全公司)
        "value": "XJ",                         # 标准化代码
        "confidence": 0.9
    },
    "group_by": None,                          # 分组维度：无分组
    "compare_target": "none",                  # 对比目标：none/yoy/mom
    "top_n": None,                             # 返回前N条：无限制
    "confidence": {                            # 整体置信度
        "overall": 0.92,                       # 整体置信度
        "metric": 0.95,                        # 指标置信度
        "time_range": 0.95,                    # 时间置信度
        "org_scope": 0.9                       # 组织范围置信度
    },
    "need_clarification": False,               # 是否需要澄清：否
    "missing_fields": [],                      # 缺失字段：无
    "ambiguous_fields": [],                    # 歧义字段：无
    "clarification_question": None             # 澄清问题：无
}
```

**输出（更新后的state）**：
```python
{
    "intent": LLM_OUTPUT,                      # LLM生成的结构化意图
    "plan": {                                  # 兼容旧版的Plan对象
        "intent": "business_analysis",
        "slots": {
            "metric": "发电量",
            "time_range": {"type": "absolute", "value": "2024-03", ...},
            "org_scope": {"type": "region", "value": "XJ", ...}
        },
        "is_executable": True,
        "planning_source": "llm_parser"
    },
    "planning_source": "llm_parser",          # 规划来源：llm_parser/rule_fallback
    "workflow_stage": "analytics_plan"
}
```

---

#### 第四步：槽位校验节点（analytics_validate_slots）

**职责**：校验 LLM 输出的 intent 是否满足执行条件

**校验规则表**：

| 规则 | 校验内容 | 不通过结果 |
|-----|---------|-----------|
| SQL字段禁止 | 检测是否包含 raw_sql/generated_sql | 直接拒绝 |
| 指标存在 | metric_code 必须在指标目录中 | invalid |
| 时间范围置信度 | >= 0.5 | clarify |
| 置信度阈值 | overall >= 0.85 可执行，< 0.65 澄清 | clarify |
| 核心槽位缺失 | metric/time_range 为空 | clarify |
| 歧义字段 | ambiguous_fields 非空 且 overall < 0.85 | clarify |

**输入**：
```python
{
    "intent": {...},                           # 第三步的LLM输出
    "plan": {...},
    "conversation": {...},
    "user_context": {...}
}
```

**输出（校验通过）**：
```python
{
    "intent_validation_result": {
        "valid": True,                         # 校验通过
        "need_clarification": False,           # 不需要澄清
        "missing_fields": [],                  # 无缺失字段
        "ambiguous_fields": [],                # 无歧义字段
        "clarification_question": None,        # 无澄清问题
        "errors": [],                          # 无错误
        "sanitized_intent": {...}              # 清洗后的intent
    },
    "task_run": {                             # 创建任务记录
        "run_id": "run_xxx",
        "trace_id": "tr_xxx",
        "conversation_id": "conv_xxx",
        "status": "executing",
        "sub_status": "planning_query"
    },
    "workflow_stage": "analytics_validate_slots",
    "next_step": "analytics_build_sql"        # 下一步：构建SQL
}
```

---

#### 第五步：SQL构建节点（analytics_build_sql）

**职责**：根据 validated intent 构建 SQL 语句

**输入**：
```python
{
    "intent": {
        "metric": {"metric_code": "generation", "metric_name": "发电量"},
        "time_range": {"type": "absolute", "value": "2024-03", "start": "2024-03-01", "end": "2024-03-31"},
        "org_scope": {"type": "region", "value": "XJ"},
        "compare_target": "none"
    },
    "user_context": {
        "department_code": "XJ"                # 用于数据权限过滤
    }
}
```

**构建流程**：
```
1. 获取指标定义
   metric_definition = metric_catalog.get("generation")
   → table_name = "bi_power_generation"
   → field_name = "generation_kwh"

2. 获取表结构
   table_definition = schema_registry.get_table("bi_power_generation")
   → columns: [region, station, generation_kwh, stat_date, ...]

3. 权限检查
   permission = check_metric_permission(user_id, "generation")
   → 通过

4. 构建SQL
   sql = f"""
   SELECT
       region,
       SUM(generation_kwh) as total_generation
   FROM bi_power_generation
   WHERE stat_date >= '2024-03-01'
     AND stat_date <= '2024-03-31'
     AND region = 'XJ'
   GROUP BY region
   """
```

**输出**：
```python
{
    "sql_bundle": {
        "generated_sql": """
        SELECT
            region,
            SUM(generation_kwh) as total_generation
        FROM bi_power_generation
        WHERE stat_date >= '2024-03-01'
          AND stat_date <= '2024-03-31'
          AND region = 'XJ'
        GROUP BY region
        """,
        "data_source": "bi_warehouse",        # 数据源标识
        "metric_scope": ["generation"],        # 涉及的指标
        "builder_metadata": {
            "metric_definition": {...},
            "table_definition": {...}
        }
    },
    "workflow_stage": "analytics_build_sql",
    "next_step": "analytics_guard_sql"
}
```

---

#### 第六步：SQL安全校验节点（analytics_guard_sql）

**职责**：9层安全校验，防止恶意SQL

**校验项**：

| 层 | 校验内容 | 不通过结果 |
|----|---------|-----------|
| 1 | 只读校验：必须是 SELECT | 阻断 |
| 2 | 白名单表：必须在 allowed_tables 中 | 阻断 |
| 3 | DDL禁止：不能有 DROP/ALTER/CREATE/TRUNCATE | 阻断 |
| 4 | DML禁止：不能有 INSERT/UPDATE/DELETE | 阻断 |
| 5 | 权限过滤：department_filter_column = user.department_code | 过滤 |
| 6 | LIMIT限制：最大 1000 行 | 自动添加 |
| 7 | 敏感字段：检查字段级权限 | 脱敏 |
| 8 | 超时限制：最大 30 秒 | 阻断 |

**输入**：
```python
{
    "sql_bundle": {
        "generated_sql": "SELECT region, SUM(generation_kwh)...",  # 生成的SQL
    },
    "table_definition": {...},
    "user_context": {
        "department_code": "XJ"
    }
}
```

**输出（校验通过）**：
```python
{
    "guard_result": {
        "is_safe": True,                       # 校验通过
        "checked_sql": """
        SELECT region, SUM(generation_kwh) as total_generation
        FROM bi_power_generation
        WHERE stat_date >= '2024-03-01'
          AND stat_date <= '2024-03-31'
          AND region = 'XJ'
        GROUP BY region
        LIMIT 1000                             -- 自动添加
        """,
        "blocked_reason": None,                # 无阻断原因
        "governance_detail": {
            "department_filter_applied": True,  # 部门过滤已应用
            "sensitive_fields_masked": [],      # 敏感字段：无
            "row_limit_applied": 1000           # 行数限制：1000
        }
    },
    "workflow_stage": "analytics_guard_sql",
    "next_step": "analytics_execute_sql"
}
```

**输出（校验失败）**：
```python
{
    "guard_result": {
        "is_safe": False,
        "blocked_reason": "检测到禁止的DDL语句: DROP"
    },
    "workflow_stage": "analytics_guard_sql",
    "next_step": "analytics_fail"
}
```

---

#### 第七步：SQL执行节点（analytics_execute_sql）

**职责**：执行只读SQL查询

**输入**：
```python
{
    "sql_bundle": {
        "generated_sql": "SELECT region, SUM(generation_kwh)...",
        "data_source": "bi_warehouse"
    },
    "guard_result": {
        "is_safe": True,
        "checked_sql": "SELECT ..."
    }
}
```

**执行流程**：
```
1. 调用 SQL Gateway
   result = sql_gateway.execute_readonly(
       data_source="bi_warehouse",
       sql="SELECT ...",
       timeout_ms=30000,
       row_limit=1000
   )

2. 记录审计日志
   audit_record = sql_audit_repository.create({
       "run_id": "run_xxx",
       "sql": "SELECT ...",
       "user_id": "u_xxx",
       "timestamp": "2026-05-02 14:30:00"
   })

3. 数据脱敏
   masked_result = data_masking_service.apply(
       rows=result.rows,
       columns=result.columns,
       user_permissions=user_context.permissions
   )
```

**输出**：
```python
{
    "execution_result": {
        "rows": [
            {"region": "新疆区域", "total_generation": 12345.67},
            {"region": "乌鲁木齐", "total_generation": 5000.00},
            {"region": "喀什", "total_generation": 3000.00}
        ],
        "columns": ["region", "total_generation"],
        "row_count": 3,
        "latency_ms": 234,
        "data_source": "bi_warehouse"
    },
    "audit_record": {
        "audit_id": "audit_xxx",
        "run_id": "run_xxx",
        "sql": "SELECT ...",
        "user_id": "u_xxx",
        "timestamp": "2026-05-02 14:30:00"
    },
    "masking_result": {
        "rows": [...],                         # 脱敏后的行数据
        "applied_masks": []                    # 应用了什么脱敏规则
    },
    "workflow_stage": "analytics_execute_sql",
    "next_step": "analytics_summarize"
}
```

---

#### 第八步：结果总结节点（analytics_summarize）

**职责**：根据 output_mode 生成 summary/chart/insight/report

**output_mode 说明**：

| 模式 | summary | chart_spec | insight_cards | report_blocks |
|-----|---------|------------|---------------|---------------|
| lite | ✅ | ❌ | ❌ | ❌ |
| standard | ✅ | ✅ | ✅ | ❌ |
| full | ✅ | ✅ | ✅ | ✅ |

**输入**：
```python
{
    "output_mode": "standard",
    "execution_result": {
        "rows": [
            {"region": "新疆区域", "total_generation": 12345.67},
            {"region": "乌鲁木齐", "total_generation": 5000.00},
            {"region": "喀什", "total_generation": 3000.00}
        ],
        "columns": ["region", "total_generation"]
    },
    "masking_result": {...},
    "sql_bundle": {...},
    "guard_result": {...},
    "plan": {
        "slots": {
            "metric": "发电量",
            "time_range": {...},
            "org_scope": {...}
        }
    }
}
```

**生成 summary（摘要文本）**：
```python
def _build_summary(slots, execution_result) -> str:
    metric = slots["metric"]                    # "发电量"
    time_label = "2024年3月"                   # 格式化时间标签
    scope_text = "新疆区域"                     # 组织范围

    # 从结果中提取汇总值
    total_value = sum(row["total_generation"] for row in rows)
    total_value_formatted = f"{total_value:.2f}万千瓦时"

    return f"{time_label}，{scope_text}的{metric}汇总值为 {total_value_formatted}。"
    # 输出："2024年3月，新疆区域的发电量汇总值为 20345.67 万千瓦时。"
```

**生成 chart_spec（图表配置）**：
```python
{
    "chart_type": "bar",                       # 图表类型：bar/line/pie
    "title": "2024年3月新疆区域发电量分布",      # 图表标题
    "x_field": "region",                        # X轴字段
    "y_field": "total_generation",              # Y轴字段
    "data_mapping": {
        "x_label": "区域",
        "y_label": "发电量（万千瓦时）"
    },
    "render_options": {
        "color_scheme": "default"
    }
}
```

**生成 insight_cards（洞察卡片）**：
```python
[
    {
        "title": "发电量区域排名洞察",          # 卡片标题
        "type": "ranking",                      # 卡片类型：trend/ranking/comparison/anomaly
        "summary": "当前排名第一的是新疆区域，数值为 12345.67 万千瓦时。",
        "evidence": {
            "dimension": "新疆区域",
            "value": 12345.67,
            "row_count": 3
        }
    }
]
```

**生成 report_blocks（报告块，仅full模式）**：
```python
[
    {
        "block_type": "overview",               # 报告块类型
        "title": "分析概览",
        "content": "2024年3月，新疆区域的发电量汇总值为 20345.67 万千瓦时。"
    },
    {
        "block_type": "key_findings",
        "title": "关键发现",
        "content": [...]                         # insight_cards 列表
    },
    {
        "block_type": "data_table",
        "title": "数据明细",
        "content": {
            "columns": ["区域", "发电量"],
            "rows": [[...], [...], [...]]
        }
    },
    {
        "block_type": "risk_note",
        "title": "风险提示",
        "content": "当前结果基于受控模板SQL生成，正式结论建议复核。"
    }
]
```

**输出**：
```python
{
    "analytics_result": {
        "run_id": "run_xxx",
        "trace_id": "tr_xxx",
        "summary": "2024年3月，新疆区域发电量为12345.67万千瓦时，环比上月增长5.2%。",
        "chart_spec": {...},                    # standard/full 模式
        "insight_cards": [...],                 # standard/full 模式
        "report_blocks": [...],                 # full 模式
        "governance_decision": {...},
        "timing_breakdown": {...}
    },
    "workflow_stage": "analytics_summarize",
    "next_step": "analytics_finish"
}
```

---

#### 第九步：结束节点（analytics_finish）

**职责**：持久化结果、更新会话上下文、返回最终响应

**持久化内容**：

```python
# 1. 持久化 task_run（任务记录）
task_run_repository.update(run_id="run_xxx", updates={
    "status": "succeeded",
    "output_snapshot": analytics_result.to_lightweight_snapshot()
})

# 2. 持久化 analytics_result（分析结果）
analytics_result_repository.save(
    run_id="run_xxx",
    result=analytics_result.to_heavy_result()
)

# 3. 持久化 slot_snapshot（槽位快照，用于澄清恢复）
slot_snapshot_repository.save(
    run_id="run_xxx",
    slots={
        "metric": "发电量",
        "metric_code": "generation",
        "time_range": {...},
        "org_scope": {...}
    }
)

# 4. 更新 conversation_memory（会话上下文，用于多轮承接）
conversation_repository.update_memory(
    conversation_id="conv_xxx",
    updates={
        "last_metric": "发电量",
        "last_time_range": {"label": "2024年3月", "type": "absolute"},
        "last_org_scope": {"label": "新疆区域", "type": "region"}
    }
)

# 5. 记录 assistant 消息
conversation_repository.add_message(
    conversation_id="conv_xxx",
    role="assistant",
    content=summary,
    related_run_id="run_xxx"
)
```

**最终返回**：
```python
{
    "final_response": {
        "data": {
            "run_id": "run_xxx",
            "status": "succeeded",
            "summary": "2024年3月，新疆区域发电量为12345.67万千瓦时。",
            "chart_spec": {...},
            "insight_cards": [...],
            "row_count": 3,
            "trace_id": "tr_xxx"
        },
        "meta": {
            "status": "succeeded",
            "conversation_id": "conv_xxx",
            "run_id": "run_xxx",
            "latency_ms": 1234,
            "timing_breakdown": {...}
        }
    },
    "workflow_stage": "analytics_finish",
    "workflow_outcome": "finish"
}
```

---

### 18.3 缺指标澄清：帮我看一下新疆区域上个月的情况

**问句**：`"帮我看一下新疆区域上个月的情况"`

**与简单查询的区别**：
- 第三步 LLM 解析时，metric 缺失
- 第四步 Validator 检测到缺失，触发澄清
- 第六步进入澄清节点，返回澄清问题
- 用户补充后，从澄清恢复

---

#### 触发澄清的判断

**LLM 输出**：
```python
{
    "task_type": "analytics_query",
    "complexity": "simple",
    "planning_mode": "clarification",          # 规划模式变为clarification
    "metric": null,                             # 指标缺失
    "time_range": {
        "raw_text": "上个月",
        "type": "relative",
        "value": "last_month",
        "confidence": 0.9
    },
    "org_scope": {
        "raw_text": "新疆区域",
        "type": "region",
        "value": "XJ",
        "confidence": 0.9
    },
    "confidence": {
        "overall": 0.5,                        # 整体置信度低
        "metric": 0.1                          # 指标置信度极低
    },
    "need_clarification": True,               # 需要澄清
    "missing_fields": ["metric"],              # 缺失指标
    "clarification_question": "你想查看哪个经营指标？例如：发电量、收入、成本、利润。"  # 澄清问题
}
```

**Validator 校验逻辑**：
```python
def validate(intent):
    # 1. 核心槽位缺失检测
    if intent.metric is None:
        missing_fields.append("metric")

    # 2. 置信度阈值检测
    if intent.confidence.overall < 0.65:        # < 0.65 必须澄清
        need_clarification = True

    # 3. 生成澄清问题
    if need_clarification:
        clarification_question = intent.clarification_question or generate_question(missing_fields)

    return IntentValidationResult(
        valid=True,                             # intent有效，但需要澄清
        need_clarification=True,
        missing_fields=["metric"],
        clarification_question="你想查看哪个经营指标？..."
    )
```

---

#### 澄清响应结构

**输出（澄清节点）**：
```python
{
    "final_response": {
        "data": {
            "need_clarification": True,         # 标记需要澄清
            "question": "你想查看哪个经营指标？例如：发电量、收入、成本、利润。",
            "target_slots": ["metric"],         # 需要补充的槽位
            "suggested_options": [
                {"value": "发电量", "description": "电厂/电站发电量"},
                {"value": "收入", "description": "发电收入"},
                {"value": "成本", "description": "发电成本"},
                {"value": "利润", "description": "利润"}
            ],
            "conversation_id": "conv_xxx",
            "run_id": "run_xxx"
        },
        "meta": {
            "status": "awaiting_user_clarification",  # 等待用户补充
            "conversation_id": "conv_xxx",
            "run_id": "run_xxx"
        }
    },
    "workflow_stage": "analytics_clarify",
    "workflow_outcome": "clarify"
}
```

---

#### 持久化澄清状态

```python
# 1. 持久化 slot_snapshot（保存已识别的槽位）
slot_snapshot_repository.save(
    run_id="run_xxx",
    slots={
        "time_range": {...},                   # 已识别：上个月
        "org_scope": {...},                    # 已识别：新疆区域
        "metric": None                          # 待补充：指标
    },
    clarification_status="pending"
)

# 2. 持久化 clarification_event（澄清事件）
clarification_event_repository.create(
    event_id="clarify_xxx",
    run_id="run_xxx",
    conversation_id="conv_xxx",
    question="你想查看哪个经营指标？...",
    target_slots=["metric"],
    suggested_options=[...],
    status="pending_user_response",
    created_at="2026-05-02 14:30:00"
)
```

---

#### 用户补充后恢复

**用户补充问句**：`"看发电量"`

**前端调接口**：
```python
POST /api/v1/analytics/clarification/respond
{
    "clarification_id": "clarify_xxx",          # 澄清事件ID
    "conversation_id": "conv_xxx",
    "user_context": {...},
    "slot_updates": {
        "metric": "发电量"                       # 用户补充的指标
    }
}
```

**恢复流程**：
```
1. 读取 slot_snapshot（已有槽位：上个月、新疆区域）
2. 合并用户补充（metric=发电量）
3. 重新构造 AnalyticsIntent
4. 重新进入 Validator
5. 校验通过 → 继续执行 SQL 构建
```

**恢复后的 intent**：
```python
{
    "metric": {
        "raw_text": "发电量",
        "metric_code": "generation",
        "confidence": 0.95
    },
    "time_range": {
        "raw_text": "上个月",
        "type": "relative",
        "value": "last_month",
        "confidence": 0.9
    },
    "org_scope": {...},                         # 新疆区域
    "confidence": {"overall": 0.9},
    "need_clarification": False                # 不再需要澄清
}
```

---

### 18.4 指标歧义澄清：新疆最近电量咋样

**问句**：`"新疆最近电量咋样"`

**与缺指标的区别**：
- LLM 识别到"电量"有多种可能
- 需要用户明确选择具体指标

---

#### 歧义检测

**LLM 输出**：
```python
{
    "metric": {
        "raw_text": "电量",                    # 用户原文
        "metric_code": None,                   # 无法确定具体指标
        "confidence": 0.4,                     # 置信度低
        "candidates": [                         # 候选指标
            {"metric_code": "generation", "metric_name": "发电量", "confidence": 0.4},
            {"metric_code": "online_generation", "metric_name": "上网电量", "confidence": 0.3},
            {"metric_code": "sales", "metric_name": "售电量", "confidence": 0.3}
        ]
    },
    "ambiguous_fields": ["metric"],            # 歧义字段
    "confidence": {"overall": 0.55},          # 整体置信度 < 0.85
    "need_clarification": True,
    "clarification_question": "你说的「电量」想看哪个口径？例如：发电量、上网电量、售电量。"
}
```

**澄清响应**：
```python
{
    "data": {
        "need_clarification": True,
        "question": "你说的「电量」想看哪个口径？例如：发电量、上网电量、售电量。",
        "target_slots": ["metric"],
        "suggested_options": [
            {"value": "发电量", "description": "电厂/电站的发电量"},
            {"value": "上网电量", "description": "实际上网销售的电量"},
            {"value": "售电量", "description": "售电收入对应的电量"}
        ],
        "ambiguous_hint": {                     # 歧义提示
            "field": "metric",
            "raw_text": "电量",
            "candidates": [
                {"value": "发电量", "confidence": 0.4},
                {"value": "上网电量", "confidence": 0.3},
                {"value": "售电量", "confidence": 0.3}
            ]
        }
    }
}
```

---

### 18.5 复杂分析：分析近三个月发电量下降原因，和去年对比

**问句**：`"分析近三个月发电量下降原因，和去年对比"`

**特点**：
- 多个时间周期（近三个月 + 去年同期）
- 需要并行执行多个子查询
- 生成同比分析

---

#### LLM 输出（decomposed 模式）

```python
{
    "task_type": "analytics_query",
    "complexity": "complex",                    # 复杂查询
    "planning_mode": "decomposed",              # 分解执行
    "analysis_intent": "decline_attribution",   # 下降归因分析
    "metric": {...},
    "time_range": {
        "raw_text": "近三个月",
        "type": "relative",
        "value": "last_3_months",
        "confidence": 0.9
    },
    "compare_target": "yoy",                   # 同比
    "group_by": "station",                     # 按电站分组
    "top_n": 10,                               # 返回前10个电站
    "required_queries": [                      # 必需的子查询
        {
            "query_name": "current",
            "purpose": "查询当前周期各电站发电量",
            "metric_code": "generation",
            "period_role": "current",          # 当前周期
            "group_by": "station"
        },
        {
            "query_name": "yoy_baseline",
            "purpose": "查询去年同期各电站发电量",
            "metric_code": "generation",
            "period_role": "yoy_baseline",     # 同比基准
            "group_by": "station"
        }
    ],
    "confidence": {"overall": 0.92},
    "need_clarification": False
}
```

---

#### 并行查询执行

**SQL Builder 生成多个 SQL**：
```python
sql_bundle = {
    "generated_sql": """
    WITH current AS (
        SELECT station, SUM(generation_kwh) as current_value
        FROM bi_power_generation
        WHERE stat_date >= '2026-02-01' AND stat_date <= '2026-04-30'
          AND region = 'XJ'
        GROUP BY station
    ),
    yoy AS (
        SELECT station, SUM(generation_kwh) as yoy_value
        FROM bi_power_generation
        WHERE stat_date >= '2025-02-01' AND stat_date <= '2025-04-30'
          AND region = 'XJ'
        GROUP BY station
    )
    SELECT
        c.station,
        c.current_value,
        COALESCE(y.yoy_value, 0) as yoy_value,
        c.current_value - COALESCE(y.yoy_value, 0) as decline
    FROM current c
    LEFT JOIN yoy y ON c.station = y.station
    ORDER BY decline DESC
    LIMIT 10
    """,
    "execution_strategy": "PARALLEL",          # 执行策略：并行
    "required_queries": [...]
}
```

**查询结果**：
```python
execution_result = {
    "rows": [
        {"station": "电站A", "current_value": 1000, "yoy_value": 1200, "decline": -200},
        {"station": "电站B", "current_value": 800, "yoy_value": 900, "decline": -100},
        {"station": "电站C", "current_value": 500, "yoy_value": 500, "decline": 0}
    ]
}
```

---

#### 洞察卡片生成

```python
insight_cards = [
    {
        "title": "发电量同比对比",
        "type": "comparison",
        "summary": "近三个月发电量同比下降，拖累最大的是电站A（下降200万千瓦时）",
        "evidence": {
            "current_value": 1000,
            "yoy_value": 1200,
            "delta": -200,
            "compare_target": "yoy"
        }
    },
    {
        "title": "发电量区域排名洞察",
        "type": "ranking",
        "summary": "当前排名第一的是电站A，数值为 1000 万千瓦时。",
        "evidence": {
            "dimension": "电站A",
            "value": 1000,
            "row_count": 10
        }
    },
    {
        "title": "异常值提醒",
        "type": "anomaly",
        "summary": "电站C发电量与去年持平，未出现下降。",
        "evidence": {
            "anomaly_count": 0
        }
    }
]
```

---

### 18.6 跨数据源：对比聚乙烯销量和发电量

**问句**：`"对比聚乙烯销量和发电量"`

**特点**：
- 两个不同数据源（化工生产系统 vs 电力生产系统）
- 需要并行查询
- JOIN 结果展示

---

#### LLM 输出

```python
{
    "complexity": "complex",
    "planning_mode": "decomposed",
    "analysis_intent": "cross_source_comparison",
    "metrics": [                               # 多个指标
        {"metric_code": "generation", "metric_name": "发电量", "data_source": "bi_warehouse"},
        {"metric_code": "polyethylene_sales", "metric_name": "聚乙烯销量", "data_source": "erp_system"}
    ],
    "execution_strategy": "PARALLEL",          # 并行执行
    "required_queries": [
        {
            "query_name": "generation",
            "purpose": "查询发电量",
            "metric_code": "generation",
            "data_source": "bi_warehouse"
        },
        {
            "query_name": "polyethylene_sales",
            "purpose": "查询聚乙烯销量",
            "metric_code": "polyethylene_sales",
            "data_source": "erp_system"
        }
    ]
}
```

---

#### 并行执行

```
┌─────────────────────────────────────────────────────────────────┐
│                    并行查询执行                                   │
│                                                                 │
│  ┌─────────────────┐           ┌─────────────────┐            │
│  │ Query 1         │           │ Query 2         │            │
│  │ 数据源: bi_warehouse │      │ 数据源: erp_system │           │
│  │ SQL: SELECT...   │           │ SQL: SELECT...   │            │
│  └────────┬────────┘           └────────┬────────┘            │
│           │                             │                      │
│           ▼                             ▼                      │
│  ┌─────────────────┐           ┌─────────────────┐            │
│  │ Result 1        │           │ Result 2        │            │
│  │ rows: [...]     │           │ rows: [...]     │            │
│  └────────┬────────┘           └────────┬────────┘            │
│           │                             │                      │
│           └──────────────┬──────────────┘                      │
│                          ▼                                      │
│                 ┌─────────────────┐                            │
│                 │ 组合结果         │                            │
│                 │ 对比表格         │                            │
│                 └─────────────────┘                            │
└─────────────────────────────────────────────────────────────────┘
```

---

## 十九、公共组件说明

### 19.1 LLM 意图解析器（LLMAnalyticsIntentParser）

**文件位置**：`core/analytics/intent/parser.py`

**职责**：
- 接收用户 query 和会话上下文
- 动态渲染 prompt（包含指标目录、schema信息）
- 调用 LLM 生成结构化 AnalyticsIntent
- 内置 fallback 机制

**Prompt 模板位置**：
- System Prompt：`core/prompts/templates/analytics/intent_parser_system.j2`
- User Prompt：`core/prompts/templates/analytics/intent_parser_user.j2`

**输入数据结构（动态渲染变量）**：

```python
{
    "query": str,                              # 用户问句
    "conversation_memory": {                   # 会话上下文
        "last_metric": str | None,             # 上轮指标
        "last_time_range": dict | None,        # 上轮时间
        "short_term_memory": {
            "last_group_by": str | None,
            "last_compare_target": str | None
        }
    },
    "metric_catalog_summary": str,             # 指标目录文本
    "schema_registry_summary": str              # Schema信息文本
}
```

**输出数据结构**：

```python
{
    "intent": AnalyticsIntent,                 # 结构化意图
    "planning_source": str,                    # llm_parser / rule_fallback
    "latency_ms": float,                      # LLM调用耗时
    "success": bool                            # 是否成功
}
```

---

### 19.2 意图校验器（AnalyticsIntentValidator）

**文件位置**：`core/analytics/intent/validator.py`

**职责**：
- 硬边界：拒绝包含 SQL 字段的 intent
- 校验指标、时间范围、组织范围的置信度
- 判断是否需要澄清

**校验规则表**：

| 规则 | 校验内容 | 不通过结果 |
|-----|---------|-----------|
| SQL 字段禁止 | 检测 raw_sql、generated_sql、sql 字段 | invalid |
| 指标有效性 | metric_code 必须在指标目录 | invalid |
| 时间置信度 | >= 0.5 | clarify |
| 整体置信度高 | >= 0.85 | 可执行 |
| 整体置信度低 | < 0.65 | 必须澄清 |
| 核心槽位 | metric/time_range 为空 | clarify |
| 歧义字段 | ambiguous_fields 非空 且 overall < 0.85 | clarify |

**输入**：AnalyticsIntent

**输出**：IntentValidationResult

```python
{
    "valid": bool,                             # 是否有效
    "need_clarification": bool,                # 是否需要澄清
    "missing_fields": list[str],               # 缺失字段
    "ambiguous_fields": list[str],             # 歧义字段
    "clarification_question": str | None,       # 澄清问题
    "errors": list[str],                       # 错误列表
    "sanitized_intent": AnalyticsIntent | None  # 清洗后的intent
}
```

---

### 19.3 SQL 构建器（AnalyticsIntentSQLBuilder）

**文件位置**：`core/agent/control_plane/intent_sql_builder.py`

**职责**：
- 根据 validated intent 生成 SQL
- 支持 simple（direct）和 complex（decomposed）两种模式
- 处理时间范围转换
- 处理组织范围过滤

**输入**：AnalyticsIntent

**输出**：SQLBundle

```python
{
    "generated_sql": str,                       # 生成的SQL语句
    "data_source": str,                         # 数据源标识
    "metric_scope": list[str],                  # 涉及的指标
    "builder_metadata": {                       # 构建元数据
        "metric_definition": MetricDefinition,
        "table_definition": TableDefinition
    }
}
```

---

### 19.4 SQL 安全校验器（SQLGuard）

**文件位置**：`core/agent/control_plane/sql_guard.py`

**职责**：9层安全防护

**校验层**：

| 层 | 校验内容 | 处理方式 |
|----|---------|---------|
| 1 | 只读校验 | 非SELECT阻断 |
| 2 | 白名单表 | 非白名单阻断 |
| 3 | DDL禁止 | DROP/ALTER等阻断 |
| 4 | DML禁止 | INSERT/UPDATE等阻断 |
| 5 | 权限过滤 | 自动添加部门过滤 |
| 6 | LIMIT限制 | 自动添加LIMIT 1000 |
| 7 | 敏感字段 | 脱敏处理 |
| 8 | 超时限制 | 超过30s阻断 |

**输入**：生成的 SQL

**输出**：SQLGuardResult

```python
{
    "is_safe": bool,                           # 是否安全
    "checked_sql": str,                        # 校验后的SQL
    "blocked_reason": str | None,               # 阻断原因
    "governance_detail": {
        "department_filter_applied": bool,
        "sensitive_fields_masked": list[str],
        "row_limit_applied": int
    }
}
```

---

### 19.5 SQL 执行网关（SQLGateway）

**文件位置**：`core/tools/sql/sql_gateway.py`

**职责**：
- 执行只读SQL查询
- 管理连接池
- 处理超时和错误

**输入**：SQLReadQueryRequest

```python
{
    "data_source": str,                        # 数据源标识
    "sql": str,                                # SQL语句
    "timeout_ms": int,                         # 超时毫秒
    "row_limit": int                           # 行数限制
}
```

**输出**：SQLReadQueryResult

```python
{
    "rows": list[dict],                        # 结果行
    "columns": list[str],                      # 列名
    "row_count": int,                          # 行数
    "latency_ms": float,                       # 查询耗时
    "data_source": str                          # 数据源
}
```

---

### 19.6 洞察构建器（InsightBuilder）

**文件位置**：`core/analytics/insight_builder.py`

**职责**：根据查询结果生成洞察卡片

**洞察类型**：

| 类型 | 触发条件 | 描述 |
|-----|---------|------|
| trend | group_by=month | 时间序列趋势 |
| ranking | group_by=region/station | 维度排名 |
| comparison | compare_target=yoy/mom | 对比分析 |
| anomaly | rows为空或含<=0值 | 异常提醒 |

**输入**：
```python
{
    "slots": dict,                             # 槽位信息
    "rows": list[dict],                        # 结果行
    "row_count": int                           # 行数
}
```

**输出**：list[InsightCard]

```python
[
    {
        "title": str,                          # 卡片标题
        "type": str,                           # 卡片类型
        "summary": str,                        # 洞察摘要
        "evidence": dict                       # 支撑证据
    }
]
```

---

### 19.7 报告格式化器（ReportFormatter）

**文件位置**：`core/analytics/report_formatter.py`

**职责**：将分析结果组织成标准报告块

**报告块类型**：

| 类型 | 始终有 | 描述 |
|-----|-------|------|
| overview | ✅ | 分析概览 |
| key_findings | ❌ | 关键发现（仅当有洞察时） |
| trend | ❌ | 趋势分析（仅当有trend洞察时） |
| ranking | ❌ | 排名分析（仅当有ranking洞察时） |
| data_table | ❌ | 数据表（每张表一个块） |
| chart | ❌ | 图表（仅当有chart_spec时） |
| risk_note | ✅ | 风险提示 |
| recommendation | ✅ | 后续建议 |

**输入**：
```python
{
    "summary": str,                            # 摘要文本
    "insight_cards": list[dict],               # 洞察卡片
    "tables": list[dict],                      # 结果表
    "chart_spec": dict | None,                  # 图表配置
    "governance_note": dict | None             # 治理说明
}
```

**输出**：list[ReportBlock]

```python
[
    {
        "block_type": str,                     # 块类型
        "title": str,                          # 块标题
        "content": str | list | dict           # 块内容
    }
]
```

---

### 19.8 SQL执行临时失败重试

#### 重试场景

用户问句：`"查询新疆区域2024年3月发电量"`

执行流程：
1. SQL 执行节点 `analytics_execute_sql` 调用 SQL Gateway
2. 第一次请求超时（SQL Gateway 临时错误）
3. 判断这是可重试错误（TimeoutError）
4. 触发重试策略
5. 第二次请求成功

重试响应：
```python
{
    "success": True,
    "data": {
        "summary": "2024年3月，新疆区域发电量为 12345.67 万千瓦时。",
        "retry_summary": {
            "retry_count": 1,
            "retry_history": [
                {
                    "node_name": "analytics_execute_sql",
                    "attempt": 1,
                    "error_type": "TimeoutError",
                    "error_message": "SQL Gateway 请求超时"
                }
            ]
        }
    }
}
```

#### 可重试错误

| 错误类型 | 是否可重试 | 说明 |
|---------|-----------|------|
| TimeoutError | ✅ | 网关超时 |
| ConnectionError | ✅ | 连接错误 |
| SQLGatewayExecutionError | ✅ | 执行错误 |
| SQLGuardBlocked | ❌ | 安全阻断，不可重试 |
| PermissionDenied | ❌ | 权限不足，不可重试 |

#### 重试字段说明

| 字段 | 示例值 | 中文含义 |
|-----|-------|---------|
| retry_count | 1 | 重试次数 |
| node_name | analytics_execute_sql | 发生重试的节点 |
| attempt | 1 | 第几次尝试 |
| error_type | TimeoutError | 错误类型 |
| error_message | SQL Gateway 请求超时 | 错误信息 |

---

### 19.9 图表/洞察/报告块降级

#### 降级场景

用户问句：`"生成新疆区域2024年3月发电量的完整分析"`

执行流程：
1. SQL 执行成功
2. Summary 生成成功
3. Chart Spec 生成失败（某些图表类型不支持）
4. Insight Cards 生成成功
5. Report Blocks 生成成功

降级后的响应：
```python
{
    "success": True,
    "data": {
        "summary": "2024年3月，新疆区域发电量为 12345.67 万千瓦时。",
        "degraded": True,  # 发生了降级
        "degraded_features": ["chart_spec"],  # 降级的功能
        "chart_spec": None,  # 图表降级为 None
        "insight_cards": [...],  # 洞察正常
        "report_blocks": [...],  # 报告正常
    }
}
```

#### 降级字段说明

| 字段 | 示例值 | 中文含义 |
|-----|-------|---------|
| degraded | true | 是否发生降级 |
| degraded_features | ["chart_spec"] | 发生降级的功能列表 |

#### 可降级功能

| 功能 | 降级结果 |
|-----|---------|
| chart_spec | null |
| insight_cards | [] |
| report_blocks | [] |

#### 不可降级功能

| 功能 | 说明 |
|-----|------|
| SQL 执行失败 | 不能降级为成功 |
| 摘要生成失败 | 不能降级为返回空摘要 |

---

### 19.10 澄清后恢复执行

#### 恢复场景

**首次问句**：`"帮我看一下新疆区域上个月的情况"`

首次流程：
1. LLM 识别出 `org_scope=新疆区域` 和 `time_range=上个月`
2. 缺少 `metric` 字段
3. 进入澄清节点
4. 返回澄清响应

首次响应：
```python
{
    "success": True,
    "meta": {
        "status": "awaiting_user_clarification"
    },
    "data": {
        "clarification": {
            "clarification_id": "clar_xxx",
            "question": "你想查看哪个经营指标？例如：发电量、收入、成本、利润。",
            "target_slots": ["metric"]
        }
    }
}
```

**用户补充**：`"看发电量"`

恢复流程：
1. 调用 `resume_from_clarification(clarification_id, "看发电量")`
2. 读取 clarification_event 和 slot_snapshot
3. 合并补充的槽位
4. 复用原 run_id 和 trace_id
5. 重新进入 StateGraph

恢复状态变化：

| 阶段 | task_run.status | 说明 |
|-----|-----------------|------|
| 首次缺槽位 | awaiting_user_clarification | 等待用户补充 |
| 用户补充后 | executing | 重新进入执行 |
| 查询完成 | succeeded | 执行成功 |

#### 恢复字段说明

| 字段 | 示例值 | 中文含义 |
|-----|-------|---------|
| clarification_id | clar_xxx | 澄清事件ID |
| resume_from_clarification | true | 是否从澄清恢复 |
| recovered_slots | {metric: "发电量"} | 恢复的槽位 |

---

### 19.11 导出报告

#### 导出场景

用户操作：基于 run_id 发起导出请求

**接口**：`POST /api/v1/analytics/export`

**请求参数**：
```python
{
    "run_id": "run_xxx",      # 分析任务ID
    "export_type": "pdf",      # 导出格式：json/markdown/docx/pdf
    "export_template": None    # 模板名称，可选
}
```

**导出流程**：
```
1. 读取 task_run 的 output_snapshot（轻量快照）
2. 从 analytics_result_repository 读取 heavy_result（完整结果）
3. 调用 ReportGateway 生成文件
4. 返回 export_task
```

**响应**：
```python
{
    "success": True,
    "data": {
        "export_id": "export_xxx",
        "run_id": "run_xxx",
        "format": "pdf",
        "status": "succeeded",
        "file_url": "/exports/analytics_20240502.pdf",
        "created_at": "2026-05-02T14:30:00Z"
    }
}
```

#### 导出字段说明

| 字段 | 示例值 | 中文含义 |
|-----|-------|---------|
| export_id | export_xxx | 导出任务ID |
| run_id | run_xxx | 对应的分析任务ID |
| format | pdf | 导出格式 |
| status | succeeded | 导出状态 |

---

### 19.12 高风险导出人工审核

#### 审核场景

用户操作：导出包含敏感指标的完整报告

**审核触发条件**：
- 导出包含敏感指标（如利润，成本）
- 导出范围超过用户权限（如全公司数据）
- 导出文件需要外发

#### 审核流程

```
1. 创建导出任务
2. Review Policy 判断需要审核
3. export_task.status = awaiting_human_review
4. 创建 review_task
5. 审核员审批
6. 通过后恢复导出 / 拒绝后终止
```

#### 审核字段说明

| 字段 | 示例值 | 中文含义 |
|-----|-------|---------|
| review_id | review_xxx | 审核任务ID |
| subject_type | analytics_export | 审核对象类型 |
| subject_id | export_xxx | 被审核的导出ID |
| review_status | pending | 审核状态 |
| review_reason | 导出包含敏感指标 | 审核原因 |

#### 审核状态

| 状态值 | 中文含义 |
|-------|---------|
| pending | 等待审核 |
| approved | 审核通过 |
| rejected | 审核拒绝 |
| expired | 审核过期 |
| cancelled | 审核取消 |

#### 审核通过示例

```python
{
    "review_id": "review_xxx",
    "subject_type": "analytics_export",
    "subject_id": "export_xxx",
    "review_status": "approved",
    "reviewer_name": "经营管理部审核员",
    "review_comment": "允许导出，仅限内部使用",
    "reviewed_at": "2026-05-02T15:00:00Z"
}
```

#### 审核拒绝示例

```python
{
    "review_id": "review_xxx",
    "subject_type": "analytics_export",
    "subject_id": "export_xxx",
    "review_status": "rejected",
    "reviewer_name": "经营管理部审核员",
    "review_comment": "导出范围过大，请缩小区域或时间范围",
    "reviewed_at": "2026-05-02T15:00:00Z"
}
```

---

## 二十、版本说明

| 版本 | 日期 | 变更内容 |
|-----|------|---------|
| v1 | 2026-04 | 初始实现，规则 Planner + Slot Fallback + ReAct 分流 |
| v2 | 2026-05-02 | 链路收敛：统一 LLMAnalyticsIntentParser + AnalyticsIntentValidator |
| v2.1 | 2026-05-02 | 新增 AnalyticsIntentSQLBuilder、AnalyticsResult、analytics_result_repository |
| v3 | 2026-05-02 | 新增 RepairController、RequiredQueriesExecutor、CheckpointManager、完整测试覆盖 |
| v4 | 2026-05-02 | 新增典型问句完整链路（新手友好版），覆盖简单查询、澄清、复杂分析、跨数据源 |
| v5 | 2026-05-02 | 补充降级场景、澄清恢复场景、导出报告场景、高风险审核场景、SQL执行重试场景 |

---

**文档结束**

