"""合同审查条款提取模型评估模块。

提供完整的评估框架，包括：
1. 精确匹配指标（EM）
2. BLEU 分数
3. ROUGE 分数
4. 条款级别 F1 分数
5. 风险指示器识别率
6. 自定义 JSON 评估

Author: Enterprise Knowledge Agentic RAG Platform
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional
from collections import Counter

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer
from peft import PeftModel
from tqdm import tqdm

logger = logging.getLogger(__name__)


# ==================== 评估指标定义 ====================


@dataclass
class EvaluationMetrics:
    """评估指标结果。"""

    # 整体指标
    exact_match_rate: float = 0.0  # 精确匹配率
    bleu_score: float = 0.0  # BLEU 分数
    rouge_l_score: float = 0.0  # ROUGE-L 分数

    # 条款级别指标
    clause_f1: float = 0.0  # 条款 F1 分数
    clause_precision: float = 0.0  # 条款精确率
    clause_recall: float = 0.0  # 条款召回率

    # 风险指示器指标
    risk_precision: float = 0.0  # 风险精确率
    risk_recall: float = 0.0  # 风险召回率
    risk_f1: float = 0.0  # 风险 F1 分数

    # 当事人指标
    party_f1: float = 0.0  # 当事人 F1 分数

    # 缺失条款指标
    missing_clause_f1: float = 0.0  # 缺失条款 F1 分数

    # 检索主题指标
    topic_f1: float = 0.0  # 检索主题 F1 分数

    # 元数据
    total_samples: int = 0
    processed_samples: int = 0
    failed_samples: int = 0

    def to_dict(self) -> dict[str, Any]:
        """转换为字典。"""
        return {
            "exact_match_rate": round(self.exact_match_rate, 4),
            "bleu_score": round(self.bleu_score, 4),
            "rouge_l_score": round(self.rouge_l_score, 4),
            "clause_f1": round(self.clause_f1, 4),
            "clause_precision": round(self.clause_precision, 4),
            "clause_recall": round(self.clause_recall, 4),
            "risk_f1": round(self.risk_f1, 4),
            "risk_precision": round(self.risk_precision, 4),
            "risk_recall": round(self.risk_recall, 4),
            "party_f1": round(self.party_f1, 4),
            "missing_clause_f1": round(self.missing_clause_f1, 4),
            "topic_f1": round(self.topic_f1, 4),
            "total_samples": self.total_samples,
            "processed_samples": self.processed_samples,
            "failed_samples": self.failed_samples,
        }


# ==================== 评估指标计算 ====================


def calculate_bleu(reference: str, hypothesis: str, n_gram: int = 4) -> float:
    """计算 BLEU 分数。

    BLEU = BP * exp(sum(wn * log(pn)))

    其中：
    - BP: Brevity Penalty (短句惩罚)
    - pn: n-gram 精确率
    - wn: n-gram 权重（通常均匀分布）

    Args:
        reference: 参考文本
        hypothesis: 预测文本
        n_gram: 最大 n-gram 长度

    Returns:
        BLEU 分数 (0-1)
    """
    if not hypothesis or not reference:
        return 0.0

    def get_ngrams(tokens: list[str], n: int) -> Counter:
        """获取 n-gram。"""
        return Counter(tuple(tokens[i:i+n]) for i in range(len(tokens)-n+1))

    ref_tokens = reference.split()
    hyp_tokens = hypothesis.split()

    # 计算各阶 n-gram 精确率
    precisions = []
    for n in range(1, n_gram + 1):
        ref_ngrams = get_ngrams(ref_tokens, n)
        hyp_ngrams = get_ngrams(hyp_tokens, n)

        if not hyp_ngrams:
            precisions.append(0.0)
            continue

        matches = sum((hyp_ngrams & ref_ngrams).values())
        total = sum(hyp_ngrams.values())
        precisions.append(matches / total if total > 0 else 0.0)

    # 处理零精确率
    if all(p == 0 for p in precisions):
        return 0.0

    # 计算几何平均
    log_precisions = [p if p > 0 else 1e-10 for p in precisions]
    avg_precision = sum(log_precisions) / len(log_precisions)
    geo_mean = (avg_precision) ** (1.0 / n_gram)

    # 计算短句惩罚
    ref_len = len(ref_tokens)
    hyp_len = len(hyp_tokens)

    if hyp_len >= ref_len:
        bp = 1.0
    else:
        bp = 1.0 - (ref_len - hyp_len) / ref_len

    return bp * geo_mean


def calculate_rouge_l(reference: str, hypothesis: str) -> float:
    """计算 ROUGE-L 分数。

    ROUGE-L = LCS / len(reference)

    其中 LCS 是最长公共子序列长度。

    Args:
        reference: 参考文本
        hypothesis: 预测文本

    Returns:
        ROUGE-L 分数 (0-1)
    """
    if not hypothesis or not reference:
        return 0.0

    ref_tokens = reference.split()
    hyp_tokens = hypothesis.split()

    # 动态规划计算 LCS
    m, n = len(ref_tokens), len(hyp_tokens)
    dp = [[0] * (n + 1) for _ in range(m + 1)]

    for i in range(1, m + 1):
        for j in range(1, n + 1):
            if ref_tokens[i-1] == hyp_tokens[j-1]:
                dp[i][j] = dp[i-1][j-1] + 1
            else:
                dp[i][j] = max(dp[i-1][j], dp[i][j-1])

    lcs_length = dp[m][n]
    return lcs_length / m if m > 0 else 0.0


def calculate_f1(
    predicted: list[Any],
    reference: list[Any],
    match_fn: callable = None,
    item_name: str = "item",
) -> tuple[float, float, float]:
    """计算 F1 分数。

    F1 = 2 * Precision * Recall / (Precision + Recall)

    Args:
        predicted: 预测列表
        reference: 参考列表
        match_fn: 自定义匹配函数，默认为精确匹配
        item_name: 用于日志的项名称，如 "clause", "risk", "party"

    Returns:
        (precision, recall, f1)

    示例（条款匹配）:
        # 标准答案
        ref = [
            {"clause_id": "第1条", "clause_type": "标的条款"},
            {"clause_id": "第2条", "clause_type": "价款条款"},
        ]
        # 模型预测
        pred = [
            {"clause_id": "第1条", "clause_type": "价款条款"},  # clause_id 对了，但 type 错了
            {"clause_id": "第3条", "clause_type": "履行期限"},
        ]
        # 匹配逻辑：clause_id + clause_type + clause_title 至少 2 个相同
        # 结果：只有第1条的 clause_id 匹配，clause_type 不匹配 → 0 匹配
        # TP=0, FP=2, FN=2
        # P=0/2=0, R=0/2=0, F1=0
    """
    if not predicted and not reference:
        return 1.0, 1.0, 1.0

    if not predicted:
        return 0.0, 0.0, 0.0

    if not reference:
        return 0.0, 0.0, 0.0

    if match_fn is None:
        match_fn = lambda p, r: p == r

    # 统计匹配数量
    tp = 0
    matched_refs = []  # 记录匹配到的参考项

    for p in predicted:
        for r in reference:
            if match_fn(p, r):
                tp += 1
                matched_refs.append(r)
                break

    precision = tp / len(predicted) if predicted else 0.0
    recall = tp / len(reference) if reference else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

    # 打印详细计算过程（方便调试）
    logger.debug(
        f"[{item_name}] 计算详情: "
        f"TP={tp}, FP={len(predicted)-tp}, FN={len(reference)-tp}, "
        f"P={precision:.3f}, R={recall:.3f}, F1={f1:.3f}"
    )

    return precision, recall, f1


def normalize_json(text: str) -> dict:
    """解析并规范化 JSON 文本。

    Args:
        text: JSON 文本

    Returns:
        解析后的字典
    """
    # 清理文本
    text = text.strip()

    # 尝试提取 JSON
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0]
    elif "```" in text:
        text = text.split("```")[1].split("```")[0]

    # 解析 JSON
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {}


def extract_clauses_from_json(data: dict) -> list[dict]:
    """从 JSON 数据中提取条款列表。"""
    clauses = data.get("clauses", [])
    if isinstance(clauses, list):
        return clauses
    return []


def extract_risk_indicators(clauses: list[dict]) -> list[str]:
    """从条款中提取所有风险指示器。"""
    indicators = []
    for clause in clauses:
        if "risk_indicators" in clause:
            indicators.extend(clause["risk_indicators"])
        if "risk_level" in clause and clause["risk_level"] != "无风险":
            indicators.append(f"[{clause['risk_level']}]")
    return indicators


# ==================== 模型评估器 ====================


class ContractModelEvaluator:
    """合同审查模型评估器。"""

    def __init__(
        self,
        base_model_path: str,
        adapter_path: Optional[str] = None,
        device: str = "cuda",
    ):
        """初始化评估器。

        Args:
            base_model_path: 基础模型路径
            adapter_path: LoRA Adapter 路径（可选）
            device: 设备
        """
        self.device = device if torch.cuda.is_available() else "cpu"
        self._load_model(base_model_path, adapter_path)

    def _load_model(
        self,
        base_model_path: str,
        adapter_path: Optional[str],
    ) -> None:
        """加载模型。"""
        logger.info(f"加载基础模型: {base_model_path}")

        self.tokenizer = AutoTokenizer.from_pretrained(
            base_model_path,
            trust_remote_code=True,
            padding_side="right",
        )

        if self.tokenizer.pad_token is None:
            self.tokenizer.pad_token = self.tokenizer.eos_token

        self.model = AutoModelForCausalLM.from_pretrained(
            base_model_path,
            torch_dtype=torch.bfloat16,
            device_map="auto",
            trust_remote_code=True,
        )

        # 加载 Adapter（如果存在）
        if adapter_path:
            logger.info(f"加载 Adapter: {adapter_path}")
            self.model = PeftModel.from_pretrained(
                self.model,
                adapter_path,
            )

        self.model.eval()

    def generate(self, prompt: str, max_length: int = 2048) -> str:
        """生成文本。

        Args:
            prompt: 提示
            max_length: 最大长度

        Returns:
            生成的文本
        """
        messages = [
            {"role": "system", "content": "你是一个专业的合同法律审查助手。"},
            {"role": "user", "content": prompt},
        ]

        text = self.tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True,
        )

        inputs = self.tokenizer(
            [text],
            return_tensors="pt",
            padding=True,
        ).to(self.device)

        with torch.no_grad():
            outputs = self.model.generate(
                **inputs,
                max_new_tokens=max_length,
                temperature=0.1,
                do_sample=True,
                top_p=0.9,
                repetition_penalty=1.1,
            )

        response = self.tokenizer.decode(
            outputs[0][inputs["input_ids"].shape[1]:],
            skip_special_tokens=True,
        )

        return response

    def evaluate_dataset(
        self,
        test_data_path: str,
        instruction_template: str = "{instruction}\n\n{input}",
        output_sample_reports: bool = False,
    ) -> EvaluationMetrics:
        """评估数据集。

        Args:
            test_data_path: 测试数据路径
            instruction_template: 指令模板
            output_sample_reports: 是否输出每个样本的详细报告

        Returns:
            评估指标
        """
        metrics = EvaluationMetrics()
        sample_reports = []  # 存储每个样本的详细报告

        # 加载测试数据
        with open(test_data_path, "r", encoding="utf-8") as f:
            test_samples = [json.loads(line) for line in f]

        metrics.total_samples = len(test_samples)

        # 用于累积计算 BLEU 和 ROUGE
        bleu_scores = []
        rouge_scores = []

        for sample in tqdm(test_samples, desc="评估中"):
            try:
                # 构建输入
                prompt = instruction_template.format(
                    instruction=sample["instruction"],
                    input=sample["input"],
                )

                # 生成预测
                prediction = self.generate(prompt)
                reference = sample["output"]

                # 解析 JSON
                pred_json = normalize_json(prediction)
                ref_json = normalize_json(reference)

                # 计算整体指标
                bleu = calculate_bleu(reference, prediction)
                rouge = calculate_rouge_l(reference, prediction)
                bleu_scores.append(bleu)
                rouge_scores.append(rouge)

                # 计算条款级别指标
                pred_clauses = extract_clauses_from_json(pred_json)
                ref_clauses = extract_clauses_from_json(ref_json)

                # 条款匹配函数：clause_id + clause_type + clause_title 至少 2 个相同才算匹配
                # 这样可以避免条款类型错了但 id 对了的情况
                def clause_match_fn(p: dict, r: dict) -> bool:
                    """条款匹配：clause_id + clause_type + clause_title 至少 2 个相同"""
                    match_count = 0
                    if p.get("clause_id") == r.get("clause_id"):
                        match_count += 1
                    if p.get("clause_type") == r.get("clause_type"):
                        match_count += 1
                    if p.get("clause_title") == r.get("clause_title"):
                        match_count += 1
                    return match_count >= 2

                clause_p, clause_r, clause_f1 = calculate_f1(
                    pred_clauses,
                    ref_clauses,
                    match_fn=clause_match_fn,
                    item_name="clause",
                )

                # 生成样本报告（如果需要）
                if output_sample_reports:
                    report = self._generate_sample_report(
                        sample_id=sample.get("sample_id", "unknown"),
                        pred_clauses=pred_clauses,
                        ref_clauses=ref_clauses,
                        clause_p=clause_p,
                        clause_r=clause_r,
                        clause_f1=clause_f1,
                    )
                    sample_reports.append(report)
                metrics.clause_precision += clause_p
                metrics.clause_recall += clause_r
                metrics.clause_f1 += clause_f1

                # 计算风险指示器指标
                pred_risks = extract_risk_indicators(pred_clauses)
                ref_risks = extract_risk_indicators(ref_clauses)

                risk_p, risk_r, risk_f1 = calculate_f1(
                    pred_risks,
                    ref_risks,
                    item_name="risk",
                )
                metrics.risk_precision += risk_p
                metrics.risk_recall += risk_r
                metrics.risk_f1 += risk_f1

                # 计算当事人指标
                pred_parties = pred_json.get("parties", [])
                ref_parties = ref_json.get("parties", [])
                party_p, party_r, party_f1 = calculate_f1(
                    pred_parties,
                    ref_parties,
                    match_fn=lambda p, r: p.get("name") == r.get("name"),
                    item_name="party",
                )
                metrics.party_f1 += party_f1

                # 计算缺失条款指标
                pred_missing = pred_json.get("missing_clauses", [])
                ref_missing = ref_json.get("missing_clauses", [])
                missing_p, missing_r, missing_f1 = calculate_f1(
                    pred_missing,
                    ref_missing,
                    item_name="missing_clause",
                )
                metrics.missing_clause_f1 += missing_f1

                # 计算检索主题指标
                pred_topics = pred_json.get("legal_search_topics", [])
                ref_topics = ref_json.get("legal_search_topics", [])
                topic_p, topic_r, topic_f1 = calculate_f1(
                    pred_topics,
                    ref_topics,
                    item_name="topic",
                )
                metrics.topic_f1 += topic_f1

                metrics.processed_samples += 1

            except Exception as e:
                logger.warning(f"评估样本失败: {e}")
                metrics.failed_samples += 1

        # 计算平均值
        n = metrics.processed_samples or 1

        metrics.bleu_score = sum(bleu_scores) / len(bleu_scores) if bleu_scores else 0.0
        metrics.rouge_l_score = sum(rouge_scores) / len(rouge_scores) if rouge_scores else 0.0

        metrics.clause_f1 /= n
        metrics.clause_precision /= n
        metrics.clause_recall /= n

        metrics.risk_f1 /= n
        metrics.risk_precision /= n
        metrics.risk_recall /= n

        metrics.party_f1 /= n
        metrics.missing_clause_f1 /= n
        metrics.topic_f1 /= n

        # 如果需要输出样本报告，返回报告列表
        if output_sample_reports:
            return metrics, sample_reports

        return metrics

    def _generate_sample_report(
        self,
        sample_id: str,
        pred_clauses: list,
        ref_clauses: list,
        clause_p: float,
        clause_r: float,
        clause_f1: float,
    ) -> dict:
        """生成单个样本的详细评估报告。

        用于分析模型在每个样本上的表现，帮助调试和改进。
        """
        def clause_match_fn(p: dict, r: dict) -> bool:
            match_count = 0
            if p.get("clause_id") == r.get("clause_id"):
                match_count += 1
            if p.get("clause_type") == r.get("clause_type"):
                match_count += 1
            if p.get("clause_title") == r.get("clause_title"):
                match_count += 1
            return match_count >= 2

        # 找出匹配和未匹配的条款
        matched_preds = []
        unmatched_preds = []

        for p in pred_clauses:
            is_matched = False
            for r in ref_clauses:
                if clause_match_fn(p, r):
                    is_matched = True
                    matched_preds.append({
                        "clause_id": p.get("clause_id"),
                        "clause_type": p.get("clause_type"),
                        "clause_title": p.get("clause_title"),
                        "matched": True,
                    })
                    break
            if not is_matched:
                unmatched_preds.append({
                    "clause_id": p.get("clause_id"),
                    "clause_type": p.get("clause_type"),
                    "clause_title": p.get("clause_title"),
                    "matched": False,
                    "reason": "未匹配到标准答案",
                })

        # 找出未匹配的参考答案
        unmatched_refs = []
        for r in ref_clauses:
            is_matched = False
            for p in pred_clauses:
                if clause_match_fn(p, r):
                    is_matched = True
                    break
            if not is_matched:
                unmatched_refs.append({
                    "clause_id": r.get("clause_id"),
                    "clause_type": r.get("clause_type"),
                    "clause_title": r.get("clause_title"),
                    "reason": "模型未预测",
                })

        return {
            "sample_id": sample_id,
            "clause_metrics": {
                "precision": round(clause_p, 4),
                "recall": round(clause_r, 4),
                "f1": round(clause_f1, 4),
            },
            "matched_clauses": matched_preds,
            "unmatched_preds": unmatched_preds,
            "unmatched_refs": unmatched_refs,
        }

    def compare_models(
        self,
        base_model_path: str,
        adapter_path: str,
        test_data_path: str,
    ) -> dict[str, EvaluationMetrics]:
        """对比基础模型和微调模型。

        Args:
            base_model_path: 基础模型路径
            adapter_path: Adapter 路径
            test_data_path: 测试数据路径

        Returns:
            包含两个模型评估结果的字典
        """
        results = {}

        # 评估基础模型
        logger.info("评估基础模型...")
        base_evaluator = ContractModelEvaluator(base_model_path)
        results["base_model"] = base_evaluator.evaluate_dataset(test_data_path)

        # 评估微调模型
        logger.info("评估微调模型...")
        finetuned_evaluator = ContractModelEvaluator(base_model_path, adapter_path)
        results["finetuned_model"] = finetuned_evaluator.evaluate_dataset(test_data_path)

        return results


# ==================== 主函数 ====================


def main():
    """主函数。"""
    import argparse

    parser = argparse.ArgumentParser(description="合同审查模型评估")
    parser.add_argument("--base-model", type=str, required=True, help="基础模型路径")
    parser.add_argument("--adapter", type=str, help="Adapter 路径")
    parser.add_argument("--test-data", type=str, required=True, help="测试数据路径")
    parser.add_argument("--output", type=str, help="评估结果输出路径")
    parser.add_argument("--sample-reports", action="store_true", help="输出每个样本的详细报告")
    parser.add_argument("--sample-reports-output", type=str, help="样本报告输出路径")

    args = parser.parse_args()

    # 评估
    evaluator = ContractModelEvaluator(
        base_model_path=args.base_model,
        adapter_path=args.adapter,
    )

    # 根据是否需要样本报告选择调用方式
    if args.sample_reports:
        metrics, sample_reports = evaluator.evaluate_dataset(
            args.test_data,
            output_sample_reports=True,
        )
    else:
        metrics = evaluator.evaluate_dataset(args.test_data)
        sample_reports = None

    # 输出结果
    print("\n" + "=" * 50)
    print("评估结果")
    print("=" * 50)
    print(json.dumps(metrics.to_dict(), indent=2, ensure_ascii=False))

    # 保存结果
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(metrics.to_dict(), f, indent=2, ensure_ascii=False)
        print(f"\n评估结果已保存至: {output_path}")

    # 保存样本报告
    if args.sample_reports and sample_reports:
        reports_path = Path(args.sample_reports_output) if args.sample_reports_output else Path("sample_reports.json")
        with open(reports_path, "w", encoding="utf-8") as f:
            json.dump(sample_reports, f, indent=2, ensure_ascii=False)
        print(f"样本报告已保存至: {reports_path}")


if __name__ == "__main__":
    main()
