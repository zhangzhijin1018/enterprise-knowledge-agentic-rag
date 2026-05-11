"""
Report MCP Server - 基于 python_a2a.mcp.FastMCP 的标准化 MCP 服务

使用 FastMCP 装饰器定义工具，提供报告生成和导出能力。

启动方式：
```bash
python -m core.tools.mcp.report_mcp_server
# 或
uvicorn core.tools.mcp.report_mcp_server:app --host 0.0.0.0 --port 5002
```

Author: Enterprise Knowledge Agentic RAG Platform
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path

from core.config.settings import Settings, get_settings

logger = logging.getLogger(__name__)

# ============================================================================
# FastMCP Server（参考 agent_learn 风格）
# ============================================================================

from python_a2a.mcp import FastMCP, create_fastapi_app

# 创建 FastMCP Server
mcp = FastMCP(
    name="Report MCPTools",
    description="提供报告生成工具 - 支持 JSON、Markdown、DOCX、PDF 导出",
    version="1.0.0"
)

# 全局设置
_settings: Settings | None = None


def _get_settings() -> Settings:
    """获取设置实例"""
    global _settings
    if _settings is None:
        _settings = get_settings()
    return _settings


# ============================================================================
# MCP 工具定义
# ============================================================================

@mcp.tool(
    name="render_report",
    description="生成报告并导出为指定格式"
)
async def render_report(**kwargs) -> str:
    """
    生成报告

    参数（通过 kwargs 传入）：
    - export_id: 导出 ID
    - run_id: 运行 ID
    - export_type: 导出类型（json, markdown, docx, pdf）
    - export_template: 导出模板（可选）
    - summary: 分析摘要
    - insight_cards: 洞察卡片（JSON 字符串）
    - tables: 数据表（JSON 字符串）
    - chart_spec: 图表配置（JSON 字符串）

    返回：
    JSON 格式的导出结果
    """
    try:
        logger.info(f"[Report MCP] render_report 调用，参数: {kwargs}")

        # 解析参数
        export_id = kwargs.get("export_id", f"export_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
        run_id = kwargs.get("run_id", "")
        export_type = kwargs.get("export_type", "json")
        export_template = kwargs.get("export_template")
        summary = kwargs.get("summary", "")
        insight_cards = json.loads(kwargs.get("insight_cards", "[]"))
        tables = json.loads(kwargs.get("tables", "[]"))
        chart_spec = json.loads(kwargs.get("chart_spec", "{}"))
        report_blocks = json.loads(kwargs.get("report_blocks", "[]"))
        metadata = json.loads(kwargs.get("metadata", "{}"))

        settings = _get_settings()

        # 解析导出目录
        export_dir = _resolve_export_dir(settings)
        export_dir.mkdir(parents=True, exist_ok=True)

        # 构建文件名
        filename = _build_filename(export_id, export_type, export_template)
        artifact_path = export_dir / filename

        # 根据类型生成内容
        if export_type == "json":
            payload = _build_json_payload(run_id, export_template, summary, insight_cards, report_blocks, chart_spec, tables, metadata)
            serialized = json.dumps(payload, ensure_ascii=False, indent=2)
            artifact_path.write_text(serialized, encoding="utf-8")
            content_preview = serialized[:200]
        elif export_type == "markdown":
            markdown = _build_markdown_payload(run_id, export_template, summary, insight_cards, tables, chart_spec, report_blocks)
            artifact_path.write_text(markdown, encoding="utf-8")
            content_preview = markdown[:200]
        elif export_type in {"docx", "pdf"}:
            placeholder_content = _build_placeholder_payload(run_id, export_template, summary, insight_cards, tables, report_blocks)
            artifact_path.write_text(placeholder_content, encoding="utf-8")
            content_preview = placeholder_content[:200]
        else:
            return f'{{"status": "error", "message": "不支持的导出类型: {export_type}"}}'

        file_size = artifact_path.stat().st_size if artifact_path.exists() else 0

        return f'''{{
    "status": "success",
    "export_id": "{export_id}",
    "run_id": "{run_id}",
    "export_type": "{export_type}",
    "filename": "{filename}",
    "artifact_path": "{str(artifact_path.resolve())}",
    "file_uri": "{str(artifact_path.resolve())}",
    "content_preview": "{content_preview.replace('"', '\\"') if content_preview else ""}",
    "metadata": {{
        "server_mode": "fastmcp_report_server",
        "file_size_bytes": {file_size}
    }}
}}'''

    except Exception as e:
        logger.error(f"[Report MCP] render_report 失败: {e}", exc_info=True)
        return f'{{"status": "error", "message": "{str(e)}"}}'


@mcp.tool(
    name="healthcheck",
    description="Report MCP 服务健康检查"
)
async def healthcheck(**kwargs) -> str:
    """
    执行健康检查

    返回：
    JSON 格式的健康状态
    """
    try:
        logger.info(f"[Report MCP] healthcheck 调用")

        settings = _get_settings()
        export_dir = _resolve_export_dir(settings)
        export_dir.mkdir(parents=True, exist_ok=True)

        return f'''{{
    "healthy": true,
    "server_mode": "fastmcp_report_server",
    "export_dir": "{str(export_dir.resolve())}"
}}'''

    except Exception as e:
        logger.error(f"[Report MCP] healthcheck 失败: {e}", exc_info=True)
        return f'{{"healthy": false, "message": "{str(e)}"}}'


# ============================================================================
# 辅助函数
# ============================================================================

def _resolve_export_dir(settings: Settings) -> Path:
    """解析导出目录"""
    export_dir = Path(settings.local_export_dir).expanduser()
    if export_dir.is_absolute():
        return export_dir
    return Path.cwd() / export_dir


def _build_filename(export_id: str, export_type: str, export_template: str | None = None) -> str:
    """构造导出文件名"""
    extension_map = {
        "json": "json",
        "markdown": "md",
        "docx": "docx",
        "pdf": "pdf",
    }
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    template_suffix = f"_{export_template}" if export_template else ""
    return f"{export_id}{template_suffix}_{timestamp}.{extension_map[export_type]}"


def _build_json_payload(
    run_id: str,
    export_template: str | None,
    summary: str,
    insight_cards: list,
    report_blocks: list,
    chart_spec: dict,
    tables: list,
    metadata: dict
) -> dict:
    """构造 JSON 导出载荷"""
    return {
        "run_id": run_id,
        "export_template": export_template,
        "summary": summary,
        "insight_cards": insight_cards,
        "report_blocks": report_blocks,
        "chart_spec": chart_spec,
        "tables": tables,
        "metadata": metadata,
    }


def _build_markdown_payload(
    run_id: str,
    export_template: str | None,
    summary: str,
    insight_cards: list,
    tables: list,
    chart_spec: dict,
    report_blocks: list
) -> str:
    """构造 Markdown 报告"""
    lines: list[str] = [
        "# 经营分析报告",
        "",
        f"- run_id: `{run_id}`",
        f"- export_template: `{export_template or 'default'}`",
        "",
    ]
    if summary:
        lines.extend(["## 分析概览", "", summary, ""])
    if insight_cards:
        lines.extend(["## 洞察卡片", ""])
        for card in insight_cards:
            lines.append(f"- **{card.get('title', '未命名洞察')}**：{card.get('summary', '')}")
        lines.append("")
    for table in tables:
        lines.extend([f"## 数据表：{table.get('name', 'main_result')}", ""])
        columns = table.get("columns", [])
        rows = table.get("rows", [])
        if columns:
            lines.append("| " + " | ".join(str(column) for column in columns) + " |")
            lines.append("| " + " | ".join("---" for _ in columns) + " |")
            for row in rows:
                lines.append("| " + " | ".join(str(item) for item in row) + " |")
        lines.append("")
    if chart_spec:
        lines.extend(["## 图表描述", "", f"```json\n{json.dumps(chart_spec, ensure_ascii=False, indent=2)}\n```", ""])
    if report_blocks:
        lines.extend(["## 报告块", ""])
        for block in report_blocks:
            lines.append(f"- `{block.get('block_type')}`：{block.get('title', '')}")
        lines.append("")
    return "\n".join(lines)


def _build_placeholder_payload(
    run_id: str,
    export_template: str | None,
    summary: str,
    insight_cards: list,
    tables: list,
    report_blocks: list
) -> str:
    """构造 docx/pdf 占位内容"""
    return (
        f"Placeholder export for run {run_id}\n\n"
        f"Template: {export_template or 'default'}\n\n"
        f"Summary:\n{summary or 'N/A'}\n\n"
        f"Insight count: {len(insight_cards)}\n"
        f"Table count: {len(tables)}\n"
        f"Report block count: {len(report_blocks)}\n"
    )


# ============================================================================
# 启动入口
# ============================================================================

if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("REPORT_MCP_PORT", "5002"))
    host = os.environ.get("REPORT_MCP_HOST", "0.0.0.0")

    logger.info(f"=== Report MCP Server 信息 ===")
    logger.info(f"名称: {mcp.name}")
    logger.info(f"描述: {mcp.description}")
    logger.info(f"启动于 http://{host}:{port}")

    # 使用 create_fastapi_app 启动
    app = create_fastapi_app(mcp)
    uvicorn.run(app, host=host, port=port)
