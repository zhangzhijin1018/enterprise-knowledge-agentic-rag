# DB_DESIGN.md

# 新疆能源集团知识与生产经营智能 Agent 平台
## 数据库设计文档

---

## 1. 文档定位

本文档用于指导本项目 PostgreSQL 元数据库的建模、迁移、索引、分区、归档与工程实现。

本文档特别强调两点：

1. 所有核心表与字段都要有清晰中文注释；
2. PostgreSQL 索引与分区不仅给出示例，还给出可实施级 SQL 和使用说明。

---

## 2. 数据库总体原则

### 2.1 PostgreSQL 作为平台元数据库

平台内部元数据统一使用 PostgreSQL，主要承载：

- 身份与权限；
- 知识库与文档元数据；
- 会话、多轮对话、槽位澄清；
- 工作流运行状态；
- Human Review；
- MCP / A2A / SQL 审计；
- 评估与用户反馈。

### 2.2 大对象分离

以下内容不放 PostgreSQL 主存：

- 原始 PDF / DOCX / 图片文件；
- 大体积正文全文；
- embedding 向量。

分别放到：

- 对象存储；
- Milvus；
- 可观测日志系统。

### 2.3 状态与审计优先

数据库设计必须服务于：

- 状态机；
- 中断恢复；
- 多轮对话；
- 审核；
- 审计；
- 评估。

---

## 2.4 经营分析真实数据源一期定型结论

经营分析数据源这一层，本轮明确统一以下结论：

1. 平台元数据库继续使用 PostgreSQL；
2. 企业经营分析真实数据源如果已经存在现成只读 PostgreSQL、MySQL 或数仓视图，系统应支持接入；
3. 但本项目一期默认优先以 PostgreSQL 作为真实经营分析数据源参考实现；
4. `local_analytics` 继续保留为 demo / fallback 数据源；
5. `enterprise_readonly` 继续作为真实经营分析只读数据源的默认 key。

### 为什么一期优先 PostgreSQL

PostgreSQL 适合作为一期经营分析真实数据源，原因主要有：

- 与平台元数据库技术栈一致，降低 DBA、运维、驱动和 ORM 复杂度；
- 支持成熟的分区、索引、只读账号、视图、物化视图和 JSONB 扩展能力；
- 对“日粒度事实表 + 维表 + 只读聚合查询”这一类经营分析负载足够稳健；
- 便于本项目当前 `SQL Gateway / SQL MCP-compatible` 执行层快速落地；
- 便于后续从本地 demo 库平滑迁移到企业只读 PostgreSQL。

### 为什么仍保留 local_analytics

保留 `local_analytics` 不是架构妥协，而是工程策略：

- 本地开发、单元测试、接口联调不能强依赖真实企业库；
- Demo / fallback 数据源能保证 `analytics/query -> export -> review` 全链路持续可运行；
- 当数据库配置、网络白名单或只读账号尚未准备好时，研发不被阻塞；
- 与 `enterprise_readonly` 并存，正好对应“本地联调”和“企业接入”两种阶段。

---

## 2.5 经营分析真实数据源核心表设计

本项目一期默认把真实经营分析参考数据源收口到三张核心表：

1. `analytics_metrics_daily`
   - 经营分析日粒度事实表；
   - 主要承接发电量、收入、成本、利润、产量等日粒度指标；
   - 是当前 `SchemaRegistry / SQL Builder / SQL Guard` 的核心事实表。

2. `analytics_metric_definitions`
   - 指标维表；
   - 主要承接指标编码、展示名称、单位、聚合方式、业务域和敏感级别；
   - 与当前代码中的 `MetricCatalog` 方向一致。

3. `analytics_org_dimensions`
   - 组织维表；
   - 主要承接组织、区域、电站、部门映射；
   - 用于部门范围过滤、区域/电站下钻和组织口径治理。

这三张表共同构成一期经营分析真实数据源的最小可实施模型。

---

## 2.6 经营分析真实数据源设计与代码映射关系

当前代码层与数据库设计的映射关系如下：

- `core/analytics/schema_registry.py`
  - 当前仍保留默认事实表结构定义；
  - 其字段命名必须与 `analytics_metrics_daily` 对齐；
  - 当前阶段仍在代码层保留默认定义，原因是要兼顾本地 demo/fallback。

- `core/analytics/metric_catalog.py`
  - 当前仍保留默认指标目录；
  - 其结构方向已向 `analytics_metric_definitions` 对齐；
  - 后续可逐步把指标目录从代码迁移到数据库配置层。

- `core/analytics/data_source_registry.py`
  - 当前负责“内置默认数据源 + repository override”的统一读取；
  - 后续可逐步演进为真正的数据源注册中心管理层。

- `core/repositories/data_source_repository.py`
  - 当前提供数据源配置的数据库优先 / 内存回退能力；
  - 未来可以承接更多数据源启停、权限和描述信息。

---

## 2.7 经营分析真实数据源 SQL 脚本目录

本项目当前把经营分析真实数据源的可实施级 SQL 设计统一放在：

```text
sql/analytics/
├── 001_analytics_metric_definitions.sql
├── 002_analytics_org_dimensions.sql
├── 003_analytics_metrics_daily.sql
├── 004_analytics_metrics_daily_partitions.sql
└── 005_analytics_metrics_daily_indexes.sql
```

这些文件当前定位是：

- 设计稿 + 实施稿；
- 可直接给 DBA / 后端开发参考；
- 未来 Alembic 或正式 DBA 落库时的基础输入。

---

## 2.8 analytics_metrics_daily 分区与索引策略

### 为什么按月分区

`analytics_metrics_daily` 一期按月分区，原因如下：

- 经营分析最常见的查询是月度趋势、近一个月、近几个月、月报；
- 月度粒度天然适合运维、归档和历史数据管理；
- PostgreSQL 分区裁剪在 `biz_date` 过滤场景下收益明显；
- 与当前 `trend / month group by / monthly_report` 场景天然匹配。

### 为什么 department_code 索引很重要

`department_code` 在经营分析里不仅是展示字段，更是治理字段：

- 当前系统已经支持部门范围过滤；
- 经营分析必须先治理再执行；
- 因此 `department_code` 索引直接关系到数据范围裁剪、权限治理和审计查询性能。

### 一期核心索引服务场景

- `(biz_date, metric_code)`
  - 服务趋势分析、月度趋势、单指标时间过滤。

- `(biz_date, metric_code, region_code)`
  - 服务区域汇总、区域排名、区域过滤。

- `(biz_date, metric_code, station_code)`
  - 服务电站汇总、电站排名、电站过滤。

- `(biz_date, department_code)`
  - 服务部门范围过滤和治理裁剪。

- `(metric_code, department_code, biz_date)`
  - 服务指标权限、部门范围治理、审计与二次验证。

### 唯一索引建议

为避免重复导入相同业务口径数据，一期建议基于：

