"""search_laws 检索质量阈值评估脚本。

本脚本专门用于评估 search_laws 工具在不同 min_relevance 阈值下的检索质量。

评估方法：
- 使用 context_precision（上下文精确率）：检索到的上下文是否与参考答案相关
- 使用 context_recall（上下文召回率）：参考答案中的信息有多少被检索到

通过对比不同阈值的结果，找出最优的 min_relevance 值。

用法：
    # 运行完整评估
    python scripts/evaluate_search_laws_threshold.py

    # 快速测试（使用较少测试用例）
    python scripts/evaluate_search_laws_threshold.py --quick

Author: Enterprise Knowledge Agentic RAG Platform
"""

import argparse
import logging
import sys
from dataclasses import dataclass
from typing import Any

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


# ==================== 测试数据集 ====================


@dataclass
class SearchLawsTestCase:
    """search_laws 测试用例"""
    user_input: str  # 用户查询
    reference: str   # 参考答案（标准法规内容）


# search_laws 场景的测试数据集
# 这些测试用例覆盖了合同审核中常见的法律问题
SEARCH_LAWS_TEST_DATASET = [
    # ===== 合同解除条款 =====
    SearchLawsTestCase(
        user_input="合同中约定一方可以无条件解除合同，这种条款是否合法？",
        reference="根据《民法典》第563条，合同解除需要法定事由或约定解除条件；《民法典》第562条规定当事人可以约定解除合同的事由，但需符合法律规定。无条件解除条款可能因违反公平原则被认定无效。"
    ),
    SearchLawsTestCase(
        user_input="委托合同中委托人或受托人能否随时解除合同？",
        reference="根据《民法典》第933条，委托人或者受托人可以随时解除委托合同。因解除合同造成对方损失的，除不可归责于该当事人的事由外，无偿委托合同的解除方应当赔偿因解除时间不当造成的直接损失，有偿委托合同的解除方应当赔偿对方的直接损失和可以获得的利益。"
    ),
    SearchLawsTestCase(
        user_input="承揽合同中定作人能否解除合同？",
        reference="根据《民法典》第787条，定作人在承揽人完成工作前可以随时解除合同，造成承揽人损失的，应当赔偿损失。"
    ),
    SearchLawsTestCase(
        user_input="租赁合同中，出租人能否提前解除合同？",
        reference="根据《民法典》第722条，承租人无正当理由未支付或者迟延支付租金的，出租人可以请求承租人在合理期限内支付。承租人逾期不支付的，出租人可以解除合同。"
    ),
    # ===== 违约金条款 =====
    SearchLawsTestCase(
        user_input="合同约定每日按合同金额的千分之五计算违约金，是否过高？",
        reference="根据《民法典》第585条，当事人可以约定违约金。约定的违约金低于造成的损失的，人民法院或者仲裁机构可以根据当事人的请求予以增加；约定的违约金过分高于造成的损失的，人民法院或者仲裁机构可以根据当事人的请求予以适当减少。"
    ),
    SearchLawsTestCase(
        user_input="合同约定的违约金是否能够同时主张赔偿损失？",
        reference="根据《民法典》第588条，当事人既约定违约金，又约定定金的，一方违约时，对方可以选择适用违约金或者定金条款。定金不足以弥补一方违约造成的损失的，对方可以请求赔偿超过定金数额的损失。"
    ),
    SearchLawsTestCase(
        user_input="建设工程合同中，承包人转包会有什么法律后果？",
        reference="根据《民法典》第791条，总承包人或者勘察、设计、施工承包人经发包人同意，可以将自己承包的部分工作交由第三人完成。第三人就其完成的工作成果与总承包人或者勘察、设计、施工承包人向发包人承担连带责任。"
    ),
    # ===== 标的物风险 =====
    SearchLawsTestCase(
        user_input="买卖合同中，标的物毁损灭失的风险由谁承担？",
        reference="根据《民法典》第604条，标的物毁损、灭失的风险，在标的物交付之前由出卖人承担，交付之后由买受人承担，但是法律另有规定或者当事人另有约定的除外。"
    ),
    SearchLawsTestCase(
        user_input="采购合同中，设备在运输过程中损毁灭失，风险由谁承担？",
        reference="根据《民法典》第606条，出卖人出卖交由承运人运输的在途标的物，除当事人另有约定外，毁损、灭失的风险自合同成立时起由买受人承担。"
    ),
    # ===== 合同效力 =====
    SearchLawsTestCase(
        user_input="超越经营范围订立的合同是否有效？",
        reference="根据《民法典》第505条，当事人超越经营范围订立的合同的效力，应当依照本法第一编第六章第三节和本编的有关规定确定，不得仅以超越经营范围确认合同无效。"
    ),
    # ===== 格式条款 =====
    SearchLawsTestCase(
        user_input="格式条款提供方未履行提示义务，会有什么后果？",
        reference="根据《民法典》第496条，采用格式条款订立合同的，提供格式条款的一方应当遵循公平原则确定当事人之间的权利和义务，并采取合理的方式提示对方注意免除或者减轻其责任等与对方有重大利害关系的条款。"
    ),
    # ===== 不可抗力 =====
    SearchLawsTestCase(
        user_input="因不可抗力导致合同无法履行，是否需要承担违约责任？",
        reference="根据《民法典》第590条，不可抗力是指不能预见、不能避免且不能克服的客观情况。因不可抗力致使不能实现合同目的，当事人可以解除合同。因不可抗力造成违约的，一般不承担民事责任，但法律另有规定的除外。"
    ),
    # ===== 质量标准 =====
    SearchLawsTestCase(
        user_input="采购设备质量不符合合同约定，买方有什么救济途径？",
        reference="根据《民法典》第582条，履行不符合约定的，应当按照当事人的约定承担违约责任。对违约责任没有约定或者约定不明确的，受损害方根据标的的性质以及损失的大小，可以合理选择请求对方承担修理、重作、更换、退货、减少价款或者报酬等违约责任。"
    ),
    # ===== 付款条款 =====
    SearchLawsTestCase(
        user_input="建设工程合同中，发包人逾期支付工程款，承包人能否主张利息？",
        reference="根据《建设工程司法解释一》第27条，利息从应付工程价款之日开始计算。当事人对应付工程价款的日期没有约定的，应当按照下列规定确定。"
    ),
    # ===== 保密条款 =====
    SearchLawsTestCase(
        user_input="合同中的保密条款有什么法律效力？",
        reference="根据《民法典》第501条，当事人在订立合同过程中知悉的商业秘密或者其他应当保密的信息，不得泄露或者不正当地使用。泄露或者不正当地使用该商业秘密或者信息给对方造成损失的，应当承担赔偿责任。"
    ),
    # ===== 争议解决 =====
    SearchLawsTestCase(
        user_input="合同约定仲裁条款，一方起诉到法院，法院会如何处理？",
        reference="根据《仲裁法》第5条，当事人达成仲裁协议，一方向人民法院起诉的，人民法院不予受理，但仲裁协议无效的除外。"
    ),
    # ===== 合同变更 =====
    SearchLawsTestCase(
        user_input="合同签订后，能否单方变更合同条款？",
        reference="根据《民法典》第543条，当事人协商一致，可以变更合同。"
    ),
    # ===== 权利义务转让 =====
    SearchLawsTestCase(
        user_input="合同权利转让需要通知债务人吗？",
        reference="根据《民法典》第546条，债权人转让权利的，应当通知债务人。未经通知，该转让对债务人不发生效力。"
    ),
    # ===== 连带责任 =====
    SearchLawsTestCase(
        user_input="什么情况下多个合同当事人需要承担连带责任？",
        reference="根据《民法典》第178条，二人以上依法承担连带责任的，权利人有权请求部分或者全部连带责任人承担责任。连带责任，由法律规定或者当事人约定。"
    ),
]


