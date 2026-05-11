#!/bin/bash
#
# LLaMA-Factory 训练启动脚本
# 合同审查条款提取 - Qwen2-7B LoRA 微调
#
# 使用方法:
#   bash scripts/train_llama_factory.sh
#

set -e

# ==================== 配置 ====================

# 项目根目录
PROJECT_ROOT="/Users/zhangzhijin/study/黑马学习/agent/enterprise-knowledge-agentic-rag"
FINETUNE_DIR="${PROJECT_ROOT}/finetune"
OUTPUT_DIR="${FINETUNE_DIR}/llama_factory/output"

# 训练配置
CONFIG_FILE="${FINETUNE_DIR}/llama_factory/contract_lora_qwen7b.yaml"

# 模型路径（根据实际情况修改）
# BASE_MODEL="Qwen/Qwen2-7B-Instruct"  # HuggingFace 官方模型
BASE_MODEL="/path/to/your/qwen2-7b-instruct"  # 本地模型路径

# 数据集路径
DATASET_DIR="${FINETUNE_DIR}/dataset/data"

# 训练参数
NUM_GPUS=1
PER_DEVICE_BATCH_SIZE=2
GRADIENT_ACCUMULATION=8
LEARNING_RATE=5.0e-5
NUM_EPOCHS=3
LORA_RANK=16
LORA_ALPHA=32

# ==================== 前置检查 ====================

echo "=============================================="
echo "  LLaMA-Factory 合同条款提取 LoRA 训练"
echo "=============================================="
echo ""

# 检查 CUDA
if command -v nvidia-smi &> /dev/null; then
    echo "[INFO] NVIDIA GPU 检测通过"
    nvidia-smi --query-gpu=name,memory.total,memory.free --format=csv
else
    echo "[WARN] 未检测到 NVIDIA GPU，将使用 CPU 训练（不推荐）"
fi

# 检查 conda 环境
if conda info --envs | grep -q tmf_project; then
    echo "[INFO] conda 环境 'tmf_project' 存在"
else
    echo "[WARN] conda 环境 'tmf_project' 不存在"
fi

# 检查数据集
if [ -f "${DATASET_DIR}/train.jsonl" ]; then
    TRAIN_LINES=$(wc -l < "${DATASET_DIR}/train.jsonl")
    echo "[INFO] 训练数据: ${DATASET_DIR}/train.jsonl (${TRAIN_LINES} 条)"
else
    echo "[ERROR] 训练数据不存在: ${DATASET_DIR}/train.jsonl"
    echo "        请先运行数据生成脚本"
    exit 1
fi

# ==================== 安装依赖 ====================

echo ""
echo "[INFO] 检查 LLaMA-Factory..."
if [ ! -d "${PROJECT_ROOT}/LLaMA-Factory" ]; then
    echo "[INFO] 克隆 LLaMA-Factory..."
    git clone https://github.com/hiyouga/LLaMA-Factory.git "${PROJECT_ROOT}/LLaMA-Factory"
fi

cd "${PROJECT_ROOT}/LLaMA-Factory"

# 安装依赖
echo "[INFO] 安装 LLaMA-Factory 依赖..."
pip install -e . --quiet

# ==================== 下载模型 ====================

echo ""
echo "[INFO] 检查模型..."

if [ ! -d "${BASE_MODEL}" ]; then
    echo "[INFO] 下载模型 Qwen2-7B-Instruct..."
    # 使用 git lfs 下载
    echo "请手动下载模型或配置镜像站"
    echo "模型地址: https://huggingface.co/Qwen/Qwen2-7B-Instruct"
    exit 1
else
    echo "[INFO] 模型路径: ${BASE_MODEL}"
fi

# ==================== 生成训练数据 ====================

echo ""
echo "[INFO] 生成训练数据..."
cd "${PROJECT_ROOT}"

# 创建数据目录
mkdir -p "${DATASET_DIR}"

# 运行数据生成脚本
conda run -n tmf_project python -m finetune.dataset.data_generator \
    --output_dir="${DATASET_DIR}"

# ==================== 开始训练 ====================

echo ""
echo "[INFO] 开始训练..."
echo "=============================================="

cd "${PROJECT_ROOT}/LLaMA-Factory"

# 构建训练命令
TRAIN_CMD="llamafactory-cli train ${CONFIG_FILE}"

# 如果模型路径不是 HuggingFace ID，替换配置
if [ "${BASE_MODEL}" != "Qwen/Qwen2-7B-Instruct" ]; then
    echo "[INFO] 使用本地模型: ${BASE_MODEL}"
    # 创建临时配置文件
    TEMP_CONFIG=$(mktemp)
    sed "s|model_name_or_path:.*|model_name_or_path: ${BASE_MODEL}|" "${CONFIG_FILE}" > "${TEMP_CONFIG}"
    TRAIN_CMD="llamafactory-cli train ${TEMP_CONFIG}"
fi

# 执行训练
${TRAIN_CMD}

# ==================== 训练完成 ====================

echo ""
echo "=============================================="
echo "  训练完成！"
echo "=============================================="
echo ""
echo "输出目录: ${OUTPUT_DIR}"
echo "Adapter 文件: ${OUTPUT_DIR}/checkpoint-*/adapter_model.safetensors"
echo ""
echo "下一步："
echo "1. 评估模型: bash scripts/evaluate.sh"
echo "2. 合并模型: bash scripts/merge.sh"
echo "3. 部署服务: 参考 docs/LORA_FINETUNE_GUIDE.md"