- `biz_date`
- `metric_code`
- `region_code`
- `station_code`
- `department_code`
- `data_version`

构造唯一业务键索引。

这能避免相同日期、相同指标、相同组织口径、相同版本的数据被重复导入。

---

## 3. 命名与字段规范

### 3.1 表命名

统一使用小写复数下划线命名，例如：

- users
- task_runs
- mcp_calls

### 3.2 主键规范

统一建议：

- `id BIGSERIAL PRIMARY KEY`：数据库内部主键；
- `*_uuid UUID UNIQUE`：对外稳定标识。

### 3.3 时间字段规范

建议统一：

- `created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()`
- `updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()`

运行类表可增加：

- `started_at`
- `finished_at`
- `reviewed_at`
- `resolved_at`

### 3.4 状态字段规范

建议第一阶段先使用：

- `VARCHAR(32)` 或 `VARCHAR(64)`

原因：

- 迁移更灵活；
- 状态变化时改动成本更低。

### 3.5 中文注释规范

所有表都建议写：

- 表注释：`COMMENT ON TABLE ...`
- 字段注释：`COMMENT ON COLUMN ...`

如果使用 SQLAlchemy，也建议在 ORM 模型中补 `comment="..."`。

---

## 4. 核心表清单

建议第一阶段重点建设这些表：

### 4.1 IAM

- users
- departments
- roles
- permissions
- role_permissions

### 4.2 Knowledge

- knowledge_bases
- documents
- document_chunks

### 4.3 Conversation

- conversations
- conversation_messages
- conversation_memory
- slot_snapshots
- clarification_events

### 4.4 Runtime

- agent_registry
- capability_registry
- task_runs
- agent_runs
- workflow_events

### 4.5 Governance / Logs

- human_reviews
- review_events
- policy_decision_logs
- retrieval_logs
- llm_calls
- mcp_calls
- a2a_delegations
- sql_audits

### 4.6 Evaluation

- evaluation_tasks
- evaluation_results
- user_feedback

---

## 5. 所有核心表与字段中文注释版

下面给出第一批核心表的“带中文注释 SQL 写法示例”。  
你后续在 Alembic 里也建议按这个标准落。

---

## 5.1 users

```sql
CREATE TABLE users (
    id BIGSERIAL PRIMARY KEY,
    user_uuid UUID NOT NULL UNIQUE,
    username VARCHAR(100) NOT NULL UNIQUE,
    email VARCHAR(255),
    display_name VARCHAR(100),
    department_id BIGINT,
    status VARCHAR(32) NOT NULL DEFAULT 'active',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE users IS '用户表：存储平台登录用户与基础身份信息';

COMMENT ON COLUMN users.id IS '数据库内部主键';
COMMENT ON COLUMN users.user_uuid IS '对外稳定用户标识';
COMMENT ON COLUMN users.username IS '登录用户名';
COMMENT ON COLUMN users.email IS '邮箱地址';
COMMENT ON COLUMN users.display_name IS '显示名称';
COMMENT ON COLUMN users.department_id IS '所属部门ID';
COMMENT ON COLUMN users.status IS '用户状态，如 active、disabled、locked';
COMMENT ON COLUMN users.created_at IS '创建时间';
COMMENT ON COLUMN users.updated_at IS '更新时间';
```

---

## 5.2 departments

```sql
CREATE TABLE departments (
    id BIGSERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    code VARCHAR(64) UNIQUE,
    parent_id BIGINT REFERENCES departments(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE departments IS '部门表：存储组织架构中的部门信息';

COMMENT ON COLUMN departments.id IS '数据库内部主键';
COMMENT ON COLUMN departments.name IS '部门名称';
COMMENT ON COLUMN departments.code IS '部门编码';
COMMENT ON COLUMN departments.parent_id IS '父部门ID';
COMMENT ON COLUMN departments.created_at IS '创建时间';
COMMENT ON COLUMN departments.updated_at IS '更新时间';
```

---

## 5.3 roles

```sql
CREATE TABLE roles (
    id BIGSERIAL PRIMARY KEY,
    code VARCHAR(64) NOT NULL UNIQUE,
    name VARCHAR(100) NOT NULL,
    description TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE roles IS '角色表：定义平台中的角色信息';

COMMENT ON COLUMN roles.id IS '数据库内部主键';
COMMENT ON COLUMN roles.code IS '角色编码';
COMMENT ON COLUMN roles.name IS '角色名称';
COMMENT ON COLUMN roles.description IS '角色说明';
COMMENT ON COLUMN roles.created_at IS '创建时间';
COMMENT ON COLUMN roles.updated_at IS '更新时间';
```

---

## 5.4 permissions

```sql
CREATE TABLE permissions (
    id BIGSERIAL PRIMARY KEY,
    permission_code VARCHAR(128) NOT NULL UNIQUE,
    permission_name VARCHAR(128) NOT NULL,
    resource_type VARCHAR(64) NOT NULL,
    action VARCHAR(64) NOT NULL,
    description TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE permissions IS '权限表：定义资源类型与动作级权限';

COMMENT ON COLUMN permissions.id IS '数据库内部主键';
COMMENT ON COLUMN permissions.permission_code IS '权限编码';
COMMENT ON COLUMN permissions.permission_name IS '权限名称';
COMMENT ON COLUMN permissions.resource_type IS '资源类型';
COMMENT ON COLUMN permissions.action IS '动作类型';
COMMENT ON COLUMN permissions.description IS '权限说明';
COMMENT ON COLUMN permissions.created_at IS '创建时间';
```

---

## 5.5 role_permissions

```sql
CREATE TABLE role_permissions (
    id BIGSERIAL PRIMARY KEY,
    role_id BIGINT NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
    permission_id BIGINT NOT NULL REFERENCES permissions(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(role_id, permission_id)
);

COMMENT ON TABLE role_permissions IS '角色权限关联表：定义角色拥有哪些权限';

COMMENT ON COLUMN role_permissions.id IS '数据库内部主键';
COMMENT ON COLUMN role_permissions.role_id IS '角色ID';
COMMENT ON COLUMN role_permissions.permission_id IS '权限ID';
COMMENT ON COLUMN role_permissions.created_at IS '创建时间';
```

---

## 5.6 knowledge_bases

```sql
CREATE TABLE knowledge_bases (
    id BIGSERIAL PRIMARY KEY,
    kb_uuid UUID NOT NULL UNIQUE,
    name VARCHAR(255) NOT NULL,
    business_domain VARCHAR(64) NOT NULL,
    description TEXT,
    status VARCHAR(32) NOT NULL DEFAULT 'active',
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE knowledge_bases IS '知识库表：定义知识库基础信息';

COMMENT ON COLUMN knowledge_bases.id IS '数据库内部主键';
COMMENT ON COLUMN knowledge_bases.kb_uuid IS '对外稳定知识库标识';
COMMENT ON COLUMN knowledge_bases.name IS '知识库名称';
COMMENT ON COLUMN knowledge_bases.business_domain IS '业务域，如 policy、safety、project';
COMMENT ON COLUMN knowledge_bases.description IS '知识库说明';
COMMENT ON COLUMN knowledge_bases.status IS '知识库状态';
COMMENT ON COLUMN knowledge_bases.metadata IS '扩展元数据';
COMMENT ON COLUMN knowledge_bases.created_at IS '创建时间';
COMMENT ON COLUMN knowledge_bases.updated_at IS '更新时间';
```

