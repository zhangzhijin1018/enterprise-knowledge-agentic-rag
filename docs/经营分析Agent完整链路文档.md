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
| v3 | 2026-05-02 | 新增 RepairController、RequiredQueriesExecutor、CheckpointManager、完整测试覆盖 |

---

**文档结束**