# ==================== 检索质量评估函数 ====================


def evaluate_single_retrieval(
    test_case: SearchLawsTestCase,
    threshold: float = 0.4,
    max_results: int = 10,
) -> dict[str, Any]:
    """评估单次检索的 context_precision 和 context_recall。

    Args:
        test_case: 测试用例，包含 user_input 和 reference
        threshold: min_relevance 阈值
        max_results: 最大返回结果数

    Returns:
        包含 contexts 和评估指标的字典
    """
    from core.contracts.rag_service import get_contract_rag_service

    rag_service = get_contract_rag_service()

    # 调用 search_laws 获取检索结果
    # 使用多路检索策略以获得更好的检索结果
    laws = rag_service.search_laws_multi(
        query=test_case.user_input,
        contract_type=None,
        business_domain="能源",
        top_k=5,
        min_relevance=threshold,
        max_results=max_results,
        legal_search_topics=None,
        contract_content=None,
        extracted_clauses=None,
    )

    # 提取 contexts（法律条款内容）
    # 将每条法规的完整内容作为 context
    contexts = []
    for law in laws:
        # 组合法规标题、章节和条款内容作为完整上下文
        context_parts = []
        if law.title:
            context_parts.append(f"《{law.title}》")
        if law.chapter:
            context_parts.append(f"{law.chapter}")
        if law.article:
            context_parts.append(law.article)
        context = "\n".join(context_parts)
        if context:
            contexts.append(context)

    return {
        "user_input": test_case.user_input,
        "reference": test_case.reference,
        "contexts": contexts,
        "context_count": len(contexts),
        "laws": [law.model_dump() for law in laws],
    }


