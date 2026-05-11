"""多路检索 Query 扩展器。

使用 LLM 从不同角度扩展用户 query，提高检索召回率。

原理：
- 用户 query 可能表述模糊或遗漏关键信息
- LLM 可以从语义层面扩展出多个相关 query
- 并行检索多个 query，合并去重后获得更全面的结果

Author: Enterprise Knowledge Agentic RAG Platform
"""

from __future__ import annotations

import logging
from typing import Optional

from pydantic import BaseModel, Field

from core.llm.gateway import LLMGateway, MockLLMGateway
from core.llm.models import LLMMessage

logger = logging.getLogger(__name__)


class MultiQueryResult(BaseModel):
    """多路检索 Query 扩展结果。"""

    # 原始 query
    original_query: str = Field(description="原始用户 query")

    # 扩展后的多个 query
    expanded_queries: list[str] = Field(
        description="LLM 扩展的多个 query 列表"
    )

    # 扩展的角度说明
    angles: list[str] = Field(
        default_factory=list,
        description="每个扩展 query 的检索角度"
    )


class MultiQueryGenerator:
    """多路检索 Query 生成器。

    使用 LLM 将单个 query 扩展为多个不同角度的 query，
    用于并行检索以提高召回率。

    使用场景：
    1. search_laws - 法规检索
    2. search_templates - 模板检索
    3. search_history - 历史案例检索

    扩展策略：
    - 语义等价扩展：不同表述方式
    - 上下位扩展：上位概念 + 下位概念
    - 领域特定扩展：结合业务域的扩展
    """

    # 默认扩展数量
    DEFAULT_NUM_QUERIES = 5

    # Prompt 模板
    SYSTEM_PROMPT = """你是一个专业的法律检索助手，擅长将用户的法律相关问题扩展为多个检索词。

你的任务是根据用户的问题，从不同角度生成多个检索 query。

扩展原则：
1. 语义等价：不同表述方式表达相同含义
2. 法律角度：考虑法律术语和专业表达
3. 实操角度：考虑实际办案/审核中的常用检索词
4. 领域特定：结合具体业务领域

输出要求：
- 生成 3-5 个不同的检索 query
- 每个 query 从不同角度切入
- query 要简洁、精准
"""

    USER_PROMPT_TEMPLATE = """请为以下法律问题生成多个检索 query：

原始问题：{original_query}

合同类型：{contract_type}
业务领域：{business_domain}

请生成 {num_queries} 个不同角度的检索 query，用换行分隔。
"""

    def __init__(
        self,
        llm_gateway: Optional[LLMGateway] = None,
        num_queries: int = DEFAULT_NUM_QUERIES,
    ) -> None:
        """初始化多路检索生成器。

        Args:
            llm_gateway: LLM 网关实例
            num_queries: 扩展的 query 数量
        """
        self._llm_gateway = llm_gateway
        self._num_queries = num_queries

    @property
    def llm_gateway(self) -> LLMGateway:
        """获取 LLM 网关（懒加载）。"""
        if self._llm_gateway is None:
            from core.config.settings import get_settings
            settings = get_settings()

            if settings.llm_api_key and settings.llm_api_key != "your-api-key":
                from core.llm.gateway import OpenAICompatibleLLMGateway
                self._llm_gateway = OpenAICompatibleLLMGateway(settings=settings)
            else:
                logger.warning("LLM API Key 未配置，使用 Mock LLM Gateway")
                self._llm_gateway = MockLLMGateway(
                    response_content=self._get_mock_response()
                )

        return self._llm_gateway

    def _get_mock_response(self) -> str:
        """获取 Mock 响应（当无 LLM API 时使用）。"""
        return "\n".join([
            "违约金条款 法律规定",
            "违约金上限 司法解释",
            "合同违约金 民法典",
            "违约金与损失赔偿关系",
            "能源行业 合同特殊规定",
        ])

    def generate(
        self,
        original_query: str,
        contract_type: Optional[str] = None,
        business_domain: str = "能源",
        num_queries: Optional[int] = None,
    ) -> MultiQueryResult:
        """生成多个扩展 query。

        Args:
            original_query: 原始用户 query
            contract_type: 合同类型
            business_domain: 业务领域
            num_queries: 扩展数量（覆盖默认值）

        Returns:
            MultiQueryResult 包含原始 query 和扩展后的 query 列表
        """
        num = num_queries or self._num_queries

        logger.info(
            f"[MultiQueryGenerator] 生成扩展 query | "
            f"原始 query: {original_query[:50]}... | "
            f"合同类型: {contract_type} | 数量: {num}"
        )

        try:
            # 构建 prompt
            user_prompt = self.USER_PROMPT_TEMPLATE.format(
                original_query=original_query,
                contract_type=contract_type or "通用",
                business_domain=business_domain,
                num_queries=num,
            )

            messages = [
                LLMMessage(role="system", content=self.SYSTEM_PROMPT),
                LLMMessage(role="user", content=user_prompt),
            ]

            # 调用 LLM
            response = self.llm_gateway.chat(messages=messages)

            # 解析响应
            expanded_queries = self._parse_response(response.content, original_query)

            result = MultiQueryResult(
                original_query=original_query,
                expanded_queries=expanded_queries,
                angles=self._infer_angles(expanded_queries),
            )

            logger.info(
                f"[MultiQueryGenerator] 生成完成 | "
                f"扩展 {len(expanded_queries)} 个 query"
            )

            return result

        except Exception as e:
            logger.warning(f"[MultiQueryGenerator] LLM 调用失败: {e}，使用默认 query")
            return self._fallback_generate(original_query, business_domain)

    def _parse_response(self, content: str, original_query: str) -> list[str]:
        """解析 LLM 响应，提取 query 列表。

        Args:
            content: LLM 响应内容
            original_query: 原始 query（兜底）

        Returns:
            query 列表
        """
        # 按行分割
        lines = content.strip().split("\n")

        queries = []
        for line in lines:
            # 清理：去除序号、标点、前后空白
            line = line.strip()
            line = line.lstrip("0123456789.-、）)")
            line = line.strip()

            # 过滤空行和太短的行
            if line and len(line) >= 3:
                queries.append(line)

        # 如果解析失败，返回原始 query
        if not queries:
            logger.warning("[MultiQueryGenerator] 解析 LLM 响应失败，使用原始 query")
            return [original_query] if original_query else []

        return queries

    def _infer_angles(self, queries: list[str]) -> list[str]:
        """推断每个 query 的检索角度。

        Args:
            queries: query 列表

        Returns:
            角度描述列表
        """
        angles = []
        for query in queries:
            if "规定" in query or "法律" in query or "法" in query:
                angles.append("法律条文角度")
            elif "司法" in query or "法院" in query:
                angles.append("司法解释角度")
            elif "责任" in query or "赔偿" in query:
                angles.append("责任认定角度")
            elif "行业" in query or "领域" in query:
                angles.append("行业特定角度")
            else:
                angles.append("语义扩展角度")
        return angles

    def _fallback_generate(
        self,
        original_query: str,
        business_domain: str,
    ) -> MultiQueryResult:
        """Fallback：当 LLM 调用失败时使用规则生成 query。

        Args:
            original_query: 原始 query
            business_domain: 业务领域

        Returns:
            扩展结果
        """
        # 基础扩展
        base_queries = [original_query] if original_query else []

        # 规则扩展：添加领域关键词
        if business_domain in ["能源", "电力", "新能源"]:
            base_queries.append(f"{original_query} 能源行业" if original_query else "能源行业法规")
            base_queries.append(f"{original_query} 电力法" if original_query else "电力法规")

        # 规则扩展：添加通用法律关键词
        if original_query:
            if "违约" in original_query:
                base_queries.append("违约金 民法典 规定")
                base_queries.append("违约金过高 调整")
            if "风险" in original_query:
                base_queries.append("合同风险 法律保护")
                base_queries.append("风险条款 法律规定")

        return MultiQueryResult(
            original_query=original_query or "",
            expanded_queries=base_queries[:self._num_queries],
            angles=["规则扩展"] * min(len(base_queries), self._num_queries),
        )


# ==================== 全局实例 ====================

_multi_query_generator: MultiQueryGenerator | None = None


def get_multi_query_generator() -> MultiQueryGenerator:
    """获取多路检索生成器全局实例。"""
    global _multi_query_generator

    if _multi_query_generator is None:
        _multi_query_generator = MultiQueryGenerator()

    return _multi_query_generator