---

## 5.7 documents

```sql
CREATE TABLE documents (
    id BIGSERIAL PRIMARY KEY,
    document_uuid UUID NOT NULL UNIQUE,
    knowledge_base_id BIGINT NOT NULL REFERENCES knowledge_bases(id),
    title VARCHAR(500) NOT NULL,
    filename VARCHAR(500) NOT NULL,
    file_type VARCHAR(32) NOT NULL,
    file_size BIGINT,
    storage_uri TEXT NOT NULL,
    business_domain VARCHAR(64) NOT NULL,
    department_id BIGINT REFERENCES departments(id),
    version_no INTEGER NOT NULL DEFAULT 1,
    effective_date DATE,
    security_level VARCHAR(32),
    access_scope JSONB NOT NULL DEFAULT '{}'::jsonb,
    parse_status VARCHAR(32) NOT NULL DEFAULT 'pending',
    index_status VARCHAR(32) NOT NULL DEFAULT 'pending',
    uploaded_by BIGINT REFERENCES users(id),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE documents IS '文档表：存储知识库中文档的元数据';

COMMENT ON COLUMN documents.id IS '数据库内部主键';
COMMENT ON COLUMN documents.document_uuid IS '对外稳定文档标识';
COMMENT ON COLUMN documents.knowledge_base_id IS '所属知识库ID';
COMMENT ON COLUMN documents.title IS '文档标题';
COMMENT ON COLUMN documents.filename IS '原始文件名';
COMMENT ON COLUMN documents.file_type IS '文件类型，如 pdf、docx';
COMMENT ON COLUMN documents.file_size IS '文件大小（字节）';
COMMENT ON COLUMN documents.storage_uri IS '对象存储URI';
COMMENT ON COLUMN documents.business_domain IS '文档所属业务域';
COMMENT ON COLUMN documents.department_id IS '所属部门ID';
COMMENT ON COLUMN documents.version_no IS '文档版本号';
COMMENT ON COLUMN documents.effective_date IS '生效日期';
COMMENT ON COLUMN documents.security_level IS '安全级别';
COMMENT ON COLUMN documents.access_scope IS '访问范围规则';
COMMENT ON COLUMN documents.parse_status IS '解析状态';
COMMENT ON COLUMN documents.index_status IS '索引状态';
COMMENT ON COLUMN documents.uploaded_by IS '上传人ID';
COMMENT ON COLUMN documents.metadata IS '扩展元数据';
COMMENT ON COLUMN documents.created_at IS '创建时间';
COMMENT ON COLUMN documents.updated_at IS '更新时间';
```

---

## 5.8 document_chunks

```sql
CREATE TABLE document_chunks (
    id BIGSERIAL PRIMARY KEY,
    chunk_uuid UUID NOT NULL UNIQUE,
    document_id BIGINT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    knowledge_base_id BIGINT NOT NULL REFERENCES knowledge_bases(id),
    chunk_index INTEGER NOT NULL,
    page_no INTEGER,
    section_title VARCHAR(255),
    content_preview TEXT,
    token_count INTEGER,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    milvus_primary_key VARCHAR(128),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(document_id, chunk_index)
);

COMMENT ON TABLE document_chunks IS '文档切片表：存储文档切片元数据与向量库引用';

COMMENT ON COLUMN document_chunks.id IS '数据库内部主键';
COMMENT ON COLUMN document_chunks.chunk_uuid IS '对外稳定切片标识';
COMMENT ON COLUMN document_chunks.document_id IS '所属文档ID';
COMMENT ON COLUMN document_chunks.knowledge_base_id IS '所属知识库ID';
COMMENT ON COLUMN document_chunks.chunk_index IS '切片序号';
COMMENT ON COLUMN document_chunks.page_no IS '所在页码';
COMMENT ON COLUMN document_chunks.section_title IS '章节标题';
COMMENT ON COLUMN document_chunks.content_preview IS '切片内容摘要';
COMMENT ON COLUMN document_chunks.token_count IS '切片Token数';
COMMENT ON COLUMN document_chunks.metadata IS '扩展元数据';
COMMENT ON COLUMN document_chunks.milvus_primary_key IS 'Milvus 主键引用';
COMMENT ON COLUMN document_chunks.created_at IS '创建时间';
```

---

## 5.9 conversations

```sql
CREATE TABLE conversations (
    id BIGSERIAL PRIMARY KEY,
    conversation_uuid UUID NOT NULL UNIQUE,
    user_id BIGINT NOT NULL REFERENCES users(id),
    title VARCHAR(255),
    current_route VARCHAR(64),
    current_status VARCHAR(32) NOT NULL DEFAULT 'active',
    last_run_id VARCHAR(128),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE conversations IS '会话表：存储多轮对话会话级信息';

COMMENT ON COLUMN conversations.id IS '数据库内部主键';
COMMENT ON COLUMN conversations.conversation_uuid IS '对外稳定会话标识';
COMMENT ON COLUMN conversations.user_id IS '会话所属用户ID';
COMMENT ON COLUMN conversations.title IS '会话标题';
COMMENT ON COLUMN conversations.current_route IS '当前主要业务路由';
COMMENT ON COLUMN conversations.current_status IS '会话状态';
COMMENT ON COLUMN conversations.last_run_id IS '最近一次任务运行ID';
COMMENT ON COLUMN conversations.metadata IS '会话扩展信息';
COMMENT ON COLUMN conversations.created_at IS '创建时间';
COMMENT ON COLUMN conversations.updated_at IS '更新时间';
```

---

## 5.10 conversation_messages

```sql
CREATE TABLE conversation_messages (
    id BIGSERIAL PRIMARY KEY,
    conversation_id BIGINT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    message_uuid UUID NOT NULL UNIQUE,
    role VARCHAR(32) NOT NULL,
    message_type VARCHAR(32) NOT NULL DEFAULT 'text',
    content TEXT NOT NULL,
    structured_content JSONB NOT NULL DEFAULT '{}'::jsonb,
    related_run_id VARCHAR(128),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE conversation_messages IS '会话消息表：存储多轮对话中的消息明细';

COMMENT ON COLUMN conversation_messages.id IS '数据库内部主键';
COMMENT ON COLUMN conversation_messages.conversation_id IS '所属会话ID';
COMMENT ON COLUMN conversation_messages.message_uuid IS '对外稳定消息标识';
COMMENT ON COLUMN conversation_messages.role IS '消息角色，如 user、assistant、system、reviewer';
COMMENT ON COLUMN conversation_messages.message_type IS '消息类型，如 text、clarification、summary';
COMMENT ON COLUMN conversation_messages.content IS '消息原文';
COMMENT ON COLUMN conversation_messages.structured_content IS '结构化消息内容';
COMMENT ON COLUMN conversation_messages.related_run_id IS '关联任务运行ID';
COMMENT ON COLUMN conversation_messages.created_at IS '创建时间';
```

