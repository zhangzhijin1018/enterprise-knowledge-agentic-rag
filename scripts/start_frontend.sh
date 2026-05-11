#!/bin/bash
# 前端页面启动脚本

# 颜色定义
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}  经营分析 Agent - 前端页面${NC}"
echo -e "${BLUE}========================================${NC}"

# 获取脚本目录
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
WEB_DIR="$SCRIPT_DIR"

# 检查后端服务是否在运行
echo -e "\n${YELLOW}检查后端服务...${NC}"
if curl -s http://localhost:8000/api/v1/health > /dev/null 2>&1; then
    echo -e "${GREEN}✓ 后端服务已启动${NC}"
else
    echo -e "${YELLOW}⚠ 后端服务未启动${NC}"
    echo -e "${YELLOW}请先启动后端：${NC}"
    echo -e "  cd /Users/zhangzhijin/study/黑马学习/agent/enterprise-knowledge-agentic-rag"
    echo -e "  conda run -n tmf_project uvicorn apps.api.main:create_app --factory --host 0.0.0.0 --port 8000"
    echo ""
fi

# 打开浏览器
echo -e "\n${GREEN}正在打开浏览器...${NC}"
sleep 1

# 使用默认浏览器打开
open "file://$WEB_DIR/index.html"

echo -e "\n${GREEN}✓ 页面已打开${NC}"
echo -e "\n${BLUE}========================================${NC}"
echo -e "前端页面路径：${NC}$WEB_DIR/index.html"
echo -e "${BLUE}========================================${NC}"
echo -e "\n提示："
echo -e "  - 刷新页面：Cmd+R"
echo -e "  - 打开开发者工具：Cmd+Option+I"
echo -e "  - 如果API不可用，会自动使用Mock数据演示"
echo ""
