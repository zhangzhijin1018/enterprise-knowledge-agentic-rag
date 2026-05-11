"""
意图检测与路由模块

提供用户意图识别和任务路由能力：
1. 意图检测：识别用户问题属于哪个业务领域
2. 槽位抽取：从问题中提取关键参数
3. 路由决策：决定由哪个 Agent 处理

设计说明：
- 支持规则模式（Rule-based IntentDetector）
- 支持 LLM 模式（LLM IntentDetector）- 生产推荐
- 支持混合模式（Hybrid IntentDetector）- LLM 优先，规则兜底
- 返回结构化的意图和槽位信息
- 路由目标明确：
  * rag_agent: 集团制度/安全生产/设备检修/新能源运维/项目资料问答
  * contract_agent: 合同审查（走 Milvus 检索）
  * analytics_agent: 经营数据分析（SQL 查询）

使用示例：
```python
# 规则模式（简单场景）
detector = IntentDetector()
result = detector.detect("本月光伏发电量是多少？")

# LLM 模式（生产推荐）
from core.agent.llm_intent_detector import HybridIntentDetector
detector = HybridIntentDetector(llm_gateway=llm_gateway, cache=redis_client)
result = await detector.detect("本月光伏发电量是多少？")
```

Author: Enterprise Knowledge Agentic RAG Platform
"""

from __future__ import annotations

import logging
import re
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ============================================================================
# 意图类型枚举
# ============================================================================

class IntentType(str, Enum):
    """
    意图类型枚举

    路由说明：
    - rag_qa: 通用知识库问答 → rag_agent
    - analytics_query: 经营分析查询 → analytics_agent
    - contract_review: 合同审查 → contract_agent
    - general_chat: 通用聊天 → rag_agent
    - clarification: 需要澄清 → supervisor
    - unsupported: 不支持的意图 → supervisor

    注意：
    - policy_qa, safety_qa, equipment_qa, new_energy_ops_qa, project_qa 都归入 rag_qa
    - 这些细分类别用于知识库过滤，不单独路由
    """
    RAG_QA = "rag_qa"
    ANALYTICS_QUERY = "analytics_query"
    CONTRACT_REVIEW = "contract_review"
    GENERAL_CHAT = "general_chat"
    CLARIFICATION = "clarification"
    UNSUPPORTED = "unsupported"


# ============================================================================
# 槽位定义
# ============================================================================

class TimeRange(BaseModel):
    """时间范围槽位"""
    type: str = Field(default="relative", description="时间类型：absolute/relative")
    value: Optional[str] = Field(default=None, description="时间值")
    start: Optional[str] = Field(default=None, description="开始日期")
    end: Optional[str] = Field(default=None, description="结束日期")
    raw_text: Optional[str] = Field(default=None, description="原始文本")


class Slot(BaseModel):
    """槽位模型"""
    name: str = Field(description="槽位名称")
    value: Any = Field(description="槽位值")
    confidence: float = Field(default=1.0, description="置信度")
    source: str = Field(default="extracted", description="来源：extracted/inferred/default")


class SlotCollection(BaseModel):
    """槽位集合"""
    slots: dict[str, Slot] = Field(default_factory=dict, description="槽位字典")
    filled: list[str] = Field(default_factory=list, description="已填充槽位")
    missing: list[str] = Field(default_factory=list, description="缺失槽位")

    def get_value(self, slot_name: str) -> Any:
        """获取槽位值"""
        slot = self.slots.get(slot_name)
        return slot.value if slot else None

    def is_filled(self, slot_name: str) -> bool:
        """检查槽位是否已填充"""
        return slot_name in self.filled


# ============================================================================
# 意图结果
# ============================================================================

class IntentResult(BaseModel):
    """
    意图识别结果

    包含：
    - intent_type: 识别的意图类型
    - confidence: 置信度
    - slots: 提取的槽位
    - requires_clarification: 是否需要澄清
    - clarification_questions: 澄清问题列表
    - routing_target: 建议的路由目标
    - business_domain: 业务域（用于 RAG 知识库过滤）
    """
    intent_type: IntentType = Field(description="意图类型")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0, description="置信度")
    slots: SlotCollection = Field(default_factory=SlotCollection, description="槽位集合")
    requires_clarification: bool = Field(default=False, description="是否需要澄清")
    clarification_questions: list[str] = Field(default_factory=list, description="澄清问题")
    routing_target: str = Field(default="unknown", description="路由目标 Agent")
    business_domain: Optional[str] = Field(default=None, description="业务域（用于 RAG 过滤）")
    message: Optional[str] = Field(default=None, description="附加消息")


