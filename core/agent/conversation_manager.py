"""
多轮对话管理器

提供多轮对话能力：
1. 会话管理：创建、读取、更新会话
2. 上下文管理：维护对话历史和槽位状态
3. 任务恢复：从澄清状态恢复执行

设计说明：
- 使用内存存储（简单实现）
- 生产环境建议使用 Redis + PostgreSQL
- 支持会话超时和自动清理

Author: Enterprise Knowledge Agentic RAG Platform
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ============================================================================
# 会话状态
# ============================================================================

class ConversationStatus(str, Enum):
    """会话状态"""
    ACTIVE = "active"                 # 活跃
    AWAITING_CLARIFICATION = "awaiting_clarification"  # 等待澄清
    EXECUTING = "executing"           # 执行中
    COMPLETED = "completed"            # 已完成
    EXPIRED = "expired"               # 已过期
    FAILED = "failed"                # 失败


# ============================================================================
# 消息记录
# ============================================================================

@dataclass
class MessageRecord:
    """消息记录"""
    message_id: str
    role: str                          # user/assistant/system
    content: str
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: dict = field(default_factory=dict)


# ============================================================================
# 会话上下文
# ============================================================================

@dataclass
class ConversationContext:
    """
    会话上下文

    包含：
    - 会话基本信息
    - 对话历史
    - 槽位状态
    - 当前意图
    """
    conversation_id: str
    user_id: str
    status: ConversationStatus = ConversationStatus.ACTIVE

    # 对话历史
    messages: list[MessageRecord] = field(default_factory=list)

    # 槽位状态
    slots: dict[str, Any] = field(default_factory=dict)
    missing_slots: list[str] = field(default_factory=list)

    # 意图信息
    current_intent: Optional[str] = None
    intent_confidence: float = 0.0

    # 路由信息
    routing_target: Optional[str] = None

    # 时间戳
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    last_message_at: datetime = field(default_factory=datetime.now)

    # 超时配置
    timeout_minutes: int = 30
    max_turns: int = 20

    # 元数据
    metadata: dict = field(default_factory=dict)

    @property
    def is_expired(self) -> bool:
        """检查是否过期"""
        expiry = self.last_message_at + timedelta(minutes=self.timeout_minutes)
        return datetime.now() > expiry

    @property
    def turn_count(self) -> int:
        """获取对话轮次"""
        return len([m for m in self.messages if m.role == "user"])

    def add_message(
        self,
        message_id: str,
        role: str,
        content: str,
        metadata: Optional[dict] = None,
    ) -> None:
        """添加消息"""
        self.messages.append(
            MessageRecord(
                message_id=message_id,
                role=role,
                content=content,
                metadata=metadata or {},
            )
        )
        self.last_message_at = datetime.now()
        self.updated_at = datetime.now()

    def update_slots(self, slots: dict[str, Any]) -> None:
        """更新槽位"""
        self.slots.update(slots)
        # 移除已填充的槽位
        self.missing_slots = [
            slot for slot in self.missing_slots
            if slot not in slots
        ]
        self.updated_at = datetime.now()

    def set_missing_slots(self, missing: list[str]) -> None:
        """设置缺失槽位"""
        self.missing_slots = missing
        if missing:
            self.status = ConversationStatus.AWAITING_CLARIFICATION
        else:
            self.status = ConversationStatus.ACTIVE
        self.updated_at = datetime.now()

    def get_history(self, limit: Optional[int] = None) -> list[dict]:
        """获取对话历史"""
        messages = self.messages[-limit:] if limit else self.messages
        return [
            {
                "message_id": m.message_id,
                "role": m.role,
                "content": m.content,
                "timestamp": m.timestamp.isoformat(),
                "metadata": m.metadata,
            }
            for m in messages
        ]

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "conversation_id": self.conversation_id,
            "user_id": self.user_id,
            "status": self.status.value,
            "slots": self.slots,
            "missing_slots": self.missing_slots,
            "current_intent": self.current_intent,
            "intent_confidence": self.intent_confidence,
            "routing_target": self.routing_target,
            "message_count": len(self.messages),
            "turn_count": self.turn_count,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "last_message_at": self.last_message_at.isoformat(),
            "is_expired": self.is_expired,
        }


# ============================================================================
# 对话管理器
# ============================================================================

class ConversationManager:
    """
    多轮对话管理器

    职责：
    1. 会话生命周期管理
    2. 上下文维护
    3. 槽位状态跟踪
    4. 任务恢复

    设计说明：
    - 简单内存实现
    - 生产环境建议使用 Redis 存储
    - 支持会话超时清理
    """

    def __init__(self, timeout_minutes: int = 30, max_turns: int = 20):
        """
        初始化对话管理器

        Args:
            timeout_minutes: 会话超时时间（分钟）
            max_turns: 最大对话轮次
        """
        self.timeout_minutes = timeout_minutes
        self.max_turns = max_turns

        # 内存存储
        self._conversations: dict[str, ConversationContext] = {}

        # 清理任务
        self._cleanup_task: Optional[asyncio.Task] = None
        self._running = False

    async def start(self) -> None:
        """启动清理任务"""
        self._running = True
        self._cleanup_task = asyncio.create_task(self._cleanup_expired())

    async def stop(self) -> None:
        """停止清理任务"""
        self._running = False
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass

    async def _cleanup_expired(self) -> None:
        """定期清理过期的会话"""
        while self._running:
            try:
                await asyncio.sleep(300)  # 每 5 分钟检查一次
                self._cleanup_sync()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"Cleanup error: {e}")

    def _cleanup_sync(self) -> None:
        """同步清理（供线程调用）"""
        expired = [
            conv_id
            for conv_id, conv in self._conversations.items()
            if conv.is_expired
        ]
        for conv_id in expired:
            self._conversations[conv_id].status = ConversationStatus.EXPIRED
            logger.info(f"Conversation expired: {conv_id}")

    def create_conversation(
        self,
        conversation_id: str,
        user_id: str,
        metadata: Optional[dict] = None,
    ) -> ConversationContext:
        """
        创建新会话

        Args:
            conversation_id: 会话 ID
            user_id: 用户 ID
            metadata: 元数据

        Returns:
            ConversationContext
        """
        if conversation_id in self._conversations:
            return self._conversations[conversation_id]

        conv = ConversationContext(
            conversation_id=conversation_id,
            user_id=user_id,
            timeout_minutes=self.timeout_minutes,
            max_turns=self.max_turns,
            metadata=metadata or {},
        )
        self._conversations[conversation_id] = conv

        logger.info(f"Created conversation: {conversation_id}")
        return conv

    def get_conversation(self, conversation_id: str) -> Optional[ConversationContext]:
        """
        获取会话

        Args:
            conversation_id: 会话 ID

        Returns:
            ConversationContext 或 None
        """
        conv = self._conversations.get(conversation_id)
        if conv and conv.is_expired:
            conv.status = ConversationStatus.EXPIRED
        return conv

    def update_conversation(
        self,
        conversation_id: str,
        **updates,
    ) -> Optional[ConversationContext]:
        """
        更新会话

        Args:
            conversation_id: 会话 ID
            **updates: 更新字段

        Returns:
            更新后的 ConversationContext
        """
        conv = self.get_conversation(conversation_id)
        if not conv:
            return None

        for key, value in updates.items():
            if hasattr(conv, key):
                setattr(conv, key, value)

        conv.updated_at = datetime.now()
        return conv

    def add_user_message(
        self,
        conversation_id: str,
        message_id: str,
        content: str,
        metadata: Optional[dict] = None,
    ) -> Optional[ConversationContext]:
        """
        添加用户消息

        Args:
            conversation_id: 会话 ID
            message_id: 消息 ID
            content: 消息内容
            metadata: 元数据

        Returns:
            更新后的 ConversationContext
        """
        conv = self.get_conversation(conversation_id)
        if not conv:
            return None

        # 检查轮次限制
        if conv.turn_count >= conv.max_turns:
            conv.status = ConversationStatus.FAILED
            conv.metadata["error"] = "max_turns_exceeded"
            return conv

        conv.add_message(message_id, "user", content, metadata)
        return conv

    def add_assistant_message(
        self,
        conversation_id: str,
        message_id: str,
        content: str,
        metadata: Optional[dict] = None,
    ) -> Optional[ConversationContext]:
        """
        添加助手消息

        Args:
            conversation_id: 会话 ID
            message_id: 消息 ID
            content: 消息内容
            metadata: 元数据

        Returns:
            更新后的 ConversationContext
        """
        conv = self.get_conversation(conversation_id)
        if not conv:
            return None

        conv.add_message(message_id, "assistant", content, metadata)
        return conv

    def update_intent(
        self,
        conversation_id: str,
        intent: str,
        confidence: float,
        routing_target: Optional[str] = None,
    ) -> Optional[ConversationContext]:
        """
        更新意图信息

        Args:
            conversation_id: 会话 ID
            intent: 意图类型
            confidence: 置信度
            routing_target: 路由目标

        Returns:
            更新后的 ConversationContext
        """
        conv = self.get_conversation(conversation_id)
        if not conv:
            return None

        conv.current_intent = intent
        conv.intent_confidence = confidence
        if routing_target:
            conv.routing_target = routing_target
        conv.updated_at = datetime.now()

        return conv

    def update_slots(
        self,
        conversation_id: str,
        slots: dict[str, Any],
        missing_slots: Optional[list[str]] = None,
    ) -> Optional[ConversationContext]:
        """
        更新槽位

        Args:
            conversation_id: 会话 ID
            slots: 槽位值
            missing_slots: 缺失槽位（可选）

        Returns:
            更新后的 ConversationContext
        """
        conv = self.get_conversation(conversation_id)
        if not conv:
            return None

        conv.update_slots(slots)
        if missing_slots is not None:
            conv.set_missing_slots(missing_slots)

        return conv

    def set_clarification(
        self,
        conversation_id: str,
        questions: list[str],
    ) -> Optional[ConversationContext]:
        """
        设置澄清状态

        Args:
            conversation_id: 会话 ID
            questions: 澄清问题列表

        Returns:
            更新后的 ConversationContext
        """
        conv = self.get_conversation(conversation_id)
        if not conv:
            return None

        conv.status = ConversationStatus.AWAITING_CLARIFICATION
        conv.metadata["clarification_questions"] = questions
        conv.updated_at = datetime.now()

        return conv

    def resume_from_clarification(
        self,
        conversation_id: str,
        user_response: str,
        message_id: str,
    ) -> Optional[ConversationContext]:
        """
        从澄清状态恢复

        Args:
            conversation_id: 会话 ID
            user_response: 用户回复
            message_id: 消息 ID

        Returns:
            更新后的 ConversationContext
        """
        conv = self.get_conversation(conversation_id)
        if not conv:
            return None

        if conv.status != ConversationStatus.AWAITING_CLARIFICATION:
            logger.warning(f"Conversation {conversation_id} is not awaiting clarification")
            return conv

        # 添加用户回复
        conv.add_message(
            message_id,
            "user",
            user_response,
            {"source": "clarification_response"},
        )

        # 清除澄清状态
        conv.status = ConversationStatus.ACTIVE
        conv.metadata.pop("clarification_questions", None)
        conv.updated_at = datetime.now()

        return conv

    def delete_conversation(self, conversation_id: str) -> bool:
        """
        删除会话

        Args:
            conversation_id: 会话 ID

        Returns:
            是否成功
        """
        if conversation_id in self._conversations:
            del self._conversations[conversation_id]
            logger.info(f"Deleted conversation: {conversation_id}")
            return True
        return False

    def list_conversations(self, user_id: Optional[str] = None) -> list[dict]:
        """
        列出会话

        Args:
            user_id: 用户 ID（可选）

        Returns:
            会话列表
        """
        convs = self._conversations.values()
        if user_id:
            convs = [c for c in convs if c.user_id == user_id]

        return [c.to_dict() for c in convs]


# ============================================================================
# 全局实例
# ============================================================================

_conversation_manager: ConversationManager | None = None


def get_conversation_manager() -> ConversationManager:
    """获取全局对话管理器实例"""
    global _conversation_manager
    if _conversation_manager is None:
        _conversation_manager = ConversationManager()
    return _conversation_manager
