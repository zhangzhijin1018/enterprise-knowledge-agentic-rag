# API_DESIGN.md

# 新疆能源集团知识与生产经营智能 Agent 平台
## API 接口设计文档

---

## 1. 文档定位

本文档用于把 `ARCHITECTURE.md`、`AGENT_WORKFLOW.md`、`DB_DESIGN.md` 进一步落到前后端与服务之间的接口契约层。

本文档重点回答：

- 前端如何调用后端；
- 后端如何表达同步、异步、审核中、澄清中等状态；
- 多轮对话如何通过 `conversation_id` 承接；
- 工作流如何通过 `run_id`、`trace_id` 串联；
- 合同审查、经营分析、智能问答、审核、Trace 的接口如何统一。

---

## 2. API 设计原则

### 2.1 统一版本前缀

所有正式业务接口统一使用：

```http
/api/v1
```

### 2.2 统一请求标识与链路标识

建议统一引入以下标识：

- `request_id`：单次 HTTP 请求标识
- `trace_id`：一次业务链路跟踪标识
- `run_id`：一次任务运行标识
- `conversation_id`：一次多轮会话标识

### 2.3 统一响应结构

无论同步还是异步，响应结构都尽量保持统一，避免前端写很多特殊判断。

### 2.4 统一错误模型

所有错误都统一返回：

- `error_code`
- `message`
- `trace_id`
- `detail`

### 2.5 工作流状态前置

接口响应不仅返回“结果”，还要返回“当前状态”，因为系统支持：

- 多轮对话
- 澄清追问
- Human Review
- 异步长任务
- 恢复执行

---

## 3. 统一响应模型

## 3.1 成功响应基础结构

```json
{
  "success": true,
  "trace_id": "tr_001",
  "request_id": "req_001",
  "data": {},
  "meta": {}
}
```

## 3.2 失败响应基础结构

```json
{
  "success": false,
  "trace_id": "tr_001",
  "request_id": "req_001",
  "error": {
    "error_code": "PERMISSION_DENIED",
    "message": "当前用户无权访问该资源",
    "detail": {}
  }
}
```

## 3.3 通用 meta 结构建议

```json
{
  "run_id": "run_xxx",
  "conversation_id": "conv_xxx",
  "status": "executing",
  "sub_status": "retrieving_context",
  "is_async": false,
  "need_human_review": false,
  "need_clarification": false
}
```

---

## 4. 统一状态字典

## 4.1 任务状态 status

建议前后端统一使用：

```text
created
context_built
authorized
risk_checked
routed
executing
waiting_review
waiting_remote
waiting_async_result
awaiting_user_clarification
resuming_previous_task
succeeded
failed
cancelled
expired
```

## 4.2 子状态 sub_status

示例：

```text
retrieving_context
reranking
drafting_answer
parsing_contract
running_sql
building_report
calling_mcp
calling_a2a
awaiting_reviewer
awaiting_slot_fill
retrying_after_timeout
```

## 4.3 会话状态 current_status

```text
active
completed
cancelled
archived
```

## 4.4 澄清状态 clarification_status

```text
pending
answered
expired
cancelled
```

## 4.5 审核状态 review_status

```text
not_required
pending
approved
rejected
revised
expired
cancelled
```

---

## 5. 统一业务对象标识规范

建议接口层统一使用对外稳定 ID，不直接暴露数据库自增主键。

推荐：

- `conversation_id`：`conv_xxx`
- `run_id`：`run_xxx`
- `review_id`：`rev_xxx`
- `document_id`：`doc_xxx`
- `knowledge_base_id`：`kb_xxx`
- `report_id`：`rpt_xxx`

---

## 6. 统一鉴权约定

### 6.1 认证方式

建议第一阶段统一：

```http
Authorization: Bearer <token>
```

### 6.2 用户上下文

服务端从 token 中解析：

- user_id
- username
- role
- department
- permissions

### 6.3 接口权限分类