# ============================================================================
# 意图检测器
# ============================================================================

class IntentDetector:
    """
    意图检测器

    基于规则和关键词的意图识别。

    设计说明：
    - 使用规则 + 关键词匹配进行意图识别
    - 意图优先级：合同审查 > 经营分析 > RAG 问答
    - 支持自定义意图模式和路由规则
    - 返回明确的路由目标

    路由规则：
    1. 合同审查关键词 → contract_agent
    2. 经营分析关键词 → analytics_agent
    3. 其他知识库问答 → rag_agent
    4. 通用聊天 → rag_agent
    """

    # 意图关键词模式（按优先级排序）
    INTENT_PATTERNS = {
        # 合同审查优先级最高
        IntentType.CONTRACT_REVIEW: [
            # 明确合同相关
            r"合同.{0,10}(审查|审核|检查|复核|合规|风险|条款)",
            r".{0,10}(合同|协议|契约).{0,10}(审查|审核|检查|复核|合规|风险|条款)",
            r"这份合同",
            r"合同.{0,5}(有哪些|存在|发现).{0,5}(风险|问题|隐患)",
            r"(煤炭|设备|工程|采购|销售|施工).{0,5}(合同|协议)",
            r"合同.{0,5}(付款|交付|验收|违约|质保|安全责任)",
            r"审查.{0,5}(合同|协议)",
            r"合规.{0,5}(检查|审查)",
            # 合同模板、制度对比
            r"合同.{0,5}(模板|范本|标准)",
            r"与.{0,5}(制度|标准|模板).{0,5}(对比|比较)",
        ],
        # 经营分析
        IntentType.ANALYTICS_QUERY: [
            # 指标类
            r"发电量",
            r"销售收入",
            r"营收",
            r"利润",
            r"成本",
            r"销售额",
            r"产量",
            r"利用小时",
            # 分析类
            r"同比",
            r"环比",
            r"增长",
            r"下降",
            r"变化",
            r"分析",
            r"统计",
            r"报表",
            r"汇总",
            # 数据查询类
            r"查询.{0,5}(数据|指标|报表)",
            r".{0,5}(本月|上月|本季度|上季度|本年|去年|最近).{0,10}(产量|收入|发电)",
            r"各.{0,5}(矿区|区域|分公司|子公司).{0,5}(产量|收入|利润)",
            r"新能源板块",
            r"煤炭板块",
            # 报告生成类
            r"生成.{0,5}(分析|统计|经营).{0,5}(报告|报表|简报)",
            r"本月.{0,5}(经营|分析)",
        ],
        # RAG 问答（制度/安全/设备/新能源/项目）
        IntentType.RAG_QA: [
            # 集团制度
            r"集团制度",
            r"管理办法",
            r"报销标准",
            r"审批流程",
            r"员工.{0,5}(制度|规定)",
            r"培训制度",
            r"立项.{0,5}(材料|流程|要求)",
            # 安全生产
            r"安全.{0,5}(生产|规程|制度|责任|操作)",
            r"动火作业",
            r"有限空间",
            r"高处作业",
            r"隐患治理",
            r"应急预案",
            r"事故案例",
            r".{0,5}(作业|操作).{0,5}(规定|要求|流程|制度)",
            r"进入.{0,5}(有限|煤仓|塔筒)",
            r"安全培训",
            # 设备检修
            r"设备.{0,5}(检修|维修|维护|故障|保养)",
            r"点检",
            r"皮带.{0,5}(输送|跑偏)",
            r"斗轮机",
            r"变压器",
            r"风机.{0,5}(振动|异常)",
            r"逆变器.{0,5}(告警|故障)",
            # 新能源运维
            r"光伏.{0,5}(运维|巡检|发电)",
            r"风电.{0,5}(运维|巡检|发电)",
            r"储能.{0,5}(运维|巡检|电池)",
            r"电站.{0,5}(运维|巡检|告警)",
            r"逆变器",
            r"组件.{0,5}(清洁|清洗)",
            r"发电量.{0,5}(下降|异常)",
            r"停机率",
            r"告警.{0,5}(处理|分析)",
            # 项目资料
            r"项目.{0,5}(可研|环评|安评|能评|审批)",
            r"土地手续",
            r"施工进度",
            r"验收.{0,5}(资料|材料)",
            r"会议纪要",
            # 通用问答
            r"是什么",
            r"如何",
            r"怎样",
            r"怎么办",
            r"请说明",
            r"介绍一下",
            r"解释",
            r"有哪些",
            r"请问",
            r"问一下",
        ],
    }

    # 业务域关键词（用于 RAG 知识库过滤）
    BUSINESS_DOMAIN_PATTERNS = {
        "policy": [
            r"集团制度", r"管理办法", r"报销标准", r"审批流程",
            r"培训制度", r"立项", r"管理制度", r"财务制度",
        ],
        "safety": [
            r"安全", r"动火", r"有限空间", r"高处作业", r"隐患",
            r"应急", r"事故", r"作业", r"操作规程",
        ],
        "equipment": [
            r"设备", r"检修", r"维修", r"故障", r"保养",
            r"点检", r"皮带", r"斗轮机", r"变压器", r"风机",
        ],
        "new_energy": [
            r"光伏", r"风电", r"储能", r"逆变器", r"组件",
            r"电站", r"发电量", r"停机", r"告警",
        ],
        "project": [
            r"可研", r"环评", r"安评", r"能评", r"审批",
            r"土地手续", r"施工进度", r"验收", r"会议纪要",
        ],
    }

    # 路由目标映射
    ROUTING_MAP = {
        IntentType.ANALYTICS_QUERY: "analytics_agent",
        IntentType.CONTRACT_REVIEW: "contract_agent",
        IntentType.RAG_QA: "rag_agent",
        IntentType.GENERAL_CHAT: "rag_agent",
        IntentType.UNSUPPORTED: "supervisor",
    }

    # 必需槽位定义
    REQUIRED_SLOTS = {
        IntentType.ANALYTICS_QUERY: ["metric", "time_range"],
        IntentType.CONTRACT_REVIEW: ["contract_file_id"],
    }

    def __init__(self):
        """初始化意图检测器"""
        self._compiled_patterns: dict[IntentType, list[re.Pattern]] = {}
        self._business_domain_patterns: dict[str, list[re.Pattern]] = {}
        self._compile_patterns()

    def _compile_patterns(self) -> None:
        """预编译正则表达式"""
        for intent_type, patterns in self.INTENT_PATTERNS.items():
            self._compiled_patterns[intent_type] = [
                re.compile(pattern, re.IGNORECASE)
                for pattern in patterns
            ]

        for domain, patterns in self.BUSINESS_DOMAIN_PATTERNS.items():
            self._business_domain_patterns[domain] = [
                re.compile(pattern, re.IGNORECASE)
                for pattern in patterns
            ]

    def detect(
        self,
        query: str,
        conversation_history: Optional[list[dict]] = None,
    ) -> IntentResult:
        """
        检测用户意图

        Args:
            query: 用户查询
            conversation_history: 对话历史（用于多轮对话）

        Returns:
            IntentResult: 意图识别结果
        """
        query = query.strip()
        if not query:
            return IntentResult(
                intent_type=IntentType.UNSUPPORTED,
                confidence=0.0,
                message="查询不能为空",
            )

        # 1. 检测意图类型（按优先级）
        intent_type, confidence = self._detect_intent_type(query)

        # 2. 提取槽位
        slots = self._extract_slots(query, intent_type)

        # 3. 检查是否需要澄清
        requires_clarification, clarification_questions = self._check_clarification(
            intent_type, slots
        )

        # 4. 确定路由目标
        routing_target = self.ROUTING_MAP.get(intent_type, "supervisor")

        # 5. 确定业务域（用于 RAG 知识库过滤）
        business_domain = self._detect_business_domain(query)

        return IntentResult(
            intent_type=intent_type,
            confidence=confidence,
            slots=slots,
            requires_clarification=requires_clarification,
            clarification_questions=clarification_questions,
            routing_target=routing_target,
            business_domain=business_domain,
        )

    def _detect_intent_type(self, query: str) -> tuple[IntentType, float]:
        """
        检测意图类型

        按优先级检测：
        1. 合同审查（最高优先级）
        2. 经营分析
        3. RAG 问答
        """
        # 按优先级计算各意图得分
        intent_scores: dict[IntentType, int] = {}

        for intent_type, patterns in self._compiled_patterns.items():
            score = sum(1 for pattern in patterns if pattern.search(query))
            if score > 0:
                intent_scores[intent_type] = score

        if not intent_scores:
            # 默认 RAG 问答
            return IntentType.RAG_QA, 0.5

        # 按优先级选择意图
        priority_order = [
            IntentType.CONTRACT_REVIEW,  # 最高优先级
            IntentType.ANALYTICS_QUERY,
            IntentType.RAG_QA,
        ]

        for intent_type in priority_order:
            if intent_type in intent_scores:
                max_score = intent_scores[intent_type]
                # 计算置信度
                confidence = min(0.5 + (max_score * 0.1), 0.95)
                return intent_type, confidence

        # 兜底 RAG 问答
        return IntentType.RAG_QA, 0.5

    def _detect_business_domain(self, query: str) -> Optional[str]:
        """
        检测业务域

        用于 RAG 知识库过滤。
        如果匹配多个域，返回得分最高的。
        """
        domain_scores: dict[str, int] = {}

        for domain, patterns in self._business_domain_patterns.items():
            score = sum(1 for pattern in patterns if pattern.search(query))
            if score > 0:
                domain_scores[domain] = score

        if not domain_scores:
            return None

        # 返回得分最高的域
        best_domain = max(domain_scores.items(), key=lambda x: x[1])[0]
        return best_domain

    def _extract_slots(self, query: str, intent_type: IntentType) -> SlotCollection:
        """提取槽位"""
        slots_dict: dict[str, Slot] = {}
        filled: list[str] = []

        if intent_type == IntentType.ANALYTICS_QUERY:
            # 提取指标
            metric = self._extract_metric(query)
            if metric:
                slots_dict["metric"] = Slot(
                    name="metric",
                    value=metric,
                    confidence=0.9,
                    source="extracted",
                )
                filled.append("metric")

            # 提取时间范围
            time_range = self._extract_time_range(query)
            if time_range:
                slots_dict["time_range"] = Slot(
                    name="time_range",
                    value=time_range.model_dump() if hasattr(time_range, 'model_dump') else time_range,
                    confidence=0.8,
                    source="extracted",
                )
                filled.append("time_range")

            # 提取组织范围
            org_scope = self._extract_org_scope(query)
            if org_scope:
                slots_dict["org_scope"] = Slot(
                    name="org_scope",
                    value=org_scope,
                    confidence=0.7,
                    source="extracted",
                )
                filled.append("org_scope")

        elif intent_type == IntentType.CONTRACT_REVIEW:
            # 提取合同 ID
            contract_id = self._extract_contract_id(query)
            if contract_id:
                slots_dict["contract_file_id"] = Slot(
                    name="contract_file_id",
                    value=contract_id,
                    confidence=0.9,
                    source="extracted",
                )
                filled.append("contract_file_id")

            # 提取合同类型
            contract_type = self._extract_contract_type(query)
            if contract_type:
                slots_dict["contract_type"] = Slot(
                    name="contract_type",
                    value=contract_type,
                    confidence=0.8,
                    source="extracted",
                )
                filled.append("contract_type")

        return SlotCollection(
            slots=slots_dict,
            filled=filled,
            missing=self._get_missing_slots(intent_type, filled),
        )

    def _extract_metric(self, query: str) -> Optional[str]:
        """提取指标"""
        metric_keywords = [
            "发电量", "销售收入", "利润", "成本", "销售额", "营收",
            "发电效率", "利用小时数", "上网电量", "装机容量",
            "产量", "销售量", "采购量",
        ]

        for metric in metric_keywords:
            if metric in query:
                return metric

        return None

    def _extract_time_range(self, query: str) -> Optional[TimeRange]:
        """提取时间范围"""
        # 绝对时间
        abs_pattern = re.compile(r"(\d{4}[-/年]\d{1,2}[-/月]\d{0,2})")
        abs_match = abs_pattern.search(query)
        if abs_match:
            return TimeRange(
                type="absolute",
                value=abs_match.group(1),
                raw_text=abs_match.group(0),
            )

        # 相对时间
        relative_patterns = [
            (r"本月", "本月"),
            (r"上月|上个月", "上月"),
            (r"本季度|本季", "本季度"),
            (r"上季度|上季", "上季度"),
            (r"本年|今年", "本年"),
            (r"去年", "去年"),
            (r"最近(\d+)个?月", "最近N月"),
            (r"最近(\d+)天", "最近N天"),
        ]

        for pattern, label in relative_patterns:
            match = re.search(pattern, query)
            if match:
                return TimeRange(
                    type="relative",
                    value=label,
                    raw_text=match.group(0),
                )

        return None

    def _extract_org_scope(self, query: str) -> Optional[dict]:
        """提取组织范围"""
        region_patterns = [
            (r"新疆区域|新疆", "region", "新疆区域"),
            (r"北疆区域|北疆", "region", "北疆区域"),
            (r"南疆区域|南疆", "region", "南疆区域"),
            (r"哈密区域|哈密", "region", "哈密区域"),
        ]

        for pattern, org_type, value in region_patterns:
            if re.search(pattern, query):
                return {"type": org_type, "value": value}

        return None

    def _extract_contract_id(self, query: str) -> Optional[str]:
        """提取合同 ID"""
        # 匹配常见的 ID 格式
        patterns = [
            r"合同[_\-]?([a-zA-Z0-9]+)",
            r"file[_\-]?([a-zA-Z0-9]+)",
            r"contract[_\-]?([a-zA-Z0-9]+)",
            r"doc[_\-]?([a-zA-Z0-9]+)",
        ]

        for pattern in patterns:
            match = re.search(pattern, query, re.IGNORECASE)
            if match:
                return match.group(0)

        return None

    def _extract_contract_type(self, query: str) -> Optional[str]:
        """提取合同类型"""
        contract_types = [
            ("煤炭采购", ["煤炭采购"]),
            ("设备采购", ["设备采购", "采购合同"]),
            ("工程合同", ["工程合同", "施工合同"]),
            ("销售合同", ["销售合同"]),
            ("采购合同", ["采购合同"]),
            ("施工合同", ["施工合同"]),
            ("租赁合同", ["租赁合同"]),
            ("服务合同", ["服务合同"]),
        ]

        for contract_type, keywords in contract_types:
            for keyword in keywords:
                if keyword in query:
                    return contract_type

        return None

    def _get_missing_slots(self, intent_type: IntentType, filled: list[str]) -> list[str]:
        """获取缺失的槽位"""
        required = self.REQUIRED_SLOTS.get(intent_type, [])
        return [slot for slot in required if slot not in filled]

    def _check_clarification(
        self,
        intent_type: IntentType,
        slots: SlotCollection,
    ) -> tuple[bool, list[str]]:
        """检查是否需要澄清"""
        if not slots.missing:
            return False, []

        questions = []
        for slot_name in slots.missing:
            if slot_name == "metric":
                questions.append("请问您想查询哪个指标？例如：发电量、收入、成本等。")
            elif slot_name == "time_range":
                questions.append("请问您想查询哪个时间范围？例如：本月、上季度、最近3个月等。")
            elif slot_name == "contract_file_id":
                questions.append("请提供要审查的合同文件 ID 或上传合同文件。")

        return len(questions) > 0, questions


# ============================================================================
# 便捷函数
# ============================================================================

def detect_intent(
    query: str,
    conversation_history: Optional[list[dict]] = None,
) -> IntentResult:
    """
    检测用户意图的便捷函数

    Args:
        query: 用户查询
        conversation_history: 对话历史

    Returns:
        IntentResult: 意图识别结果
    """
    detector = IntentDetector()
    return detector.detect(query, conversation_history)
