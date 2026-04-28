"""会话 Repository。

当前实现采用内存版存储，目的不是替代数据库，
而是先把调用边界、字段结构和最小闭环流程稳定下来。
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from core.database.models import Conversation, ConversationMemory, ConversationMessage

_CONVERSATIONS: dict[str, dict] = {}
_CONVERSATION_MESSAGES: dict[str, list[dict]] = {}
_CONVERSATION_MEMORIES: dict[str, dict] = {}


def _utcnow() -> datetime:
    """返回带时区的当前 UTC 时间。"""

    return datetime.now(timezone.utc)


def _generate_prefixed_id(prefix: str) -> str:
    """生成带业务前缀的稳定占位 ID。"""

    return f"{prefix}_{uuid4().hex[:12]}"


def reset_in_memory_conversation_store() -> None:
    """重置会话相关内存存储。

    该函数主要用于单元测试隔离，避免不同测试用例共享同一批内存状态。
    """

    _CONVERSATIONS.clear()
    _CONVERSATION_MESSAGES.clear()
    _CONVERSATION_MEMORIES.clear()


class ConversationRepository:
    """会话数据访问层。"""

    def __init__(self, session: Session | None = None) -> None:
        """初始化会话 Repository。

        设计说明：
        - 如果依赖注入层已经提供真实 SQLAlchemy Session，则当前 Repository 默认优先走数据库；
        - 如果没有 Session，则自动回退到内存实现，保证本地无数据库时项目仍可跑；
        - 这样可以把“数据库模式还是回退模式”的判断集中在更靠近基础设施的一层。
        """

        self.session = session

    def _use_database(self) -> bool:
        """判断当前是否启用真实数据库模式。

        这里不再额外读取 Settings，
        因为模式选择已经由 `get_db_session()` 和依赖注入层提前完成。
        Repository 只关注“当前有没有拿到可用 Session”。
        """

        return self.session is not None

    def _serialize_conversation(self, conversation: Conversation) -> dict:
        """把 ORM 对象转换成 service 可直接使用的字典结构。"""

        return {
            "conversation_id": conversation.conversation_uuid,
            "user_id": conversation.user_id,
            "title": conversation.title,
            "current_route": conversation.current_route,
            "current_status": conversation.current_status,
            "last_run_id": conversation.last_run_id,
            "metadata": conversation.metadata_json or {},
            "created_at": conversation.created_at,
            "updated_at": conversation.updated_at,
        }

    def _serialize_message(self, message: ConversationMessage, conversation_uuid: str) -> dict:
        """序列化消息对象。"""

        return {
            "message_id": message.message_uuid,
            "conversation_id": conversation_uuid,
            "role": message.role,
            "message_type": message.message_type,
            "content": message.content,
            "structured_content": message.structured_content or {},
            "related_run_id": message.related_run_id,
            "created_at": message.created_at,
        }

    def _get_conversation_model(self, conversation_id: str) -> Conversation | None:
        """在数据库模式下根据对外会话 ID 查找 ORM 对象。"""

        if not self._use_database():
            return None
        statement = select(Conversation).where(Conversation.conversation_uuid == conversation_id)
        return self.session.execute(statement).scalar_one_or_none()

    def create_conversation(
        self,
        user_id: int,
        title: str | None,
        current_route: str = "chat",
        current_status: str = "active",
    ) -> dict:
        """创建最小会话记录。"""

        if self._use_database():
            conversation = Conversation(
                conversation_uuid=_generate_prefixed_id("conv"),
                user_id=user_id,
                title=title,
                current_route=current_route,
                current_status=current_status,
                last_run_id=None,
                metadata_json={},
            )
            self.session.add(conversation)
            self.session.flush()
            self.session.refresh(conversation)
            return self._serialize_conversation(conversation)

        now = _utcnow()
        conversation_id = _generate_prefixed_id("conv")
        record = {
            "conversation_id": conversation_id,
            "user_id": user_id,
            "title": title,
            "current_route": current_route,
            "current_status": current_status,
            "last_run_id": None,
            "metadata": {},
            "created_at": now,
            "updated_at": now,
        }
        _CONVERSATIONS[conversation_id] = record
        _CONVERSATION_MESSAGES[conversation_id] = []
        return record

    def get_conversation(self, conversation_id: str) -> dict | None:
        """根据会话 ID 获取会话记录。"""

        if self._use_database():
            conversation = self._get_conversation_model(conversation_id)
            if conversation is None:
                return None
            return self._serialize_conversation(conversation)

        return _CONVERSATIONS.get(conversation_id)

    def update_conversation(self, conversation_id: str, **updates) -> dict | None:
        """更新会话记录。"""

        if self._use_database():
            conversation = self._get_conversation_model(conversation_id)
            if conversation is None:
                return None
            for key, value in updates.items():
                if key == "metadata":
                    setattr(conversation, "metadata_json", value)
                elif hasattr(conversation, key):
                    setattr(conversation, key, value)
            self.session.flush()
            self.session.refresh(conversation)
            return self._serialize_conversation(conversation)

        record = self.get_conversation(conversation_id)
        if record is None:
            return None

        record.update(updates)
        record["updated_at"] = _utcnow()
        return record

    def cancel_conversation(self, conversation_id: str) -> dict | None:
        """将会话标记为已取消。

        设计说明：
        - 当前阶段使用“状态取消”而不是“物理删除”；
        - 这样历史消息、澄清记录和运行轨迹仍可保留，便于后续 Trace 与审计；
        - Repository 只负责落库，不在这里扩展额外业务副作用。
        """

        return self.update_conversation(
            conversation_id,
            current_status="cancelled",
        )

    def list_conversations(
        self,
        page: int = 1,
        page_size: int = 20,
        status: str | None = None,
        user_id: int | None = None,
    ) -> tuple[list[dict], int]:
        """分页查询会话列表。

        参数中的 ``user_id`` 不是临时拼凑出来的过滤条件，
        而是为后续“权限前置”能力预留的最小边界。

        业务意义：
        1. 普通员工默认只能看到自己的多轮会话；
        2. 后续如果要支持管理员跨用户查看，也应该在上层 service 先完成授权判断，
           再决定这里是否传入用户过滤条件；
        3. 这样可以避免先把所有会话查出来再在 API 层过滤，减少越权数据泄露风险。
        """

        if self._use_database():
            statement = select(Conversation)
            if user_id is not None:
                statement = statement.where(Conversation.user_id == user_id)
            if status:
                statement = statement.where(Conversation.current_status == status)
            start = (page - 1) * page_size
            statement = statement.order_by(desc(Conversation.updated_at))
            rows = list(self.session.execute(statement).scalars())
            total = len(rows)
            return [self._serialize_conversation(item) for item in rows[start : start + page_size]], total

        items = list(_CONVERSATIONS.values())
        if user_id is not None:
            items = [item for item in items if item["user_id"] == user_id]
        if status:
            items = [item for item in items if item["current_status"] == status]

        items.sort(key=lambda item: item["updated_at"], reverse=True)
        total = len(items)
        start = (page - 1) * page_size
        end = start + page_size
        return items[start:end], total

    def add_message(
        self,
        conversation_id: str,
        role: str,
        message_type: str,
        content: str,
        related_run_id: str | None = None,
        structured_content: dict | None = None,
    ) -> dict:
        """向会话中追加一条消息。"""

        if self._use_database():
            conversation = self._get_conversation_model(conversation_id)
            if conversation is None:
                raise ValueError(f"Conversation not found: {conversation_id}")

            message = ConversationMessage(
                conversation_id=conversation.id,
                message_uuid=_generate_prefixed_id("msg"),
                role=role,
                message_type=message_type,
                content=content,
                structured_content=structured_content or {},
                related_run_id=related_run_id,
            )
            self.session.add(message)
            # 新消息到达后主动刷新会话更新时间，便于会话列表按最近活跃时间排序。
            conversation.updated_at = _utcnow()
            self.session.flush()
            self.session.refresh(message)
            return self._serialize_message(message, conversation_id)

        now = _utcnow()
        message = {
            "message_id": _generate_prefixed_id("msg"),
            "conversation_id": conversation_id,
            "role": role,
            "message_type": message_type,
            "content": content,
            "structured_content": structured_content or {},
            "related_run_id": related_run_id,
            "created_at": now,
        }
        _CONVERSATION_MESSAGES.setdefault(conversation_id, []).append(message)
        self.update_conversation(conversation_id)
        return message

    def list_messages(self, conversation_id: str) -> list[dict]:
        """读取会话消息列表。"""

        if self._use_database():
            conversation = self._get_conversation_model(conversation_id)
            if conversation is None:
                return []
            statement = (
                select(ConversationMessage)
                .where(ConversationMessage.conversation_id == conversation.id)
                .order_by(ConversationMessage.created_at.asc())
            )
            rows = list(self.session.execute(statement).scalars())
            return [self._serialize_message(item, conversation_id) for item in rows]

        return list(_CONVERSATION_MESSAGES.get(conversation_id, []))

    def upsert_memory(self, conversation_id: str, **updates) -> dict:
        """创建或更新会话记忆快照。"""

        if self._use_database():
            conversation = self._get_conversation_model(conversation_id)
            if conversation is None:
                raise ValueError(f"Conversation not found: {conversation_id}")

            statement = select(ConversationMemory).where(ConversationMemory.conversation_id == conversation.id)
            memory = self.session.execute(statement).scalar_one_or_none()
            if memory is None:
                memory = ConversationMemory(
                    conversation_id=conversation.id,
                    last_route=None,
                    last_agent=None,
                    last_primary_object=None,
                    last_metric=None,
                    last_time_range={},
                    last_org_scope={},
                    last_kb_scope={},
                    last_report_id=None,
                    last_contract_id=None,
                    short_term_memory={},
                )
                self.session.add(memory)

            for key, value in updates.items():
                if hasattr(memory, key):
                    setattr(memory, key, value)

            # 会话记忆的变化本质上也代表会话上下文发生了刷新。
            conversation.updated_at = _utcnow()
            self.session.flush()
            self.session.refresh(memory)
            return {
                "conversation_id": conversation_id,
                "last_route": memory.last_route,
                "last_agent": memory.last_agent,
                "last_primary_object": memory.last_primary_object,
                "last_metric": memory.last_metric,
                "last_time_range": memory.last_time_range or {},
                "last_org_scope": memory.last_org_scope or {},
                "last_kb_scope": memory.last_kb_scope or {},
                "last_report_id": memory.last_report_id,
                "last_contract_id": memory.last_contract_id,
                "short_term_memory": memory.short_term_memory or {},
                "updated_at": memory.updated_at,
            }

        memory = _CONVERSATION_MEMORIES.get(conversation_id)
        if memory is None:
            memory = {
                "conversation_id": conversation_id,
                "last_route": None,
                "last_agent": None,
                "last_primary_object": None,
                "last_metric": None,
                "last_time_range": {},
                "last_org_scope": {},
                "last_kb_scope": {},
                "last_report_id": None,
                "last_contract_id": None,
                "short_term_memory": {},
                "updated_at": _utcnow(),
            }
            _CONVERSATION_MEMORIES[conversation_id] = memory

        memory.update(updates)
        memory["updated_at"] = _utcnow()
        return memory

    def get_memory(self, conversation_id: str) -> dict | None:
        """读取会话记忆快照。

        业务意义：
        - 经营分析、多轮问答、合同审查后续都需要继承上一轮上下文；
        - 读取接口应该放在 Repository，而不是让上层业务直接摸 ORM 或内存字典；
        - 这样后续无论切数据库模式还是增加更多记忆字段，调用方都不需要改。
        """

        if self._use_database():
            conversation = self._get_conversation_model(conversation_id)
            if conversation is None:
                return None

            statement = select(ConversationMemory).where(ConversationMemory.conversation_id == conversation.id)
            memory = self.session.execute(statement).scalar_one_or_none()
            if memory is None:
                return None
            return {
                "conversation_id": conversation_id,
                "last_route": memory.last_route,
                "last_agent": memory.last_agent,
                "last_primary_object": memory.last_primary_object,
                "last_metric": memory.last_metric,
                "last_time_range": memory.last_time_range or {},
                "last_org_scope": memory.last_org_scope or {},
                "last_kb_scope": memory.last_kb_scope or {},
                "last_report_id": memory.last_report_id,
                "last_contract_id": memory.last_contract_id,
                "short_term_memory": memory.short_term_memory or {},
                "updated_at": memory.updated_at,
            }

        memory = _CONVERSATION_MEMORIES.get(conversation_id)
        if memory is None:
            return None
        return dict(memory)