---

## 5.11 conversation_memory

```sql
CREATE TABLE conversation_memory (
    id BIGSERIAL PRIMARY KEY,
    conversation_id BIGINT NOT NULL UNIQUE REFERENCES conversations(id) ON DELETE CASCADE,
    last_route VARCHAR(64),
    last_agent VARCHAR(128),
    last_primary_object VARCHAR(255),
    last_metric VARCHAR(255),
    last_time_range JSONB NOT NULL DEFAULT '{}'::jsonb,
    last_org_scope JSONB NOT NULL DEFAULT '{}'::jsonb,
    last_kb_scope JSONB NOT NULL DEFAULT '{}'::jsonb,
    last_report_id VARCHAR(128),
    last_contract_id VARCHAR(128),
    short_term_memory JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE conversation_memory IS '会话记忆表：存储多轮对话短期记忆快照';

COMMENT ON COLUMN conversation_memory.id IS '数据库内部主键';
COMMENT ON COLUMN conversation_memory.conversation_id IS '所属会话ID';
COMMENT ON COLUMN conversation_memory.last_route IS '最近业务路由';
COMMENT ON COLUMN conversation_memory.last_agent IS '最近使用的业务专家';
COMMENT ON COLUMN conversation_memory.last_primary_object IS '最近主对象，如合同、项目、制度';
COMMENT ON COLUMN conversation_memory.last_metric IS '最近分析指标';
COMMENT ON COLUMN conversation_memory.last_time_range IS '最近时间范围';
COMMENT ON COLUMN conversation_memory.last_org_scope IS '最近组织范围';
COMMENT ON COLUMN conversation_memory.last_kb_scope IS '最近知识库范围';
COMMENT ON COLUMN conversation_memory.last_report_id IS '最近报告ID';
COMMENT ON COLUMN conversation_memory.last_contract_id IS '最近合同ID';
COMMENT ON COLUMN conversation_memory.short_term_memory IS '短期会话记忆快照';
COMMENT ON COLUMN conversation_memory.updated_at IS '更新时间';
```

---

## 5.12 slot_snapshots

```sql
CREATE TABLE slot_snapshots (
    id BIGSERIAL PRIMARY KEY,
    run_id VARCHAR(128) NOT NULL UNIQUE,
    task_type VARCHAR(64) NOT NULL,
    required_slots JSONB NOT NULL DEFAULT '[]'::jsonb,
    collected_slots JSONB NOT NULL DEFAULT '{}'::jsonb,
    missing_slots JSONB NOT NULL DEFAULT '[]'::jsonb,
    min_executable_satisfied BOOLEAN NOT NULL DEFAULT FALSE,
    awaiting_user_input BOOLEAN NOT NULL DEFAULT FALSE,
    resume_step VARCHAR(128),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE slot_snapshots IS '槽位快照表：存储任务执行过程中的槽位收集状态';

COMMENT ON COLUMN slot_snapshots.id IS '数据库内部主键';
COMMENT ON COLUMN slot_snapshots.run_id IS '关联任务运行ID';
COMMENT ON COLUMN slot_snapshots.task_type IS '任务类型';
COMMENT ON COLUMN slot_snapshots.required_slots IS '必填槽位列表';
COMMENT ON COLUMN slot_snapshots.collected_slots IS '已收集槽位';
COMMENT ON COLUMN slot_snapshots.missing_slots IS '缺失槽位';
COMMENT ON COLUMN slot_snapshots.min_executable_satisfied IS '是否满足最小可执行条件';
COMMENT ON COLUMN slot_snapshots.awaiting_user_input IS '是否正在等待用户补充信息';
COMMENT ON COLUMN slot_snapshots.resume_step IS '恢复执行入口步骤';
COMMENT ON COLUMN slot_snapshots.updated_at IS '更新时间';
```

---

## 5.13 clarification_events

```sql
CREATE TABLE clarification_events (
    id BIGSERIAL PRIMARY KEY,
    clarification_uuid UUID NOT NULL UNIQUE,
    run_id VARCHAR(128) NOT NULL,
    conversation_id BIGINT REFERENCES conversations(id) ON DELETE CASCADE,
    question_text TEXT NOT NULL,
    target_slots JSONB NOT NULL DEFAULT '[]'::jsonb,
    user_reply TEXT,
    resolved_slots JSONB NOT NULL DEFAULT '{}'::jsonb,
    status VARCHAR(32) NOT NULL DEFAULT 'pending',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved_at TIMESTAMPTZ
);

COMMENT ON TABLE clarification_events IS '澄清事件表：存储系统追问、用户回复与槽位补齐结果';

COMMENT ON COLUMN clarification_events.id IS '数据库内部主键';
COMMENT ON COLUMN clarification_events.clarification_uuid IS '对外稳定澄清事件标识';
COMMENT ON COLUMN clarification_events.run_id IS '关联任务运行ID';
COMMENT ON COLUMN clarification_events.conversation_id IS '所属会话ID';
COMMENT ON COLUMN clarification_events.question_text IS '系统发出的澄清问题';
COMMENT ON COLUMN clarification_events.target_slots IS '本次要补齐的目标槽位';
COMMENT ON COLUMN clarification_events.user_reply IS '用户回复内容';
COMMENT ON COLUMN clarification_events.resolved_slots IS '解析出的已补齐槽位';
COMMENT ON COLUMN clarification_events.status IS '澄清状态';
COMMENT ON COLUMN clarification_events.created_at IS '创建时间';
COMMENT ON COLUMN clarification_events.resolved_at IS '解决时间';
```

---

## 5.14 task_runs

> **V1 性能优化说明**：`output_snapshot` 已轻量化。重内容（tables / insight_cards / report_blocks / chart_spec）不再写入此字段，而是单独存储到 `analytics_results` 表。轻快照仅保留 summary、slots、sql_preview、row_count、latency_ms、compare_target、group_by、governance_decision（简版）、timing_breakdown。目的是减少 task_runs 的大 JSON 写入与读取压力。
>
> 这套轻重分离设计的验收结果与慢点复盘见：`docs/ANALYTICS_PERF_REVIEW_V1.md`。