#### 普通用户接口
- chat
- conversation
- document upload
- contract review submit
- analytics query submit

#### 审核人接口
- review list
- review detail
- review decision

#### 管理员接口
- knowledge base 管理
- trace 查询
- evaluation 查询
- capability / agent registry 管理（后续）

---

## 7. 智能问答接口

## 7.1 提交问答请求

```http
POST /api/v1/chat
```

### 请求体

```json
{
  "query": "集团新能源业务有哪些核心制度？",
  "conversation_id": null,
  "history_messages": [],
  "business_hint": null,
  "knowledge_base_ids": [],
  "stream": false
}
```

### 字段说明

- `query`：用户问题
- `conversation_id`：多轮对话时传已有会话 ID；首轮可为空
- `history_messages`：可选，前端传最近历史消息；服务端仍以数据库会话为准
- `business_hint`：业务提示，例如 `policy`、`safety`
- `knowledge_base_ids`：限制候选知识库范围
- `stream`：是否流式返回

### 成功响应：直接返回答案

```json
{
  "success": true,
  "trace_id": "tr_001",
  "request_id": "req_001",
  "data": {
    "answer": "集团新能源业务相关制度主要包括……",
    "citations": [
      {
        "document_id": "doc_001",
        "document_title": "新能源业务管理办法",
        "chunk_id": "chunk_001",
        "page_no": 3,
        "snippet": "……"
      }
    ]
  },
  "meta": {
    "conversation_id": "conv_001",
    "run_id": "run_001",
    "status": "succeeded",
    "sub_status": "drafting_answer",
    "need_human_review": false,
    "need_clarification": false,
    "is_async": false
  }
}
```

### 成功响应：需要澄清

```json
{
  "success": true,
  "trace_id": "tr_002",
  "request_id": "req_002",
  "data": {
    "clarification": {
      "clarification_id": "clr_001",
      "question": "你想看哪个指标？发电量、收入还是成本？",
      "target_slots": ["metric"]
    }
  },
  "meta": {
    "conversation_id": "conv_001",
    "run_id": "run_002",
    "status": "awaiting_user_clarification",
    "sub_status": "awaiting_slot_fill",
    "need_clarification": true,
    "is_async": false
  }
}
```

### 成功响应：进入审核

```json
{
  "success": true,
  "trace_id": "tr_003",
  "request_id": "req_003",
  "data": {
    "message": "该问题已进入人工复核"
  },
  "meta": {
    "conversation_id": "conv_001",
    "run_id": "run_003",
    "review_id": "rev_001",
    "status": "waiting_review",
    "need_human_review": true,
    "is_async": true
  }
}
```

---

## 8. 多轮对话接口

## 8.1 查询会话列表

```http
GET /api/v1/conversations
```

### 查询参数

```text
page=1
page_size=20
status=active
```

### 响应

```json
{
  "success": true,
  "trace_id": "tr_010",
  "request_id": "req_010",
  "data": {
    "items": [
      {
        "conversation_id": "conv_001",
        "title": "新能源制度问答",
        "current_route": "chat",
        "current_status": "active",
        "last_run_id": "run_100",
        "updated_at": "2026-04-27T10:00:00+08:00"
      }
    ],
    "total": 1
  },
  "meta": {}
}
```

## 8.2 查询单会话消息

```http
GET /api/v1/conversations/{conversation_id}/messages
```

### 响应

```json
{
  "success": true,
  "trace_id": "tr_011",
  "request_id": "req_011",
  "data": {
    "conversation_id": "conv_001",
    "messages": [
      {
        "message_id": "msg_001",
        "role": "user",
        "message_type": "text",
        "content": "集团新能源业务有哪些核心制度？",
        "related_run_id": "run_001",
        "created_at": "2026-04-27T09:59:00+08:00"
      },
      {
        "message_id": "msg_002",
        "role": "assistant",
        "message_type": "answer",
        "content": "集团新能源业务相关制度主要包括……",
        "related_run_id": "run_001",
        "created_at": "2026-04-27T09:59:03+08:00"
      }
    ]
  },
  "meta": {}
}
```

