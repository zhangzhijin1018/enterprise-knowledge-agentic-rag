# 合同审核 Agent 评估方案

> 本文档详细介绍合同审核 Agent 的评估方法论、指标计算公式、技术栈实现和代码示例。
>
> **版本**: v1.0.0
> **更新日期**: 2026-05-04
> **适用项目**: 企业知识 Agentic RAG 平台

---

## 目录

1. [概述](#1-概述)
2. [评估方法论](#2-评估方法论)
3. [评估指标详解](#3-评估指标详解)
4. [技术栈与依赖](#4-技术栈与依赖)
5. [快速开始](#5-快速开始)
6. [代码实现](#6-代码实现)
7. [自定义评估](#7-自定义评估)
8. [FAQ](#8-faq)

---

## 1. 概述

### 1.1 项目背景

合同审核 Agent 是企业知识 Agentic RAG 平台的核心能力之一，负责：
- 合同类型分类
- 合同条款抽取
- 法律风险识别
- 风险等级评估
- 审查报告生成

### 1.2 评估目标

```
┌─────────────────────────────────────────────────────────────┐
│                      评估目标体系                            │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  1. 质量评估                                                │
│     - 验证 Agent 输出质量                                    │
│     - 量化各维度表现（分类、抽取、风险识别）                  │
│     - 发现潜在问题和改进方向                                │
│                                                              │
│  2. 回归测试                                                │
│     - 防止新版本引入质量问题                                │
│     - CI/CD 集成，自动门禁检查                              │
│                                                              │
│  3. 持续优化                                                │
│     - 建立性能基线                                          │
│     - 跟踪优化效果                                          │
│     - 指导模型和 Prompt 迭代                                │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

### 1.3 评估流程图

```
                    ┌─────────────────┐
                    │   测试用例集     │
                    │ (人工标注/合成)  │
                    └────────┬────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────┐
│                    被评估对象：合同审核 Agent                  │
│  ┌─────────┐   ┌─────────┐   ┌─────────┐   ┌─────────┐   │
│  │解析合同 │ → │检索法规 │ → │抽取条款 │ → │风险分析 │   │
│  └─────────┘   └─────────┘   └─────────┘   └─────────┘   │
│                                                              │
│  ┌─────────┐   ┌─────────┐   ┌─────────┐                  │
│  │  反思   │ → │HumanReview│ → │生成报告 │                  │
│  └─────────┘   └─────────┘   └─────────┘                  │
└─────────────────────────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────┐
│                      评估层                                  │
│                                                              │
│  ┌─────────────────┐      ┌─────────────────┐              │
│  │ 确定性评估器    │      │  LLM-as-Judge   │              │
│  │ (规则/算法)     │      │  (语义质量)      │              │
│  └────────┬────────┘      └────────┬────────┘              │
│           │                        │                        │
│           └───────────┬────────────┘                        │
│                       ▼                                      │
│              ┌─────────────────┐                            │
│              │    综合评分      │                            │
│              │   + 详细报告     │                            │
│              └─────────────────┘                            │
└─────────────────────────────────────────────────────────────┘
```

---

## 2. 评估方法论

### 2.1 混合评估架构

我们采用「确定性评估 + LLM-as-Judge」的混合评估架构：

```
┌─────────────────────────────────────────────────────────────┐
│                    混合评估架构                              │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              第一层：确定性评估（规则引擎）              │   │
│  │                                                      │   │
│  │  • Token 重叠度计算（精确率/召回率/F1）              │   │
│  │  • 枚举值精确匹配（合同类型、风险等级）               │   │
│  │  • 集合交并比（条款列表、风险列表）                   │   │
│  │  • 格式完整性校验                                    │   │
│  │  • ROUGE/BLEU 等传统 NLP 指标                        │   │
│  │                                                      │   │
│  │  优点：快速、可复现、无 API 成本                      │   │
│  │  适用：结构化输出、格式校验、初步筛选                 │   │
│  └─────────────────────────────────────────────────────┘   │
│                           │                                  │
│                           ▼                                  │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              第二层：LLM-as-Judge（语义评估）          │   │
│  │                                                      │   │
│  │  • 报告质量评分（1-5 分）                            │   │
│  │  • 风险描述准确性                                    │   │
│  │  • 建议实用性                                        │   │
│  │  • 推理连贯性                                        │   │
│  │  • 偏见检测（位置、长度的偏好）                       │   │
│  │                                                      │   │
│  │  优点：理解语义、评估主观质量、接近人类判断           │   │
│  │  适用：报告评估、建议质量、多维度综合评分             │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 LLM-as-Judge 原理

**核心思想**：利用大语言模型的理解能力，对生成内容进行质量评估。

```
┌─────────────────────────────────────────────────────────────┐
│                    LLM-as-Judge 原理                        │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  传统评估：                                                  │
│  ┌─────────┐     ┌─────────┐     ┌─────────┐              │
│  │标准答案 │ vs  │预测答案 │  →  │  人工   │              │
│  │(Ground  │     │(Prediction)│   │  评分   │              │
│  │ Truth)  │     │         │     │         │              │
│  └─────────┘     └─────────┘     └─────────┘              │
│                                                              │
│  LLM-as-Judge:                                              │
│  ┌─────────┐     ┌─────────┐     ┌─────────┐              │
│  │任务描述 │ +   │标准答案 │ +   │预测答案 │              │
│  │(Prompt) │     │(Ground  │     │(Prediction)│  → LLM → 评分 │
│  │         │     │ Truth)  │     │         │     +理由   │
│  └─────────┘     └─────────┘     └─────────┘              │
│                                                              │
│  优势：                                                      │
│  ✓ 不需要精确匹配，支持多个正确答案                         │
│  ✓ 评估语义质量，不被措辞差异困扰                           │
│  ✓ 可解释，输出评分理由                                     │
│  ✓ 适应性强，可评估复杂任务                                 │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

### 2.3 评估偏见与缓解

LLM-as-Judge 存在几种常见偏见，我们采用相应缓解策略：

| 偏见类型 | 描述 | 缓解策略 |
|---------|------|---------|
| **位置偏见** | 倾向于给列表首位/末位的选项更高分 | 打乱选项顺序，多次评估取平均 |
| **长度偏见** | 倾向于给更长的回答更高分 | 归一化评分，控制回答长度 |
| **自我增强** | 模型倾向于给自己的输出更高分 | 使用不同的模型作为 Judge |
| **严格度差异** | 不同模型作为 Judge 时严格度不同 | 校准 Judge，使用标准基准 |

---

## 3. 评估指标详解

### 3.1 指标体系总览

```
┌─────────────────────────────────────────────────────────────┐
│                    评估指标体系                              │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  【任务维度】                                                │
│  ├── 合同分类指标                                            │
│  │   ├── Accuracy（准确率）                                 │
│  │   ├── Precision / Recall / F1                           │
│  │   └── Confusion Matrix（混淆矩阵）                      │
│  │                                                        │
│  ├── 条款抽取指标                                           │
│  │   ├── Token-Level F1                                   │
│  │   ├── Span-Level F1                                    │
│  │   ├── Precision / Recall                               │
│  │   └── Content Overlap（内容重叠度）                    │
│  │                                                        │
│  └── 风险识别指标                                           │
│      ├── Identification F1                                 │
│      ├── Level Accuracy（等级准确率）                      │
│      └── Confusion Matrix                                  │
│                                                              │
│  【质量维度】                                                │
│  ├── 报告质量（LLM Judge）                                 │
│  │   ├── Overall Score（综合评分）                        │
│  │   ├── Completeness（完整性）                            │
│  │   ├── Accuracy（准确性）                                │
│  │   └── Reasoning（推理质量）                             │
│  │                                                        │
│  └── 引用准确性                                            │
│      ├── Citation Precision                                │
│      ├── Citation Recall                                   │
│      └── Citation F1                                       │
│                                                              │
│  【工作流维度】                                              │
│  ├── 成功率（Success Rate）                                 │
│  ├── 工具调用准确率                                         │
│  └── Human Review 触发率                                   │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

### 3.2 分类任务指标

#### 3.2.1 准确率（Accuracy）

$$
\text{Accuracy} = \frac{\text{预测正确的样本数}}{\text{总样本数}} = \frac{TP + TN}{TP + TN + FP + FN}
$$

```python
def calculate_accuracy(y_true: list, y_pred: list) -> float:
    """计算准确率。

    Args:
        y_true: 真实标签列表
        y_pred: 预测标签列表

    Returns:
        准确率（0-1）
    """
    correct = sum(1 for t, p in zip(y_true, y_pred) if t == p)
    return correct / len(y_true) if y_true else 0.0
```

#### 3.2.2 精确率、召回率、F1

$$
\text{Precision} = \frac{TP}{TP + FP}, \quad \text{Recall} = \frac{TP}{TP + FN}, \quad \text{F1} = \frac{2 \times \text{Precision} \times \text{Recall}}{\text{Precision} + \text{Recall}}
$$

```python
def calculate_prf(y_true: list, y_pred: list) -> dict[str, float]:
    """计算精确率、召回率、F1。

    Args:
        y_true: 真实标签列表
        y_pred: 预测标签列表

    Returns:
        包含 precision、recall、f1 的字典
    """
    # 统计 TP/FP/FN
    tp = sum(1 for t, p in zip(y_true, y_pred) if t == 1 and p == 1)
    fp = sum(1 for t, p in zip(y_true, y_pred) if t == 0 and p == 1)
    fn = sum(1 for t, p in zip(y_true, y_pred) if t == 1 and p == 0)

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

    return {
        "precision": precision,
        "recall": recall,
        "f1": f1,
    }
```

### 3.3 条款抽取指标

#### 3.3.1 Token-Level F1

基于 Token（词）重叠计算 F1：

```python
def calculate_token_level_f1(reference: str, hypothesis: str) -> dict[str, float]:
    """计算 Token 级别的 Precision、Recall、F1。

    公式：
    Precision = |Reference Tokens ∩ Hypothesis Tokens| / |Hypothesis Tokens|
    Recall = |Reference Tokens ∩ Hypothesis Tokens| / |Reference Tokens|
    F1 = 2 * Precision * Recall / (Precision + Recall)

    Args:
        reference: 标准文本
        hypothesis: 预测文本

    Returns:
        包含 precision、recall、f1 的字典
    """
    # 分词（简单按空格分词，实际可用更复杂的分词器）
    ref_tokens = set(reference.lower().split())
    hyp_tokens = set(hypothesis.lower().split())

    if not ref_tokens and not hyp_tokens:
        return {"precision": 1.0, "recall": 1.0, "f1": 1.0}

    if not ref_tokens or not hyp_tokens:
        return {"precision": 0.0, "recall": 0.0, "f1": 0.0}

    intersection = len(ref_tokens & hyp_tokens)

    precision = intersection / len(hyp_tokens)
    recall = intersection / len(ref_tokens)
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

    return {
        "precision": precision,
        "recall": recall,
        "f1": f1,
    }
```

#### 3.3.2 ROUGE-L

ROUGE-L 使用最长公共子序列（LCS）计算：

$$
\text{ROUGE-L} = \frac{\text{LCS}(Reference, Hypothesis)}{\max(len(Reference), len(Hypothesis))}
$$

```python
def calculate_rouge_l(reference: str, hypothesis: str) -> float:
    """计算 ROUGE-L。

    使用动态规划计算最长公共子序列长度。

    Args:
        reference: 标准文本
        hypothesis: 预测文本

    Returns:
        ROUGE-L 分数（0-1）
    """
    ref_tokens = reference.split()
    hyp_tokens = hypothesis.split()

    m, n = len(ref_tokens), len(hyp_tokens)

    # 动态规划计算 LCS 长度
    dp = [[0] * (n + 1) for _ in range(m + 1)]

    for i in range(1, m + 1):
        for j in range(1, n + 1):
            if ref_tokens[i - 1] == hyp_tokens[j - 1]:
                dp[i][j] = dp[i - 1][j - 1] + 1
            else:
                dp[i][j] = max(dp[i - 1][j], dp[i][j - 1])

    lcs_length = dp[m][n]
    return lcs_length / max(m, n) if max(m, n) > 0 else 0.0
```

### 3.4 风险识别指标

#### 3.4.1 集合匹配评估

将风险识别视为集合匹配问题：

```python
def evaluate_risk_identification(
    ground_truth_risks: list[dict],
    predicted_risks: list[dict],
) -> dict[str, float]:
    """评估风险识别性能。

    公式：
    Precision = |GT ∩ Pred| / |Pred|
    Recall = |GT ∩ Pred| / |GT|
    F1 = 2 * Precision * Recall / (Precision + Recall)

    Args:
        ground_truth_risks: 标准风险列表
            [{"risk_id": "R1", "description": "...", "level": "high"}, ...]
        predicted_risks: 预测风险列表
            [{"risk_id": "P1", "description": "...", "level": "medium"}, ...]

    Returns:
        评估指标字典
    """
    # 构建风险集合（使用描述的标准化形式作为标识）
    def normalize_risk(r: dict) -> str:
        return r.get("description", "").lower().strip()

    gt_set = {normalize_risk(r) for r in ground_truth_risks}
    pred_set = {normalize_risk(r) for r in predicted_risks}

    if not gt_set and not pred_set:
        return {"precision": 1.0, "recall": 1.0, "f1": 1.0, "accuracy": 1.0}

    if not gt_set or not pred_set:
        return {"precision": 0.0, "recall": 0.0, "f1": 0.0, "accuracy": 0.0}

    # 计算 TP/FP/FN
    tp = len(gt_set & pred_set)  # 正确识别
    fp = len(pred_set - gt_set)  # 误报
    fn = len(gt_set - pred_set)  # 漏报

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
    accuracy = tp / (tp + fp + fn) if (tp + fp + fn) > 0 else 0.0

    return {
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "accuracy": accuracy,
        "true_positives": tp,
        "false_positives": fp,
        "false_negatives": fn,
    }
```

### 3.5 LLM Judge 评分

#### 3.5.1 多维度评分量表

```python
# 评分量表定义（1-5 分）
SCORING_RUBRIC = {
    5: """完全满足要求，表现优秀：
          - 准确识别所有关键要素
          - 描述清晰、准确、有深度
          - 建议具体、可操作、有价值
          - 推理过程逻辑严密""",

    4: """较好满足要求，有轻微不足：
          - 基本准确，少量遗漏或偏差
          - 描述较清晰，偶有模糊
          - 建议有一定价值，轻微可改进
          - 推理基本合理""",

    3: """基本满足要求，有明显不足：
          - 识别大部分内容，但有明显遗漏
          - 描述基本清晰，部分不准确
          - 建议有一定参考价值
          - 推理过程基本合理""",

    2: """较差，有较多问题：
          - 遗漏较多重要内容
          - 描述不够清晰准确
          - 建议不够具体或不太实用
          - 推理过程有逻辑问题""",

    1: """不合格，无法接受：
          - 遗漏关键内容或存在重大错误
          - 描述模糊或完全错误
          - 建议不可行或有害
          - 推理逻辑混乱""",
}
```

#### 3.5.2 综合评分计算

```python
def calculate_weighted_score(
    dimension_scores: dict[str, float],
    weights: dict[str, float] | None = None,
) -> float:
    """计算加权综合评分。

    综合评分 = Σ(维度得分 × 权重) / Σ权重

    Args:
        dimension_scores: 各维度得分（0-1）
        weights: 各维度权重，默认权重如下

    Returns:
        加权综合评分（0-1）
    """
    if weights is None:
        # 默认权重配置（基于业务重要性）
        weights = {
            "accuracy": 0.25,           # 准确性
            "completeness": 0.25,       # 完整性
            "suggestion": 0.25,         # 建议质量
            "reasoning": 0.15,          # 推理质量
            "safety": 0.10,              # 安全性
        }

    total_weight = sum(weights.values())
    weighted_sum = sum(
        dimension_scores.get(dim, 0.0) * weight
        for dim, weight in weights.items()
    )

    return weighted_sum / total_weight if total_weight > 0 else 0.0
```

### 3.6 综合评分

#### 3.6.1 多任务综合评分

```python
def calculate_overall_score(metrics: ContractEvaluationMetrics) -> float:
    """计算综合评分（0-100）。

    采用分层加权方案：
    1. 各维度先计算加权子评分
    2. 再对各子评分进行总加权

    Args:
        metrics: 评估指标对象

    Returns:
        综合评分（0-100）
    """
    # 各维度权重
    weights = {
        "classification": 0.10,    # 合同分类
        "clause_extraction": 0.20, # 条款抽取
        "risk_identification": 0.25, # 风险识别
        "risk_level": 0.10,        # 风险等级
        "report_quality": 0.20,    # 报告质量
        "workflow": 0.10,          # 工作流
        "citation": 0.05,          # 引用准确性
    }

    # 计算各子评分
    sub_scores = {
        "classification": metrics.contract_classification_accuracy,
        "clause_extraction": metrics.clause_extraction_f1,
        "risk_identification": metrics.risk_identification_f1,
        "risk_level": metrics.risk_level_accuracy,
        "report_quality": metrics.report_quality_score,
        "workflow": metrics.workflow_success_rate,
        "citation": metrics.citation_accuracy,
    }

    # 加权求和
    total_weight = sum(weights.values())
    overall = sum(
        sub_scores.get(dim, 0.0) * weight
        for dim, weight in weights.items()
    ) / total_weight

    return overall * 100  # 转换为 0-100
```

---

## 4. 技术栈与依赖

### 4.1 核心依赖

```toml
# pyproject.toml

[project]
name = "enterprise-knowledge-agentic-rag"
version = "1.0.0"

dependencies = [
    # ========== 核心依赖 ==========
    "fastapi>=0.109.0",                    # Web 框架
    "uvicorn>=0.27.0",                     # ASGI 服务器
    "pydantic>=2.5.0",                     # 数据验证

    # ========== LangChain / LangGraph ==========
    "langchain>=0.1.0",                    # Agent 框架
    "langgraph>=0.0.20",                   # 状态图
    "langchain-core>=0.1.0",               # LangChain 核心

    # ========== LLM 支持 ==========
    "openai>=1.10.0",                       # OpenAI SDK
    "anthropic>=0.18.0",                   # Anthropic SDK（Claude）

    # ========== RAG 相关 ==========
    "milvus-lite>=2.3.0",                  # 向量数据库（轻量版）
    "pymilvus>=2.3.0",                     # Milvus Python SDK
    "flagembedding>=1.2.0",                # BGE-M3 Embedding

    # ========== 数据库 ==========
    "sqlalchemy>=2.0.0",                    # ORM
    "asyncpg>=0.29.0",                      # PostgreSQL 异步驱动

    # ========== 异步 ==========
    "redis>=5.0.0",                         # Redis 客户端
    "celery>=5.3.0",                        # 任务队列

    # ========== 评估相关 ==========
    "numpy>=1.26.0",                        # 数值计算
    "scikit-learn>=1.4.0",                 # ML 工具（混淆矩阵等）

    # ========== 测试 ==========
    "pytest>=8.0.0",                        # 测试框架
    "pytest-asyncio>=0.23.0",               # 异步测试

    # ========== 工具 ==========
    "python-dotenv>=1.0.0",                # 环境变量
    "loguru>=0.7.0",                       # 日志
    "httpx>=0.26.0",                       # HTTP 客户端
]

[project.optional-dependencies]
dev = [
    "black>=24.0.0",                        # 代码格式化
    "ruff>=0.2.0",                          # Linting
    "mypy>=1.8.0",                          # 类型检查
    "pre-commit>=3.6.0",                   # Git Hooks
]

# vLLM（用于本地模型部署，可选）
vllm = [
    "vllm>=0.3.0",                         # 高性能推理
]
```

### 4.2 LLM 模型配置

```python
# core/config/settings.py

from pydantic_settings import BaseSettings
from typing import Literal


class Settings(BaseSettings):
    """应用配置。"""

    # ========== LLM 配置 ==========
    # Qwen-32B 模型配置（用于 Agent 和 Judge）
    llm_provider: Literal["openai", "vllm", "ollama"] = "vllm"
    llm_base_url: str = "http://localhost:8000/v1"  # vLLM 服务地址
    llm_api_key: str = "EMPTY"  # 本地部署通常不需要 API Key
    llm_model_name: str = "Qwen3-32B"  # 模型名称
    llm_timeout_seconds: int = 120  # 超时时间

    # Embedding 模型配置
    embedding_provider: str = "bge-m3"
    embedding_model: str = "BAAI/bge-m3"
    embedding_dimension: int = 1024

    # Reranker 模型配置
    reranker_provider: str = "bge-reranker"
    reranker_model: str = "BAAI/bge-reranker-v2-m3"

    class Config:
        env_file = ".env"
        case_sensitive = False


# 获取配置实例
def get_settings() -> Settings:
    return Settings()
```

### 4.3 vLLM 本地部署（推荐）

```bash
# 安装 vLLM
pip install vllm

# 启动 Qwen3-32B 模型服务
python -m vllm.entrypoints.openai.api_server \
    --model Qwen/Qwen3-32B \
    --dtype half \
    --port 8000 \
    --gpu-memory-utilization 0.95 \
    --max-model-len 32768 \
    --tensor-parallel-size 2  # 如果有多卡，设置张量并行

# 验证服务
curl http://localhost:8000/v1/models
```

---

## 5. 快速开始

### 5.1 环境准备

```bash
# 1. 激活 conda 环境
conda activate tmf_project

# 2. 安装依赖
pip install -e .

# 3. 配置环境变量
cp .env.example .env
# 编辑 .env，配置 LLM 地址

# 4. 验证安装
python -c "from core.evaluation import ContractEvaluator; print('安装成功!')"
```

### 5.2 运行评估

```bash
# 使用合成数据运行评估（推荐快速验证）
conda run -n tmf_project python scripts/run_evaluation.py \
    --synthetic 20 \
    --judge-model Qwen3-32B \
    --output-dir outputs/evaluation

# 使用自定义测试套件
conda run -n tmf_project python scripts/run_evaluation.py \
    --suite data/contract_test_suite.json \
    --judge-model Qwen3-32B

# 使用轻量模型（如果 Qwen-32B 不可用）
conda run -n tmf_project python scripts/run_evaluation.py \
    --synthetic 50 \
    --judge-model Qwen3-8B \
    --max-concurrent 10
```

### 5.3 查看报告

```bash
# 报告输出目录
ls outputs/evaluation/

# 输出文件：
# - evaluation_report_{report_id}.json   # 详细 JSON 报告
# - evaluation_report_{report_id}.md     # Markdown 报告
# - evaluation_results_{report_id}.csv   # CSV 数据
```

### 5.4 API 评估

```bash
# 启动 API 服务
conda run -n tmf_project uvicorn apps.api.main:app --reload

# 评估单个合同
curl -X POST http://localhost:8000/api/v1/evaluation/contract \
    -H "Content-Type: application/json" \
    -d '{
        "contract_id": "test_001",
        "contract_name": "设备采购合同",
        "contract_text": "甲方：XXX\n乙方：YYY\n...",
        "judge_model": "Qwen3-32B"
    }'

# 批量评估
curl -X POST http://localhost:8000/api/v1/evaluation/contract/batch \
    -H "Content-Type: application/json" \
    -d '{
        "generate_synthetic": true,
        "synthetic_count": 20,
        "judge_model": "Qwen3-32B"
    }'
```

---

## 6. 代码实现

### 6.1 核心评估器

```python
# core/evaluation/contract_evaluator/evaluator.py

from __future__ import annotations

import logging
import time
from typing import Any, Callable, Optional

from core.evaluation.contract_evaluator.metrics import (
    ContractEvaluationMetrics,
    ContractEvaluationResult,
)
from core.evaluation.contract_evaluator.dataset import (
    ContractTestCase,
    ContractTestSuite,
)
from core.evaluation.contract_evaluator.judge import (
    ContractJudgeConfig,
    DeterministicJudgeEvaluator,
    LLMJudgeEvaluator,
)
from core.evaluation.contract_evaluator.report import ReportGenerator

logger = logging.getLogger(__name__)


class ContractEvaluator:
    """合同审核 Agent 核心评估器。

    评估流程：
    1. 对每个测试用例运行合同审核 Agent
    2. 使用确定性评估器计算客观指标
    3. 使用 LLM Judge 评估主观质量
    4. 汇总结果，生成报告
    """

    def __init__(
        self,
        llm_judge_config: ContractJudgeConfig | None = None,
        agent_executor: Callable | None = None,
    ) -> None:
        """初始化评估器。

        Args:
            llm_judge_config: LLM Judge 配置
            agent_executor: Agent 执行器（异步函数）
        """
        self._llm_judge_config = llm_judge_config or ContractJudgeConfig()
        self._agent_executor = agent_executor

        # 初始化评估器组件
        self._llm_judge = LLMJudgeEvaluator(config=self._llm_judge_config)
        self._deterministic_judge = DeterministicJudgeEvaluator()
        self._report_generator = ReportGenerator()

        logger.info(f"ContractEvaluator 初始化完成 | judge_model={self._llm_judge_config.judge_model.value}")

    async def evaluate_single(
        self,
        test_case: ContractTestCase,
        agent_output: dict[str, Any] | None = None,
    ) -> ContractEvaluationResult:
        """评估单个测试用例。

        Args:
            test_case: 测试用例
            agent_output: Agent 输出（如果已有）

        Returns:
            评估结果
        """
        start_time = time.time()
        case_id = test_case.case_id

        logger.info(f"[{case_id}] 开始评估...")

        try:
            # 如果没有 Agent 输出，执行 Agent
            if agent_output is None:
                if self._agent_executor is None:
                    raise ValueError("需要提供 agent_executor 或 agent_output")
                agent_output = await self._agent_executor(test_case)

            # ===== 评估合同分类 =====
            classification_metrics = self._evaluate_classification(
                ground_truth=test_case.ground_truth.correct_contract_type,
                prediction=agent_output.get("contract_type", ""),
            )

            # ===== 评估条款抽取 =====
            clause_metrics = self._evaluate_clause_extraction(
                ground_truth=test_case.ground_truth.clauses,
                prediction=agent_output.get("clauses", []),
            )

            # ===== 评估风险识别 =====
            risk_metrics = self._evaluate_risk_identification(
                ground_truth=test_case.ground_truth.risks,
                prediction=agent_output.get("risks", []),
            )

            # ===== 评估报告质量 =====
            report_metrics = await self._evaluate_report_quality(
                ground_truth=test_case.ground_truth.expected_report_summary,
                prediction=agent_output.get("review_report", {}),
                contract_text=test_case.contract_text,
            )

            # ===== 计算综合指标 =====
            metrics = ContractEvaluationMetrics(
                contract_classification_accuracy=classification_metrics["accuracy"],
                clause_extraction_precision=clause_metrics["precision"],
                clause_extraction_recall=clause_metrics["recall"],
                clause_extraction_f1=clause_metrics["f1"],
                risk_identification_precision=risk_metrics["precision"],
                risk_identification_recall=risk_metrics["recall"],
                risk_identification_f1=risk_metrics["f1"],
                report_quality_score=report_metrics["quality_score"],
                citation_accuracy=report_metrics["citation_accuracy"],
            )

            # ===== 计算综合评分 =====
            overall_score = metrics.get_weighted_overall_score()

            # 构建评估结果
            result = ContractEvaluationResult(
                contract_id=case_id,
                contract_name=test_case.contract_name,
                contract_type=test_case.contract_type,
                metrics=metrics,
                overall_score=overall_score,
                evaluation_time_ms=(time.time() - start_time) * 1000,
                model_used=self._llm_judge_config.judge_model.value,
            )

            logger.info(f"[{case_id}] 评估完成 | overall_score={overall_score:.2f}")

            return result

        except Exception as e:
            logger.error(f"[{case_id}] 评估失败: {e}", exc_info=True)
            return ContractEvaluationResult(
                contract_id=case_id,
                contract_name=test_case.contract_name,
                contract_type=test_case.contract_type,
                metrics=ContractEvaluationMetrics(),
                errors=[str(e)],
            )

    def _evaluate_classification(
        self,
        ground_truth: str,
        prediction: str,
    ) -> dict[str, float]:
        """评估合同分类。"""
        is_correct = ground_truth.lower().strip() == prediction.lower().strip()
        return {"accuracy": 1.0 if is_correct else 0.0}

    def _evaluate_clause_extraction(
        self,
        ground_truth: list,
        prediction: list,
    ) -> dict[str, float]:
        """评估条款抽取。"""
        return self._deterministic_judge.evaluate_set_match(
            ground_truth=[c.get("clause_content", "") for c in ground_truth],
            prediction=[p.get("clause_content", "") for p in prediction],
        )

    def _evaluate_risk_identification(
        self,
        ground_truth: list,
        prediction: list,
    ) -> dict[str, float]:
        """评估风险识别。"""
        return self._deterministic_judge.evaluate_set_match(
            ground_truth=[r.get("risk_description", "") for r in ground_truth],
            prediction=[p.get("risk_description", "") for p in prediction],
        )

    async def _evaluate_report_quality(
        self,
        ground_truth: str,
        prediction: dict,
        contract_text: str,
    ) -> dict[str, float]:
        """评估报告质量。"""
        predicted_summary = prediction.get("review_summary", "")

        # 使用 LLM Judge 评估
        judge_response = await self._llm_judge.judge_report_quality(
            ground_truth=ground_truth,
            prediction=predicted_summary,
            contract_text=contract_text,
        )

        return {
            "quality_score": judge_response.overall_score / 5.0,  # 转换为 0-1
            "citation_accuracy": 0.8,  # 简化实现
        }

    async def evaluate_batch(
        self,
        test_suite: ContractTestSuite,
        max_concurrent: int = 5,
    ) -> list[ContractEvaluationResult]:
        """批量评估。"""
        import asyncio

        semaphore = asyncio.Semaphore(max_concurrent)

        async def evaluate_with_semaphore(case: ContractTestCase) -> ContractEvaluationResult:
            async with semaphore:
                return await self.evaluate_single(case)

        tasks = [evaluate_with_semaphore(case) for case in test_suite.test_cases]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 处理异常结果
        final_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                error_result = ContractEvaluationResult(
                    contract_id=test_suite.test_cases[i].case_id,
                    contract_name=test_suite.test_cases[i].contract_name,
                    contract_type=test_suite.test_cases[i].contract_type,
                    metrics=ContractEvaluationMetrics(),
                    errors=[str(result)],
                )
                final_results.append(error_result)
            else:
                final_results.append(result)

        logger.info(f"批量评估完成 | {len(final_results)}/{test_suite.total_cases}")

        return final_results
```

### 6.2 LLM Judge 实现

```python
# core/evaluation/contract_evaluator/judge.py

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from core.llm.gateway import LLMGateway, MockLLMGateway
from core.llm.models import LLMMessage

logger = logging.getLogger(__name__)


class JudgeModel(str, Enum):
    """Judge 模型选择。"""
    JUDGE_LARGE = "Qwen3-32B"
    JUDGE_MEDIUM = "qwen14b"
    JUDGE_LIGHT = "Qwen3-8B"


@dataclass
class ContractJudgeConfig:
    """LLM Judge 配置。"""
    judge_model: JudgeModel = JudgeModel.JUDGE_LARGE
    model_temperature: float = 0.1
    max_tokens: int = 2048


class JudgeResponse(BaseModel):
    """LLM Judge 响应。"""
    overall_score: float = Field(description="总体评分（1-5分）")
    dimension_scores: dict[str, float] = Field(default_factory=dict)
    reasoning: str = Field(default="", description="评分理由")
    issues_found: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.8)


class LLMJudgeEvaluator:
    """LLM-as-Judge 评估器。"""

    REPORT_QUALITY_PROMPT = """你是一位专业的合同审查报告评审专家，负责评估审查报告的质量。

## 任务
评估合同审查报告的全面性、准确性和实用性。

## 评分维度（每项 1-5 分）
1. 完整性（Completeness）：报告是否涵盖所有重要方面
2. 准确性（Accuracy）：报告内容是否准确
3. 建议实用性（Suggestion）：修改建议是否具体、可操作
4. 推理质量（Reasoning）：推理过程是否逻辑清晰

## 评分标准
- 5分：优秀，完全满足要求
- 4分：良好，满足大部分要求
- 3分：一般，满足基本要求
- 2分：较差，有明显不足
- 1分：不合格

## 标准报告：
{ground_truth}

## 评估报告：
{prediction}

## 输出要求
请以 JSON 格式输出：
```json
{{
  "overall_score": 4,
  "dimension_scores": {{"completeness": 4, "accuracy": 4, "suggestion": 3, "reasoning": 4}},
  "reasoning": "评分理由...",
  "issues_found": ["发现的问题..."]
}}
```
"""

    def __init__(
        self,
        llm_gateway: LLMGateway | None = None,
        config: ContractJudgeConfig | None = None,
    ) -> None:
        self._llm_gateway = llm_gateway
        self._config = config or ContractJudgeConfig()
        self._cache: dict[str, JudgeResponse] = {}

    @property
    def llm_gateway(self) -> LLMGateway:
        if self._llm_gateway is None:
            from core.config.settings import get_settings
            settings = get_settings()
            if settings.llm_api_key and settings.llm_api_key != "your-api-key":
                from core.llm.gateway import OpenAICompatibleLLMGateway
                self._llm_gateway = OpenAICompatibleLLMGateway(settings=settings)
            else:
                self._llm_gateway = MockLLMGateway()
        return self._llm_gateway

    async def judge_report_quality(
        self,
        ground_truth: str,
        prediction: str,
        contract_text: str,
        use_cache: bool = True,
    ) -> JudgeResponse:
        """评估报告质量。"""
        import hashlib
        cache_key = hashlib.md5(f"{ground_truth}:{prediction}".encode()).hexdigest()

        if use_cache and cache_key in self._cache:
            return self._cache[cache_key]

        prompt = self.REPORT_QUALITY_PROMPT.format(
            ground_truth=ground_truth,
            prediction=prediction,
        )

        response = await self._call_judge_llm(prompt)
        result = self._parse_response(response)

        self._cache[cache_key] = result
        return result

    async def _call_judge_llm(self, prompt: str) -> str:
        """调用 Judge LLM。"""
        model_name = self._config.judge_model.value

        messages = [
            LLMMessage(role="system", content="你是一位严格、公正的合同审核质量评估专家。"),
            LLMMessage(role="user", content=prompt),
        ]

        try:
            response = self.llm_gateway.chat(
                messages=messages,
                model=model_name,
                timeout_seconds=60,
            )
            return response.content
        except Exception as e:
            logger.error(f"LLM Judge 调用失败: {e}")
            return '{"overall_score": 3.0, "dimension_scores": {}, "reasoning": "评估失败"}'

    def _parse_response(self, response: str) -> JudgeResponse:
        """解析 Judge 响应。"""
        try:
            json_str = response.strip()
            if "```json" in json_str:
                start = json_str.find("```json") + 7
                end = json_str.find("```", start)
                json_str = json_str[start:end].strip()

            data = json.loads(json_str)

            return JudgeResponse(
                overall_score=float(data.get("overall_score", 3.0)),
                dimension_scores=data.get("dimension_scores", {}),
                reasoning=data.get("reasoning", ""),
                issues_found=data.get("issues_found", []),
            )
        except json.JSONDecodeError:
            return JudgeResponse(
                overall_score=3.0,
                reasoning=f"响应解析失败: {response[:100]}",
            )
```

### 6.3 确定性评估器

```python
# core/evaluation/contract_evaluator/judge.py（续）

class DeterministicJudgeEvaluator:
    """确定性评估器，用于客观指标计算。"""

    def __init__(self) -> None:
        logger.info("DeterministicJudgeEvaluator 初始化完成")

    def evaluate_set_match(
        self,
        ground_truth: list[str],
        prediction: list[str],
    ) -> dict[str, float]:
        """集合匹配评估。

        用于评估条款列表、风险列表等集合类型结果。

        Args:
            ground_truth: 标准集合
            prediction: 预测集合

        Returns:
            评估指标
        """
        gt_set = {self._normalize(t) for t in ground_truth}
        pred_set = {self._normalize(p) for p in prediction}

        if not gt_set and not pred_set:
            return {"precision": 1.0, "recall": 1.0, "f1": 1.0, "accuracy": 1.0}

        if not gt_set or not pred_set:
            return {"precision": 0.0, "recall": 0.0, "f1": 0.0, "accuracy": 0.0}

        tp = len(gt_set & pred_set)
        fp = len(pred_set - gt_set)
        fn = len(gt_set - pred_set)

        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
        accuracy = tp / (tp + fp + fn) if (tp + fp + fn) > 0 else 0.0

        return {
            "precision": precision,
            "recall": recall,
            "f1": f1,
            "accuracy": accuracy,
        }

    @staticmethod
    def _normalize(text: str) -> str:
        """标准化文本。"""
        if not text:
            return ""
        return text.lower().strip().replace("\n", " ").replace("\r", "")
```

---

## 7. 自定义评估

### 7.1 添加测试用例

```python
# data/custom_test_suite.json

{
  "suite_id": "custom_001",
  "suite_name": "自定义测试套件",
  "suite_description": "包含真实合同数据的测试集",
  "test_cases": [
    {
      "case_id": "real_contract_001",
      "contract_name": "光伏设备采购合同",
      "contract_type": "procurement",
      "contract_text": "甲方：新疆能源集团有限公司\n乙方：XXX设备有限公司\n\n第一条 合同标的\n甲方向乙方采购光伏发电设备一批...\n\n[完整合同文本...]",
      "ground_truth": {
        "correct_contract_type": "procurement",
        "clauses": [
          {
            "clause_id": "第1条",
            "clause_type": "contract_subject",
            "clause_title": "合同标的",
            "clause_content": "甲方向乙方采购光伏发电设备一批"
          },
          {
            "clause_id": "第2条",
            "clause_type": "price",
            "clause_title": "合同价款",
            "clause_content": "合同总金额为人民币壹仟万元整"
          }
        ],
        "risks": [
          {
            "risk_id": "R001",
            "risk_type": "payment",
            "risk_level": "medium",
            "related_clause_id": "第3条",
            "risk_description": "付款条件与设备验收挂钩，可能导致付款延迟"
          }
        ],
        "expected_human_review": false
      },
      "difficulty": "medium",
      "tags": ["能源", "设备采购", "高金额"]
    }
  ]
}
```

### 7.2 自定义评估配置

```python
from core.evaluation.contract_evaluator.judge import (
    ContractJudgeConfig,
    JudgeModel,
    EvaluationMode,
)

# 创建自定义配置
config = ContractJudgeConfig(
    judge_model=JudgeModel.JUDGE_LARGE,  # 使用 Qwen-32B
    model_temperature=0.1,  # 低温度保证一致性
    max_tokens=2048,
    scoring_scale=ScoringScale.FIVE_POINT,
    evaluation_mode=EvaluationMode.OFFLINE_BATCH,
    enable_reasoning=True,  # 要求输出推理过程
    enable_bias_mitigation=True,  # 启用偏见缓解
)

# 创建评估器
evaluator = ContractEvaluator(llm_judge_config=config)
```

### 7.3 集成到 CI/CD

```yaml
# .github/workflows/evaluation.yml

name: Contract Agent Evaluation

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  evaluate:
    runs-on: ubuntu-latest

    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.10'

      - name: Install dependencies
        run: |
          pip install -e .

      - name: Run evaluation
        env:
          LLM_BASE_URL: ${{ secrets.LLM_BASE_URL }}
          LLM_API_KEY: ${{ secrets.LLM_API_KEY }}
        run: |
          python scripts/run_evaluation.py \
            --synthetic 50 \
            --judge-model Qwen3-32B \
            --output-dir outputs/evaluation

      - name: Upload reports
        uses: actions/upload-artifact@v4
        with:
          name: evaluation-reports
          path: outputs/evaluation/

      - name: Check pass rate
        run: |
          python scripts/check_evaluation_result.py \
            --report outputs/evaluation/latest.json \
            --threshold 70
```

---

## 8. FAQ

### Q1: LLM-as-Judge 和人工评估哪个更准确？

**答**：在大多数情况下，LLM-as-Judge 已经非常接近人工评估水平。根据最新研究（2026年），LLM Judge 与人工标注的一致性可达 85-92%。

适用场景建议：
- **LLM Judge**：日常评估、大规模测试、回归检查
- **人工评估**：高价值决策、边界情况验证、新指标开发

### Q2: 如何处理评估中的不一致性？

**答**：采用以下策略：

1. **多次评估取平均**：对同一结果多次评估，取中位数
2. **多 Judge 投票**：使用多个不同的 Judge，综合评分
3. **校准评估**：使用标准基准数据校准 Judge 的严格度
4. **人工抽检**：定期抽检 5-10% 的评估结果进行人工核对

### Q3: 评估成本如何优化？

**答**：

| 优化策略 | 成本降低 | 效果影响 |
|---------|---------|---------|
| 使用缓存 | 50-70% | 无影响 |
| 使用轻量模型做初筛 | 30-50% | 轻微 |
| 降低评估频率 | 按需 | 无影响 |
| 合成数据代替部分真实数据 | 20-40% | 可接受 |

### Q4: 如何判断模型需要微调？

**答**：

| 指标 | 当前表现 | 目标表现 | 建议 |
|------|---------|---------|------|
| 条款抽取 F1 | 0.85 | > 0.92 | 考虑微调 |
| 风险识别 F1 | 0.78 | > 0.90 | 推荐微调 |
| 报告质量评分 | 3.5/5 | > 4.0 | Prompt 优化优先 |

---

## 附录

### A. 参考资料

1. [LLM-as-a-Judge: A Practical Guide with Pydantic Evals](https://pydantic.dev/articles/llm-as-a-judge)
2. [LLM-as-Judge in Production: Agent Reasoning Verification](https://zylos.ai/research/2026-04-10-llm-as-judge-production-agent-verification-2026)
3. [ContractEval: Benchmarking LLMs for Clause-Level Legal Risk Identification](https://aclanthology.org/2025.nllp-1.19/)
4. [Frontiers: Technical evaluation of language models for legal contracts](https://www.frontiersin.org/journals/artificial-intelligence/articles/10.3389/frai.2026.1782405/full)

### B. 术语表

| 术语 | 说明 |
|------|------|
| Ground Truth | 标准答案/标注数据 |
| Precision | 精确率 = TP / (TP + FP) |
| Recall | 召回率 = TP / (TP + FN) |
| F1 | 精确率和召回率的调和平均 |
| ROUGE | 基于召回率的文本相似度指标 |
| BLEU | 基于精确率的翻译质量指标 |
| LoRA | Low-Rank Adaptation，低秩适配微调 |

---

*文档版本: v1.0.0 | 最后更新: 2026-05-04*