```sql
CREATE TABLE task_runs (
    id BIGSERIAL PRIMARY KEY,
    run_id VARCHAR(128) NOT NULL UNIQUE,
    task_id VARCHAR(128) NOT NULL,
    parent_task_id VARCHAR(128),
    conversation_id BIGINT REFERENCES conversations(id),
    user_id BIGINT REFERENCES users(id),
    trace_id VARCHAR(128) NOT NULL,
    task_type VARCHAR(64) NOT NULL,
    route VARCHAR(64),
    selected_agent VARCHAR(128),
    selected_capability VARCHAR(128),
    selected_remote_agent VARCHAR(128),
    risk_level VARCHAR(32) NOT NULL DEFAULT 'low',
    review_status VARCHAR(32) NOT NULL DEFAULT 'not_required',
    status VARCHAR(32) NOT NULL,
    sub_status VARCHAR(64),
    input_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
    output_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
    context_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
    retry_count INTEGER NOT NULL DEFAULT 0,
    error_code VARCHAR(64),
    error_message TEXT,
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE task_runs IS '任务运行表：存储工作流任务的主运行状态';

COMMENT ON COLUMN task_runs.output_snapshot IS '输出轻快照：仅包含 summary、slots、sql_preview、row_count、latency_ms、compare_target、group_by、governance_decision（简版）、timing_breakdown。重内容存储到 analytics_results 表';
```

---

## 5.14.1 analytics_results（V1 性能优化新增）

> 重内容单独存储表，与 task_runs.output_snapshot 轻快照配合使用。
> 目的是将 tables、insight_cards、report_blocks、chart_spec 等大 JSON 从 task_runs 拆出，
> 减少 task_runs 的大 JSON 写入与读取压力。

```sql
CREATE TABLE analytics_results (
    id BIGSERIAL PRIMARY KEY,
    run_id VARCHAR(128) NOT NULL UNIQUE REFERENCES task_runs(run_id),
    tables JSONB NOT NULL DEFAULT '[]'::jsonb,
    insight_cards JSONB NOT NULL DEFAULT '[]'::jsonb,
    report_blocks JSONB NOT NULL DEFAULT '[]'::jsonb,
    chart_spec JSONB NOT NULL DEFAULT '{}'::jsonb,
    masking_result JSONB NOT NULL DEFAULT '{}'::jsonb,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE analytics_results IS '经营分析重结果表：存储 tables、insight_cards、report_blocks、chart_spec 等大 JSON，与 task_runs.output_snapshot 轻快照配合';
COMMENT ON COLUMN analytics_results.run_id IS '关联 task_runs.run_id';
COMMENT ON COLUMN analytics_results.tables IS '结果表数据';
COMMENT ON COLUMN analytics_results.insight_cards IS '洞察卡片';
COMMENT ON COLUMN analytics_results.report_blocks IS '报告块';
COMMENT ON COLUMN analytics_results.chart_spec IS '图表描述';
COMMENT ON COLUMN analytics_results.masking_result IS '脱敏与字段可见性结果';
COMMENT ON COLUMN analytics_results.metadata IS '重结果扩展元数据，例如 sql_explain、audit_info、timing_breakdown';
```

---

## 5.15 human_reviews

```sql
CREATE TABLE human_reviews (
    id BIGSERIAL PRIMARY KEY,
    review_id VARCHAR(128) NOT NULL UNIQUE,
    run_id VARCHAR(128) NOT NULL,
    task_id VARCHAR(128) NOT NULL,
    agent_id VARCHAR(128),
    capability_id VARCHAR(128),
    risk_level VARCHAR(32) NOT NULL,
    review_status VARCHAR(32) NOT NULL,
    reviewer_id BIGINT REFERENCES users(id),
    review_comment TEXT,
    review_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    reviewed_at TIMESTAMPTZ
);

COMMENT ON TABLE human_reviews IS '人工审核表：存储高风险任务的审核任务与结果';

COMMENT ON COLUMN human_reviews.id IS '数据库内部主键';
COMMENT ON COLUMN human_reviews.review_id IS '审核任务唯一ID';
COMMENT ON COLUMN human_reviews.run_id IS '关联任务运行ID';
COMMENT ON COLUMN human_reviews.task_id IS '关联任务ID';
COMMENT ON COLUMN human_reviews.agent_id IS '关联专家ID';
COMMENT ON COLUMN human_reviews.capability_id IS '关联能力ID';
COMMENT ON COLUMN human_reviews.risk_level IS '风险等级';
COMMENT ON COLUMN human_reviews.review_status IS '审核状态';
COMMENT ON COLUMN human_reviews.reviewer_id IS '审核人用户ID';
COMMENT ON COLUMN human_reviews.review_comment IS '审核意见';
COMMENT ON COLUMN human_reviews.review_payload IS '审核上下文负载';
COMMENT ON COLUMN human_reviews.created_at IS '创建时间';
COMMENT ON COLUMN human_reviews.reviewed_at IS '审核完成时间';
```

---

## 5.16 mcp_calls

```sql
CREATE TABLE mcp_calls (
    id BIGSERIAL PRIMARY KEY,
    run_id VARCHAR(128) NOT NULL,
    task_id VARCHAR(128),
    mcp_server VARCHAR(128) NOT NULL,
    capability_name VARCHAR(128) NOT NULL,
    input_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    output_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    status VARCHAR(32) NOT NULL,
    latency_ms INTEGER,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE mcp_calls IS 'MCP 调用日志表：存储 MCP 工具调用记录';

COMMENT ON COLUMN mcp_calls.id IS '数据库内部主键';
COMMENT ON COLUMN mcp_calls.run_id IS '关联任务运行ID';
COMMENT ON COLUMN mcp_calls.task_id IS '关联任务ID';
COMMENT ON COLUMN mcp_calls.mcp_server IS 'MCP服务名称';
COMMENT ON COLUMN mcp_calls.capability_name IS 'MCP能力名称';
COMMENT ON COLUMN mcp_calls.input_json IS '调用输入';
COMMENT ON COLUMN mcp_calls.output_json IS '调用输出';
COMMENT ON COLUMN mcp_calls.status IS '调用状态';
COMMENT ON COLUMN mcp_calls.latency_ms IS '调用耗时（毫秒）';
COMMENT ON COLUMN mcp_calls.error_message IS '错误信息';
COMMENT ON COLUMN mcp_calls.created_at IS '创建时间';
```

---

## 5.17 sql_audits