def calculate_context_precision(
    reference: str,
    contexts: list[str],
    laws: list[dict] = None,
) -> float:
    """计算上下文精确率。

    衡量检索到的上下文中有多少与参考答案相关。

    对于法律检索，我们检查：
    1. 检索结果中是否包含参考答案中的法律条款编号（如"第563条"）
    2. 检索结果中是否包含参考答案中的法律概念关键词
    3. 考虑检索结果的相关性分数分布

    Args:
        reference: 参考答案
        contexts: 检索到的上下文列表
        laws: 检索结果（包含相关性分数）

    Returns:
        精确率分数 [0, 1]
    """
    if not contexts and not laws:
        return 0.0

    # 合并所有上下文
    all_context = " ".join(contexts)

    # 1. 检查法律条款编号
    import re
    ref_article_pattern = re.findall(r'第[一二三四五六七八九十百千零\d]+条', reference)
    context_article_pattern = re.findall(r'第[一二三四五六七八九十百千零\d]+条', all_context)

    # 条款编号匹配
    article_matches = 0
    for pattern in ref_article_pattern:
        if pattern in all_context:
            article_matches += 1

    article_precision = article_matches / len(ref_article_pattern) if ref_article_pattern else 0.0

    # 2. 检查法律概念关键词匹配
    legal_concepts = [
        "民法典", "合同法", "合同", "解除", "违约", "赔偿", "损失", "无效",
        "约定", "法定", "公平", "定金", "标的物", "交付", "风险",
        "不可抗力", "变更", "转让", "通知", "连带责任", "格式条款",
        "商业秘密", "利息", "工程", "质量", "价款", "报酬",
        "仲裁", "诉讼", "管辖", "第三人", "承揽", "委托", "租赁",
        "解除权", "违约金", "请求", "催告", "合理期限", "主要债务",
    ]

    # 统计参考答案中的概念
    ref_concepts = set()
    for concept in legal_concepts:
        if concept in reference:
            ref_concepts.add(concept)

    # 统计检索结果中匹配的概念
    matched_concepts = set()
    for concept in ref_concepts:
        if concept in all_context:
            matched_concepts.add(concept)

    concept_precision = len(matched_concepts) / len(ref_concepts) if ref_concepts else 0.0

    # 3. 如果有相关性分数，考虑相关性加权
    relevance_weight = 1.0
    if laws:
        # 计算平均相关性
        avg_relevance = sum(law.get("relevance", 0.5) for law in laws) / len(laws)
        # 分数高于 0.7 的结果越多，精确率越高
        high_relevance_ratio = sum(1 for law in laws if law.get("relevance", 0) >= 0.7) / len(laws)
        relevance_weight = 0.5 + 0.5 * high_relevance_ratio

    # 综合精确率：条款编号权重更高
    if ref_article_pattern:
        base_precision = article_precision * 0.6 + concept_precision * 0.4
    else:
        base_precision = concept_precision

    final_precision = base_precision * relevance_weight

    return min(final_precision, 1.0)


def calculate_context_recall(
    reference: str,
    contexts: list[str],
    laws: list[dict] = None,
) -> float:
    """计算上下文召回率。

    衡量参考答案中有多少信息被检索到。

    对于法律检索，我们检查：
    1. 参考答案中的法律条款编号是否出现在检索结果中
    2. 参考答案中的法律概念是否出现在检索结果中
    3. 考虑检索结果的数量

    Args:
        reference: 参考答案
        contexts: 检索到的上下文列表
        laws: 检索结果（包含相关性分数）

    Returns:
        召回率分数 [0, 1]
    """
    if not reference:
        return 1.0

    if not contexts and not laws:
        return 0.0

    # 合并所有上下文
    all_context = " ".join(contexts)

    # 1. 检查法律条款编号
    import re
    ref_article_pattern = re.findall(r'第[一二三四五六七八九十百千零\d]+条', reference)

    article_recall = 0.0
    for pattern in ref_article_pattern:
        if pattern in all_context:
            article_recall += 1

    article_recall = article_recall / len(ref_article_pattern) if ref_article_pattern else 1.0

    # 2. 检查法律概念关键词匹配
    legal_concepts = [
        "民法典", "合同法", "合同", "解除", "违约", "赔偿", "损失", "无效",
        "约定", "法定", "公平", "定金", "标的物", "交付", "风险",
        "不可抗力", "变更", "转让", "通知", "连带责任", "格式条款",
        "商业秘密", "利息", "工程", "质量", "价款", "报酬",
        "仲裁", "诉讼", "管辖", "第三人", "承揽", "委托", "租赁",
        "解除权", "违约金", "请求", "催告", "合理期限", "主要债务",
    ]

    # 统计参考答案中包含的法律概念
    ref_concepts = set()
    for concept in legal_concepts:
        if concept in reference:
            ref_concepts.add(concept)

    # 统计检索结果中匹配到的概念
    matched_concepts = set()
    for concept in ref_concepts:
        if concept in all_context:
            matched_concepts.add(concept)

    concept_recall = len(matched_concepts) / len(ref_concepts) if ref_concepts else 1.0

    # 3. 考虑检索数量对召回的影响
    # 检索结果越多，覆盖的信息可能越多
    count_bonus = 1.0
    if laws:
        # 检索结果数量对召回的贡献（有上限）
        count = len(laws)
        if count >= 5:
            count_bonus = 1.0
        elif count >= 3:
            count_bonus = 0.85
        elif count >= 1:
            count_bonus = 0.6
        else:
            count_bonus = 0.0

    # 综合召回率
    if ref_article_pattern:
        base_recall = article_recall * 0.6 + concept_recall * 0.4
    else:
        base_recall = concept_recall

    final_recall = base_recall * count_bonus

    return min(final_recall, 1.0)


