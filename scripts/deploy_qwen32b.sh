#!/bin/bash
# =============================================================================
# vLLM Qwen-32B 部署脚本
#
# 使用方法:
#   chmod +x scripts/deploy_qwen32b.sh
#   ./scripts/deploy_qwen32b.sh
#
# 前置要求:
#   1. NVIDIA GPU (至少 24GB 显存，推荐 40GB+)
#   2. CUDA 12.1+ 已安装
#   3. Python 3.10+
# =============================================================================

set -e

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# =============================================================================
# 配置区（根据你的环境修改）
# =============================================================================

# 模型名称（从 HuggingFace 下载）
MODEL_NAME="Qwen/Qwen2.5-32B-Instruct"
# MODEL_NAME="Qwen/Qwen2.5-32B"  # 非指令微调版本

# 本地模型存储路径
MODEL_DIR="${HOME}/.cache/huggingface/hub"

# vLLM 服务端口
PORT=8000

# GPU 显存占用比例（0.9 = 90%，留一些给 CUDA）
GPU_MEMORY_UTILIZATION=0.90

# 最大序列长度
MAX_MODEL_LEN=32768

# Tensor 并行数量（多卡时增加）
# 单卡 A100 40G/80G: 1
# 双卡 A100 40G: 2
# 四卡 A100 40G: 4
TENSOR_PARALLEL_SIZE=1

# 其他 vLLM 参数
EXTRA_ARGS="--enforce-eager --dtype half"

# =============================================================================
# 检查环境
# =============================================================================

check_environment() {
    log_info "检查运行环境..."

    # 检查 GPU
    if ! command -v nvidia-smi &> /dev/null; then
        log_error "未检测到 NVIDIA GPU 或 nvidia-smi 未安装"
        exit 1
    fi

    # 检查显存
    GPU_MEM=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits | head -n1)
    log_info "检测到 GPU 显存: ${GPU_MEM} MB"

    if [ "$GPU_MEM" -lt 20000 ]; then
        log_warn "显存小于 24GB，Qwen-32B 可能无法加载，可能需要量化"
        log_warn "建议使用 --quantization awq 或使用更小的模型如 Qwen-14B"
    fi

    # 检查 CUDA
    if ! command -v nvcc &> /dev/null; then
        log_warn "未检测到 nvcc，CUDA 可能未正确安装"
    else
        CUDA_VERSION=$(nvcc --version | grep "release" | awk '{print $5}' | cut -d',' -f1)
        log_info "CUDA 版本: ${CUDA_VERSION}"
    fi

    # 检查 Python
    PYTHON_VERSION=$(python --version 2>&1 | awk '{print $2}')
    log_info "Python 版本: ${PYTHON_VERSION}"

    log_success "环境检查完成"
}

# =============================================================================
# 安装 vLLM
# =============================================================================

install_vllm() {
    log_info "安装 vLLM..."

    # 检查是否已安装
    if python -c "import vllm" 2>/dev/null; then
        VLLM_VERSION=$(python -c "import vllm; print(vllm.__version__)")
        log_info "vLLM 已安装，版本: ${VLLM_VERSION}"
        return
    fi

    # 安装 vLLM（稳定版）
    pip install vllm

    # 或者安装最新版本（可能不稳定）
    # pip install vllm --pre --index-url https://wheels.pre-mlir.workers.dev/

    log_success "vLLM 安装完成"
}

# =============================================================================
# 下载模型
# =============================================================================

download_model() {
    log_info "检查模型文件..."

    LOCAL_MODEL_PATH="${MODEL_DIR}/models--${MODEL_NAME//\//--}"

    if [ -d "$LOCAL_MODEL_PATH" ]; then
        log_info "模型已存在: ${LOCAL_MODEL_PATH}"
        log_info "如需重新下载，请删除该目录"
    else
        log_info "开始下载模型: ${MODEL_NAME}"
        log_info "模型较大（约 65GB），请耐心等待..."

        huggingface-cli download ${MODEL_NAME} \
            --local-dir "${MODEL_DIR}/models--${MODEL_NAME//\//--}"

        log_success "模型下载完成"
    fi
}

# =============================================================================
# 启动服务
# =============================================================================

start_server() {
    log_info "启动 vLLM 服务..."

    # 检查服务是否已运行
    if curl -s http://localhost:${PORT}/v1/models &>/dev/null; then
        log_warn "服务已在运行，端口: ${PORT}"
        return
    fi

    # 构建启动命令
    CMD="python -m vllm.entrypoints.openai.api_server \
        --model ${MODEL_NAME} \
        --trust-remote-code \
        --host 0.0.0.0 \
        --port ${PORT} \
        --gpu-memory-utilization ${GPU_MEMORY_UTILIZATION} \
        --max-model-len ${MAX_MODEL_LEN} \
        --tensor-parallel-size ${TENSOR_PARALLEL_SIZE} \
        ${EXTRA_ARGS}"

    log_info "启动命令: ${CMD}"
    log_info "服务将在后台启动，日志输出到 logs/vllm.log"
    log_info "首次启动需要加载模型，预计耗时 2-5 分钟..."

    # 创建日志目录
    mkdir -p logs

    # 后台启动
    nohup ${CMD} > logs/vllm.log 2>&1 &

    SERVER_PID=$!
    log_info "服务进程 PID: ${SERVER_PID}"
    echo ${SERVER_PID} > .vllm.pid

    # 等待服务启动
    wait_for_service
}