```sql
CREATE TABLE sql_audits (
    id BIGSERIAL PRIMARY KEY,
    run_id VARCHAR(128) NOT NULL,
    user_id BIGINT REFERENCES users(id),
    db_type VARCHAR(32) NOT NULL,
    metric_scope VARCHAR(255),
    generated_sql TEXT NOT NULL,
    checked_sql TEXT,
    is_safe BOOLEAN NOT NULL DEFAULT FALSE,
    blocked_reason TEXT,
    execution_status VARCHAR(32) NOT NULL,
    row_count INTEGER,
    latency_ms INTEGER,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE sql_audits IS 'SQL 审计表：存储经营分析 SQL 生成、安全校验与执行审计记录';

COMMENT ON COLUMN sql_audits.id IS '数据库内部主键';
COMMENT ON COLUMN sql_audits.run_id IS '关联任务运行ID';
COMMENT ON COLUMN sql_audits.user_id IS '发起用户ID';
COMMENT ON COLUMN sql_audits.db_type IS '数据库类型，如 postgres、mysql';
COMMENT ON COLUMN sql_audits.metric_scope IS '指标或分析范围说明';
COMMENT ON COLUMN sql_audits.generated_sql IS '模型生成SQL';
COMMENT ON COLUMN sql_audits.checked_sql IS '安全校验后的SQL';
COMMENT ON COLUMN sql_audits.is_safe IS '是否通过安全检查';
COMMENT ON COLUMN sql_audits.blocked_reason IS '拦截原因';
COMMENT ON COLUMN sql_audits.execution_status IS '执行状态';
COMMENT ON COLUMN sql_audits.row_count IS '返回行数';
COMMENT ON COLUMN sql_audits.latency_ms IS '查询耗时（毫秒）';
COMMENT ON COLUMN sql_audits.metadata IS '扩展信息';
COMMENT ON COLUMN sql_audits.created_at IS '创建时间';
```

---

## 6. SQLAlchemy ORM 示例代码

以下代码为工程风格示例，可作为项目起步模板。

### 6.1 Base 与公共 Mixin 示例

```python
from datetime import datetime
from sqlalchemy import DateTime, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        comment="创建时间",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
        comment="更新时间",
    )
```

### 6.2 Conversation 模型示例

```python
import uuid
from sqlalchemy import BigInteger, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.database.base import Base
from core.database.mixins import TimestampMixin


class Conversation(Base, TimestampMixin):
    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True, comment="数据库内部主键")
    conversation_uuid: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), default=uuid.uuid4, unique=True, nullable=False, comment="对外稳定会话标识")
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True, comment="会话所属用户ID")
    title: Mapped[str | None] = mapped_column(String(255), comment="会话标题")
    current_route: Mapped[str | None] = mapped_column(String(64), comment="当前业务路由")
    current_status: Mapped[str] = mapped_column(String(32), default="active", nullable=False, comment="会话状态")
    last_run_id: Mapped[str | None] = mapped_column(String(128), comment="最近一次任务运行ID")
    metadata: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False, comment="会话扩展元数据")

    messages = relationship("ConversationMessage", back_populates="conversation", cascade="all, delete-orphan")
    memory = relationship("ConversationMemory", back_populates="conversation", uselist=False, cascade="all, delete-orphan")
```

### 6.3 TaskRun 模型示例

```python
class TaskRun(Base, TimestampMixin):
    __tablename__ = "task_runs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True, comment="数据库内部主键")
    run_id: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True, comment="任务运行唯一ID")
    task_id: Mapped[str] = mapped_column(String(128), nullable=False, comment="任务ID")
    parent_task_id: Mapped[str | None] = mapped_column(String(128), comment="父任务ID")
    conversation_id: Mapped[int | None] = mapped_column(ForeignKey("conversations.id"), index=True, comment="所属会话ID")
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True, comment="发起用户ID")
    trace_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True, comment="Trace标识")
    task_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True, comment="任务类型")
    route: Mapped[str | None] = mapped_column(String(64), index=True, comment="路由结果")
    selected_agent: Mapped[str | None] = mapped_column(String(128), comment="选中的业务专家")
    risk_level: Mapped[str] = mapped_column(String(32), default="low", nullable=False, comment="风险等级")
    review_status: Mapped[str] = mapped_column(String(32), default="not_required", nullable=False, comment="审核状态")
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True, comment="任务主状态")
    sub_status: Mapped[str | None] = mapped_column(String(64), comment="任务子状态")
    input_snapshot: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False, comment="输入快照")
    output_snapshot: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False, comment="输出轻快照")
    context_snapshot: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False, comment="上下文快照")
```

---

## 7. Repository 示例代码

### 7.1 Repository 设计建议

不建议业务代码到处直接使用 ORM Session 拼查询。  
建议对关键领域建立 Repository：

- ConversationRepository
- TaskRunRepository
- ReviewRepository
- DocumentRepository
- AuditRepository

### 7.2 ConversationRepository 示例

```python
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.database.models.conversation import Conversation


class ConversationRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_by_uuid(self, conversation_uuid: str) -> Conversation | None:
        stmt = select(Conversation).where(Conversation.conversation_uuid == conversation_uuid)
        return self.session.scalar(stmt)

    def list_by_user(self, user_id: int, limit: int = 20) -> list[Conversation]:
        stmt = (
            select(Conversation)
            .where(Conversation.user_id == user_id)
            .order_by(Conversation.updated_at.desc())
            .limit(limit)
        )
        return list(self.session.scalars(stmt))
```

---

## 8. Alembic 初始迁移脚本示例

### 8.1 建议的迁移分批

#### 第一批
- users
- departments
- roles
- permissions
- role_permissions
- knowledge_bases
- documents
- document_chunks

#### 第二批
- conversations
- conversation_messages
- conversation_memory
- slot_snapshots
- clarification_events

#### 第三批
- agent_registry
- capability_registry
- task_runs
- agent_runs
- workflow_events

#### 第四批
- human_reviews
- review_events
- policy_decision_logs
- retrieval_logs
- llm_calls
- mcp_calls
- a2a_delegations
- sql_audits

#### 第五批
- evaluation_tasks
- evaluation_results
- user_feedback

### 8.2 创建 conversations 表示例

```python
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0002_create_conversations"
down_revision = "0001_create_iam_and_knowledge"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "conversations",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True, comment="数据库内部主键"),
        sa.Column("conversation_uuid", postgresql.UUID(as_uuid=True), nullable=False, unique=True, comment="对外稳定会话标识"),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=False, comment="会话所属用户ID"),
        sa.Column("title", sa.String(length=255), nullable=True, comment="会话标题"),
        sa.Column("current_route", sa.String(length=64), nullable=True, comment="当前业务路由"),
        sa.Column("current_status", sa.String(length=32), nullable=False, server_default="active", comment="会话状态"),
        sa.Column("last_run_id", sa.String(length=128), nullable=True, comment="最近一次任务运行ID"),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb"), comment="会话扩展元数据"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False, comment="创建时间"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False, comment="更新时间"),
    )
    op.create_index("idx_conversations_user_id", "conversations", ["user_id"])
    op.create_index("idx_conversations_updated_at", "conversations", ["updated_at"])


def downgrade():
    op.drop_index("idx_conversations_updated_at", table_name="conversations")
    op.drop_index("idx_conversations_user_id", table_name="conversations")
    op.drop_table("conversations")
```

### 8.3 Alembic 工程要求

