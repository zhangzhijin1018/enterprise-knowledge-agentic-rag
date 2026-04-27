"""ChatWorkflowFacade 单元测试。

当前测试重点不是重复验证整个 API 闭环，
而是验证“工作流门面层”本身已经承载了关键工作流职责：
1. 能根据问题路由到不同场景；
2. 能驱动 task_run 的状态与路由结果落库；
3. 能在缺槽位时进入 clarification，而不是让 service 自己分支判断。
"""

from apps.api.schemas.chat import ChatRequest
from core.agent.workflow import ChatWorkflowFacade
from core.repositories.conversation_repository import ConversationRepository
from core.repositories.conversation_repository import reset_in_memory_conversation_store
from core.repositories.task_run_repository import TaskRunRepository
from core.repositories.task_run_repository import reset_in_memory_task_run_store
from core.security.auth import UserContext


def setup_function() -> None:
    """每个测试前清空内存存储。"""

    reset_in_memory_conversation_store()
    reset_in_memory_task_run_store()


def build_mock_user_context() -> UserContext:
    """构造测试使用的最小用户上下文。"""

    return UserContext(
        user_id=1,
        username="workflow_user",
        display_name="Workflow User",
        roles=["employee"],
    )


def test_workflow_facade_routes_policy_question_to_policy_qa() -> None:
    """制度类问题应由工作流门面路由到 policy_qa，并成功生成回答。"""

    conversation_repository = ConversationRepository()
    task_run_repository = TaskRunRepository()
    workflow_facade = ChatWorkflowFacade(
        conversation_repository=conversation_repository,
        task_run_repository=task_run_repository,
    )

    result = workflow_facade.execute_chat(
        payload=ChatRequest(
            query="集团新能源业务有哪些核心制度？",
            conversation_id=None,
            history_messages=[],
            business_hint=None,
            knowledge_base_ids=[],
            stream=False,
        ),
        user_context=build_mock_user_context(),
    )

    run_id = result["meta"]["run_id"]
    task_run = task_run_repository.get_task_run(run_id)

    assert result["meta"]["status"] == "succeeded"
    assert task_run is not None
    assert task_run["route"] == "policy_qa"
    assert task_run["selected_agent"] == "mock_policy_agent"


def test_workflow_facade_routes_analytics_question_to_clarification() -> None:
    """经营分析但缺指标的问题应由工作流门面进入 clarification 分支。"""

    conversation_repository = ConversationRepository()
    task_run_repository = TaskRunRepository()
    workflow_facade = ChatWorkflowFacade(
        conversation_repository=conversation_repository,
        task_run_repository=task_run_repository,
    )

    result = workflow_facade.execute_chat(
        payload=ChatRequest(
            query="帮我分析经营情况",
            conversation_id=None,
            history_messages=[],
            business_hint=None,
            knowledge_base_ids=[],
            stream=False,
        ),
        user_context=build_mock_user_context(),
    )

    run_id = result["meta"]["run_id"]
    task_run = task_run_repository.get_task_run(run_id)

    assert result["meta"]["status"] == "awaiting_user_clarification"
    assert task_run is not None
    assert task_run["route"] == "business_analysis"
    assert task_run["selected_agent"] == "mock_business_analysis_agent"
