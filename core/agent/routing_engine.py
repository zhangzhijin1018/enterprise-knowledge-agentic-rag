"""
任务路由引擎

基于意图检测结果，决策由哪个 Agent/MCP 处理请求：
1. 本地执行 vs 远程 A2A 委托
2. Agent 选择
3. 降级策略

设计说明：
- 路由决策基于意图类型和 Agent 能力
- 支持静态配置和动态服务发现
- 提供降级和回退机制

Author: Enterprise Knowledge Agentic RAG Platform
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional

import httpx

from .intent_detector import IntentResult, IntentType

logger = logging.getLogger(__name__)


# ============================================================================
# 路由决策类型
# ============================================================================

class ExecutionMode(str, Enum):
    """执行模式"""
    LOCAL = "local"           # 本地执行
    A2A = "a2a"               # A2A 远程调用
    MCP = "mcp"               # MCP 调用
    FALLBACK = "fallback"     # 降级处理


# ============================================================================
# 路由目标定义
# ============================================================================

@dataclass
class RoutingTarget:
    """
    路由目标定义

    包含：
    - agent_name: Agent 名称
    - execution_mode: 执行模式
    - endpoint: 调用端点
    - fallback_targets: 降级目标列表
    """
    agent_name: str
    execution_mode: ExecutionMode
    endpoint: str
    fallback_targets: list[str] = None
    timeout: int = 300
    retry_count: int = 3


@dataclass
class RouteDecision:
    """
    路由决策结果

    包含：
    - target: 路由目标
    - reason: 决策原因
    - can_fallback: 是否支持降级
    """
    target: RoutingTarget
    reason: str
    can_fallback: bool = True


# ============================================================================
# 路由引擎
# ============================================================================

class RoutingEngine:
    """
    任务路由引擎

    职责：
    1. 根据意图类型选择合适的 Agent
    2. 决定执行模式（本地/A2A/MCP）
    3. 提供降级策略
    4. 管理 Agent 注册表

    设计说明：
    - 支持静态配置（环境变量、配置文件）
    - 支持动态服务发现（K8s DNS）
    - 提供统一的路由接口
    """

    # 默认 Agent 端点配置
    DEFAULT_ENDPOINTS = {
        "rag-agent": {
            "url": "http://rag-agent-svc.default.svc.cluster.local:6001",
            "mode": ExecutionMode.A2A,
            "timeout": 300,
        },
        "analytics-agent": {
            "url": "http://analytics-agent-svc.default.svc.cluster.local:6002",
            "mode": ExecutionMode.A2A,
            "timeout": 300,
        },
        "contract-agent": {
            "url": "http://contract-agent-svc.default.svc.cluster.local:6003",
            "mode": ExecutionMode.A2A,
            "timeout": 300,
        },
        "policy-agent": {
            "url": "http://policy-agent-svc.default.svc.cluster.local:6004",
            "mode": ExecutionMode.A2A,
            "timeout": 300,
        },
        "sql-mcp": {
            "url": "http://sql-mcp-svc.default.svc.cluster.local:5001",
            "mode": ExecutionMode.MCP,
            "timeout": 60,
        },
        "report-mcp": {
            "url": "http://report-mcp-svc.default.svc.cluster.local:5002",
            "mode": ExecutionMode.MCP,
            "timeout": 120,
        },
    }

    def __init__(self, namespace: str = "default"):
        """
        初始化路由引擎

        Args:
            namespace: K8s 命名空间
        """
        self.namespace = namespace
        self._agent_registry: dict[str, RoutingTarget] = {}
        self._initialize_default_routes()

    def _initialize_default_routes(self) -> None:
        """初始化默认路由"""
        for agent_name, config in self.DEFAULT_ENDPOINTS.items():
            import os

            # 检查环境变量覆盖
            env_key = f"{agent_name.upper().replace('-', '_')}_URL"
            url = os.environ.get(env_key, config["url"])

            self._agent_registry[agent_name] = RoutingTarget(
                agent_name=agent_name,
                execution_mode=config["mode"],
                endpoint=f"{url}/a2a",  # python_a2a 标准端点
                timeout=config.get("timeout", 300),
            )

    def register_agent(
        self,
        agent_name: str,
        endpoint: str,
        execution_mode: ExecutionMode = ExecutionMode.A2A,
        timeout: int = 300,
    ) -> None:
        """
        注册 Agent

        Args:
            agent_name: Agent 名称
            endpoint: 调用端点
            execution_mode: 执行模式
            timeout: 超时时间
        """
        self._agent_registry[agent_name] = RoutingTarget(
            agent_name=agent_name,
            execution_mode=execution_mode,
            endpoint=endpoint,
            timeout=timeout,
        )
        logger.info(f"Registered agent: {agent_name} -> {endpoint}")

    def unregister_agent(self, agent_name: str) -> bool:
        """取消注册 Agent"""
        if agent_name in self._agent_registry:
            del self._agent_registry[agent_name]
            return True
        return False

    def route(self, intent_result) -> RouteDecision:
        """
        根据意图结果路由请求

        Args:
            intent_result: 意图识别结果（支持 IntentResult 对象或 dict）

        Returns:
            RouteDecision: 路由决策
        """
        # 支持 IntentResult 对象和 dict 两种格式
        if hasattr(intent_result, 'intent_type'):
            # IntentResult 对象格式
            intent_type = intent_result.intent_type
            routing_target = intent_result.routing_target
        else:
            # dict 格式（来自上下文感知意图检测器）
            intent_type_str = intent_result.get("intent_type", "rag_qa")
            routing_target = intent_result.get("routing_target", "rag_agent")

            # 将字符串转换为 IntentType
            try:
                intent_type = IntentType(intent_type_str)
            except ValueError:
                intent_type = IntentType.RAG_QA

        # 检查目标是否存在
        if routing_target not in self._agent_registry:
            # 尝试查找 fallback
            return self._route_with_fallback(intent_type)

        target = self._agent_registry[routing_target]
        reason = f"Intent '{intent_type.value if hasattr(intent_type, 'value') else intent_type}' matched to '{routing_target}'"

        return RouteDecision(
            target=target,
            reason=reason,
            can_fallback=True,
        )

    def _route_with_fallback(self, intent_type: IntentType) -> RouteDecision:
        """带降级的路由"""
        # 定义降级映射
        fallback_map = {
            IntentType.ANALYTICS_QUERY: "analytics-agent",
            IntentType.RAG_QA: "rag-agent",
            IntentType.CONTRACT_REVIEW: "contract-agent",
            IntentType.POLICY_SEARCH: "policy-agent",
            IntentType.SAFETY_QA: "rag-agent",
            IntentType.EQUIPMENT_QA: "rag-agent",
        }

        fallback_name = fallback_map.get(intent_type)
        if fallback_name and fallback_name in self._agent_registry:
            target = self._agent_registry[fallback_name]
            return RouteDecision(
                target=target,
                reason=f"Fallback route for '{intent_type.value}' to '{fallback_name}'",
                can_fallback=False,
            )

        # 最后的降级：使用 rag-agent
        if "rag-agent" in self._agent_registry:
            target = self._agent_registry["rag-agent"]
            return RouteDecision(
                target=target,
                reason=f"Final fallback to 'rag-agent' for '{intent_type.value}'",
                can_fallback=False,
            )

        raise ValueError(f"No available route for intent: {intent_type.value}")

    def get_available_agents(self) -> list[str]:
        """获取所有已注册的 Agent"""
        return list(self._agent_registry.keys())

    async def check_agent_health(self, agent_name: str) -> bool:
        """
        检查 Agent 健康状态

        Args:
            agent_name: Agent 名称

        Returns:
            是否健康
        """
        if agent_name not in self._agent_registry:
            return False

        target = self._agent_registry[agent_name]
        health_url = target.endpoint.replace("/a2a", "/a2a/health")  # python_a2a health 端点

        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(health_url)
                return response.status_code == 200
        except Exception as e:
            logger.warning(f"Health check failed for {agent_name}: {e}")
            return False

    async def check_all_agents_health(self) -> dict[str, bool]:
        """
        检查所有 Agent 健康状态

        Returns:
            {agent_name: is_healthy}
        """
        import asyncio

        tasks = [
            self.check_agent_health(agent_name)
            for agent_name in self._agent_registry.keys()
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        return {
            agent_name: isinstance(result, bool) and result
            for agent_name, result in zip(self._agent_registry.keys(), results)
        }


# ============================================================================
# 全局路由引擎实例
# ============================================================================

_routing_engine: RoutingEngine | None = None


def get_routing_engine() -> RoutingEngine:
    """获取全局路由引擎实例"""
    global _routing_engine
    if _routing_engine is None:
        _routing_engine = RoutingEngine()
    return _routing_engine


# ============================================================================
# 便捷函数
# ============================================================================

def route_request(intent_result: IntentResult) -> RouteDecision:
    """
    路由请求的便捷函数

    Args:
        intent_result: 意图识别结果

    Returns:
        RouteDecision: 路由决策
    """
    engine = get_routing_engine()
    return engine.route(intent_result)