## 8.3 取消会话或重置上下文

```http
POST /api/v1/conversations/{conversation_id}/cancel
```

### 响应

```json
{
  "success": true,
  "trace_id": "tr_012",
  "request_id": "req_012",
  "data": {
    "message": "会话已取消"
  },
  "meta": {
    "conversation_id": "conv_001",
    "status": "cancelled"
  }
}
```

---

## 9. 澄清与槽位补充接口

## 9.1 回答澄清问题

```http
POST /api/v1/clarifications/{clarification_id}/reply
```

### 请求体

```json
{
  "reply": "发电量"
}
```

### 响应：恢复原任务继续执行

```json
{
  "success": true,
  "trace_id": "tr_020",
  "request_id": "req_020",
  "data": {
    "message": "已收到补充信息，任务继续执行"
  },
  "meta": {
    "conversation_id": "conv_002",
    "run_id": "run_020",
    "status": "resuming_previous_task",
    "sub_status": "running_sql",
    "need_clarification": false,
    "is_async": false
  }
}
```

---

## 10. 文档上传接口

## 10.1 上传文档

```http
POST /api/v1/documents/upload
Content-Type: multipart/form-data
```

### 表单字段

- `file`：上传文件
- `knowledge_base_id`：目标知识库 ID
- `business_domain`：业务域
- `department_id`：部门 ID，可选
- `security_level`：安全级别，可选

### 响应

```json
{
  "success": true,
  "trace_id": "tr_030",
  "request_id": "req_030",
  "data": {
    "document_id": "doc_001",
    "title": "新能源业务管理办法",
    "parse_status": "pending",
    "index_status": "pending"
  },
  "meta": {
    "is_async": true
  }
}
```

## 10.2 查询文档详情

```http
GET /api/v1/documents/{document_id}
```

---

## 11. 合同审查接口

## 11.1 提交合同审查

```http
POST /api/v1/contracts/review
```

### 请求体

```json
{
  "document_id": "doc_100",
  "conversation_id": null,
  "review_mode": "standard",
  "template_type": null,
  "output_format": "json"
}
```

### 字段说明

- `document_id`：已上传合同文档 ID
- `conversation_id`：可选，会话承接
- `review_mode`：审查模式，如 `standard` / `strict`
- `template_type`：模板类型，可选
- `output_format`：返回格式，如 `json` / `pdf` / `docx`

### 响应：任务已创建

```json
{
  "success": true,
  "trace_id": "tr_040",
  "request_id": "req_040",
  "data": {
    "message": "合同审查任务已创建"
  },
  "meta": {
    "conversation_id": "conv_100",
    "run_id": "run_100",
    "status": "executing",
    "sub_status": "parsing_contract",
    "is_async": true
  }
}
```

## 11.2 查询合同审查结果

```http
GET /api/v1/contracts/reviews/{run_id}
```

### 响应

```json
{
  "success": true,
  "trace_id": "tr_041",
  "request_id": "req_041",
  "data": {
    "summary": "共识别 5 个风险点，其中高风险 1 个",
    "risk_items": [
      {
        "risk_level": "high",
        "title": "违约责任不对等",
        "basis": "标准合同模板第 8 条",
        "suggestion": "建议补充对方违约责任"
      }
    ],
    "report_download_url": null
  },
  "meta": {
    "run_id": "run_100",
    "status": "waiting_review",
    "review_id": "rev_100",
    "need_human_review": true,
    "is_async": true
  }
}
```

---

## 12. 经营分析接口

### 12.0 V1 性能优化说明

经营分析接口已完成 V1 性能优化，核心变更：