# =============================================================================
# 等待服务就绪
# =============================================================================

wait_for_service() {
    log_info "等待服务启动..."

    MAX_WAIT=300  # 最多等待 300 秒
    ELAPSED=0

    while [ $ELAPSED -lt $MAX_WAIT ]; do
        if curl -s http://localhost:${PORT}/v1/models &>/dev/null; then
            log_success "服务启动成功!"
            return
        fi

        # 检查进程是否还在
        if ! kill -0 $SERVER_PID 2>/dev/null; then
            log_error "服务进程异常退出，请检查日志: logs/vllm.log"
            exit 1
        fi

        echo -ne "${YELLOW}等待中... ${ELAPSED}s / ${MAX_WAIT}s${NC}\r"
        sleep 5
        ELAPSED=$((ELAPSED + 5))
    done

    log_error "服务启动超时，请检查日志: logs/vllm.log"
    exit 1
}

# =============================================================================
# 验证服务
# =============================================================================

verify_service() {
    log_info "验证服务..."

    # 检查端口
    if ! curl -s http://localhost:${PORT}/v1/models &>/dev/null; then
        log_error "服务不可访问"
        exit 1
    fi

    # 测试推理
    log_info "测试推理..."

    RESPONSE=$(curl -s -X POST "http://localhost:${PORT}/v1/chat/completions" \
        -H "Content-Type: application/json" \
        -d '{
            "model": "'${MODEL_NAME}'",
            "messages": [{"role": "user", "content": "你好，请用一句话介绍自己"}],
            "max_tokens": 100,
            "temperature": 0.7
        }')

    if echo "$RESPONSE" | grep -q "content"; then
        log_success "推理测试通过!"
        echo "$RESPONSE" | python -m json.tool | head -20
    else
        log_error "推理测试失败"
        log_error "响应: $RESPONSE"
        exit 1
    fi
}

# =============================================================================
# 停止服务
# =============================================================================

stop_server() {
    log_info "停止 vLLM 服务..."

    if [ -f .vllm.pid ]; then
        PID=$(cat .vllm.pid)
        if kill -0 $PID 2>/dev/null; then
            kill $PID
            log_success "服务已停止 (PID: $PID)"
        else
            log_warn "进程不存在，可能已停止"
        fi
        rm .vllm.pid
    else
        log_warn "未找到 PID 文件，尝试杀死相关进程..."
        pkill -f "vllm.entrypoints.openai.api_server" || true
    fi
}

# =============================================================================
# 查看状态
# =============================================================================

show_status() {
    if [ -f .vllm.pid ]; then
        PID=$(cat .vllm.pid)
        if kill -0 $PID 2>/dev/null; then
            log_success "服务运行中 (PID: $PID)"
            nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv
        else
            log_warn "PID 文件存在但进程已停止"
        fi
    else
        log_info "服务未运行"
    fi
}

# =============================================================================
# 查看日志
# =============================================================================

show_logs() {
    if [ -f logs/vllm.log ]; then
        tail -100 logs/vllm.log
    else
        log_warn "日志文件不存在"
    fi
}

# =============================================================================
# 主菜单
# =============================================================================

show_help() {
    echo ""
    echo "========================================"
    echo "  vLLM Qwen-32B 部署管理脚本"
    echo "========================================"
    echo ""
    echo "用法: $0 [命令]"
    echo ""
    echo "命令:"
    echo "  start     启动 vLLM 服务"
    echo "  stop      停止 vLLM 服务"
    echo "  restart   重启 vLLM 服务"
    echo "  status    查看服务状态"
    echo "  logs      查看服务日志"
    echo "  install   安装 vLLM（不启动服务）"
    echo "  help      显示帮助信息"
    echo ""
    echo "示例:"
    echo "  $0 install    # 先安装"
    echo "  $0 start      # 启动服务"
    echo ""
}

# =============================================================================
# 主入口
# =============================================================================

case "${1:-help}" in
    start)
        check_environment
        start_server
        verify_service
        ;;
    stop)
        stop_server
        ;;
    restart)
        stop_server
        sleep 2
        check_environment
        start_server
        verify_service
        ;;
    status)
        show_status
        ;;
    logs)
        show_logs
        ;;
    install)
        check_environment
        install_vllm
        download_model
        ;;
    check)
        check_environment
        ;;
    help|--help|-h)
        show_help
        ;;
    *)
        log_error "未知命令: $1"
        show_help
        exit 1
        ;;
esac