- 所有建表、加字段、加索引都走迁移；
- 不允许手工改生产库 schema；
- 自动生成后必须人工复查；
- 字段注释和索引定义尽量写进迁移脚本。

---

## 9. PostgreSQL 索引与分区的实施级 SQL

这一章是重点展开部分。

### 9.1 索引实施原则

#### B-Tree 适合什么
适合：

- 等值查询
- 范围查询
- 排序字段
- 业务唯一键
- 外键关联字段

#### GIN 适合什么
适合：

- JSONB 包含查询
- 数组字段
- 全文检索场景

#### 不要乱建索引
索引不是越多越好。  
问题在于：

- 写入会变慢；
- 更新会变慢；
- 占空间；
- 真正没命中的索引反而增加维护成本。

所以原则是：

> 先围绕高频查询路径建索引，再根据慢查询持续补充。

---

### 9.2 高频查询索引的实施级 SQL

#### 会话列表

场景：按用户查询最近会话。

```sql
CREATE INDEX idx_conversations_user_id_updated_at
ON conversations (user_id, updated_at DESC);
```

说明：

- `user_id` 用于过滤；
- `updated_at DESC` 用于按最近更新时间排序；
- 这是会话列表接口的核心索引。

#### 会话消息回放

场景：打开一个会话时，按时间顺序读取消息。

```sql
CREATE INDEX idx_conversation_messages_conversation_id_created_at
ON conversation_messages (conversation_id, created_at);
```

说明：

- `conversation_id` 用于过滤；
- `created_at` 用于时间排序；
- 这个索引必须有，否则消息多时会明显变慢。

#### 根据 run_id 恢复任务

```sql
CREATE UNIQUE INDEX idx_task_runs_run_id
ON task_runs (run_id);

CREATE UNIQUE INDEX idx_slot_snapshots_run_id
ON slot_snapshots (run_id);
```

说明：

- 恢复执行是工作流核心能力；
- `run_id` 必须唯一并可快速定位；
- `task_runs + slot_snapshots` 是恢复链路的核心组合。

#### 待审核任务列表

```sql
CREATE INDEX idx_human_reviews_reviewer_id_status_created_at
ON human_reviews (reviewer_id, review_status, created_at DESC);
```

说明：

- 审核人查看自己的待办审核任务；
- `reviewer_id + review_status` 是过滤条件；
- `created_at DESC` 是排序条件。

#### 澄清问题恢复

```sql
CREATE INDEX idx_clarification_events_run_id_status
ON clarification_events (run_id, status);

CREATE INDEX idx_clarification_events_conversation_id_created_at
ON clarification_events (conversation_id, created_at DESC);
```

说明：

- 一个用于按 run_id 恢复；
- 一个用于按 conversation 展示澄清历史。

#### SQL 审计检索

```sql
CREATE INDEX idx_sql_audits_run_id
ON sql_audits (run_id);

CREATE INDEX idx_sql_audits_user_id_created_at
ON sql_audits (user_id, created_at DESC);
```

说明：

- 运维 / 安全排查常按 `run_id` 查；
- 也常按用户维度看最近 SQL 审计。

---

### 9.3 JSONB GIN 索引的实施级 SQL

#### documents.metadata

```sql
CREATE INDEX gin_documents_metadata
ON documents
USING GIN (metadata);
```

适用场景：

- 根据 metadata 中某些 key 做包含查询；
- 如文档来源、标签、业务属性等。

#### documents.access_scope

```sql
CREATE INDEX gin_documents_access_scope
ON documents
USING GIN (access_scope);
```

适用场景：

- 文档访问范围基于 JSONB 存储；
- 需要按角色、部门、业务域等做过滤。

#### conversation_memory.short_term_memory

```sql
CREATE INDEX gin_conversation_memory_short_term_memory
ON conversation_memory
USING GIN (short_term_memory);
```

适用场景：

- 后续若需要基于记忆字段做查询；
- 但这类索引要谨慎，只有确认确实有查询需求时再建。

#### 使用提醒

GIN 索引不要滥用，特别是：

- 高频写入表；
- 大 JSONB 字段；
- 几乎不查询的字段。

---

### 9.4 唯一索引与约束 SQL

```sql
CREATE UNIQUE INDEX uq_users_user_uuid
ON users (user_uuid);

CREATE UNIQUE INDEX uq_users_username
ON users (username);

CREATE UNIQUE INDEX uq_documents_document_uuid
ON documents (document_uuid);

CREATE UNIQUE INDEX uq_conversations_conversation_uuid
ON conversations (conversation_uuid);

CREATE UNIQUE INDEX uq_conversation_messages_message_uuid
ON conversation_messages (message_uuid);

CREATE UNIQUE INDEX uq_clarification_events_clarification_uuid
ON clarification_events (clarification_uuid);
```

组合唯一约束示例：

```sql
CREATE UNIQUE INDEX uq_role_permissions_role_permission
ON role_permissions (role_id, permission_id);

CREATE UNIQUE INDEX uq_document_chunks_document_chunk_index
ON document_chunks (document_id, chunk_index);
```

---

### 9.5 分区为什么要做

分区主要解决这些问题：

- 大表不断增长；
- 查询热点通常集中在最近数据；
- 老数据不该影响新数据性能；
- 归档和清理更方便。

你这个项目里，最容易变大的表是：

- conversation_messages
- workflow_events
- llm_calls
- mcp_calls
- sql_audits
- retrieval_logs

所以分区优先考虑这些表。

---

### 9.6 分区实施建议

#### 第一阶段
先不强制上分区，但建表时就要考虑：

- 是否会成为高增长表；
- 是否按时间查询为主；
- 是否适合按月分区。

#### 第二阶段优先分区表
建议顺序：

1. conversation_messages
2. workflow_events
3. llm_calls
4. mcp_calls
5. sql_audits

---

### 9.7 conversation_messages 按月分区实施级 SQL

#### 第一步：建立分区主表

```sql
CREATE TABLE conversation_messages (
    id BIGSERIAL,
    conversation_id BIGINT NOT NULL,
    message_uuid UUID NOT NULL,
    role VARCHAR(32) NOT NULL,
    message_type VARCHAR(32) NOT NULL DEFAULT 'text',
    content TEXT NOT NULL,
    structured_content JSONB NOT NULL DEFAULT '{}'::jsonb,
    related_run_id VARCHAR(128),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (id, created_at)
) PARTITION BY RANGE (created_at);

COMMENT ON TABLE conversation_messages IS '会话消息表：按时间范围分区';
COMMENT ON COLUMN conversation_messages.id IS '数据库内部主键';
COMMENT ON COLUMN conversation_messages.conversation_id IS '所属会话ID';
COMMENT ON COLUMN conversation_messages.message_uuid IS '对外稳定消息标识';
COMMENT ON COLUMN conversation_messages.role IS '消息角色';
COMMENT ON COLUMN conversation_messages.message_type IS '消息类型';
COMMENT ON COLUMN conversation_messages.content IS '消息原文';
COMMENT ON COLUMN conversation_messages.structured_content IS '结构化消息内容';
COMMENT ON COLUMN conversation_messages.related_run_id IS '关联任务运行ID';
COMMENT ON COLUMN conversation_messages.created_at IS '创建时间';
```

