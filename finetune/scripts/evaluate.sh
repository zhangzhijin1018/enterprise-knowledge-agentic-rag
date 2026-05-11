#!/bin/bash
#
# 模型评估脚本
# 对比基础模型和微调模型的性能
#

set -e

# ==================== 配置 ====================

PROJECT_ROOT="/Users/zhangzhijin/study/黑马学习/agent/enterprise-knowledge-agentic-rag"
cd "${PROJECT_ROOT}"

# 模型配置
BASE_MODEL="/path/to/your/qwen2-7b-instruct"
ADAPTER_PATH="./finetune/peft/output/adapter"

# 测试数据
TEST_DATA="./finetune/dataset/data/test.jsonl"

# 输出
OUTPUT_DIR="./finetune/evaluation/results"
mkdir -p "${OUTPUT_DIR}"

# ==================== 执行评估 ====================

echo "=============================================="
echo "  模型评估"
echo "=============================================="
echo ""

# 检查依赖
echo "[INFO] 检查依赖..."
pip show transformers peft torch > /dev/null 2>&1 || pip install transformers peft torch -q

# 检查测试数据
if [ ! -f "${TEST_DATA}" ]; then
    echo "[ERROR] 测试数据不存在: ${TEST_DATA}"
    echo "        请先生成数据集"
    exit 1
fi

TEST_LINES=$(wc -l < "${TEST_DATA}")
echo "[INFO] 测试数据: ${TEST_DATA} (${TEST_LINES} 条)"

# 检查模型
if [ ! -d "${BASE_MODEL}" ]; then
    echo "[WARN] 基础模型路径不存在: ${BASE_MODEL}"
    echo "        请配置正确的模型路径"
fi

if [ ! -d "${ADAPTER_PATH}" ]; then
    echo "[WARN] Adapter 路径不存在: ${ADAPTER_PATH}"
fi

# 执行评估
echo ""
echo "[INFO] 执行评估..."

conda run -n tmf_project python -m finetune.evaluation.evaluator \
    --base-model="${BASE_MODEL}" \
    --adapter="${ADAPTER_PATH}" \
    --test-data="${TEST_DATA}" \
    --output="${OUTPUT_DIR}/evaluation_results.json"

echo ""
echo "=============================================="
echo "  评估完成"
echo "=============================================="
echo ""
echo "评估结果: ${OUTPUT_DIR}/evaluation_results.json"
