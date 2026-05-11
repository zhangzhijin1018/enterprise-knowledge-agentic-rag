"""合同条款抽取器。

使用 LLM 从合同文本中抽取关键条款。
"""

from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING, Any

from core.contracts.models import (
    ClauseType,
    ContractClause,
    ContractMetadata,
    ContractParty,
    ContractType,
    RiskIndicatorKeywords,
)

if TYPE_CHECKING:
    from core.llm.gateway import LLMGateway

logger = logging.getLogger(__name__)


class ClauseExtractor:
    """合同条款抽取器。

    职责：
    - 解析合同文本结构
    - 识别合同类型
    - 抽取关键条款（标的、价款、期限、当事人、违约责任等）
    - 返回结构化条款列表

    设计原因：
    - 企业合同审查需要系统化抽取条款
    - 不同类型合同的关键条款不同
    - 需要识别条款类型和重要性
    """

    # 条款类型映射（中文到枚举）
    CLAUSE_TYPE_MAPPING = {
        "当事人": ClauseType.当事人信息,
        "标的": ClauseType.标的条款,
        "价款": ClauseType.价款条款,
        "金额": ClauseType.价款条款,
        "费用": ClauseType.价款条款,
        "付款": ClauseType.价款条款,
        "支付": ClauseType.价款条款,
        "期限": ClauseType.履行期限,
        "时间": ClauseType.履行期限,
        "交付": ClauseType.履行期限,
        "地点": ClauseType.履行地点,
        "方式": ClauseType.履行方式,
        "质量": ClauseType.质量标准,
        "标准": ClauseType.质量标准,
        "验收": ClauseType.验收标准,
        "保密": ClauseType.保密条款,
        "知识产权": ClauseType.知识产权,
        "违约": ClauseType.违约责任,
        "责任": ClauseType.违约责任,
        "争议": ClauseType.争议解决,
        "仲裁": ClauseType.争议解决,
        "诉讼": ClauseType.争议解决,
        "变更": ClauseType.合同变更,
        "解除": ClauseType.合同解除,
        "终止": ClauseType.合同解除,
        "不可抗力": ClauseType.不可抗力,
    }

    def __init__(
        self,
        llm_gateway: "LLMGateway | None" = None,
        use_llm: bool = True,
    ) -> None:
        """初始化条款抽取器。

        Args:
            llm_gateway: LLM 网关（用于 LLM 抽取）
            use_llm: 是否使用 LLM 抽取，False 则使用规则抽取
        """

        self.llm_gateway = llm_gateway
        self.use_llm = use_llm and llm_gateway is not None

    async def extract_clauses(
        self,
        contract_text: str,
        contract_type: ContractType | str | None = None,
    ) -> tuple[list[ContractClause], list[ContractParty], ContractMetadata]:
        """从合同文本中抽取条款。

        Args:
            contract_text: 合同文本内容
            contract_type: 合同类型

        Returns:
            (条款列表, 当事人列表, 合同元数据)
        """

        logger.info(f"开始抽取条款，合同类型: {contract_type}")

        # 1. 提取当事人信息
        parties = self._extract_parties(contract_text)

        # 2. 提取合同元数据
        metadata = self._extract_metadata(contract_text)

        # 3. 抽取条款
        if self.use_llm:
            clauses = await self._extract_clauses_with_llm(contract_text, contract_type)
        else:
            clauses = self._extract_clauses_with_rules(contract_text)

        logger.info(f"成功抽取 {len(clauses)} 个条款, {len(parties)} 个当事人")

        return clauses, parties, metadata

    def _extract_parties(self, text: str) -> list[ContractParty]:
        """提取当事人信息。

        Args:
            text: 合同文本

        Returns:
            当事人列表
        """

        parties = []

        # 使用正则提取甲方、乙方等
        party_patterns = [
            (r"甲方[：:]\s*([^\n，,。]+)", "甲方"),
            (r"乙方[：:]\s*([^\n，,。]+)", "乙方"),
            (r"丙方[：:]\s*([^\n，,。]+)", "丙方"),
            (r"丁方[：:]\s*([^\n，,。]+)", "丁方"),
        ]

        for pattern, role in party_patterns:
            matches = re.findall(pattern, text)
            for match in matches:
                name = match.strip()
                if name and len(name) < 100:  # 过滤异常长度的名称
                    parties.append(ContractParty(
                        name=name,
                        role=role,
                    ))

        return parties

    def _extract_metadata(self, text: str) -> ContractMetadata:
        """提取合同元数据。

        Args:
            text: 合同文本

        Returns:
            合同元数据
        """

        metadata = ContractMetadata()

        # 提取金额
        amount_patterns = [
            r"(?:合同)?金额[：:]\s*([0-9,，.]+[万千佰亿]?[元圆]?)",
            r"(?:合同)?价款[：:]\s*([0-9,，.]+[万千佰亿]?[元圆]?)",
            r"¥\s*([0-9,，.]+)",
            r"￥\s*([0-9,，.]+)",
        ]
        for pattern in amount_patterns:
            match = re.search(pattern, text)
            if match:
                metadata.contract_value = match.group(1).strip()
                break

        # 提取期限
        period_patterns = [
            r"(?:合同)?期限[：:]\s*([^\n，,。]+)",
            r"有效期[：:]\s*([^\n，,。]+)",
            r"自[^\n]{0,20}至[^\n]{0,20}",
        ]
        for pattern in period_patterns:
            match = re.search(pattern, text)
            if match:
                metadata.contract_period = match.group(1).strip()
                break

        # 提取付款方式
        payment_patterns = [
            r"付款[方式方式：:]\s*([^\n，,。]+)",
            r"支付[方式方式：:]\s*([^\n，,。]+)",
        ]
        for pattern in payment_patterns:
            match = re.search(pattern, text)
            if match:
                metadata.payment_method = match.group(1).strip()
                break

        return metadata

    def _extract_clauses_with_rules(self, text: str) -> list[ContractClause]:
        """使用规则抽取条款。

        适用于没有 LLM 的场景。

        Args:
            text: 合同文本

        Returns:
            条款列表
        """

        clauses = []

        # 按行分割
        lines = text.split("\n")

        clause_id = 0
        for line in lines:
            line = line.strip()
            if not line:
                continue

            # 检查是否是条款（以第X条开头）
            clause_match = re.match(r"第([一二三四五六七八九十百千0-9]+)条[：:]\s*(.+)", line)
            if clause_match:
                clause_id_str = f"第{clause_match.group(1)}条"
                clause_content = clause_match.group(2).strip()

                # 确定条款类型
                clause_type = self._infer_clause_type(clause_content)

                # 检查风险指标
                risk_indicators = self._check_risk_indicators(clause_content)

                clauses.append(ContractClause(
                    clause_id=clause_id_str,
                    clause_type=clause_type,
                    clause_title=clause_content[:50],
                    clause_content=clause_content,
                    key_points=[],
                    risk_indicators=risk_indicators,
                ))
                clause_id += 1
                continue

            # 检查是否是风险条款
            risk_indicators = self._check_risk_indicators(line)
            if risk_indicators:
                clauses.append(ContractClause(
                    clause_id=f"第{clause_id + 1}条",
                    clause_type=self._infer_clause_type(line),
                    clause_title=line[:50],
                    clause_content=line,
                    key_points=[],
                    risk_indicators=risk_indicators,
                ))
                clause_id += 1

        return clauses

    async def _extract_clauses_with_llm(
        self,
        text: str,
        contract_type: ContractType | str | None,
    ) -> list[ContractClause]:
        """使用 LLM 抽取条款。

        Args:
            text: 合同文本
            contract_type: 合同类型

        Returns:
            条款列表
        """

        if not self.llm_gateway:
            return self._extract_clauses_with_rules(text)

        contract_type_hint = f"合同类型：{contract_type}" if contract_type else "合同类型：未知"

        prompt = f"""你是一个专业的合同审查助手。请从以下合同文本中抽取关键条款。

{contract_type_hint}

要求：
1. 识别并抽取所有关键条款
2. 对每个条款，标注条款类型
3. 提取条款的关键要点
4. 识别可能的风险指标

条款类型包括：
{', '.join([t.value for t in ClauseType])}

合同文本：
---
{text[:8000]}
---

请以 JSON 格式返回条款列表，每个条款包含：
- clause_id: 条款编号（如"第1条"）
- clause_type: 条款类型
- clause_title: 条款标题
- clause_content: 条款原文
- key_points: 关键要点列表
- risk_indicators: 风险指标列表

返回格式：
{{"clauses": [...]}}"""

        try:
            response = await self.llm_gateway.agenerate(
                messages=[{"role": "system", "content": "你是一个专业的合同审查助手。"}],
                prompt=prompt,
            )

            content = response.content if hasattr(response, "content") else str(response)

            # 解析 JSON
            json_match = re.search(r'\{[^{}]*"clauses"[^{}]*\}', content, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
                clauses_data = data.get("clauses", [])

                clauses = []
                for item in clauses_data:
                    clauses.append(ContractClause(
                        clause_id=item.get("clause_id", ""),
                        clause_type=item.get("clause_type", "其他条款"),
                        clause_title=item.get("clause_title", ""),
                        clause_content=item.get("clause_content", ""),
                        key_points=item.get("key_points", []),
                        risk_indicators=item.get("risk_indicators", []),
                    ))

                return clauses

        except Exception as e:
            logger.warning(f"LLM 条款抽取失败，使用规则抽取: {e}")

        return self._extract_clauses_with_rules(text)

    def _infer_clause_type(self, content: str) -> str:
        """推断条款类型。

        Args:
            content: 条款内容

        Returns:
            条款类型
        """

        for keyword, clause_type in self.CLAUSE_TYPE_MAPPING.items():
            if keyword in content:
                return clause_type.value

        return ClauseType.其他条款.value

    def _check_risk_indicators(self, content: str) -> list[str]:
        """检查风险指标。

        Args:
            content: 条款内容

        Returns:
            匹配到的风险关键词列表
        """

        indicators = []

        # 检查高风险关键词
        for keyword in RiskIndicatorKeywords.HIGH_RISK:
            if keyword in content:
                indicators.append(f"[高风险] {keyword}")

        # 检查中风险关键词
        for keyword in RiskIndicatorKeywords.MEDIUM_RISK:
            if keyword in content:
                indicators.append(f"[中风险] {keyword}")

        # 检查低风险关键词
        for keyword in RiskIndicatorKeywords.LOW_RISK:
            if keyword in content:
                indicators.append(f"[提示] {keyword}")

        return indicators