# ==================== 模拟 RAG 检索（用于测试阈值） ====================


class MockRAGService:
    """模拟 RAG 服务，用于阈值评估测试。

    根据不同的阈值模拟不同的检索结果质量。
    阈值越低，返回的结果越多，但可能包含更多低相关性结果。

    分数分布设计：
    - 高分（0.6-0.8）：高度相关
    - 中分（0.35-0.55）：部分相关
    - 低分（0.2-0.35）：弱相关
    """

    def __init__(self):
        """初始化模拟 RAG 服务"""
        # 预定义的法律条款库（模拟 Milvus 中的数据）
        # 分数分布：高分（0.6-0.8）、中分（0.35-0.55）、低分（0.2-0.35）
        self.law_database = [
            # 高分法律（与大部分合同法律问题高度相关）
            {
                "law_id": "civil_code_563",
                "title": "中华人民共和国民法典",
                "chapter": "第三编 合同编 第七章 合同解除",
                "article": "第五百六十三条　有下列情形之一的，当事人可以解除合同：\n（一）因不可抗力致使不能实现合同目的；\n（二）履行期限届满前，当事人一方明确表示或者以自己的行为表明不履行主要债务；\n（三）当事人一方迟延履行主要债务，经催告后在合理期限内仍未履行；\n（四）当事人一方迟延履行债务或者有其他违约行为致使不能实现合同目的；\n（五）法律规定的其他情形。",
                "base_score": 0.78,
            },
            {
                "law_id": "civil_code_562",
                "title": "中华人民共和国民法典",
                "chapter": "第三编 合同编 第七章 合同解除",
                "article": "第五百六十二条　当事人协商一致，可以解除合同。\n当事人可以约定一方解除合同的事由。解除合同的事由发生时，解除权人可以解除合同。",
                "base_score": 0.75,
            },
            {
                "law_id": "civil_code_585",
                "title": "中华人民共和国民法典",
                "chapter": "第三编 合同编 第八章 违约责任",
                "article": "第五百八十五条　当事人可以约定一方违约时应当根据违约情况向对方支付一定数额的违约金，也可以约定因违约产生的损失赔偿额的计算方法。\n约定的违约金低于造成的损失的，人民法院或者仲裁机构可以根据当事人的请求予以增加；约定的违约金过分高于造成的损失的，人民法院或者仲裁机构可以根据当事人的请求予以适当减少。",
                "base_score": 0.72,
            },
            {
                "law_id": "civil_code_588",
                "title": "中华人民共和国民法典",
                "chapter": "第三编 合同编 第八章 违约责任",
                "article": "第五百八十八条　当事人既约定违约金，又约定定金的，一方违约时，对方可以选择适用违约金或者定金条款。\n定金不足以弥补一方违约造成的损失的，对方可以请求赔偿超过定金数额的损失。",
                "base_score": 0.68,
            },
            {
                "law_id": "civil_code_604",
                "title": "中华人民共和国民法典",
                "chapter": "第三编 合同编 第九章 买卖合同",
                "article": "第六百零四条　标的物毁损、灭失的风险，在标的物交付之前由出卖人承担，交付之后由买受人承担，但是法律另有规定或者当事人另有约定的除外。",
                "base_score": 0.65,
            },
            # 中分法律（部分相关）
            {
                "law_id": "civil_code_787",
                "title": "中华人民共和国民法典",
                "chapter": "第三编 合同编 第十七章 承揽合同",
                "article": "第七百八十七条　定作人在承揽人完成工作前可以随时解除合同，造成承揽人损失的，应当赔偿损失。",
                "base_score": 0.52,
            },
            {
                "law_id": "civil_code_722",
                "title": "中华人民共和国民法典",
                "chapter": "第三编 合同编 第十四章 租赁合同",
                "article": "第七百二十二条　承租人无正当理由未支付或者迟延支付租金的，出租人可以请求承租人在合理期限内支付。承租人逾期不支付的，出租人可以解除合同。",
                "base_score": 0.50,
            },
            {
                "law_id": "civil_code_501",
                "title": "中华人民共和国民法典",
                "chapter": "第一编 总则 第六章 民事法律行为",
                "article": "第五百零一条　当事人在订立合同过程中知悉的商业秘密或者其他应当保密的信息，不得泄露或者不正当地使用。泄露或者不正当地使用该商业秘密或者信息给对方造成损失的，应当承担赔偿责任。",
                "base_score": 0.48,
            },
            {
                "law_id": "civil_code_590",
                "title": "中华人民共和国民法典",
                "chapter": "第三编 合同编 第八章 违约责任",
                "article": "第五百九十条　不可抗力是指不能预见、不能避免且不能克服的客观情况。\n因不可抗力致使不能实现合同目的，当事人可以解除合同。因不可抗力造成违约的，一般不承担民事责任，但法律另有规定的除外。",
                "base_score": 0.46,
            },
            {
                "law_id": "civil_code_582",
                "title": "中华人民共和国民法典",
                "chapter": "第三编 合同编 第一章 一般规定",
                "article": "第五百八十二条　履行不符合约定的，应当按照当事人的约定承担违约责任。对违约责任没有约定或者约定不明确的，受损害方根据标的的性质以及损失的大小，可以合理选择请求对方承担修理、重作、更换、退货、减少价款或者报酬等违约责任。",
                "base_score": 0.44,
            },
            {
                "law_id": "civil_code_791",
                "title": "中华人民共和国民法典",
                "chapter": "第三编 合同编 第十八章 建设工程合同",
                "article": "第七百九十一条　建设工程合同应当采用书面形式。\n发包人可以与总承包人订立建设工程合同，也可以分别与勘察人、设计人、施工人订立勘察、设计、施工承包合同。",
                "base_score": 0.42,
            },
            {
                "law_id": "civil_code_546",
                "title": "中华人民共和国民法典",
                "chapter": "第三编 合同编 第五章 合同的保全",
                "article": "第五百四十六条　债权人转让权利的，应当通知债务人。未经通知，该转让对债务人不发生效力。\n但是，债权人转让权利的通知不得撤销，但是经受让人同意的除外。",
                "base_score": 0.40,
            },
            # 低分法律（弱相关，可能在查询关键词匹配时会被提升分数）
            {
                "law_id": "civil_code_543",
                "title": "中华人民共和国民法典",
                "chapter": "第三编 合同编 第一章 一般规定",
                "article": "第五百四十三条　当事人协商一致，可以变更合同。",
                "base_score": 0.35,
            },
            {
                "law_id": "civil_code_496",
                "title": "中华人民共和国民法典",
                "chapter": "第三编 合同编 第一章 一般规定",
                "article": "第四百九十六条　格式条款是当事人为了重复使用而预先拟定，并在订立合同时未与对方协商的条款。\n采用格式条款订立合同的，提供格式条款的一方应当遵循公平原则确定当事人之间的权利和义务。",
                "base_score": 0.32,
            },
            {
                "law_id": "civil_code_178",
                "title": "中华人民共和国民法典",
                "chapter": "第一编 总则 第八章 民事责任",
                "article": "第一百七十八条　二人以上依法承担连带责任的，权利人有权请求部分或者全部连带责任人承担责任。\n连带责任，由法律规定或者当事人约定。",
                "base_score": 0.28,
            },
            {
                "law_id": "civil_code_119",
                "title": "中华人民共和国民法典",
                "chapter": "第一编 总则 第七章 代理",
                "article": "第一百一十九条　依法成立的合同，对当事人具有法律约束力。",
                "base_score": 0.25,
            },
            {
                "law_id": "civil_code_136",
                "title": "中华人民共和国民法典",
                "chapter": "第一编 总则 第七章 代理",
                "article": "第一百三十六条　民事法律行为自成立时生效，但是法律另有规定或者当事人另有约定的除外。",
                "base_score": 0.22,
            },
            {
                "law_id": "civil_code_155",
                "title": "中华人民共和国民法典",
                "chapter": "第一编 总则 第八章 民事责任",
                "article": "第一百五十五条　无效的或者被撤销的民事法律行为自始没有法律约束力。",
                "base_score": 0.20,
            },
        ]

    def search_laws_mock(
        self,
        query: str,
        min_relevance: float = 0.4,
        max_results: int = 10,
    ) -> list[dict]:
        """模拟检索法律条款。

        Args:
            query: 检索 query
            min_relevance: 最低相关性阈值
            max_results: 最大返回数量

        Returns:
            检索结果列表
        """
        # 根据查询关键词调整部分结果的分数（模拟语义相关性）
        query_lower = query.lower()
        adjusted_results = []

        for law in self.law_database:
            # 基础分数
            score = law["base_score"]

            # 根据关键词匹配微调分数（0.02-0.05 的小幅度调整）
            boost = 0.0
            if "解除" in query_lower or "终止" in query_lower:
                if "解除" in law["article"]:
                    boost += 0.03
            if "违约" in query_lower or "违约金" in query_lower:
                if "违约" in law["article"] or "违约金" in law["article"]:
                    boost += 0.03
            if "风险" in query_lower or "毁损" in query_lower:
                if "风险" in law["article"] or "毁损" in law["article"]:
                    boost += 0.03
            if "变更" in query_lower:
                if "变更" in law["article"]:
                    boost += 0.03
            if "委托" in query_lower:
                if "委托" in law["article"]:
                    boost += 0.03

            score = score + boost

            # 限制分数范围
            score = min(score, 1.0)

            # 应用阈值过滤
            if score >= min_relevance:
                adjusted_results.append({
                    "law_id": law["law_id"],
                    "title": law["title"],
                    "chapter": law["chapter"],
                    "article": law["article"],
                    "relevance": score,
                })

        # 按相关性排序
        adjusted_results.sort(key=lambda x: x["relevance"], reverse=True)

        # 限制返回数量
        return adjusted_results[:max_results]


