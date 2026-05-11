"""审计日志模块。

该模块提供企业级 Agent 平台的审计能力，用于记录安全和合规相关事件。

什么是审计日志？
---------------
审计日志是系统安全的核心组成部分，记录所有与安全、合规相关的操作。

审计 vs 普通日志的区别：
| 维度 | 普通日志 | 审计日志 |
|------|----------|----------|
| 目的 | 调试、监控 | 合规、安全 |
| 内容 | 技术细节 | 业务操作 |
| 保存 | 短期 | 长期（通常1-5年）|
| 访问 | 开发运维 | 安全合规团队 |
| 格式 | 灵活 | 标准化 |

为什么需要审计日志？
-------------------
1. **合规要求**：等保、GDPR、SOX 等法规要求
2. **安全分析**：追踪异常行为、定位安全事件
3. **问题追溯**：发生问题时能还原操作历史
4. **责任认定**：明确操作人、时间、内容

核心设计：
---------
1. 事件类型化：每类操作有明确的类型
2. 风险分级：区分低/中/高/极高风险
3. 完整上下文：trace_id、user_id、时间戳等
4. 可扩展存储：支持多种后端

覆盖的事件类型：
---------------
1. Agent 执行（请求、响应、错误）
2. 工具调用（Tool 权限、调用结果）
3. 数据访问（RAG 检索、SQL 查询）
4. 高风险操作（人工复核、敏感操作）
5. 安全事件（认证、授权）

使用示例：
    from core.observability.audit import audit_log, AuditEventType, RiskLevel

    # 记录 Agent 请求
    audit_log.log_agent_request(
        action="rag.query",
        trace_id="tr_abc123",
        user_id="user_001",
        success=True,
    )

    # 记录高风险操作
    audit_log.log(
        event_type=AuditEventType.RISK_OPERATION,
        action="contract.approve",
        trace_id="tr_abc123",
        risk_level=RiskLevel.HIGH,
        metadata={"contract_id": "ct_001", "amount": 1000000}
    )
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional
from uuid import uuid4

from core.observability.context import (
    get_trace_id,
    get_run_id,
    get_user_id,
    get_conversation_id,
)


# ============================================================================
# 审计事件类型枚举
# ============================================================================

class AuditEventType(Enum):
    """
    审计事件类型枚举

    覆盖 Agent 平台的所有关键操作类型

    分类说明：
    - AGENT_*: Agent 执行相关
    - TOOL_*: 工具调用相关
    - DATA_*: 数据访问相关
    - REVIEW_*: 人工复核相关
    - AUTH_*: 认证授权相关
    """
    # ==================== Agent 执行 ====================
    # Agent 收到请求
    AGENT_REQUEST = "agent.request"
    # Agent 返回响应
    AGENT_RESPONSE = "agent.response"
    # Agent 执行错误
    AGENT_ERROR = "agent.error"

    # ==================== 工具调用 ====================
    # 工具被调用
    TOOL_INVOCATION = "tool.invocation"
    # 工具返回结果
    TOOL_RESULT = "tool.result"
    # 工具调用错误
    TOOL_ERROR = "tool.error"

    # ==================== 数据访问 ====================
    # 数据查询（如 SQL）
    DATA_QUERY = "data.query"
    # 文档检索（RAG）
    DATA_RETRIEVAL = "data.retrieval"
    # 数据导出
    DATA_EXPORT = "data.export"

    # ==================== 高风险操作 ====================
    # 高风险操作执行
    RISK_OPERATION = "risk.operation"
    # 人工复核请求
    REVIEW_REQUEST = "review.request"
    # 人工复核通过
    REVIEW_APPROVE = "review.approve"
    # 人工复核拒绝
    REVIEW_REJECT = "review.reject"
    # 人工复核修改
    REVIEW_REVISE = "review.revise"

    # ==================== 安全相关 ====================
    # 认证成功
    AUTH_SUCCESS = "auth.success"
    # 认证失败
    AUTH_FAILURE = "auth.failure"
    # 权限拒绝
    PERMISSION_DENIED = "permission.denied"
    # 敏感数据访问
    SENSITIVE_ACCESS = "sensitive.access"


# ============================================================================
# 风险等级枚举
# ============================================================================

class RiskLevel(Enum):
    """
    风险等级枚举

    用于评估操作的风险程度，影响：
    1. 是否需要人工复核
    2. 是否触发告警
    3. 保存时长
    """
    # 低风险：普通操作
    LOW = "low"

    # 中风险：需要注意的操作
    MEDIUM = "medium"

    # 高风险：需要复核的操作
    HIGH = "high"

    # 极高风险：必须立即处理
    CRITICAL = "critical"


# ============================================================================
# 审计事件对象
# ============================================================================

@dataclass
class AuditEvent:
    """
    审计事件对象

    包含一次审计操作的完整信息

    字段说明：
    --------
    - event_id: 事件唯一标识（UUID）
    - timestamp: 事件时间
    - event_type: 事件类型
    - trace_id / run_id: 链路追踪
    - user_id / session_id: 用户上下文
    - action: 操作名称
    - resource_type / resource_id: 资源信息
    - success / error_message: 执行结果
    - risk_level / risk_factors: 风险评估
    - metadata: 额外数据

    设计原理：
    --------
    1. 使用 dataclass 方便创建和序列化
    2. 所有字段可选，支持灵活创建
    3. to_dict() 方法便于 JSON 输出
    4. 参考 OpenTelemetry Span 的设计
    """
    # 标识
    event_id: str = field(default_factory=lambda: str(uuid4()))
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # 类型
    event_type: AuditEventType

    # 链路追踪
    trace_id: str | None = None
    run_id: str | None = None

    # 用户上下文
    user_id: str | None = None
    session_id: str | None = None
    conversation_id: str | None = None

    # 操作信息
    action: str = ""
    resource_type: str | None = None
    resource_id: str | None = None

    # 结果
    success: bool = True
    error_message: str | None = None

    # 风险评估
    risk_level: RiskLevel = RiskLevel.LOW
    risk_factors: list[str] = field(default_factory=list)

    # 额外数据
    metadata: dict[str, Any] = field(default_factory=dict)

    # IP 和 User Agent
    ip_address: str | None = None
    user_agent: str | None = None

    def to_dict(self) -> dict:
        """
        转换为字典

        用于 JSON 序列化和数据库存储
        """
        return {
            # 标识
            "event_id": self.event_id,
            "timestamp": self.timestamp.isoformat(),

            # 类型
            "event_type": self.event_type.value,

            # 链路追踪
            "trace_id": self.trace_id,
            "run_id": self.run_id,

            # 用户上下文
            "user_id": self.user_id,
            "session_id": self.session_id,
            "conversation_id": self.conversation_id,

            # 操作信息
            "action": self.action,
            "resource_type": self.resource_type,
            "resource_id": self.resource_id,

            # 结果
            "success": self.success,
            "error_message": self.error_message,

            # 风险评估
            "risk_level": self.risk_level.value,
            "risk_factors": self.risk_factors,

            # 额外数据
            "metadata": self.metadata,

            # 网络信息
            "ip_address": self.ip_address,
            "user_agent": self.user_agent,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "AuditEvent":
        """
        从字典创建（用于反序列化）

        Args:
            data: 字典数据

        Returns:
            AuditEvent 实例
        """
        # 处理枚举类型
        if isinstance(data.get("event_type"), str):
            data["event_type"] = AuditEventType(data["event_type"])
        if isinstance(data.get("risk_level"), str):
            data["risk_level"] = RiskLevel(data["risk_level"])

        # 处理时间
        if isinstance(data.get("timestamp"), str):
            data["timestamp"] = datetime.fromisoformat(data["timestamp"])

        return cls(**data)


# ============================================================================
# 审计日志导出器
# ============================================================================

class AuditExporter(ABC):
    """
    审计日志导出器抽象基类

    定义审计事件的导出接口

    实现类：
    - ConsoleExporter: 输出到控制台（开发调试）
    - FileExporter: 输出到文件
    - DatabaseExporter: 输出到数据库
    - S3Exporter: 输出到对象存储
    """

    @abstractmethod
    def export(self, event: AuditEvent) -> None:
        """导出单个事件"""
        pass

    @abstractmethod
    def export_batch(self, events: list[AuditEvent]) -> None:
        """批量导出事件"""
        pass


class ConsoleAuditExporter(AuditExporter):
    """
    控制台审计日志导出器

    用于开发调试，生产环境建议使用其他导出器
    """

    def export(self, event: AuditEvent) -> None:
        """输出到控制台"""
        print(f"[AUDIT] {json.dumps(event.to_dict(), ensure_ascii=False)}")

    def export_batch(self, events: list[AuditEvent]) -> None:
        """批量输出"""
        for event in events:
            self.export(event)


# ============================================================================
# 审计日志记录器
# ============================================================================

class AuditLogger:
    """
    审计日志记录器

    核心功能：
    1. 统一记录所有审计事件
    2. 支持多级风险评估
    3. 自动补全上下文信息
    4. 可扩展的导出后端

    使用方式：
    --------
    1. 使用全局实例（推荐）：
        from core.observability.audit import audit_log
        audit_log.log_agent_request(...)

    2. 注入使用（便于测试）：
        logger = AuditLogger(exporter=MyExporter())
        logger.log(...)
    """

    def __init__(self, exporter: AuditExporter | None = None):
        """
        初始化审计日志记录器

        Args:
            exporter: 导出器，默认使用 ConsoleExporter
        """
        self.exporter = exporter or ConsoleAuditExporter()

    def log(
        self,
        event_type: AuditEventType,
        action: str,
        trace_id: str | None = None,
        run_id: str | None = None,
        user_id: str | None = None,
        session_id: str | None = None,
        conversation_id: str | None = None,
        resource_type: str | None = None,
        resource_id: str | None = None,
        success: bool = True,
        error_message: str | None = None,
        risk_level: RiskLevel = RiskLevel.LOW,
        risk_factors: list[str] | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
        **metadata,
    ) -> AuditEvent:
        """
        记录审计事件

        这是最底层的方法，其他便捷方法都是基于此方法

        Args:
            event_type: 事件类型
            action: 操作名称
            trace_id: 链路追踪 ID
            run_id: 运行 ID
            user_id: 用户 ID
            session_id: 会话 ID
            conversation_id: 对话 ID
            resource_type: 资源类型
            resource_id: 资源 ID
            success: 是否成功
            error_message: 错误信息
            risk_level: 风险等级
            risk_factors: 风险因素列表
            ip_address: IP 地址
            user_agent: 用户代理
            **metadata: 额外元数据

        Returns:
            创建的审计事件
        """
        # 自动从上下文获取
        trace_id = trace_id or get_trace_id()
        run_id = run_id or get_run_id()
        user_id = user_id or get_user_id()
        conversation_id = conversation_id or get_conversation_id()

        # 创建事件
        event = AuditEvent(
            event_type=event_type,
            action=action,
            trace_id=trace_id,
            run_id=run_id,
            user_id=user_id,
            session_id=session_id,
            conversation_id=conversation_id,
            resource_type=resource_type,
            resource_id=resource_id,
            success=success,
            error_message=error_message,
            risk_level=risk_level,
            risk_factors=risk_factors or [],
            ip_address=ip_address,
            user_agent=user_agent,
            metadata=metadata,
        )

        # 导出
        self.exporter.export(event)

        # 高风险事件触发告警
        if risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL):
            self._handle_high_risk_event(event)

        return event

    # ==================== Agent 相关便捷方法 ====================

    def log_agent_request(
        self,
        action: str,
        intent_type: str | None = None,
        query: str | None = None,
        trace_id: str | None = None,
        run_id: str | None = None,
        user_id: str | None = None,
        success: bool = True,
        **metadata,
    ) -> AuditEvent:
        """
        记录 Agent 请求

        Args:
            action: 操作名称（如 "rag.query", "contract.review"）
            intent_type: 意图类型
            query: 用户查询
            其他参数同 log()

        Returns:
            审计事件
        """
        return self.log(
            event_type=AuditEventType.AGENT_REQUEST,
            action=f"agent.{action}",
            trace_id=trace_id,
            run_id=run_id,
            user_id=user_id,
            success=success,
            resource_type="agent",
            risk_level=RiskLevel.LOW,
            intent_type=intent_type,
            query=query,
            **metadata,
        )

    def log_agent_response(
        self,
        action: str,
        trace_id: str | None = None,
        run_id: str | None = None,
        success: bool = True,
        duration_ms: float | None = None,
        token_usage: dict | None = None,
        **metadata,
    ) -> AuditEvent:
        """
        记录 Agent 响应

        Args:
            action: 操作名称
            其他参数同 log()
            duration_ms: 耗时
            token_usage: Token 使用量
        """
        return self.log(
            event_type=AuditEventType.AGENT_RESPONSE,
            action=f"agent.{action}",
            trace_id=trace_id,
            run_id=run_id,
            success=success,
            resource_type="agent",
            risk_level=RiskLevel.LOW,
            duration_ms=duration_ms,
            token_usage=token_usage,
            **metadata,
        )

    def log_agent_error(
        self,
        action: str,
        error_message: str,
        trace_id: str | None = None,
        run_id: str | None = None,
        user_id: str | None = None,
        **metadata,
    ) -> AuditEvent:
        """
        记录 Agent 错误

        Args:
            action: 操作名称
            error_message: 错误信息
        """
        return self.log(
            event_type=AuditEventType.AGENT_ERROR,
            action=f"agent.{action}",
            trace_id=trace_id,
            run_id=run_id,
            user_id=user_id,
            success=False,
            error_message=error_message,
            resource_type="agent",
            risk_level=RiskLevel.MEDIUM,
            **metadata,
        )

    # ==================== 工具调用相关 ====================

    def log_tool_invocation(
        self,
        tool_name: str,
        parameters: dict | None = None,
        trace_id: str | None = None,
        run_id: str | None = None,
        success: bool = True,
        risk_level: RiskLevel = RiskLevel.LOW,
        **metadata,
    ) -> AuditEvent:
        """
        记录工具调用

        Args:
            tool_name: 工具名称
            parameters: 调用参数
        """
        return self.log(
            event_type=AuditEventType.TOOL_INVOCATION,
            action=f"tool.{tool_name}",
            trace_id=trace_id,
            run_id=run_id,
            success=success,
            resource_type="tool",
            resource_id=tool_name,
            risk_level=risk_level,
            parameters=parameters,
            **metadata,
        )

    def log_tool_result(
        self,
        tool_name: str,
        result_summary: str | None = None,
        trace_id: str | None = None,
        run_id: str | None = None,
        success: bool = True,
        duration_ms: float | None = None,
        **metadata,
    ) -> AuditEvent:
        """
        记录工具执行结果

        Args:
            tool_name: 工具名称
            result_summary: 结果摘要
        """
        return self.log(
            event_type=AuditEventType.TOOL_RESULT,
            action=f"tool.{tool_name}.result",
            trace_id=trace_id,
            run_id=run_id,
            success=success,
            resource_type="tool",
            resource_id=tool_name,
            risk_level=RiskLevel.LOW,
            result_summary=result_summary,
            duration_ms=duration_ms,
            **metadata,
        )

    # ==================== 数据访问相关 ====================

    def log_data_retrieval(
        self,
        retrieval_type: str,
        query: str,
        retrieved_count: int,
        trace_id: str | None = None,
        run_id: str | None = None,
        user_id: str | None = None,
        success: bool = True,
        duration_ms: float | None = None,
        **metadata,
    ) -> AuditEvent:
        """
        记录数据检索（RAG）

        Args:
            retrieval_type: 检索类型（如 "hybrid_search"）
            query: 检索查询
            retrieved_count: 检索结果数量
        """
        return self.log(
            event_type=AuditEventType.DATA_RETRIEVAL,
            action=f"data.retrieval.{retrieval_type}",
            trace_id=trace_id,
            run_id=run_id,
            user_id=user_id,
            success=success,
            resource_type="retrieval",
            risk_level=RiskLevel.LOW,
            query=query,
            retrieved_count=retrieved_count,
            duration_ms=duration_ms,
            **metadata,
        )

    def log_sql_query(
        self,
        sql: str,
        row_count: int,
        trace_id: str | None = None,
        run_id: str | None = None,
        user_id: str | None = None,
        success: bool = True,
        duration_ms: float | None = None,
        risk_level: RiskLevel = RiskLevel.MEDIUM,
        **metadata,
    ) -> AuditEvent:
        """
        记录 SQL 查询

        Args:
            sql: SQL 语句
            row_count: 返回行数
        """
        return self.log(
            event_type=AuditEventType.DATA_QUERY,
            action="data.sql.query",
            trace_id=trace_id,
            run_id=run_id,
            user_id=user_id,
            success=success,
            resource_type="sql",
            risk_level=risk_level,
            sql=sql,
            row_count=row_count,
            duration_ms=duration_ms,
            **metadata,
        )

    # ==================== 人工复核相关 ====================

    def log_review_request(
        self,
        review_id: str,
        review_type: str,
        reason: str,
        trace_id: str | None = None,
        run_id: str | None = None,
        user_id: str | None = None,
        priority: str = "normal",
        **metadata,
    ) -> AuditEvent:
        """
        记录人工复核请求

        Args:
            review_id: 复核 ID
            review_type: 复核类型（如 "contract", "sensitive_data"）
            reason: 请求原因
            priority: 优先级
        """
        risk_level = RiskLevel.HIGH if priority == "high" else RiskLevel.MEDIUM

        return self.log(
            event_type=AuditEventType.REVIEW_REQUEST,
            action=f"review.request.{review_type}",
            trace_id=trace_id,
            run_id=run_id,
            user_id=user_id,
            success=True,
            resource_type="review",
            resource_id=review_id,
            risk_level=risk_level,
            review_type=review_type,
            reason=reason,
            priority=priority,
            **metadata,
        )

    def log_review_result(
        self,
        review_id: str,
        action: str,
        reviewer_id: str,
        comment: str | None = None,
        trace_id: str | None = None,
        run_id: str | None = None,
        **metadata,
    ) -> AuditEvent:
        """
        记录人工复核结果

        Args:
            review_id: 复核 ID
            action: 操作（approve / reject / revise）
            reviewer_id: 复核人 ID
            comment: 复核意见
        """
        action_map = {
            "approve": AuditEventType.REVIEW_APPROVE,
            "reject": AuditEventType.REJECT,
            "revise": AuditEventType.REVIEW_REVISE,
        }
        event_type = action_map.get(action, AuditEventType.REVIEW_APPROVE)

        return self.log(
            event_type=event_type,
            action=f"review.{action}",
            trace_id=trace_id,
            run_id=run_id,
            user_id=reviewer_id,
            success=True,
            resource_type="review",
            resource_id=review_id,
            risk_level=RiskLevel.HIGH,
            action=action,
            reviewer_id=reviewer_id,
            comment=comment,
            **metadata,
        )

    # ==================== 安全相关 ====================

    def log_auth_success(
        self,
        user_id: str,
        method: str = "password",
        trace_id: str | None = None,
        **metadata,
    ) -> AuditEvent:
        """
        记录认证成功
        """
        return self.log(
            event_type=AuditEventType.AUTH_SUCCESS,
            action="auth.login",
            trace_id=trace_id,
            user_id=user_id,
            success=True,
            resource_type="auth",
            risk_level=RiskLevel.LOW,
            auth_method=method,
            **metadata,
        )

    def log_auth_failure(
        self,
        user_id: str | None = None,
        reason: str = "invalid_credentials",
        ip_address: str | None = None,
        trace_id: str | None = None,
        **metadata,
    ) -> AuditEvent:
        """
        记录认证失败
        """
        return self.log(
            event_type=AuditEventType.AUTH_FAILURE,
            action="auth.login",
            trace_id=trace_id,
            user_id=user_id,
            success=False,
            error_message=reason,
            ip_address=ip_address,
            resource_type="auth",
            risk_level=RiskLevel.MEDIUM,
            failure_reason=reason,
            **metadata,
        )

    def log_permission_denied(
        self,
        action: str,
        required_permission: str,
        user_id: str | None = None,
        trace_id: str | None = None,
        **metadata,
    ) -> AuditEvent:
        """
        记录权限拒绝
        """
        return self.log(
            event_type=AuditEventType.PERMISSION_DENIED,
            action=action,
            trace_id=trace_id,
            user_id=user_id,
            success=False,
            error_message=f"权限不足，需要: {required_permission}",
            resource_type="permission",
            risk_level=RiskLevel.MEDIUM,
            required_permission=required_permission,
            **metadata,
        )

    # ==================== 高风险操作 ====================

    def log_risk_operation(
        self,
        action: str,
        risk_level: RiskLevel,
        reason: str,
        trace_id: str | None = None,
        run_id: str | None = None,
        user_id: str | None = None,
        resource_type: str | None = None,
        resource_id: str | None = None,
        **metadata,
    ) -> AuditEvent:
        """
        记录高风险操作

        Args:
            action: 操作名称
            risk_level: 风险等级
            reason: 风险原因
        """
        return self.log(
            event_type=AuditEventType.RISK_OPERATION,
            action=action,
            trace_id=trace_id,
            run_id=run_id,
            user_id=user_id,
            success=True,
            resource_type=resource_type,
            resource_id=resource_id,
            risk_level=risk_level,
            risk_factors=[reason],
            **metadata,
        )

    # ==================== 内部方法 ====================

    def _handle_high_risk_event(self, event: AuditEvent) -> None:
        """
        处理高风险事件

        当前实现只是打印警告，后续可以扩展为：
        1. 发送告警通知
        2. 写入单独的告警表
        3. 触发自动化处理
        """
        import logging
        logger = logging.getLogger("agent.audit")
        logger.warning(
            f"[HIGH RISK EVENT] {event.event_type.value} | "
            f"action={event.action} | "
            f"risk_level={event.risk_level.value} | "
            f"trace_id={event.trace_id} | "
            f"user_id={event.user_id}"
        )


# ============================================================================
# 全局实例
# ============================================================================

_audit_logger: AuditLogger | None = None


def get_audit_logger() -> AuditLogger:
    """
    获取全局审计日志记录器

    Returns:
        AuditLogger 实例
    """
    global _audit_logger
    if _audit_logger is None:
        _audit_logger = AuditLogger()
    return _audit_logger


# 便捷访问
audit_log = get_audit_logger()
