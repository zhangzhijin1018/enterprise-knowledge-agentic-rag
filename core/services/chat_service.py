"""智能问答 Service。

当前阶段不接真实 LLM / RAG / LangGraph，
但要先把“接口层如何进入统一工作流门面”这条边界打通。

这样后续把 mock 替换成真实工作流时，外层 API 契约基本不需要再变。
"""

from __future__ import annotations

from apps.api.schemas.chat import ChatRequest
from core.agent.workflow import ChatWorkflowFacade
from core.security.auth import UserContext


class ChatService:
    """最小智能问答应用服务。

    当前 Service 不再直接承载分支判断和状态流转，
    而是把“执行 chat 工作流”委托给独立的 workflow facade。

    这样做的原因：
    - Service 继续只负责应用层入口职责；
    - 工作流细节集中在 agent/workflow 层；
    - 后续接真实 LangGraph 时，只需要优先替换 facade。
    """

    def __init__(self, chat_workflow_facade: ChatWorkflowFacade) -> None:
        """显式注入 chat 工作流门面。"""

        self.chat_workflow_facade = chat_workflow_facade

    def submit_chat(self, payload: ChatRequest, user_context: UserContext) -> dict:
        """处理最小问答请求。"""

        return self.chat_workflow_facade.execute_chat(
            payload=payload,
            user_context=user_context,
        )