def evaluate_single_retrieval_with_mock(
    test_case: SearchLawsTestCase,
    threshold: float = 0.4,
    max_results: int = 10,
) -> dict[str, Any]:
    """使用模拟 RAG 服务评估单次检索。

    Args:
        test_case: 测试用例
        threshold: min_relevance 阈值
        max_results: 最大返回结果数

    Returns:
        包含 contexts 和评估指标的字典
    """
    mock_rag = MockRAGService()

    # 调用模拟 search_laws 获取检索结果
    laws = mock_rag.search_laws_mock(
        query=test_case.user_input,
        min_relevance=threshold,
        max_results=max_results,
    )

    # 提取 contexts（法律条款内容）
    contexts = []
    for law in laws:
        context_parts = []
        if law.get("title"):
            context_parts.append(f"《{law['title']}》")
        if law.get("chapter"):
            context_parts.append(law["chapter"])
        if law.get("article"):
            context_parts.append(law["article"])
        context = "\n".join(context_parts)
        if context:
            contexts.append(context)

    # 调试输出
    if threshold in [0.30, 0.50]:
        logger.debug(
            f"[阈值 {threshold}] 检索 '{test_case.user_input[:30]}...' "
            f"返回 {len(laws)} 条结果"
        )

    return {
        "user_input": test_case.user_input,
        "reference": test_case.reference,
        "contexts": contexts,
        "context_count": len(contexts),
        "laws": laws,
    }


