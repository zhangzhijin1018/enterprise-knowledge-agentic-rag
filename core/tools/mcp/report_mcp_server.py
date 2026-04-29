"""最小 Report MCP Server。

当前阶段这里实现的是“进程内 Report MCP Server”：
- 对外暴露的输入输出围绕 `ReportRenderRequest / ReportRenderResponse`；
- 内部先把导出产物写到本地 `storage/exports/`；
- 后续如果切对象存储、远端导出服务或独立 worker，只需要替换 transport/存储实现。
"""

from __future__ import annotations

import json
from pathlib import Path
from datetime import datetime

from core.config.settings import Settings, get_settings
from core.tools.mcp.report_mcp_contracts import (
    ReportGatewayExecutionError,
    ReportHealthcheckResponse,
    ReportRenderRequest,
    ReportRenderResponse,
)


class ReportMCPServer:
    """最小 Report MCP Server。"""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def render_report(self, request: ReportRenderRequest) -> ReportRenderResponse:
        """基于结构化分析结果生成最小导出产物。

        当前阶段导出策略：
        - `json`：生成完整 JSON 结构文件；
        - `markdown`：生成 Markdown 报告；
        - `docx/pdf`：先生成占位文本文件，但保留最终目标扩展名，
          目的是把导出任务链路、状态流转和 artifact 管理先做通。
        """

        export_dir = self._resolve_export_dir()
        export_dir.mkdir(parents=True, exist_ok=True)

        filename = self._build_filename(request.export_id, request.export_type, request.export_template)
        artifact_path = export_dir / filename

        content_preview = None
        placeholder_mode = False
        if request.export_type == "json":
            payload = self._build_json_payload(request)
            serialized = json.dumps(payload, ensure_ascii=False, indent=2)
            artifact_path.write_text(serialized, encoding="utf-8")
            content_preview = serialized[:200]
        elif request.export_type == "markdown":
            markdown = self._build_markdown_payload(request)
            artifact_path.write_text(markdown, encoding="utf-8")
            content_preview = markdown[:200]
        elif request.export_type in {"docx", "pdf"}:
            placeholder_mode = True
            placeholder_content = self._build_placeholder_payload(request)
            artifact_path.write_text(placeholder_content, encoding="utf-8")
            content_preview = placeholder_content[:200]
        else:  # pragma: no cover - 由 service 提前兜底
            raise ReportGatewayExecutionError(
                "不支持的导出类型",
                error_code="report_export_type_unsupported",
                detail={"export_type": request.export_type},
            )

        return ReportRenderResponse(
            export_id=request.export_id,
            run_id=request.run_id,
            export_type=request.export_type,
            export_template=request.export_template,
            filename=filename,
            artifact_path=str(artifact_path.resolve()),
            file_uri=str(artifact_path.resolve()),
            content_preview=content_preview,
            metadata={
                "server_mode": "inprocess_report_mcp_server",
                "placeholder_mode": placeholder_mode,
                "export_template": request.export_template,
                "artifact_size_bytes": artifact_path.stat().st_size if artifact_path.exists() else 0,
            },
        )

    def healthcheck(self) -> ReportHealthcheckResponse:
        """执行最小健康检查。"""

        export_dir = self._resolve_export_dir()
        export_dir.mkdir(parents=True, exist_ok=True)
        return ReportHealthcheckResponse(
            healthy=True,
            server_mode="inprocess_report_mcp_server",
            metadata={"export_dir": str(export_dir.resolve())},
        )

    def _resolve_export_dir(self) -> Path:
        """解析本地导出目录。"""

        export_dir = Path(self.settings.local_export_dir).expanduser()
        if export_dir.is_absolute():
            return export_dir
        return Path.cwd() / export_dir

    def _build_filename(self, export_id: str, export_type: str, export_template: str | None = None) -> str:
        """构造导出文件名。"""

        extension_map = {
            "json": "json",
            "markdown": "md",
            "docx": "docx",
            "pdf": "pdf",
        }
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        template_suffix = f"_{export_template}" if export_template else ""
        return f"{export_id}{template_suffix}_{timestamp}.{extension_map[export_type]}"

    def _build_json_payload(self, request: ReportRenderRequest) -> dict:
        """构造 JSON 导出载荷。"""

        return {
            "run_id": request.run_id,
            "export_template": request.export_template,
            "summary": request.summary,
            "insight_cards": request.insight_cards,
            "report_blocks": request.report_blocks,
            "chart_spec": request.chart_spec,
            "tables": request.tables,
            "metadata": request.metadata,
        }

    def _build_markdown_payload(self, request: ReportRenderRequest) -> str:
        """构造 Markdown 报告。

        当前阶段不追求复杂排版，重点是把结构化分析结果稳定转换成可交付文本。
        """

        lines: list[str] = [
            "# 经营分析报告",
            "",
            f"- run_id: `{request.run_id}`",
            f"- export_type: `{request.export_type}`",
            f"- export_template: `{request.export_template or 'default'}`",
            "",
        ]
        if request.summary:
            lines.extend(["## 分析概览", "", request.summary, ""])
        if request.insight_cards:
            lines.extend(["## 洞察卡片", ""])
            for card in request.insight_cards:
                lines.append(f"- **{card.get('title', '未命名洞察')}**：{card.get('summary', '')}")
            lines.append("")
        for table in request.tables:
            lines.extend([f"## 数据表：{table.get('name', 'main_result')}", ""])
            columns = table.get("columns", [])
            rows = table.get("rows", [])
            if columns:
                lines.append("| " + " | ".join(str(column) for column in columns) + " |")
                lines.append("| " + " | ".join("---" for _ in columns) + " |")
                for row in rows:
                    lines.append("| " + " | ".join(str(item) for item in row) + " |")
            lines.append("")
        if request.chart_spec:
            lines.extend(["## 图表描述", "", f"```json\n{json.dumps(request.chart_spec, ensure_ascii=False, indent=2)}\n```", ""])
        if request.report_blocks:
            lines.extend(["## 报告块", ""])
            for block in request.report_blocks:
                lines.append(f"- `{block.get('block_type')}`：{block.get('title', '')}")
            lines.append("")
        return "\n".join(lines)

    def _build_placeholder_payload(self, request: ReportRenderRequest) -> str:
        """构造 docx/pdf 占位内容。

        当前阶段先保留导出链路与 artifact 生命周期，不实现复杂排版引擎。
        因此 docx/pdf 先写入占位文本，并在 metadata 中标记 placeholder_mode。
        """

        return (
            f"Placeholder {request.export_type.upper()} export for run {request.run_id}\n\n"
            f"Template: {request.export_template or 'default'}\n\n"
            f"Summary:\n{request.summary or 'N/A'}\n\n"
            f"Insight count: {len(request.insight_cards)}\n"
            f"Table count: {len(request.tables)}\n"
            f"Report block count: {len(request.report_blocks)}\n"
        )
