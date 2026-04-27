-- schema.sql
-- 新疆能源集团知识与生产经营智能 Agent 平台
-- PostgreSQL 初始 Schema 草案
-- 说明：
-- 1. 本文件聚焦平台元数据库；
-- 2. 所有核心表与字段均附中文注释；
-- 3. 包含基础索引示例；
-- 4. 不包含 Milvus / 对象存储 / 外部业务库表。

BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- =========================================================
-- 1. IAM：身份与权限
-- =========================================================

CREATE TABLE users (
    id BIGSERIAL PRIMARY KEY,
    user_uuid UUID NOT NULL DEFAULT gen_random_uuid() UNIQUE,
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

ALTER TABLE users
ADD CONSTRAINT fk_users_department_id
FOREIGN KEY (department_id) REFERENCES departments(id);

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

-- =========================================================
-- 2. Knowledge：知识库与文档
-- =========================================================

CREATE TABLE knowledge_bases (
    id BIGSERIAL PRIMARY KEY,
    kb_uuid UUID NOT NULL DEFAULT gen_random_uuid() UNIQUE,
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
COMMENT ON COLUMN knowledge_bases.business_domain IS '业务域';
COMMENT ON COLUMN knowledge_bases.description IS '知识库说明';
COMMENT ON COLUMN knowledge_bases.status IS '知识库状态';
COMMENT ON COLUMN knowledge_bases.metadata IS '扩展元数据';
COMMENT ON COLUMN knowledge_bases.created_at IS '创建时间';
COMMENT ON COLUMN knowledge_bases.updated_at IS '更新时间';

CREATE TABLE documents (
    id BIGSERIAL PRIMARY KEY,
    document_uuid UUID NOT NULL DEFAULT gen_random_uuid() UNIQUE,
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
COMMENT ON COLUMN documents.file_type IS '文件类型';
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

CREATE TABLE document_chunks (
    id BIGSERIAL PRIMARY KEY,
    chunk_uuid UUID NOT NULL DEFAULT gen_random_uuid() UNIQUE,
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

-- =========================================================
-- 3. Conversation：多轮对话与记忆
-- =========================================================

CREATE TABLE conversations (
    id BIGSERIAL PRIMARY KEY,
    conversation_uuid UUID NOT NULL DEFAULT gen_random_uuid() UNIQUE,
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

CREATE TABLE conversation_messages (
    id BIGSERIAL PRIMARY KEY,
    conversation_id BIGINT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    message_uuid UUID NOT NULL DEFAULT gen_random_uuid() UNIQUE,
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
COMMENT ON COLUMN conversation_messages.role IS '消息角色';
COMMENT ON COLUMN conversation_messages.message_type IS '消息类型';
COMMENT ON COLUMN conversation_messages.content IS '消息原文';
COMMENT ON COLUMN conversation_messages.structured_content IS '结构化内容';
COMMENT ON COLUMN conversation_messages.related_run_id IS '关联任务运行ID';
COMMENT ON COLUMN conversation_messages.created_at IS '创建时间';

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
COMMENT ON COLUMN conversation_memory.last_primary_object IS '最近主对象';
COMMENT ON COLUMN conversation_memory.last_metric IS '最近分析指标';
COMMENT ON COLUMN conversation_memory.last_time_range IS '最近时间范围';
COMMENT ON COLUMN conversation_memory.last_org_scope IS '最近组织范围';
COMMENT ON COLUMN conversation_memory.last_kb_scope IS '最近知识库范围';
COMMENT ON COLUMN conversation_memory.last_report_id IS '最近报告ID';
COMMENT ON COLUMN conversation_memory.last_contract_id IS '最近合同ID';
COMMENT ON COLUMN conversation_memory.short_term_memory IS '短期会话记忆快照';
COMMENT ON COLUMN conversation_memory.updated_at IS '更新时间';

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
COMMENT ON COLUMN slot_snapshots.awaiting_user_input IS '是否等待用户补充信息';
COMMENT ON COLUMN slot_snapshots.resume_step IS '恢复执行入口步骤';
COMMENT ON COLUMN slot_snapshots.updated_at IS '更新时间';

CREATE TABLE clarification_events (
    id BIGSERIAL PRIMARY KEY,
    clarification_uuid UUID NOT NULL DEFAULT gen_random_uuid() UNIQUE,
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

-- =========================================================
-- 4. Runtime：运行时
-- =========================================================

CREATE TABLE agent_registry (
    id BIGSERIAL PRIMARY KEY,
    agent_id VARCHAR(128) NOT NULL UNIQUE,
    name VARCHAR(255) NOT NULL,
    agent_type VARCHAR(32) NOT NULL,
    protocol VARCHAR(32) NOT NULL,
    endpoint TEXT,
    owner_team VARCHAR(128),
    status VARCHAR(32) NOT NULL DEFAULT 'active',
    health_status VARCHAR(32) NOT NULL DEFAULT 'unknown',
    agent_card_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
COMMENT ON TABLE agent_registry IS 'Agent 注册表：存储业务专家或远程智能体信息';

CREATE TABLE capability_registry (
    id BIGSERIAL PRIMARY KEY,
    capability_id VARCHAR(128) NOT NULL UNIQUE,
    capability_type VARCHAR(32) NOT NULL,
    name VARCHAR(255) NOT NULL,
    protocol VARCHAR(32) NOT NULL,
    description TEXT,
    required_permission VARCHAR(128),
    risk_level VARCHAR(32) NOT NULL DEFAULT 'low',
    timeout_seconds INTEGER NOT NULL DEFAULT 30,
    audit_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    human_review_required BOOLEAN NOT NULL DEFAULT FALSE,
    owner VARCHAR(128),
    input_schema JSONB NOT NULL DEFAULT '{}'::jsonb,
    output_schema JSONB NOT NULL DEFAULT '{}'::jsonb,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
COMMENT ON TABLE capability_registry IS '能力注册表：存储本地工具、MCP 工具、远程能力元数据';

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

CREATE TABLE agent_runs (
    id BIGSERIAL PRIMARY KEY,
    run_id VARCHAR(128) NOT NULL,
    agent_id VARCHAR(128) NOT NULL,
    input_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    output_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    status VARCHAR(32) NOT NULL,
    latency_ms INTEGER,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
COMMENT ON TABLE agent_runs IS '专家运行表：存储单个专家在某次任务中的运行记录';

CREATE TABLE workflow_events (
    id BIGSERIAL PRIMARY KEY,
    run_id VARCHAR(128) NOT NULL,
    event_type VARCHAR(64) NOT NULL,
    step_name VARCHAR(128),
    from_status VARCHAR(32),
    to_status VARCHAR(32),
    detail_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
COMMENT ON TABLE workflow_events IS '工作流事件表：记录状态迁移与关键事件';

-- =========================================================
-- 5. Governance / Logs：审核与审计
-- =========================================================

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

CREATE TABLE review_events (
    id BIGSERIAL PRIMARY KEY,
    run_id VARCHAR(128) NOT NULL,
    task_id VARCHAR(128) NOT NULL,
    review_id VARCHAR(128) NOT NULL,
    hook_point VARCHAR(64) NOT NULL,
    event_type VARCHAR(64) NOT NULL,
    detail_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
COMMENT ON TABLE review_events IS '审核事件表：记录审核过程中的关键事件';

CREATE TABLE policy_decision_logs (
    id BIGSERIAL PRIMARY KEY,
    run_id VARCHAR(128),
    task_id VARCHAR(128),
    subject_type VARCHAR(32) NOT NULL,
    subject_id VARCHAR(128) NOT NULL,
    target_type VARCHAR(32) NOT NULL,
    target_id VARCHAR(128) NOT NULL,
    decision VARCHAR(32) NOT NULL,
    matched_policy VARCHAR(255),
    reason TEXT,
    detail_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
COMMENT ON TABLE policy_decision_logs IS '策略决策日志表：记录权限与风控决策';

CREATE TABLE retrieval_logs (
    id BIGSERIAL PRIMARY KEY,
    run_id VARCHAR(128) NOT NULL,
    query_text TEXT NOT NULL,
    rewritten_queries JSONB NOT NULL DEFAULT '[]'::jsonb,
    knowledge_base_id BIGINT REFERENCES knowledge_bases(id),
    document_id BIGINT REFERENCES documents(id),
    chunk_id BIGINT REFERENCES document_chunks(id),
    score DOUBLE PRECISION,
    rank_no INTEGER,
    content_preview TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
COMMENT ON TABLE retrieval_logs IS '检索日志表：记录 RAG 检索输入与候选结果';

CREATE TABLE llm_calls (
    id BIGSERIAL PRIMARY KEY,
    run_id VARCHAR(128),
    model_name VARCHAR(128) NOT NULL,
    prompt_template VARCHAR(128),
    stage_name VARCHAR(128),
    input_tokens INTEGER,
    output_tokens INTEGER,
    latency_ms INTEGER,
    status VARCHAR(32) NOT NULL,
    error_message TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
COMMENT ON TABLE llm_calls IS '大模型调用日志表：记录 LLM 调用情况';

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

CREATE TABLE a2a_delegations (
    id BIGSERIAL PRIMARY KEY,
    run_id VARCHAR(128) NOT NULL,
    task_id VARCHAR(128) NOT NULL,
    parent_task_id VARCHAR(128),
    remote_agent_id VARCHAR(128) NOT NULL,
    task_envelope_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    result_contract_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    status VARCHAR(32) NOT NULL,
    latency_ms INTEGER,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
COMMENT ON TABLE a2a_delegations IS 'A2A 委托日志表：记录远程专家委托调用';

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

-- =========================================================
-- 6. Evaluation：评估与反馈
-- =========================================================

CREATE TABLE evaluation_tasks (
    id BIGSERIAL PRIMARY KEY,
    eval_task_id VARCHAR(128) NOT NULL UNIQUE,
    dataset_name VARCHAR(255),
    evaluation_type VARCHAR(64) NOT NULL,
    status VARCHAR(32) NOT NULL,
    metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
    result_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_by BIGINT REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);
COMMENT ON TABLE evaluation_tasks IS '评估任务表：记录评估任务的元信息与总体结果';

CREATE TABLE evaluation_results (
    id BIGSERIAL PRIMARY KEY,
    eval_task_id VARCHAR(128) NOT NULL,
    run_id VARCHAR(128),
    sample_key VARCHAR(255),
    actual_answer TEXT,
    actual_citations JSONB NOT NULL DEFAULT '[]'::jsonb,
    score_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
COMMENT ON TABLE evaluation_results IS '评估结果表：记录单样本评估结果';

CREATE TABLE user_feedback (
    id BIGSERIAL PRIMARY KEY,
    run_id VARCHAR(128) NOT NULL,
    user_id BIGINT REFERENCES users(id),
    rating SMALLINT,
    feedback_text TEXT,
    feedback_type VARCHAR(32),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
COMMENT ON TABLE user_feedback IS '用户反馈表：记录用户评分与文字反馈';

-- =========================================================
-- 7. 基础索引
-- =========================================================

CREATE INDEX idx_users_department_id ON users(department_id);
CREATE INDEX idx_documents_knowledge_base_id ON documents(knowledge_base_id);
CREATE INDEX idx_documents_department_id ON documents(department_id);
CREATE INDEX idx_documents_parse_status ON documents(parse_status);
CREATE INDEX idx_documents_index_status ON documents(index_status);
CREATE INDEX idx_document_chunks_document_id ON document_chunks(document_id);
CREATE INDEX idx_document_chunks_knowledge_base_id ON document_chunks(knowledge_base_id);

CREATE INDEX idx_conversations_user_id_updated_at ON conversations(user_id, updated_at DESC);
CREATE INDEX idx_conversation_messages_conversation_id_created_at ON conversation_messages(conversation_id, created_at);
CREATE INDEX idx_conversation_messages_related_run_id ON conversation_messages(related_run_id);
CREATE UNIQUE INDEX idx_slot_snapshots_run_id ON slot_snapshots(run_id);
CREATE INDEX idx_clarification_events_run_id_status ON clarification_events(run_id, status);
CREATE INDEX idx_clarification_events_conversation_id_created_at ON clarification_events(conversation_id, created_at DESC);

CREATE UNIQUE INDEX idx_task_runs_run_id ON task_runs(run_id);
CREATE INDEX idx_task_runs_user_id_created_at ON task_runs(user_id, created_at DESC);
CREATE INDEX idx_task_runs_status_route ON task_runs(status, route);
CREATE INDEX idx_workflow_events_run_id_created_at ON workflow_events(run_id, created_at);

CREATE INDEX idx_human_reviews_reviewer_id_status_created_at ON human_reviews(reviewer_id, review_status, created_at DESC);
CREATE INDEX idx_retrieval_logs_run_id ON retrieval_logs(run_id);
CREATE INDEX idx_llm_calls_run_id ON llm_calls(run_id);
CREATE INDEX idx_mcp_calls_run_id ON mcp_calls(run_id);
CREATE INDEX idx_sql_audits_run_id ON sql_audits(run_id);
CREATE INDEX idx_sql_audits_user_id_created_at ON sql_audits(user_id, created_at DESC);

CREATE INDEX gin_documents_metadata ON documents USING GIN(metadata);
CREATE INDEX gin_documents_access_scope ON documents USING GIN(access_scope);

COMMIT;

-- =========================================================
-- 8. 分区实施参考 SQL
-- =========================================================
-- 说明：
-- 下面不是必须立即执行的初始表，而是高增长表后续升级为分区表的实施参考。
--
-- 典型分区目标：
-- 1. conversation_messages
-- 2. workflow_events
-- 3. llm_calls
-- 4. mcp_calls
-- 5. sql_audits

-- 8.1 conversation_messages 按月分区参考
--
-- CREATE TABLE conversation_messages (
--     id BIGSERIAL,
--     conversation_id BIGINT NOT NULL,
--     message_uuid UUID NOT NULL,
--     role VARCHAR(32) NOT NULL,
--     message_type VARCHAR(32) NOT NULL DEFAULT 'text',
--     content TEXT NOT NULL,
--     structured_content JSONB NOT NULL DEFAULT '{}'::jsonb,
--     related_run_id VARCHAR(128),
--     created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
--     PRIMARY KEY (id, created_at)
-- ) PARTITION BY RANGE (created_at);
--
-- COMMENT ON TABLE conversation_messages IS '会话消息表：按时间范围分区';
--
-- CREATE TABLE conversation_messages_2026_04
-- PARTITION OF conversation_messages
-- FOR VALUES FROM ('2026-04-01') TO ('2026-05-01');
--
-- CREATE INDEX idx_conversation_messages_2026_04_conversation_id_created_at
-- ON conversation_messages_2026_04 (conversation_id, created_at);

-- 8.2 sql_audits 按月分区参考
--
-- CREATE TABLE sql_audits (
--     id BIGSERIAL,
--     run_id VARCHAR(128) NOT NULL,
--     user_id BIGINT,
--     db_type VARCHAR(32) NOT NULL,
--     metric_scope VARCHAR(255),
--     generated_sql TEXT NOT NULL,
--     checked_sql TEXT,
--     is_safe BOOLEAN NOT NULL DEFAULT FALSE,
--     blocked_reason TEXT,
--     execution_status VARCHAR(32) NOT NULL,
--     row_count INTEGER,
--     latency_ms INTEGER,
--     metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
--     created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
--     PRIMARY KEY (id, created_at)
-- ) PARTITION BY RANGE (created_at);
--
-- CREATE TABLE sql_audits_2026_04
-- PARTITION OF sql_audits
-- FOR VALUES FROM ('2026-04-01') TO ('2026-05-01');