def evaluate_threshold(
    test_cases: list[SearchLawsTestCase],
    threshold: float,
    max_results: int = 10,
    use_mock: bool = True,
) -> dict[str, float]:
    """评估给定阈值下的检索质量。

    Args:
        test_cases: 测试用例列表
        threshold: min_relevance 阈值
        max_results: 最大返回结果数
        use_mock: 是否使用模拟 RAG 服务

    Returns:
        包含 context_precision 和 context_recall 的字典
    """
    precisions = []
    recalls = []
    details = []

    for test_case in test_cases:
        try:
            if use_mock:
                result = evaluate_single_retrieval_with_mock(
                    test_case=test_case,
                    threshold=threshold,
                    max_results=max_results,
                )
            else:
                result = evaluate_single_retrieval(
                    test_case=test_case,
                    threshold=threshold,
                    max_results=max_results,
                )

            precision = calculate_context_precision(
                reference=result["reference"],
                contexts=result["contexts"],
            )
            recall = calculate_context_recall(
                reference=result["reference"],
                contexts=result["contexts"],
            )

            precisions.append(precision)
            recalls.append(recall)

            details.append({
                "user_input": test_case.user_input[:50],
                "context_count": result["context_count"],
                "precision": precision,
                "recall": recall,
            })

        except Exception as e:
            logger.warning(f"评估失败: {test_case.user_input[:30]}... - {e}")
            precisions.append(0.0)
            recalls.append(0.0)

    avg_precision = sum(precisions) / len(precisions) if precisions else 0.0
    avg_recall = sum(recalls) / len(recalls) if recalls else 0.0
    composite = (avg_precision + avg_recall) / 2

    return {
        "context_precision": avg_precision,
        "context_recall": avg_recall,
        "composite": composite,
        "details": details,
    }


def run_threshold_experiment(
    test_cases: list[SearchLawsTestCase],
    thresholds: list[float] = None,
    max_results: int = 10,
    use_mock: bool = True,
) -> dict[float, dict[str, float]]:
    """运行不同阈值的对比实验。

    Args:
        test_cases: 测试用例列表
        thresholds: 要测试的阈值列表
        max_results: 最大返回结果数
        use_mock: 是否使用模拟 RAG 服务（默认 True）

    Returns:
        各阈值对应的评估结果
    """
    if thresholds is None:
        thresholds = [0.3, 0.35, 0.4, 0.45, 0.5, 0.55, 0.6]

    results = {}

    mode_str = "模拟 RAG" if use_mock else "真实 RAG"
    print("\n" + "=" * 70)
    print(f"search_laws 检索质量阈值评估实验 ({mode_str})")
    print("=" * 70)
    print(f"测试用例数量: {len(test_cases)}")
    print(f"最大返回数量: {max_results}")
    print("-" * 70)

    for threshold in thresholds:
        logger.info(f"评估阈值 {threshold}...")
        result = evaluate_threshold(
            test_cases=test_cases,
            threshold=threshold,
            max_results=max_results,
            use_mock=use_mock,
        )
        results[threshold] = result

        print(f"\n阈值 = {threshold:.2f}")
        print(f"  精确率 (Precision): {result['context_precision']:.4f}")
        print(f"  召回率 (Recall):    {result['context_recall']:.4f}")
        print(f"  综合分数 (Composite): {result['composite']:.4f}")

    return results


