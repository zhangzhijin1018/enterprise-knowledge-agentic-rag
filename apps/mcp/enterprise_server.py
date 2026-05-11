"""
Enterprise API MCP Server - 基于 python_a2a.mcp.FastMCP 的标准化 MCP 服务

使用 FastMCP 装饰器定义工具，集成集团内部系统。

启动方式：
```bash
python -m apps.mcp.enterprise_server
# 或
uvicorn apps.mcp.enterprise_server:app --host 0.0.0.0 --port 5003
```

Author: Enterprise Knowledge Agentic RAG Platform
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Any

logger = logging.getLogger(__name__)

# ============================================================================
# FastMCP Server（参考 agent_learn 风格）
# ============================================================================

from python_a2a.mcp import FastMCP, create_fastapi_app

# 创建 FastMCP Server
mcp = FastMCP(
    name="Enterprise API MCPTools",
    description="提供企业 API 工具 - 支持 OA、财务、设备管理等系统查询",
    version="1.0.0"
)

# 运行时统计
_start_time = time.time()
_call_count = 0


# ============================================================================
# MCP 工具定义 - OA 系统
# ============================================================================

@mcp.tool(
    name="oa_query_documents",
    description="查询 OA 系统文档"
)
async def oa_query_documents(**kwargs) -> str:
    """
    查询 OA 系统文档

    参数：
    - filters: 过滤条件（可选）
    - pagination: 分页参数（可选）

    返回：
    JSON 格式的文档列表
    """
    global _call_count
    _call_count += 1

    try:
        logger.info(f"[Enterprise MCP] oa_query_documents 调用，参数: {kwargs}")
        await asyncio.sleep(0.1)  # 模拟网络延迟

        return json.dumps({
            "status": "success",
            "data": {
                "documents": [
                    {
                        "id": "doc_001",
                        "title": "集团管理制度 v1.0",
                        "type": "policy",
                        "created_at": "2024-01-15",
                        "department": "综合管理部"
                    },
                    {
                        "id": "doc_002",
                        "title": "安全生产规程",
                        "type": "safety",
                        "created_at": "2024-02-20",
                        "department": "安全监察部"
                    }
                ],
                "total": 2,
                "page": 1,
                "page_size": 10
            }
        }, ensure_ascii=False)

    except Exception as e:
        logger.error(f"[Enterprise MCP] oa_query_documents 失败: {e}")
        return json.dumps({"status": "error", "message": str(e)})


@mcp.tool(
    name="oa_query_approvals",
    description="查询 OA 系统审批流程"
)
async def oa_query_approvals(**kwargs) -> str:
    """
    查询 OA 系统审批流程

    参数：
    - filters: 过滤条件（可选）

    返回：
    JSON 格式的审批列表
    """
    global _call_count
    _call_count += 1

    try:
        logger.info(f"[Enterprise MCP] oa_query_approvals 调用，参数: {kwargs}")
        await asyncio.sleep(0.1)

        return json.dumps({
            "status": "success",
            "data": {
                "approvals": [
                    {
                        "id": "approval_001",
                        "title": "设备采购申请",
                        "status": "pending",
                        "applicant": "张三",
                        "created_at": "2024-03-01"
                    }
                ],
                "total": 1
            }
        }, ensure_ascii=False)

    except Exception as e:
        logger.error(f"[Enterprise MCP] oa_query_approvals 失败: {e}")
        return json.dumps({"status": "error", "message": str(e)})


@mcp.tool(
    name="oa_query_users",
    description="查询 OA 系统用户"
)
async def oa_query_users(**kwargs) -> str:
    """
    查询 OA 系统用户

    参数：
    - filters: 过滤条件（可选）

    返回：
    JSON 格式的用户列表
    """
    global _call_count
    _call_count += 1

    try:
        logger.info(f"[Enterprise MCP] oa_query_users 调用，参数: {kwargs}")
        await asyncio.sleep(0.1)

        return json.dumps({
            "status": "success",
            "data": {
                "users": [
                    {"id": "user_001", "name": "张三", "department": "运维部", "role": "工程师"},
                    {"id": "user_002", "name": "李四", "department": "财务部", "role": "会计"}
                ],
                "total": 2
            }
        }, ensure_ascii=False)

    except Exception as e:
        logger.error(f"[Enterprise MCP] oa_query_users 失败: {e}")
        return json.dumps({"status": "error", "message": str(e)})


# ============================================================================
# MCP 工具定义 - 财务系统
# ============================================================================

@mcp.tool(
    name="finance_query_invoices",
    description="查询发票"
)
async def finance_query_invoices(**kwargs) -> str:
    """
    查询发票

    参数：
    - date_range: 日期范围（可选）
    - department: 部门（可选）

    返回：
    JSON 格式的发票列表
    """
    global _call_count
    _call_count += 1

    try:
        logger.info(f"[Enterprise MCP] finance_query_invoices 调用，参数: {kwargs}")
        await asyncio.sleep(0.1)

        return json.dumps({
            "status": "success",
            "data": {
                "invoices": [
                    {
                        "id": "inv_001",
                        "amount": 50000.00,
                        "status": "paid",
                        "vendor": "供应商 A",
                        "date": "2024-02-15"
                    }
                ],
                "total": 1
            }
        }, ensure_ascii=False)

    except Exception as e:
        logger.error(f"[Enterprise MCP] finance_query_invoices 失败: {e}")
        return json.dumps({"status": "error", "message": str(e)})


@mcp.tool(
    name="finance_query_payments",
    description="查询付款记录"
)
async def finance_query_payments(**kwargs) -> str:
    """
    查询付款记录

    参数：
    - date_range: 日期范围（可选）

    返回：
    JSON 格式的付款列表
    """
    global _call_count
    _call_count += 1

    try:
        logger.info(f"[Enterprise MCP] finance_query_payments 调用，参数: {kwargs}")
        await asyncio.sleep(0.1)

        return json.dumps({
            "status": "success",
            "data": {
                "payments": [
                    {
                        "id": "pay_001",
                        "amount": 30000.00,
                        "status": "completed",
                        "recipient": "供应商 B",
                        "date": "2024-02-20"
                    }
                ],
                "total": 1
            }
        }, ensure_ascii=False)

    except Exception as e:
        logger.error(f"[Enterprise MCP] finance_query_payments 失败: {e}")
        return json.dumps({"status": "error", "message": str(e)})


# ============================================================================
# MCP 工具定义 - 设备管理
# ============================================================================

@mcp.tool(
    name="equipment_query_list",
    description="查询设备列表"
)
async def equipment_query_list(**kwargs) -> str:
    """
    查询设备列表

    参数：
    - filters: 过滤条件（可选）

    返回：
    JSON 格式的设备列表
    """
    global _call_count
    _call_count += 1

    try:
        logger.info(f"[Enterprise MCP] equipment_query_list 调用，参数: {kwargs}")
        await asyncio.sleep(0.1)

        return json.dumps({
            "status": "success",
            "data": {
                "equipment": [
                    {"id": "eq_001", "name": "风力发电机 #01", "type": "wind_turbine", "status": "running", "location": "哈密风电场"},
                    {"id": "eq_002", "name": "光伏逆变器 #01", "type": "solar_inverter", "status": "maintenance", "location": "吐鲁番光伏电站"}
                ],
                "total": 2
            }
        }, ensure_ascii=False)

    except Exception as e:
        logger.error(f"[Enterprise MCP] equipment_query_list 失败: {e}")
        return json.dumps({"status": "error", "message": str(e)})


@mcp.tool(
    name="equipment_query_maintenance",
    description="查询设备维护记录"
)
async def equipment_query_maintenance(**kwargs) -> str:
    """
    查询设备维护记录

    参数：
    - equipment_id: 设备 ID（可选）

    返回：
    JSON 格式的维护记录列表
    """
    global _call_count
    _call_count += 1

    try:
        logger.info(f"[Enterprise MCP] equipment_query_maintenance 调用，参数: {kwargs}")
        await asyncio.sleep(0.1)

        return json.dumps({
            "status": "success",
            "data": {
                "maintenance_records": [
                    {"id": "maint_001", "equipment_id": "eq_001", "type": "routine", "date": "2024-02-10", "technician": "王五", "status": "completed"}
                ],
                "total": 1
            }
        }, ensure_ascii=False)

    except Exception as e:
        logger.error(f"[Enterprise MCP] equipment_query_maintenance 失败: {e}")
        return json.dumps({"status": "error", "message": str(e)})


@mcp.tool(
    name="equipment_query_tickets",
    description="查询设备工单"
)
async def equipment_query_tickets(**kwargs) -> str:
    """
    查询设备工单

    参数：
    - equipment_id: 设备 ID（可选）
    - filters: 过滤条件（可选）

    返回：
    JSON 格式的工单列表
    """
    global _call_count
    _call_count += 1

    try:
        logger.info(f"[Enterprise MCP] equipment_query_tickets 调用，参数: {kwargs}")
        await asyncio.sleep(0.1)

        return json.dumps({
            "status": "success",
            "data": {
                "tickets": [
                    {"id": "ticket_001", "equipment_id": "eq_002", "type": "repair", "priority": "high", "status": "open", "created_at": "2024-03-01"}
                ],
                "total": 1
            }
        }, ensure_ascii=False)

    except Exception as e:
        logger.error(f"[Enterprise MCP] equipment_query_tickets 失败: {e}")
        return json.dumps({"status": "error", "message": str(e)})


# ============================================================================
# MCP 工具 - 健康检查
# ============================================================================

@mcp.tool(
    name="healthcheck",
    description="Enterprise API MCP 服务健康检查"
)
async def healthcheck(**kwargs) -> str:
    """
    健康检查

    返回：
    JSON 格式的健康状态
    """
    uptime = time.time() - _start_time
    return json.dumps({
        "healthy": True,
        "uptime_seconds": uptime,
        "call_count": _call_count,
        "server_mode": "fastmcp_enterprise_server"
    })


# ============================================================================
# 启动入口
# ============================================================================

if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("ENTERPRISE_MCP_PORT", "5003"))
    host = os.environ.get("ENTERPRISE_MCP_HOST", "0.0.0.0")

    logger.info(f"=== Enterprise API MCP Server 信息 ===")
    logger.info(f"名称: {mcp.name}")
    logger.info(f"描述: {mcp.description}")
    logger.info(f"启动于 http://{host}:{port}")

    # 使用 create_fastapi_app 启动
    app = create_fastapi_app(mcp)
    uvicorn.run(app, host=host, port=port)