1. **output_snapshot 轻量化**：重内容（tables / insight_cards / report_blocks / chart_spec）不再写入 task_run.output_snapshot，单独存储到 analytics_result_repository；
2. **query 响应分级**：正式支持 output_mode = lite / standard / full，默认 lite；
3. **export 真异步化**：POST export 只创建任务并返回 export_id，后台异步处理，GET 轮询读取状态；
4. **insight / report 延迟生成**：按 output_mode 决定是否生成 chart_spec / insight_cards / report_blocks；
5. **registry / schema / cache 常驻缓存**：高频只读对象通过 RegistryCache 进程内缓存。

对应的验收与慢点复盘结果见：`docs/ANALYTICS_PERF_REVIEW_V1.md`。

## 12.1 提交经营分析请求

```http
POST /api/v1/analytics/query
```

### 请求体

```json
{
  "query": "帮我分析一下上个月新疆区域发电量",
  "conversation_id": null,
  "output_mode": "lite",
  "need_sql_explain": false
}
```

### output_mode 说明

| output_mode | 返回内容 | 适用场景 |
|---|---|---|
| lite | summary、row_count、latency_ms、run_id、trace_id、metric_scope、data_source、compare_target、group_by | 主查询默认返回，减少 payload |
| standard | 在 lite 基础上增加 sql_preview、chart_spec、insight_cards、masked_fields、effective_filters、governance_decision | 前端需要图表和洞察卡片 |
| full | 在 standard 基础上增加 tables、report_blocks、sql_explain、safety_check_result、permission_check_result、data_scope_result、audit_info、timing_breakdown | 详情页、导出等需要完整数据 |

兼容性说明：

- 旧参数 `summary` / `default` 仍然保留为向后兼容别名，服务端内部会按 `standard` 处理；
- 新接入方应优先使用正式枚举值：`lite / standard / full`。

### 响应：lite 模式

```json
{
  "success": true,
  "trace_id": "tr_050",
  "request_id": "req_050",
  "data": {
    "run_id": "run_200",
    "trace_id": "tr_050",
    "summary": "上个月新疆区域发电量环比增长 8.2%",
    "row_count": 1,
    "latency_ms": 120,
    "metric_scope": "发电量",
    "data_source": "local_analytics",
    "compare_target": null,
    "group_by": null
  },
  "meta": {
    "conversation_id": "conv_200",
    "run_id": "run_200",
    "status": "succeeded",
    "is_async": false
  }
}
```

### 响应：需要澄清

```json
{
  "success": true,
  "trace_id": "tr_051",
  "request_id": "req_051",
  "data": {
    "clarification": {
      "clarification_id": "clr_200",
      "question": "你想看哪个指标？发电量、收入还是成本？",
      "target_slots": ["metric"]
    }
  },
  "meta": {
    "conversation_id": "conv_200",
    "run_id": "run_201",
    "status": "awaiting_user_clarification",
    "sub_status": "awaiting_slot_fill",
    "need_clarification": true
  }
}
```

## 12.2 查询经营分析任务详情

```http
GET /api/v1/analytics/runs/{run_id}?output_mode=full
```

### output_mode 参数

与 query 接口一致，默认 full（向后兼容）。

## 12.3 创建经营分析导出任务

```http
POST /api/v1/analytics/runs/{run_id}/export
```

### 请求体

```json
{
  "export_type": "markdown",
  "export_template": "weekly_report"
}
```

### 响应：异步任务已创建

```json
{
  "success": true,
  "trace_id": "tr_055",
  "request_id": "req_055",
  "data": {
    "export_id": "exp_abc123",
    "run_id": "run_200",
    "export_type": "markdown",
    "export_template": "weekly_report",
    "status": "pending",
    "review_required": false,
    "review_status": "not_required",
    "filename": null,
    "artifact_path": null,
    "created_at": "2026-04-29T10:00:00+08:00",
    "finished_at": null,
    "metadata": {},
    "governance_decision": {}
  },
  "meta": {
    "run_id": "run_200",
    "status": "pending",
    "is_async": true,
    "need_human_review": false
  }
}
```

### 响应：需要人工审核