def analyze_and_recommend(results: dict[float, dict[str, float]]) -> dict[str, Any]:
    """分析结果并推荐最优阈值。

    Args:
        results: 各阈值对应的评估结果

    Returns:
        推荐结果
    """
    print("\n" + "=" * 70)
    print("阈值对比分析")
    print("=" * 70)

    # 输出对比表格
    print(f"\n{'阈值':<10} {'精确率':<12} {'召回率':<12} {'综合':<10} {'推荐理由'}")
    print("-" * 70)

    # 按综合分数排序
    sorted_results = sorted(
        results.items(),
        key=lambda x: x[1]["composite"],
        reverse=True
    )

    best_threshold = None
    best_composite = 0.0

    for threshold, metrics in sorted_results:
        # 生成推荐理由
        reasons = []
        if metrics["context_precision"] >= 0.7:
            reasons.append("精确率高")
        if metrics["context_recall"] >= 0.6:
            reasons.append("召回率高")
        if threshold >= 0.35 and threshold <= 0.5:
            reasons.append("阈值适中")
        if metrics["composite"] >= sorted_results[0][1]["composite"] - 0.02:
            reasons.append("★")

        reason_str = ", ".join(reasons) if reasons else ""

        print(
            f"{threshold:<10.2f} "
            f"{metrics['context_precision']:<12.4f} "
            f"{metrics['context_recall']:<12.4f} "
            f"{metrics['composite']:<10.4f} "
            f"{reason_str}"
        )

        if metrics["composite"] > best_composite:
            best_composite = metrics["composite"]
            best_threshold = threshold

    # 找到精确率和召回率平衡点
    # 计算 precision - recall 的差距
    balance_scores = {}
    for threshold, metrics in results.items():
        # 平衡分数：同时考虑综合分数和精确率召回率的平衡性
        diff = abs(metrics["context_precision"] - metrics["context_recall"])
        balance = metrics["composite"] - diff * 0.1  # 惩罚不平衡
        balance_scores[threshold] = balance

    balanced_threshold = max(balance_scores.keys(), key=lambda t: balance_scores[t])

    print("\n" + "-" * 70)

    # 最终推荐
    print("\n" + "=" * 70)
    print("推荐结果")
    print("=" * 70)

    print(f"\n1. 综合最优阈值: {best_threshold:.2f}")
    print(f"   - 综合分数: {results[best_threshold]['composite']:.4f}")
    print(f"   - 精确率: {results[best_threshold]['context_precision']:.4f}")
    print(f"   - 召回率: {results[best_threshold]['context_recall']:.4f}")

    print(f"\n2. 平衡最优阈值: {balanced_threshold:.2f}")
    print(f"   - 综合分数: {results[balanced_threshold]['composite']:.4f}")
    print(f"   - 精确率: {results[balanced_threshold]['context_precision']:.4f}")
    print(f"   - 召回率: {results[balanced_threshold]['context_recall']:.4f}")
    print("   - 特点: 精确率和召回率更加平衡")

    # 根据分析给出最终建议
    final_recommendation = _determine_final_threshold(results, best_threshold, balanced_threshold)

    print(f"\n3. 最终建议阈值: {final_recommendation:.2f}")
    print("-" * 70)
    print(f"\n建议理由:")
    print(f"   - 该阈值在精确率和召回率之间取得了良好平衡")
    print(f"   - 可以有效过滤低相关性结果，同时保留足够的法律条款")

    return {
        "best_threshold": best_threshold,
        "balanced_threshold": balanced_threshold,
        "final_recommendation": final_recommendation,
        "best_metrics": results[best_threshold],
        "balanced_metrics": results[balanced_threshold],
    }


def _determine_final_threshold(
    results: dict[float, dict[str, float]],
    best_threshold: float,
    balanced_threshold: float,
) -> float:
    """根据分析确定最终推荐阈值。

    考虑因素：
    1. 综合分数优先
    2. 精确率和召回率的平衡
    3. 实际业务场景（法律检索需要高精度，但也不能漏掉相关条款）

    Args:
        results: 各阈值对应的评估结果
        best_threshold: 综合最优阈值
        balanced_threshold: 平衡最优阈值

    Returns:
        最终推荐阈值
    """
    # 如果综合最优和平衡最优相同，直接返回
    if best_threshold == balanced_threshold:
        return best_threshold

    # 比较两个阈值的综合分数差距
    best_composite = results[best_threshold]["composite"]
    balanced_composite = results[balanced_threshold]["composite"]

    composite_diff = best_composite - balanced_composite

    # 如果差距小于 0.02，选择平衡阈值
    if composite_diff < 0.02:
        return balanced_threshold

    # 如果精确率差距不大，选择平衡阈值
    # 法律检索场景，精确率更重要
    best_precision = results[best_threshold]["context_precision"]
    balanced_precision = results[balanced_threshold]["context_precision"]

    if balanced_precision >= best_precision - 0.05:
        return balanced_threshold

    # 否则选择综合最优
    return best_threshold


