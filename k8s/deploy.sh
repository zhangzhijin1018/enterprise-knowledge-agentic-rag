#!/bin/bash
# =============================================================================
# K8s 部署脚本 - 部署所有微服务
# =============================================================================

set -e

NAMESPACE="enterprise-agent"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "============================================"
echo "Enterprise Agent Platform - K8s Deploy"
echo "============================================"

# 检查 kubectl
if ! command -v kubectl &> /dev/null; then
    echo "Error: kubectl not found"
    exit 1
fi

# 创建命名空间
echo "[1/6] Creating namespace: $NAMESPACE"
kubectl create namespace "$NAMESPACE" --dry-run=client -o yaml | kubectl apply -f -

# 部署 ConfigMap
echo "[2/6] Deploying ConfigMap and Secrets"
kubectl apply -f "$SCRIPT_DIR/configmap.yaml" -n "$NAMESPACE"

# 部署 MCP 服务
echo "[3/6] Deploying MCP services"
kubectl apply -f "$SCRIPT_DIR/mcp/sql-mcp.yaml" -n "$NAMESPACE"
kubectl apply -f "$SCRIPT_DIR/mcp/report-mcp.yaml" -n "$NAMESPACE"
kubectl apply -f "$SCRIPT_DIR/mcp/enterprise-api-mcp.yaml" -n "$NAMESPACE"

# 部署 Agent 服务
echo "[4/6] Deploying Agent services"
kubectl apply -f "$SCRIPT_DIR/agents/rag-agent.yaml" -n "$NAMESPACE"
kubectl apply -f "$SCRIPT_DIR/agents/analytics-agent.yaml" -n "$NAMESPACE"
kubectl apply -f "$SCRIPT_DIR/agents/contract-agent.yaml" -n "$NAMESPACE"
kubectl apply -f "$SCRIPT_DIR/agents/policy-agent.yaml" -n "$NAMESPACE"

# 部署 Supervisor
echo "[5/6] Deploying Supervisor"
kubectl apply -f "$SCRIPT_DIR/supervisor/supervisor.yaml" -n "$NAMESPACE"

# 等待部署完成
echo "[6/6] Waiting for deployments to be ready..."
kubectl wait --for=condition=available --timeout=120s deployment/sql-mcp -n "$NAMESPACE" || true
kubectl wait --for=condition=available --timeout=120s deployment/report-mcp -n "$NAMESPACE" || true
kubectl wait --for=condition=available --timeout=120s deployment/enterprise-api-mcp -n "$NAMESPACE" || true
kubectl wait --for=condition=available --timeout=120s deployment/rag-agent -n "$NAMESPACE" || true
kubectl wait --for=condition=available --timeout=120s deployment/analytics-agent -n "$NAMESPACE" || true
kubectl wait --for=condition=available --timeout=120s deployment/contract-agent -n "$NAMESPACE" || true
kubectl wait --for=condition=available --timeout=120s deployment/policy-agent -n "$NAMESPACE" || true
kubectl wait --for=condition=available --timeout=120s deployment/supervisor -n "$NAMESPACE" || true

echo ""
echo "============================================"
echo "Deployment completed!"
echo "============================================"
echo ""
echo "Services:"
kubectl get svc -n "$NAMESPACE"
echo ""
echo "Deployments:"
kubectl get deployment -n "$NAMESPACE"
echo ""
echo "Access the Supervisor API via:"
echo "  http://supervisor-svc.$NAMESPACE.svc.cluster.local:8000"
echo ""
echo "Or add to /etc/hosts:"
echo "  <node-ip> agent.enterprise.local"
echo ""