#### 第二步：创建月分区

```sql
CREATE TABLE conversation_messages_2026_04
PARTITION OF conversation_messages
FOR VALUES FROM ('2026-04-01') TO ('2026-05-01');

CREATE TABLE conversation_messages_2026_05
PARTITION OF conversation_messages
FOR VALUES FROM ('2026-05-01') TO ('2026-06-01');

CREATE TABLE conversation_messages_2026_06
PARTITION OF conversation_messages
FOR VALUES FROM ('2026-06-01') TO ('2026-07-01');
```

#### 第三步：对子分区建索引

```sql
CREATE INDEX idx_conversation_messages_2026_04_conversation_id_created_at
ON conversation_messages_2026_04 (conversation_id, created_at);

CREATE INDEX idx_conversation_messages_2026_05_conversation_id_created_at
ON conversation_messages_2026_05 (conversation_id, created_at);

CREATE INDEX idx_conversation_messages_2026_06_conversation_id_created_at
ON conversation_messages_2026_06 (conversation_id, created_at);
```

说明：

- PostgreSQL 分区表上的索引策略要特别注意；
- 有些版本和场景下，仍然需要对子分区明确建索引；
- 不要以为父表建了索引就永远够了，实际要结合版本验证。

---

### 9.8 sql_audits 按月分区实施思路

如果 SQL 审计增长很快，也可以按月分区：

```sql
CREATE TABLE sql_audits (
    id BIGSERIAL,
    run_id VARCHAR(128) NOT NULL,
    user_id BIGINT,
    db_type VARCHAR(32) NOT NULL,
    metric_scope VARCHAR(255),
    generated_sql TEXT NOT NULL,
    checked_sql TEXT,
    is_safe BOOLEAN NOT NULL DEFAULT FALSE,
    blocked_reason TEXT,
    execution_status VARCHAR(32) NOT NULL,
    row_count INTEGER,
    latency_ms INTEGER,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (id, created_at)
) PARTITION BY RANGE (created_at);
```

然后按月建：

```sql
CREATE TABLE sql_audits_2026_04
PARTITION OF sql_audits
FOR VALUES FROM ('2026-04-01') TO ('2026-05-01');
```

适合场景：

- SQL 审计量大；
- 安全审计保留周期长；
- 最近排障只查近几个月。

---

### 9.9 分区运维建议

分区不是只建表，还要配套运维。

建议至少有这些自动化能力：

- 自动创建下个月分区；
- 自动检查是否缺分区；
- 自动给新分区建索引；
- 自动归档旧分区；
- 自动删除符合清理策略的旧分区。

否则很容易出现：

- 到了新月份没有分区，写入失败；
- 分区建了但索引没建，性能异常。

---

### 9.10 索引与分区的常见误区

#### 误区 1：索引越多越好
错。索引会拖慢写入和更新。

#### 误区 2：所有 JSONB 都要 GIN
错。只有明确要查询的 JSONB 才建 GIN。

#### 误区 3：表一大就必须立刻分区
错。第一阶段先监控增长趋势，按真实数据量上分区。

#### 误区 4：父表建了索引就不用管分区索引
不一定。要根据 PostgreSQL 版本和实际执行计划确认。

---

## 10. 典型查询 SQL 优化示例

### 10.1 会话列表查询

```sql
SELECT
    id,
    conversation_uuid,
    title,
    current_route,
    current_status,
    last_run_id,
    updated_at
FROM conversations
WHERE user_id = :user_id
ORDER BY updated_at DESC
LIMIT 20;
```

优化点：

- 配合 `(user_id, updated_at DESC)` 复合索引；
- 不要在列表页回表拿大 JSONB；
- 不要联表查全量 message。

### 10.2 待审核任务列表

```sql
SELECT
    review_id,
    run_id,
    task_id,
    risk_level,
    review_status,
    reviewer_id,
    created_at
FROM human_reviews
WHERE reviewer_id = :reviewer_id
  AND review_status = 'pending'
ORDER BY created_at DESC
LIMIT 50;
```

优化点：

- 配合 `(reviewer_id, review_status, created_at DESC)` 索引；
- 高并发时分页优先 keyset pagination。

### 10.3 根据 run_id 恢复任务

```sql
SELECT
    tr.run_id,
    tr.status,
    tr.sub_status,
    tr.context_snapshot,
    ss.collected_slots,
    ss.missing_slots,
    ss.resume_step
FROM task_runs tr
LEFT JOIN slot_snapshots ss ON tr.run_id = ss.run_id
WHERE tr.run_id = :run_id;
```

优化点：

- `task_runs.run_id` 唯一索引；
- `slot_snapshots.run_id` 唯一索引；
- 这是恢复执行核心 SQL，必须极稳。

---

## 11. Celery 归档任务示例

### 11.1 归档任务设计原则

- 必须幂等
- 必须可重试
- 必须可审计
- 不允许影响在线核心查询

### 11.2 示例：归档旧会话消息

```python
from celery import shared_task
from sqlalchemy import text

from core.database.session import SessionLocal


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, max_retries=3)
def archive_old_conversation_messages(self, before_ts: str) -> dict:
    session = SessionLocal()
    try:
        insert_sql = text(
            "INSERT INTO conversation_messages_archive "
            "SELECT * FROM conversation_messages "
            "WHERE created_at < :before_ts"
        )
        delete_sql = text(
            "DELETE FROM conversation_messages "
            "WHERE created_at < :before_ts"
        )

        inserted = session.execute(insert_sql, {"before_ts": before_ts})
        session.execute(delete_sql, {"before_ts": before_ts})
        session.commit()

        return {
            "status": "succeeded",
            "before_ts": before_ts,
            "moved_rows": inserted.rowcount,
        }
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
```

### 11.3 建议的归档任务类型

- 会话消息归档任务
- Workflow 事件归档任务
- LLM 调用日志归档任务
- MCP / SQL 审计归档任务
- Review 相关历史数据归档任务
- 过期 clarification 清理任务

---

## 12. 当前版本说明

本文档已经覆盖：

- 所有核心表的中文注释写法示例
- SQLAlchemy ORM 示例代码
- Repository 示例代码
- Alembic 初始迁移脚本示例
- PostgreSQL 索引与分区的实施级 SQL
- 典型查询 SQL 优化示例
- Celery 归档任务示例

这一版已经可以直接作为后续：

- 建模
- 迁移
- 索引实施
- 分区实施
- 查询优化
- 归档设计

的依据。
