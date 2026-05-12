"""
Supervisor API - 基于 python_a2a 的标准化总控服务

Supervisor 职责：
1. 意图识别（支持 LLM + 规则双模式）
2. Agent 路由
3. 直接 HTTP 调用 Agent（不用 AgentNetwork）

双模式设计：
- USE_LLM_INTENT_DETECTION=true：纯 LLM 检测 + 置信度自适应处理
- 默认：规则 + 上下文感知检测

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

from core.agent.context_aware_intent_detector import ContextAwareIntentDetector
from core.agent.confidence_handler import ConfidenceHandler, HandlingStrategy
from core.agent.llm_only_intent_detector import LLMIntentDetector
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
        from python_a2a import Task, Message, TextContent, MessageRole

        self.namespace = namespace
        self._Message = Message
        self._TextContent = TextContent
        self._MessageRole = MessageRole
        self._Task = Task

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

        self._base_client = BaseA2AClient(self._agent_endpoints)

    def get_agent_url(self, agent_name: str) -> str:
        """获取 Agent URL"""
        return self._agent_endpoints.get(agent_name, "")

    async def send_task(
        self,
        agent_name: str,
        message: str,
        task_id: str,
        trace_id: str,
        conversation_id: str,
        user_id: str,
        user_role: str,
        department_code: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> dict:
        """发送任务到 Agent"""
        try:
            endpoint = self.get_agent_url(agent_name)
            if not endpoint:
                logger.warning(f"[{task_id}] Agent {agent_name} endpoint not found")
                return {"error": f"Agent {agent_name} not found"}

            logger.info(f"[{task_id}] Sending task to {agent_name}: {endpoint}")

            message_obj = self._Message(
                content=self._TextContent(text=message),
                role=self._MessageRole.USER,
            )

            task = self._Task(
                id=task_id,
                message=message_obj,
                session_id=conversation_id,
            )

            result = await self._base_client.send_task(endpoint, task)

            if hasattr(result, 'message') and hasattr(result.message, 'content'):
                return {"answer": result.message.content.text}

            return {"result": result}

        except Exception as e:
            logger.error(f"[{task_id}] Failed to send task to {agent_name}: {e}")
            return {"error": str(e)}


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

    # 上下文信息（用于多轮对话的意图继承）
    previous_intent: Optional[str] = Field(
        default=None,
        description="上一轮意图类型（用于意图继承）"
    )
    previous_domain: Optional[str] = Field(
        default=None,
        description="上一轮业务域（用于域一致性判断）"
    )
    previous_slots: Optional[dict] = Field(
        default=None,
        description="上一轮槽位（用于槽位补全）"
    )


class ChatResponse(BaseModel):
    """聊天响应"""
    run_id: str
    trace_id: str
    conversation_id: Optional[str]
    intent: str
    # 置信度信息
    confidence: float = Field(default=0.0, description="意图识别置信度")
    confidence_breakdown: Optional[dict] = Field(
        default=None,
        description="置信度分解（每个因子的贡献）"
    )
    # 是否需要 SSE 订阅
    needs_sse: bool = False
    answer: Optional[str] = None
    status: str
    routing_target: str
    needs_clarification: bool = False
    clarification_questions: list[str] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)
    # 代词消解信息
    pronoun_resolved: bool = Field(default=False, description="是否进行了代词消解")
    resolved_query: Optional[str] = Field(default=None, description="代词消解后的查询")


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
_context_aware_detector = ContextAwareIntentDetector()
_routing_engine = get_routing_engine()
_a2a_client = A2AClient()

# LLM 意图检测和置信度处理器（按需初始化）
_llm_detector: Optional[LLMIntentDetector] = None
_confidence_handler: Optional[ConfidenceHandler] = None
_use_llm_detection: bool = os.environ.get("USE_LLM_INTENT_DETECTION", "false").lower() == "true"


def _get_llm_detector() -> LLMIntentDetector:
    """获取或创建 LLM 意图检测器（懒加载）"""
    global _llm_detector
    if _llm_detector is None:
        _llm_detector = LLMIntentDetector(
            llm_gateway=_get_llm_gateway(),
            cache=_get_cache(),
        )
    return _llm_detector


def _get_confidence_handler() -> ConfidenceHandler:
    """获取或创建置信度处理器（懒加载）"""
    global _confidence_handler
    if _confidence_handler is None:
        _confidence_handler = ConfidenceHandler(
            fallback_detector=_context_aware_detector,
        )
    return _confidence_handler


def _get_llm_gateway():
    """获取 LLM 网关（待实现）"""
    # TODO: 接入实际的 LLM 网关
    # 例如：from core.llm_gateway import get_llm_gateway
    return None


def _get_cache():
    """获取缓存客户端（待实现）"""
    # TODO: 接入 Redis 等缓存
    # 例如：return await get_redis_client()
    return None


# ============================================================================
# API 路由
# ============================================================================

router = APIRouter(prefix="/api/v1", tags=["supervisor"])


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    """
    统一聊天接口

    设计说明：
    1. 支持两种意图检测模式：
       - USE_LLM_INTENT_DETECTION=true：纯 LLM 检测 + 置信度自适应处理
       - 默认：规则 + 上下文感知检测
    2. 置信度自适应处理：
       - >= 0.80：立即执行
       - 0.60-0.80：谨慎执行（带风险警告）
       - < 0.60：请求澄清或多意图候选
    3. 支持上下文继承和代词消解
    """
    run_id = f"run_{uuid.uuid4().hex[:12]}"
    trace_id = f"tr_{uuid.uuid4().hex[:12]}"
    conversation_id = request.conversation_id or f"conv_{uuid.uuid4().hex[:12]}"

    logger.info(f"[{run_id}] Chat request: {request.query[:50]}...")

    # 1. 检查是否需要合同审查
    if request.contract_file_id:
        agent_name = "contract-agent"
        logger.info(f"[{run_id}] 强制路由到合同审查: contract_file_id={request.contract_file_id}")

        intent_result = await _context_aware_detector.detect(
            query=request.query,
            conversation_id=conversation_id,
            user_id=request.user_id,
            previous_intent=request.previous_intent,
            previous_domain=request.previous_domain,
            previous_slots=request.previous_slots,
        )
        intent_type_str = "contract_review"
        confidence = intent_result.get("confidence", 0.0)
        confidence_breakdown = intent_result.get("confidence_breakdown")
        pronoun_resolved = intent_result.get("pronoun_resolved", False)
        resolved_query = intent_result.get("resolved_query")
        decision = None
    else:
        # 2. 意图识别
        if _use_llm_detection:
            intent_result, decision = await _llm_intent_detection(request, run_id, conversation_id)
        else:
            intent_result, decision = await _rule_based_intent_detection(request, run_id, conversation_id)

        intent_type_str = intent_result.get("intent_type", "rag_qa")
        confidence = intent_result.get("confidence", 0.0)
        confidence_breakdown = intent_result.get("confidence_breakdown")
        requires_clarification = intent_result.get("requires_clarification", False)
        clarification_questions = intent_result.get("clarification_questions", [])
        routing_target = intent_result.get("routing_target", "rag_agent")
        slots = intent_result.get("slots", {})
        pronoun_resolved = intent_result.get("pronoun_resolved", False)
        resolved_query = intent_result.get("resolved_query")

        logger.info(f"[{run_id}] Intent: {intent_type_str}, confidence: {confidence:.3f}")

        # 3. 检查置信度处理决策
        if decision and not decision.can_execute:
            return _build_clarification_response(
                run_id=run_id,
                trace_id=trace_id,
                conversation_id=conversation_id,
                intent_type_str=intent_type_str,
                confidence=confidence,
                confidence_breakdown=confidence_breakdown,
                decision=decision,
                routing_target=routing_target,
                slots=slots,
                pronoun_resolved=pronoun_resolved,
                resolved_query=resolved_query,
            )

        # 4. 路由决策
        route_decision = _routing_engine.route(intent_result)
        agent_name = route_decision.target.agent_name

    logger.info(f"[{run_id}] Routed to: {agent_name}")

    # 5. 判断是否需要 SSE 推送结果
    needs_sse = agent_name in {"analytics-agent", "contract-agent"}

    # 6. 构建元数据
    metadata = {
        "trace_id": trace_id,
        "conversation_id": conversation_id,
        "user_id": request.user_id,
        "user_role": request.user_role,
        "department_code": request.department_code,
    }

    intent_type_str = "contract_review" if request.contract_file_id else intent_type_str

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
            return ChatResponse(
                run_id=run_id,
                trace_id=trace_id,
                conversation_id=conversation_id,
                intent=intent_type_str,
                confidence=confidence,
                confidence_breakdown=confidence_breakdown,
                needs_sse=True,
                status="processing",
                routing_target=agent_name,
                metadata={"message": "任务已提交，请订阅 SSE 获取进度和结果"},
                pronoun_resolved=pronoun_resolved,
                resolved_query=resolved_query,
            )
        else:
            answer = result.get("answer") or result.get("result", {}).get("answer", "")

            return ChatResponse(
                run_id=run_id,
                trace_id=trace_id,
                conversation_id=conversation_id,
                intent=intent_type_str,
                confidence=confidence,
                confidence_breakdown=confidence_breakdown,
                needs_sse=False,
                answer=answer,
                status="succeeded",
                routing_target=agent_name,
                metadata=result,
                pronoun_resolved=pronoun_resolved,
                resolved_query=resolved_query,
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[{run_id}] Agent call failed: {e}", exc_info=True)
        return ChatResponse(
            run_id=run_id,
            trace_id=trace_id,
            conversation_id=conversation_id,
            intent=intent_type_str,
            confidence=confidence,
            confidence_breakdown=confidence_breakdown,
            needs_sse=False,
            answer="处理失败，请稍后重试。",
            status="failed",
            routing_target=agent_name,
            metadata={"error": str(e)},
            pronoun_resolved=pronoun_resolved,
            resolved_query=resolved_query,
        )


# ============================================================================
# 辅助函数
# ============================================================================

async def _llm_intent_detection(
    request: ChatRequest,
    run_id: str,
    conversation_id: str,
) -> tuple[dict, Any]:
    """
    纯 LLM 意图检测 + 置信度自适应处理
    """
    try:
        llm_detector = _get_llm_detector()
        llm_gateway = _get_llm_gateway()

        if llm_gateway is None:
            logger.warning(f"[{run_id}] LLM 网关未配置，降级到规则检测")
            return await _rule_based_intent_detection(request, run_id, conversation_id)

        history = await _get_conversation_history(conversation_id)

        prediction = await llm_detector.detect(
            query=request.query,
            conversation_history=history,
            previous_intent=request.previous_intent,
            previous_slots=request.previous_slots,
        )

        handler = _get_confidence_handler()
        decision = handler.handle(
            intent_prediction=prediction,
            user_query=request.query,
            business_domain=prediction.business_domain.value if prediction.business_domain else None,
        )

        intent_result = {
            "intent_type": prediction.intent_type.value,
            "confidence": prediction.confidence,
            "confidence_breakdown": {
                "final_score": prediction.confidence,
                "reasoning": prediction.reasoning,
            },
            "routing_target": prediction.routing_target,
            "slots": prediction.extracted_slots,
            "requires_clarification": decision.can_execute is False,
            "clarification_questions": decision.clarification_questions,
            "pronoun_resolved": prediction.refers_to_previous,
            "resolved_query": request.query,
        }

        logger.info(
            f"[{run_id}] LLM 检测: intent={prediction.intent_type.value}, "
            f"confidence={prediction.confidence:.3f}, "
            f"strategy={decision.strategy.value}"
        )

        return intent_result, decision

    except Exception as e:
        logger.error(f"[{run_id}] LLM 意图检测失败: {e}", exc_info=True)
        return await _rule_based_intent_detection(request, run_id, conversation_id)


async def _rule_based_intent_detection(
    request: ChatRequest,
    run_id: str,
    conversation_id: str,
) -> tuple[dict, None]:
    """
    规则 + 上下文感知意图检测
    """
    intent_result = await _context_aware_detector.detect(
        query=request.query,
        conversation_id=conversation_id,
        user_id=request.user_id,
        previous_intent=request.previous_intent,
        previous_domain=request.previous_domain,
        previous_slots=request.previous_slots,
    )

    return intent_result, None


async def _get_conversation_history(conversation_id: str) -> list[dict]:
    """获取对话历史"""
    # TODO: 从数据库或缓存获取对话历史
    return []


def _build_clarification_response(
    run_id: str,
    trace_id: str,
    conversation_id: str,
    intent_type_str: str,
    confidence: float,
    confidence_breakdown: dict,
    decision: Any,
    routing_target: str,
    slots: dict,
    pronoun_resolved: bool,
    resolved_query: Optional[str],
) -> ChatResponse:
    """构建澄清响应"""
    clarification_questions = list(decision.clarification_questions)

    if decision.strategy == HandlingStrategy.MULTI_INTENT_CANDIDATES:
        clarification_questions = [
            "您的问题可能有多种理解，请选择或确认您的意图：",
        ]
        for i, alt in enumerate(decision.alternative_intents[:3]):
            clarification_questions.append(
                f"{i+1}. {alt.get('reasoning', alt.get('intent_type', '未知意图'))}"
            )

    return ChatResponse(
        run_id=run_id,
        trace_id=trace_id,
        conversation_id=conversation_id,
        intent=intent_type_str,
        confidence=confidence,
        confidence_breakdown=confidence_breakdown,
        status="awaiting_clarification",
        routing_target=routing_target,
        needs_sse=False,
        needs_clarification=True,
        clarification_questions=clarification_questions,
        metadata={
            "slots": slots,
            "confidence_strategy": decision.strategy.value,
            "risk_warning": decision.risk_warning,
        },
        pronoun_resolved=pronoun_resolved,
        resolved_query=resolved_query,
    )