```json
{
  "success": true,
  "data": {
    "export_id": "exp_def456",
    "status": "awaiting_human_review",
    "review_required": true,
    "review_status": "pending"
  },
  "meta": {
    "run_id": "run_200",
    "review_id": "rev_001",
    "status": "awaiting_human_review",
    "is_async": true,
    "need_human_review": true
  }
}
```

## 12.4 查询导出任务详情

```http
GET /api/v1/analytics/exports/{export_id}
```

说明：

- `POST /api/v1/analytics/runs/{run_id}/export` 只负责创建导出任务；
- 真正的渲染在后台 `AsyncTaskRunner` 中执行；
- 前端或调用方应通过 `GET /api/v1/analytics/exports/{export_id}` 轮询状态，直到进入 `succeeded / failed` 终态。

### 响应：导出进行中

```json
{
  "success": true,
  "data": {
    "export_id": "exp_abc123",
    "status": "running",
    "filename": null,
    "finished_at": null
  },
  "meta": {
    "run_id": "run_200",
    "status": "running",
    "is_async": true
  }
}
```

### 响应：导出完成

```json
{
  "success": true,
  "data": {
    "export_id": "exp_abc123",
    "status": "succeeded",
    "filename": "analytics_run_200_weekly_report.md",
    "artifact_path": "/storage/exports/exp_abc123.md",
    "content_preview": "# 经营分析周报\n\n...",
    "finished_at": "2026-04-29T10:00:05+08:00",
    "metadata": {
      "export_render_ms": 3200.5,
      "server_mode": "inprocess_report_mcp_server"
    }
  },
  "meta": {
    "run_id": "run_200",
    "status": "succeeded",
    "is_async": true
  }
}
```

---

## 13. 报告生成接口

## 13.1 提交报告生成任务

```http
POST /api/v1/reports/generate
```

### 请求体

```json
{
  "report_type": "analytics_report",
  "source_run_id": "run_200",
  "output_format": "pdf"
}
```

### 响应

```json
{
  "success": true,
  "trace_id": "tr_060",
  "request_id": "req_060",
  "data": {
    "message": "报告生成任务已创建"
  },
  "meta": {
    "run_id": "run_300",
    "status": "waiting_async_result",
    "sub_status": "building_report",
    "is_async": true
  }
}
```

## 13.2 查询报告详情

```http
GET /api/v1/reports/{run_id}
```

### 响应

```json
{
  "success": true,
  "trace_id": "tr_061",
  "request_id": "req_061",
  "data": {
    "report_id": "rpt_001",
    "title": "经营分析报告",
    "download_url": "https://example.com/rpt_001.pdf"
  },
  "meta": {
    "run_id": "run_300",
    "status": "succeeded"
  }
}
```

---

## 14. Human Review 接口

## 14.1 查询待审核列表

```http
GET /api/v1/reviews
```

### 查询参数

```text
status=pending
page=1
page_size=20
```

## 14.2 查询审核详情

```http
GET /api/v1/reviews/{review_id}
```

### 响应重点字段

- `review_id`
- `run_id`
- `task_id`
- `risk_level`
- `review_status`
- `draft_result`
- `evidence`
- `review_payload`

## 14.3 提交审核结论

```http
POST /api/v1/reviews/{review_id}/decision
```

### 请求体

```json
{
  "decision": "approved",
  "comment": "审核通过"
}
```

### decision 可选值

```text
approved
rejected
revised
```

### 响应

```json
{
  "success": true,
  "trace_id": "tr_070",
  "request_id": "req_070",
  "data": {
    "message": "审核结果已提交"
  },
  "meta": {
    "review_id": "rev_001",
    "review_status": "approved"
  }
}
```

---

## 15. Trace 接口

## 15.1 查询任务 Trace

```http
GET /api/v1/traces/{run_id}
```

### 响应

