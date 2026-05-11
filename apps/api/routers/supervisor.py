"""
Supervisor API - 基于 python_a2a 的标准化总控服务

Supervisor 职责：
1. 意图识别
2. Agent 路由
3. 直接 HTTP 调用 Agent（不用 AgentNetwork）

使用 python_a2a 客户端直接调用各 Agent 的 A2A 端点。

启动方式：
```bash
uvicorn apps.api.routers.supervisor:app --host 0.0.0.0 --port 8000
```

Author: Enterprise Knowledge Agentic RAG Platform
"""

from __future__ import annotations

import logging
import os
import uuid
from typing import Any, Optional

from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from core.agent.intent_detector import IntentDetector, IntentType
from core.agent.routing_engine import get_routing_engine
from core.common.events import sse_event_stream

logger = logging.getLogger(__name__)


# ============================================================================
# A2A 客户端 - 使用 python_a2a 库
# ============================================================================

from python_a2a import A2AClient as BaseA2AClient


class A2AClient:
    """
    A2A 客户端 - 基于 python_a2a 库

    封装 python_a2a.A2AClient，支持 K8s 环境变量覆盖和 Agent 服务发现。
    简化调用方式，直接传入 agent_name 和 message。
    """

    def __init__(self, namespace: str = "enterprise-agent"):
        """
        初始化 A2A 客户端

        Args:
            namespace: K8s 命名空间
        """
        from python_a2a import Task, Message, TextContent, MessageRole

        self.namespace = namespace
        self._Message = Message
        self._TextContent = TextContent
        self._MessageRole = MessageRole
        self._Task = Task

        # Agent 端点配置（K8s DNS）
        self._agent_endpoints = {
            "rag-agent": os.environ.get(
                "RAG_AGENT_URL",
                f"http://rag-agent-svc.{namespace}.svc.cluster.local:6001"
            ),
            "analytics-agent": os.environ.get(
                "ANALYTICS_AGENT_URL",
                f"http://analytics-agent-svc.{namespace}.svc.cluster.local:6002"
            ),
            "contract-agent": os.environ.get(
                "CONTRACT_AGENT_URL",
                f"http://contract-agent-svc.{namespace}.svc.cluster.local:6003"
            ),
            "policy-agent": os.environ.get(
                "POLICY_AGENT_URL",
                f"http://policy-agent-svc.{namespace}.svc.cluster.local:6004"
            ),
        }

        # 初始化基类 A2A 客户端
        self._base_client = BaseA2AClient(self._agent_endpoints)

    def get_agent_url(self, agent_name: str) -> str:
        """获取 Agent URL"""
        return self._agent_endpoints.get(agent_name, "")

    async def send_task(
        self,
        agent_name: str,
        message: str,
        *,
        task_id: Optional[str] = None,
        trace_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
        user_id: str = "anonymous",
        user_role: str = "user",
        department_code: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> dict:
        """
        发送任务到 Agent

        Args:
            agent_name: Agent 名称
            message: 用户消息
            task_id: 任务 ID
            trace_id: 追踪 ID
            conversation_id: 会话 ID
            user_id: 用户 ID
            user_role: 用户角色
            department_code: 部门代码
            metadata: 额外元数据

        Returns:
            Agent 响应 (dict)
        """
        # 构建 A2A 消息（参考 agent_learn 示例）
        a2a_message = self._Message(
            content=self._TextContent(text=message),
            role=self._MessageRole.USER,
            conversation_id=conversation_id,
        )

        # 构建 A2A 任务
        a2a_task = self._Task(
            id=task_id or f"task_{uuid.uuid4().hex[:12]}",
            message=a2a_message.to_dict(),
            metadata={
                "user_id": user_id,
                "user_role": user_role,
                "department_code": department_code,
                "trace_id": trace_id,
                "conversation_id": conversation_id,
                **(metadata or {}),
            },
        )

        # 调用 python_a2a 的 send_task_async
        try:
            response = await self._base_client.send_task_async(
                agent_name=agent_name,
                task=a2a_task,
            )
            # 返回 dict 格式
            if hasattr(response, 'to_dict'):
                return response.to_dict()
            return response
        except Exception as e:
            logger.error(f"[{agent_name}] A2A call failed: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# 请求/响应模型
# ============================================================================

class ChatRequest(BaseModel):
    """聊天请求"""
    query: str = Field(description="用户问题")
    conversation_id: Optional[str] = Field(default=None, description="会话 ID")
    user_id: str = Field(default="anonymous", description="用户 ID")
    user_role: str = Field(default="user", description="用户角色")
    department_code: Optional[str] = Field(default=None, description="部门代码")

    # 合同审查相关参数
    contract_file_id: Optional[str] = Field(
        default=None,
        description="合同文件 ID（用于合同审查场景）"
    )
    contract_name: Optional[str] = Field(
        default=None,
        description="合同名称"
    )
    contract_type: Optional[str] = Field(
        default=None,
        description="合同类型"
    )


class ChatResponse(BaseModel):
    """聊天响应"""
    run_id: str
    trace_id: str
    conversation_id: Optional[str]
    intent: str
    # 是否需要 SSE 订阅（RAG 等快速场景同步返回时为 false）
    needs_sse: bool = False
    # SSE 模式下的完整结果（同步返回时直接返回）
    answer: Optional[str] = None
    status: str
    routing_target: str
    needs_clarification: bool = False
    clarification_questions: list[str] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)


# ============================================================================
# FastAPI 应用
# ============================================================================

app = FastAPI(
    title="Supervisor API",
    description="统一入口路由服务 - 意图识别、Agent 路由",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 全局组件
_intent_detector = IntentDetector()
_routing_engine = get_routing_engine()
_a2a_client = A2AClient()


# ============================================================================
# API 路由
# ============================================================================

router = APIRouter(prefix="/api/v1", tags=["supervisor"])


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    """
    统一聊天接口

    设计说明：
    1. 所有场景都推送 SSE 进度（只是快慢不同）
    2. needs_sse 控制是否通过 SSE 推送最终结果：
       - needs_sse=true：结果通过 SSE complete 事件推送，前端订阅 SSE 获取结果
       - needs_sse=false：结果在 HTTP 响应中返回，前端直接使用
    3. 合同审查场景：如果提供 contract_file_id，强制路由到合同审查流程
    """
    run_id = f"run_{uuid.uuid4().hex[:12]}"
    trace_id = f"tr_{uuid.uuid4().hex[:12]}"
    conversation_id = request.conversation_id or f"conv_{uuid.uuid4().hex[:12]}"

    logger.info(f"[{run_id}] Chat request: {request.query[:50]}...")

    # 1. 检查是否需要合同审查
    if request.contract_file_id:
        # 强制路由到合同审查
        agent_name = "contract-agent"
        logger.info(f"[{run_id}] 强制路由到合同审查: contract_file_id={request.contract_file_id}")
    else:
        # 2. 意图识别
        intent_result = _intent_detector.detect(request.query)
        logger.info(f"[{run_id}] Intent: {intent_result.intent_type.value}")

        # 3. 检查澄清
        if intent_result.requires_clarification:
            return ChatResponse(
                run_id=run_id,
                trace_id=trace_id,
                conversation_id=conversation_id,
                intent=intent_result.intent_type.value,
                status="awaiting_clarification",
                routing_target=intent_result.routing_target,
                needs_sse=False,
                needs_clarification=True,
                clarification_questions=intent_result.clarification_questions,
                metadata={"slots": intent_result.slots.model_dump()},
            )

        # 4. 路由决策
        route_decision = _routing_engine.route(intent_result)
        agent_name = route_decision.target.agent_name

    logger.info(f"[{run_id}] Routed to: {agent_name}")

    # 5. 判断是否需要 SSE 推送结果
    # Analytics/Contract 等慢速场景需要 SSE 推送结构化结果
    needs_sse = agent_name in {"analytics-agent", "contract-agent"}

    # 6. 构建元数据
    metadata = {
        "trace_id": trace_id,
        "conversation_id": conversation_id,
        "user_id": request.user_id,
        "user_role": request.user_role,
        "department_code": request.department_code,
    }

    # 如果是合同审查，添加合同相关元数据
    if request.contract_file_id:
        metadata["contract_file_id"] = request.contract_file_id
        metadata["contract_name"] = request.contract_name
        metadata["contract_type"] = request.contract_type

    # 7. 调用 Agent
    try:
        result = await _a2a_client.send_task(
            agent_name=agent_name,
            message=request.query,
            task_id=run_id,
            trace_id=trace_id,
            conversation_id=conversation_id,
            user_id=request.user_id,
            user_role=request.user_role,
            department_code=request.department_code,
            metadata=metadata,
        )

        if needs_sse:
            # 慢速场景：返回 run_id，前端订阅 SSE 获取结果
            return ChatResponse(
                run_id=run_id,
                trace_id=trace_id,
                conversation_id=conversation_id,
                intent="contract_review" if request.contract_file_id else intent_result.intent_type.value,
                needs_sse=True,
                status="processing",
                routing_target=agent_name,
                metadata={
                    "message": "任务已提交，请订阅 SSE 获取进度和结果"
                },
            )
        else:
            # 快速场景（RAG 等）：同步返回完整结果
            answer = result.get("answer") or result.get("result", {}).get("answer", "")

            return ChatResponse(
                run_id=run_id,
                trace_id=trace_id,
                conversation_id=conversation_id,
                intent=intent_result.intent_type.value if not request.contract_file_id else "contract_review",
                needs_sse=False,
                answer=answer,
                status="succeeded",
                routing_target=agent_name,
                metadata=result,
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[{run_id}] Agent call failed: {e}", exc_info=True)
        return ChatResponse(
            run_id=run_id,
            trace_id=trace_id,
            conversation_id=conversation_id,
            intent="contract_review" if request.contract_file_id else intent_result.intent_type.value,
            needs_sse=False,
            answer="处理失败，请稍后重试。",
            status="failed",
            routing_target=agent_name,
            metadata={"error": str(e)},
        )


@router.get("/intent/detect")
async def detect_intent(query: str) -> dict:
    """意图检测接口"""
    result = _intent_detector.detect(query)
    return {
        "intent_type": result.intent_type.value,
        "confidence": result.confidence,
        "routing_target": result.routing_target,
        "requires_clarification": result.requires_clarification,
        "clarification_questions": result.clarification_questions,
        "slots": result.slots.model_dump(),
    }


@router.get("/agents")
async def list_agents() -> dict:
    """列出可用 Agent"""
    return {
        "agents": list(_a2a_client._agent_endpoints.keys()),
        "total": len(_a2a_client._agent_endpoints),
    }


@router.get("/health")
async def health_check() -> dict:
    """健康检查"""
    return {"status": "healthy", "service": "supervisor"}


# ============================================================================
# SSE 流式推送端点
# ============================================================================

@router.get("/stream/{run_id}")
async def stream_progress(run_id: str) -> StreamingResponse:
    """
    SSE 流式进度推送端点

    订阅指定 run_id 的事件流，通过 SSE 推送给前端。

    支持多 Agent 并行推送进度：
    - Analytics Agent: 推送 SQL 构建、图表生成等进度
    - RAG Agent: 推送检索、答案生成等进度
    - Contract Agent: 推送合同解析、风险分析等进度

    前端订阅方式：
    ```javascript
    const eventSource = new EventSource(`/api/v1/stream/${run_id}`);
    eventSource.addEventListener('progress', (e) => {
        const data = JSON.parse(e.data);
        console.log(data); // {run_id, stage, progress, message, ...}
    });
    eventSource.addEventListener('summary_done', (e) => {
        const data = JSON.parse(e.data);
        // 收到摘要数据
    });
    eventSource.addEventListener('completed', (e) => {
        const data = JSON.parse(e.data);
        // 任务完成
    });
    ```

    Returns:
        SSE 流
    """
    return StreamingResponse(
        sse_event_stream(run_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # 禁用 Nginx 缓冲
        },
    )


@router.get("/stream/{run_id}/progress")
async def get_progress_status(run_id: str) -> dict:
    """
    获取任务进度状态（非 SSE）

    用于轮询场景或检查任务是否存在。

    Returns:
        进度状态
    """
    from core.common.events.consumer import AgentEventConsumer

    consumer = AgentEventConsumer()
    stream_key = f"events:{run_id}"

    try:
        await consumer.connect()
        exists = await consumer.client.exists(stream_key)

        if not exists:
            return {
                "run_id": run_id,
                "exists": False,
                "message": "Task not found or expired",
            }

        # 获取最新消息
        messages = await consumer.client.xrange(stream_key, count=1)
        if messages:
            _, fields = messages[0]
            event_data = fields.get("event", "{}")
            return {
                "run_id": run_id,
                "exists": True,
                "message": "Task is running",
            }

        return {
            "run_id": run_id,
            "exists": True,
            "message": "Task is waiting",
        }

    finally:
        await consumer.close()


# ============================================================================
# 主入口
# ============================================================================

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "apps.api.routers.supervisor:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
    )