def print_detailed_results(results: dict[float, dict[str, float]]):
    """打印详细结果分析。

    Args:
        results: 各阈值对应的评估结果
    """
    print("\n" + "=" * 70)
    print("详细结果分析")
    print("=" * 70)

    # 分析各阈值的特点
    print("\n【阈值分析】")

    thresholds = sorted(results.keys())

    for i, threshold in enumerate(thresholds):
        metrics = results[threshold]

        print(f"\n阈值 {threshold:.2f}:")

        # 精确率分析
        if metrics["context_precision"] >= 0.75:
            precision_analysis = "精确率高，检索结果噪声少"
        elif metrics["context_precision"] >= 0.6:
            precision_analysis = "精确率中等，存在一定噪声"
        elif metrics["context_precision"] >= 0.4:
            precision_analysis = "精确率较低，需要关注噪声问题"
        else:
            precision_analysis = "精确率低，检索质量需要改进"
        print(f"  精确率: {metrics['context_precision']:.4f} - {precision_analysis}")

        # 召回率分析
        if metrics["context_recall"] >= 0.75:
            recall_analysis = "召回率高，相关条款覆盖全面"
        elif metrics["context_recall"] >= 0.6:
            recall_analysis = "召回率中等，可能遗漏部分条款"
        elif metrics["context_recall"] >= 0.4:
            recall_analysis = "召回率较低，遗漏较多相关条款"
        else:
            recall_analysis = "召回率低，检索结果不完整"
        print(f"  召回率: {metrics['context_recall']:.4f} - {recall_analysis}")

        # 综合评价
        if metrics["composite"] >= 0.7:
            overall = "优秀"
        elif metrics["composite"] >= 0.6:
            overall = "良好"
        elif metrics["composite"] >= 0.5:
            overall = "一般"
        else:
            overall = "需改进"
        print(f"  综合: {metrics['composite']:.4f} - 评价: {overall}")


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="search_laws 检索质量阈值评估")
    parser.add_argument(
        "--quick",
        action="store_true",
        help="快速测试模式，使用较少测试用例"
    )
    parser.add_argument(
        "--threshold",
        type=float,
        nargs="+",
        default=[0.3, 0.35, 0.4, 0.45, 0.5, 0.55, 0.6],
        help="要测试的阈值列表"
    )
    parser.add_argument(
        "--max-results",
        type=int,
        default=10,
        help="最大返回结果数"
    )
    parser.add_argument(
        "--use-real",
        action="store_true",
        help="使用真实 RAG 服务（需要 Milvus 连接）"
    )
    parser.add_argument(
        "--use-mock",
        action="store_true",
        default=True,
        help="使用模拟 RAG 服务（默认）"
    )
    args = parser.parse_args()

    # 根据参数调整测试用例数量
    test_cases = SEARCH_LAWS_TEST_DATASET
    if args.quick:
        test_cases = SEARCH_LAWS_TEST_DATASET[:5]
        print("快速测试模式: 使用 5 个测试用例")

    # 确定是否使用模拟 RAG
    use_mock = not args.use_real

    print(f"\n测试用例总数: {len(test_cases)}")
    print(f"测试阈值: {args.threshold}")
    print(f"检索模式: {'模拟 RAG（用于阈值评估测试）' if use_mock else '真实 RAG（需要 Milvus 连接）'}")

    # 运行实验
    results = run_threshold_experiment(
        test_cases=test_cases,
        thresholds=args.threshold,
        max_results=args.max_results,
        use_mock=use_mock,
    )

    # 分析并推荐
    recommendation = analyze_and_recommend(results)

    # 打印详细结果
    print_detailed_results(results)

    # 输出代码配置建议
    print("\n" + "=" * 70)
    print("代码配置建议")
    print("=" * 70)
    print(f"\n推荐在 SearchLawsInput 中设置默认值:")
    print(f"\n    min_relevance: float = Field(")
    print(f"        default={recommendation['final_recommendation']:.2f},")
    print(f'        description="最低相关性阈值（默认{recommendation["final_recommendation"]:.2f}），'
          f'低于此分数的结果会被过滤"')
    print(f"    )")

    print("\n" + "=" * 70)
    print("评估完成")
    print("=" * 70)

    return recommendation


if __name__ == "__main__":
    main()