```json
{
  "success": true,
  "trace_id": "tr_080",
  "request_id": "req_080",
  "data": {
    "run_id": "run_001",
    "trace_events": [
      {
        "time": "2026-04-27T10:00:00+08:00",
        "event_type": "task_created",
        "detail": {}
      },
      {
        "time": "2026-04-27T10:00:01+08:00",
        "event_type": "retrieval_started",
        "detail": {}
      }
    ]
  },
  "meta": {}
}
```

---

## 16. Evaluation 接口

## 16.1 创建评估任务

```http
POST /api/v1/evaluations
```

## 16.2 查询评估列表

```http
GET /api/v1/evaluations
```

## 16.3 查询单个评估任务

```http
GET /api/v1/evaluations/{eval_task_id}
```

---

## 17. 统一错误码建议

建议第一阶段统一这些错误码：

```text
INVALID_ARGUMENT
UNAUTHORIZED
PERMISSION_DENIED
RESOURCE_NOT_FOUND
CONFLICT
RATE_LIMITED
DOCUMENT_PARSE_FAILED
INDEXING_FAILED
RETRIEVAL_FAILED
LLM_CALL_FAILED
TOOL_CALL_FAILED
MCP_CALL_FAILED
A2A_CALL_FAILED
SQL_SAFETY_BLOCKED
HUMAN_REVIEW_REQUIRED
CLARIFICATION_REQUIRED
TASK_EXPIRED
INTERNAL_ERROR
```

### 示例：权限错误

```json
{
  "success": false,
  "trace_id": "tr_090",
  "request_id": "req_090",
  "error": {
    "error_code": "PERMISSION_DENIED",
    "message": "当前用户无权访问该知识库",
    "detail": {
      "knowledge_base_id": "kb_001"
    }
  }
}
```

---

## 18. 同步与异步接口约定

## 18.1 同步场景

适合：

- 简单问答
- 短链路经营分析
- 简单澄清补充后重试

### 特征

- HTTP 请求直接返回最终结果
- `is_async = false`

## 18.2 异步场景

适合：

- OCR
- 长文合同审查
- 大报告生成
- 大查询经营分析
- Human Review
- 远程 A2A 长任务

### 特征

- 首次请求返回“任务已创建”
- 前端轮询详情接口
- `is_async = true`

---

## 19. 流式返回约定

第一阶段建议：

- `/chat` 支持可选流式
- 合同审查、报告生成、经营分析先以非流式 + 异步为主

若流式开启，建议返回：

- `event: status`
- `event: chunk`
- `event: citation`
- `event: done`

---

## 20. 第一阶段必须先实现的接口

建议第一阶段最小闭环先做这些：

```text
POST /api/v1/chat
GET  /api/v1/conversations
GET  /api/v1/conversations/{conversation_id}/messages
POST /api/v1/clarifications/{clarification_id}/reply

POST /api/v1/documents/upload
POST /api/v1/contracts/review
GET  /api/v1/contracts/reviews/{run_id}

POST /api/v1/analytics/query
GET  /api/v1/analytics/runs/{run_id}

GET  /api/v1/reviews
GET  /api/v1/reviews/{review_id}
POST /api/v1/reviews/{review_id}/decision

GET  /api/v1/traces/{run_id}
```

---

## 21. 前后端联调重点

前后端联调时，优先确认这些点：

- `conversation_id` 是否正确承接多轮
- 澄清问题是否能返回 `clarification_id`
- 用户补充后是否能恢复原任务
- `run_id` / `trace_id` 是否贯穿所有业务链路
- `waiting_review` / `awaiting_user_clarification` / `waiting_async_result` 前端是否能正确展示
- 错误码是否统一

---

## 22. 当前版本说明

本文档已经覆盖：

- 统一响应模型
- 统一错误模型
- 统一状态字典
- chat / conversation / clarification 接口
- documents / contracts / analytics / reports 接口
- Human Review / Trace / Evaluation 接口
- 同步 / 异步 / 审核中 / 澄清中的接口表达方式

这版已经可以作为后续：

- FastAPI 路由设计
- Pydantic Schema 设计
- 前后端联调契约
- 最小闭环开发

的直接依据。
