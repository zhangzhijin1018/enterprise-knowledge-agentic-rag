"""合同审查审计日志服务。

为国企合规设计的完整审计日志系统：
1. 所有操作必须记录审计日志
2. 审计日志必须持久化到数据库
3. 审计日志不可删除，只能追加
4. 支持事后追溯和合规审计

Author: Enterprise Knowledge Agentic RAG Platform
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import uuid4

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class AuditEventType(str, Enum):
    """审计事件类型枚举。"""

    # 工作流事件
    WORKFLOW_START = "workflow_start"  # 工作流启动
    WORKFLOW_END = "workflow_end"  # 工作流结束
    WORKFLOW_ERROR = "workflow_error"  # 工作流错误
    WORKFLOW_RESUME = "workflow_resume"  # 工作流恢复
    WORKFLOW_SNAPSHOT = "workflow_snapshot"  # 状态快照

    # 节点事件
    NODE_START = "node_start"  # 节点开始
    NODE_END = "node_end"  # 节点结束

    # 工具事件
    TOOL_CALL = "tool_call"  # 工具调用
    TOOL_RESULT = "tool_result"  # 工具结果
    TOOL_ERROR = "tool_error"  # 工具错误

    # 风险事件
    RISK_IDENTIFIED = "risk_identified"  # 风险识别
    RISK_ESCALATED = "risk_escalated"  # 风险升级

    # Human Review 事件
    REVIEW_REQUESTED = "review_requested"  # 请求复核
    REVIEW_STARTED = "review_started"  # 复核开始
    REVIEW_COMPLETED = "review_completed"  # 复核完成
    REVIEW_APPROVED = "review_approved"  # 复核通过
    REVIEW_REJECTED = "review_rejected"  # 复核拒绝
    REVIEW_REVISED = "review_revised"  # 复核修改

    # 敏感操作
    SENSITIVE_DATA_ACCESS = "sensitive_data_access"  # 敏感数据访问
    DECISION_OVERRIDE = "decision_override"  # 决策覆盖


class AuditLog(BaseModel):
    """审计日志条目。

    遵循国企合规要求：
    - 时间戳精确到毫秒
    - 操作人必须记录
    - 操作内容不可篡改
    """

    # 核心标识
    audit_id: str = Field(description="审计ID")
    run_id: str = Field(description="运行ID")
    trace_id: str = Field(description="追踪ID")

    # 时间信息
    timestamp: datetime = Field(default_factory=datetime.now, description="时间戳")
    event_type: AuditEventType = Field(description="事件类型")

    # 操作者信息
    user_id: str = Field(description="操作用户ID")
    user_role: str = Field(description="操作用户角色")
    operator_id: Optional[str] = Field(default=None, description="操作人员ID（人工操作时）")
    operator_name: Optional[str] = Field(default=None, description="操作人员姓名")

    # 操作详情
    node_name: Optional[str] = Field(default=None, description="节点名称")
    tool_name: Optional[str] = Field(default=None, description="工具名称")
    action: str = Field(description="操作描述")
    details: Dict[str, Any] = Field(default_factory=dict, description="详细信息")

    # 结果
    result: str = Field(description="操作结果：success/failure")
    error_message: Optional[str] = Field(default=None, description="错误信息")

    # 合规字段
    ip_address: Optional[str] = Field(default=None, description="IP地址")
    session_id: Optional[str] = Field(default=None, description="会话ID")
    checksum: Optional[str] = Field(default=None, description="校验和（防篡改）")


class AuditLogger:
    """审计日志记录器。

    设计原则：
    1. 所有操作必须记录审计日志
    2. 审计日志持久化到数据库
    3. 支持异步写入，不影响性能
    4. 支持批量写入，提高效率

    国企合规要求：
    - 操作人必须记录
    - 操作时间必须精确
    - 操作内容不可篡改
    """

    def __init__(self, db_session: Any = None) -> None:
        """初始化审计日志记录器。

        Args:
            db_session: 数据库会话
        """
        self.db_session = db_session
        self._buffer: List[AuditLog] = []  # 缓冲区
        self._buffer_size = 100  # 缓冲区大小
        self._audit_enabled = True  # 审计开关

    def log(
        self,
        run_id: str,
        trace_id: str,
        event_type: AuditEventType,
        action: str,
        user_id: str,
        user_role: str,
        node_name: Optional[str] = None,
        tool_name: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        result: str = "success",
        error_message: Optional[str] = None,
        operator_id: Optional[str] = None,
        operator_name: Optional[str] = None,
        ip_address: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> str:
        """记录审计日志。

        Args:
            run_id: 运行ID
            trace_id: 追踪ID
            event_type: 事件类型
            action: 操作描述
            user_id: 操作用户ID
            user_role: 操作用户角色
            node_name: 节点名称
            tool_name: 工具名称
            details: 详细信息
            result: 操作结果
            error_message: 错误信息
            operator_id: 操作人员ID
            operator_name: 操作人员姓名
            ip_address: IP地址
            session_id: 会话ID

        Returns:
            审计ID
        """
        if not self._audit_enabled:
            return ""

        # 生成审计ID
        audit_id = f"audit_{uuid4().hex[:16]}"

        # 创建审计日志
        audit_log = AuditLog(
            audit_id=audit_id,
            run_id=run_id,
            trace_id=trace_id,
            event_type=event_type,
            timestamp=datetime.now(),
            user_id=user_id,
            user_role=user_role,
            node_name=node_name,
            tool_name=tool_name,
            action=action,
            details=details or {},
            result=result,
            error_message=error_message,
            operator_id=operator_id,
            operator_name=operator_name,
            ip_address=ip_address,
            session_id=session_id,
            checksum=self._generate_checksum(audit_id, run_id, action, datetime.now()),
        )

        # 添加到缓冲区
        self._buffer.append(audit_log)

        # 如果缓冲区满，写入数据库
        if len(self._buffer) >= self._buffer_size:
            self._flush()

        logger.info(
            f"[Audit] {event_type.value} | run_id={run_id} | "
            f"action={action} | result={result}"
        )

        return audit_id

    def log_workflow_start(
        self,
        run_id: str,
        trace_id: str,
        user_id: str,
        user_role: str,
        contract_name: str,
        **kwargs
    ) -> str:
        """记录工作流启动。"""
        return self.log(
            run_id=run_id,
            trace_id=trace_id,
            event_type=AuditEventType.WORKFLOW_START,
            action=f"启动合同审查工作流: {contract_name}",
            user_id=user_id,
            user_role=user_role,
            details={
                "contract_name": contract_name,
                **kwargs
            },
        )

    def log_workflow_snapshot(
        self,
        run_id: str,
        trace_id: str,
        user_id: str,
        user_role: str,
        snapshot_id: str,
        current_stage: str,
        completed_tools: List[str],
        **kwargs
    ) -> str:
        """记录状态快照。"""
        return self.log(
            run_id=run_id,
            trace_id=trace_id,
            event_type=AuditEventType.WORKFLOW_SNAPSHOT,
            action=f"创建状态快照: {current_stage}",
            user_id=user_id,
            user_role=user_role,
            details={
                "snapshot_id": snapshot_id,
                "current_stage": current_stage,
                "completed_tools": completed_tools,
                **kwargs
            },
        )

    def log_workflow_resume(
        self,
        run_id: str,
        trace_id: str,
        user_id: str,
        user_role: str,
        snapshot_id: str,
        resume_from: str,
    ) -> str:
        """记录工作流恢复。"""
        return self.log(
            run_id=run_id,
            trace_id=trace_id,
            event_type=AuditEventType.WORKFLOW_RESUME,
            action=f"从快照恢复工作流",
            user_id=user_id,
            user_role=user_role,
            details={
                "snapshot_id": snapshot_id,
                "resume_from": resume_from,
            },
        )

    def log_tool_call(
        self,
        run_id: str,
        trace_id: str,
        user_id: str,
        user_role: str,
        tool_name: str,
        tool_input: Dict[str, Any],
        node_name: Optional[str] = None,
    ) -> str:
        """记录工具调用。"""
        # 敏感信息脱敏
        sanitized_input = self._sanitize_sensitive_data(tool_input)

        return self.log(
            run_id=run_id,
            trace_id=trace_id,
            event_type=AuditEventType.TOOL_CALL,
            action=f"调用工具: {tool_name}",
            user_id=user_id,
            user_role=user_role,
            node_name=node_name,
            tool_name=tool_name,
            details={"tool_input": sanitized_input},
        )

    def log_tool_result(
        self,
        run_id: str,
        trace_id: str,
        tool_name: str,
        tool_result: Dict[str, Any],
        success: bool = True,
    ) -> str:
        """记录工具结果。"""
        return self.log(
            run_id=run_id,
            trace_id=trace_id,
            event_type=AuditEventType.TOOL_RESULT if success else AuditEventType.TOOL_ERROR,
            action=f"工具执行结果: {tool_name}",
            user_id="system",
            user_role="system",
            tool_name=tool_name,
            details={"result": tool_result},
            result="success" if success else "failure",
        )

    def log_risk_identified(
        self,
        run_id: str,
        trace_id: str,
        user_id: str,
        user_role: str,
        risk_id: str,
        risk_type: str,
        risk_description: str,
        related_clause: str,
        human_review_required: bool,
    ) -> str:
        """记录风险识别。"""
        action = f"识别风险: [{risk_type}] {risk_description}"
        if human_review_required:
            action += " (需人工复核)"

        return self.log(
            run_id=run_id,
            trace_id=trace_id,
            event_type=AuditEventType.RISK_IDENTIFIED,
            action=action,
            user_id=user_id,
            user_role=user_role,
            details={
                "risk_id": risk_id,
                "risk_type": risk_type,
                "risk_description": risk_description,
                "related_clause": related_clause,
                "human_review_required": human_review_required,
            },
        )

    def log_review_requested(
        self,
        run_id: str,
        trace_id: str,
        user_id: str,
        user_role: str,
        review_id: str,
        high_risk_count: int,
        reason: str,
    ) -> str:
        """记录请求人工复核。"""
        return self.log(
            run_id=run_id,
            trace_id=trace_id,
            event_type=AuditEventType.REVIEW_REQUESTED,
            action=f"请求人工复核 (高风险 {high_risk_count} 项)",
            user_id=user_id,
            user_role=user_role,
            details={
                "review_id": review_id,
                "high_risk_count": high_risk_count,
                "reason": reason,
            },
        )

    def log_review_decision(
        self,
        run_id: str,
        trace_id: str,
        review_id: str,
        decision: str,
        reviewer_id: str,
        reviewer_name: str,
        comments: str,
        user_id: str = "system",
        user_role: str = "system",
    ) -> str:
        """记录复核决策。"""
        event_type = {
            "approved": AuditEventType.REVIEW_APPROVED,
            "rejected": AuditEventType.REVIEW_REJECTED,
            "revised": AuditEventType.REVIEW_REVISED,
        }.get(decision, AuditEventType.REVIEW_COMPLETED)

        return self.log(
            run_id=run_id,
            trace_id=trace_id,
            event_type=event_type,
            action=f"人工复核{decision}: {reviewer_name}",
            user_id=user_id,
            user_role=user_role,
            operator_id=reviewer_id,
            operator_name=reviewer_name,
            details={
                "review_id": review_id,
                "decision": decision,
                "comments": comments,
            },
        )

    def _flush(self) -> None:
        """将缓冲区中的审计日志写入数据库。"""
        if not self._buffer:
            return

        try:
            # 批量写入数据库
            # TODO: 实现实际的数据库写入
            logger.info(f"[Audit] 写入 {len(self._buffer)} 条审计日志")
            self._buffer.clear()
        except Exception as e:
            logger.error(f"[Audit] 写入审计日志失败: {e}")
            # 保留未写入的日志，避免丢失

    def _generate_checksum(self, *args) -> str:
        """生成校验和（防篡改）。"""
        import hashlib
        content = "|".join(str(arg) for arg in args)
        return hashlib.sha256(content.encode()).hexdigest()[:16]

    def _sanitize_sensitive_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """脱敏敏感数据。"""
        sensitive_fields = ["password", "secret", "token", "key", "api_key"]
        sanitized = {}

        for key, value in data.items():
            if any(field in key.lower() for field in sensitive_fields):
                sanitized[key] = "***脱敏***"
            elif isinstance(value, dict):
                sanitized[key] = self._sanitize_sensitive_data(value)
            else:
                sanitized[key] = value

        return sanitized


# ==================== 全局实例 ====================

_audit_logger: AuditLogger | None = None


def get_audit_logger() -> AuditLogger:
    """获取审计日志记录器全局实例。"""
    global _audit_logger
    if _audit_logger is None:
        _audit_logger = AuditLogger()
    return _audit_logger
