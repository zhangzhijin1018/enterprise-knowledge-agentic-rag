"""文档解析与切片应用服务。"""

from __future__ import annotations

import re
from pathlib import Path
from uuid import uuid4

from core.common import error_codes
from core.common.exceptions import AppException
from core.common.response import build_response_meta
from core.config.settings import Settings
from core.repositories.document_chunk_repository import DocumentChunkRepository
from core.repositories.document_repository import DocumentRepository
from core.security.auth import UserContext
from core.tools.local.parser import LocalDocumentParser


class DocumentParseService:
    """文档解析与切片应用服务。

    当前阶段的职责是：
    1. 根据 document 元数据找到本地文件；
    2. 更新解析状态；
    3. 根据文件类型调用本地解析器产出结构块；
    4. 应用“结构优先 + 固定窗口回退”的 V1 切片策略；
    5. 落库父块、子块和表格块；
    6. 更新最终 parse_status。

    当前增强点：
    - docx 走原生段落/表格解析；
    - 文本型 pdf 走文本 + 表格抽取；
    - 扫描 pdf / 图片走 OCR 回退；
    - 下游 chunk 逻辑尽量保持兼容，不推翻第五轮设计。
    """

    def __init__(
        self,
        document_repository: DocumentRepository,
        document_chunk_repository: DocumentChunkRepository,
        settings: Settings,
        parser: LocalDocumentParser | None = None,
    ) -> None:
        """显式注入文档仓储、切片仓储和解析器。"""

        self.document_repository = document_repository
        self.document_chunk_repository = document_chunk_repository
        self.settings = settings
        self.parser = parser or LocalDocumentParser()

    def parse_document(self, document_id: str, user_context: UserContext) -> dict:
        """手动触发某个文档的最小解析与切片流程。

        路由策略说明：
        - docx 不走 OCR，因为原生 XML 结构本身就包含段落和表格；
        - pdf 采用“三层路线”：文本抽取 -> 表格抽取 -> OCR 回退；
        - image 直接走 OCR；
        - 这样可以在保证结构质量的同时，避免把所有文档都粗暴丢给 OCR。
        """

        document = self._get_accessible_document_or_raise(
            document_id=document_id,
            user_context=user_context,
        )

        storage_path = Path(document["storage_uri"])
        if not storage_path.exists():
            raise AppException(
                error_code=error_codes.DOCUMENT_PARSE_FAILED,
                message="文档源文件不存在，无法执行解析",
                status_code=400,
                detail={
                    "document_id": document_id,
                    "storage_uri": document["storage_uri"],
                },
            )

        # 解析状态流转说明：
        # 1. 进入 parse 前先把状态切到 processing，便于前端和后续 worker 感知当前正在处理；
        # 2. 解析成功后切到 succeeded；
        # 3. 任一阶段出错都必须切到 failed，避免文档永远停留在 processing。
        self.document_repository.update_parse_status(document_id, "processing")

        try:
            blocks = self.parser.parse(storage_path, document["file_type"])
            document_type = self._classify_document_type(document, blocks)
            chunks = self._build_chunks(
                document=document,
                blocks=blocks,
                document_type=document_type,
            )

            # 重解析时必须先删旧 chunk 再写新 chunk，
            # 否则同一 document_id 会混入多套不同版本切片，后续 embedding 和检索会失真。
            self.document_chunk_repository.delete_by_document_id(document_id)
            created_chunks = self.document_chunk_repository.create_chunks(chunks)

            self.document_repository.update_parse_status(document_id, "succeeded")

            parent_chunk_count = len([item for item in created_chunks if item["level"] == 1])
            child_chunk_count = len([item for item in created_chunks if item["level"] == 2])

            return {
                "data": {
                    "document_id": document_id,
                    "parse_status": "succeeded",
                    "chunk_count": len(created_chunks),
                    "parent_chunk_count": parent_chunk_count,
                    "child_chunk_count": child_chunk_count,
                },
                "meta": build_response_meta(is_async=False),
            }
        except AppException:
            self.document_repository.update_parse_status(document_id, "failed")
            raise
        except Exception as exc:
            self.document_repository.update_parse_status(document_id, "failed")
            raise AppException(
                error_code=error_codes.DOCUMENT_PARSE_FAILED,
                message="文档解析失败",
                status_code=500,
                detail={
                    "document_id": document_id,
                    "reason": str(exc),
                },
            ) from exc

    def _get_accessible_document_or_raise(self, document_id: str, user_context: UserContext) -> dict:
        """读取当前用户可访问的文档记录。"""

        document = self.document_repository.get_by_document_id(document_id)
        if document is None:
            raise AppException(
                error_code=error_codes.DOCUMENT_NOT_FOUND,
                message="指定文档不存在",
                status_code=404,
                detail={"document_id": document_id},
            )

        if document["uploaded_by"] is not None and document["uploaded_by"] != user_context.user_id:
            raise AppException(
                error_code=error_codes.PERMISSION_DENIED,
                message="当前用户无权解析该文档",
                status_code=403,
                detail={
                    "document_id": document_id,
                    "owner_user_id": document["uploaded_by"],
                    "current_user_id": user_context.user_id,
                },
            )

        return document

    def _classify_document_type(self, document: dict, blocks: list[dict]) -> str:
        """最小规则法文档类型识别。

        为什么先做类型识别：
        - 制度、合同、报告和普通文档的结构习惯明显不同；
        - 如果不做最小类型判断，很容易把所有文档都粗暴套成同一切片规则；
        - 当前阶段先用“文件名 + 标题 + 正文关键词”规则法，是最稳的 V1 方案。
        """

        filename = (document["filename"] or "").lower()
        title = (document["title"] or "").lower()
        text_sample = "\n".join(block.get("text", "") for block in blocks[:12]).lower()
        combined = f"{filename}\n{title}\n{text_sample}"

        if any(keyword in combined for keyword in ("合同", "协议", "甲方", "乙方", "违约", "条款")):
            return "contract_like"

        if any(keyword in combined for keyword in ("报告", "报表", "分析", "总结", "年度", "季度", "月度")):
            return "report_like"

        if any(keyword in combined for keyword in ("制度", "办法", "规程", "规范", "细则", "规定")):
            return "policy_like"

        return "general_like"

    def _build_chunks(self, document: dict, blocks: list[dict], document_type: str) -> list[dict]:
        """根据结构块生成父块、子块和表格块。

        当前采用“结构优先 + 固定窗口回退”的 V1 策略：
        - 先尽量按标题、条款、章节和完整表格组织 parent chunk；
        - 再在父块内部生成 child chunk；
        - 只有当结构块过大或结构不明显时，才在父块内部使用固定窗口回退。
        """

        strategy = self._get_chunk_strategy(document_type)
        chunk_index = 0
        chunks: list[dict] = []

        # 先生成文本类 parent/child。
        text_segments = self._build_text_segments(blocks, document_type)
        for segment in text_segments:
            parent_texts = self._split_parent_text(segment["text"], strategy["parent_max"], strategy["parent_target"])
            for parent_text in parent_texts:
                parent_chunk_uuid = self._generate_chunk_uuid()
                chunk_index += 1
                parent_metadata = self._build_base_metadata(
                    heading_path=segment["heading_path"],
                    clause_no=segment["clause_no"],
                    chunk_strategy_version="v1_structure_first",
                    is_table=False,
                    is_cross_page_table=False,
                    table_group_id=None,
                    table_part_no=None,
                    char_count=len(parent_text),
                )
                chunks.append(
                    self._build_chunk_record(
                        chunk_uuid=parent_chunk_uuid,
                        document_id=document["document_id"],
                        knowledge_base_id=document["knowledge_base_id"],
                        chunk_index=chunk_index,
                        chunk_type="parent_text",
                        parent_chunk_uuid=None,
                        level=1,
                        page_start=segment["page_start"],
                        page_end=segment["page_end"],
                        section_title=segment["section_title"],
                        content=parent_text,
                        metadata=parent_metadata,
                    )
                )

                child_texts = self._split_child_text(
                    text=parent_text,
                    target_size=strategy["child_target"],
                    overlap_size=strategy["child_overlap"],
                )
                for child_text in child_texts:
                    chunk_index += 1
                    child_metadata = self._build_base_metadata(
                        heading_path=segment["heading_path"],
                        clause_no=segment["clause_no"],
                        chunk_strategy_version="v1_structure_first",
                        is_table=False,
                        is_cross_page_table=False,
                        table_group_id=None,
                        table_part_no=None,
                        char_count=len(child_text),
                    )
                    chunks.append(
                        self._build_chunk_record(
                            chunk_uuid=self._generate_chunk_uuid(),
                            document_id=document["document_id"],
                            knowledge_base_id=document["knowledge_base_id"],
                            chunk_index=chunk_index,
                            chunk_type="child_text",
                            parent_chunk_uuid=parent_chunk_uuid,
                            level=2,
                            page_start=segment["page_start"],
                            page_end=segment["page_end"],
                            section_title=segment["section_title"],
                            content=child_text,
                            metadata=child_metadata,
                        )
                    )

        # 再生成表格块。表格不能混在普通段落块里切。
        table_groups = self._group_table_blocks(blocks)
        for group in table_groups:
            table_group_id = f"tblgrp_{uuid4().hex[:12]}"
            is_cross_page_table = len({item["page_no"] for item in group}) > 1
            table_title = self._build_table_title(group)
            merged_columns, merged_rows = self._merge_table_group(group)

            table_parent_text = self._build_table_parent_text(table_title, merged_columns, merged_rows)
            table_parent_uuid = self._generate_chunk_uuid()
            chunk_index += 1
            table_parent_metadata = self._build_table_metadata(
                heading_path=group[0]["heading_path"],
                chunk_strategy_version="v1_table_grouping",
                table_title=table_title,
                column_names=merged_columns,
                row_count=len(merged_rows),
                table_group_id=table_group_id,
                is_cross_page_table=is_cross_page_table,
                table_part_no=1,
                char_count=len(table_parent_text),
            )
            chunks.append(
                self._build_chunk_record(
                    chunk_uuid=table_parent_uuid,
                    document_id=document["document_id"],
                    knowledge_base_id=document["knowledge_base_id"],
                    chunk_index=chunk_index,
                    chunk_type="table_parent",
                    parent_chunk_uuid=None,
                    level=1,
                    page_start=min(item["page_no"] for item in group),
                    page_end=max(item["page_no"] for item in group),
                    section_title=group[0]["section_title"],
                    content=table_parent_text,
                    metadata=table_parent_metadata,
                )
            )

            table_summary_text = self._build_table_summary_text(table_title, merged_columns, len(merged_rows))
            chunk_index += 1
            table_summary_metadata = self._build_table_metadata(
                heading_path=group[0]["heading_path"],
                chunk_strategy_version="v1_table_grouping",
                table_title=table_title,
                column_names=merged_columns,
                row_count=len(merged_rows),
                table_group_id=table_group_id,
                is_cross_page_table=is_cross_page_table,
                table_part_no=1,
                char_count=len(table_summary_text),
            )
            chunks.append(
                self._build_chunk_record(
                    chunk_uuid=self._generate_chunk_uuid(),
                    document_id=document["document_id"],
                    knowledge_base_id=document["knowledge_base_id"],
                    chunk_index=chunk_index,
                    chunk_type="table_summary",
                    parent_chunk_uuid=table_parent_uuid,
                    level=2,
                    page_start=min(item["page_no"] for item in group),
                    page_end=max(item["page_no"] for item in group),
                    section_title=group[0]["section_title"],
                    content=table_summary_text,
                    metadata=table_summary_metadata,
                )
            )

            for part_no, row_group in enumerate(self._split_table_rows(merged_rows), start=1):
                table_child_text = self._build_table_child_text(table_title, merged_columns, row_group)
                chunk_index += 1
                table_child_metadata = self._build_table_metadata(
                    heading_path=group[0]["heading_path"],
                    chunk_strategy_version="v1_table_grouping",
                    table_title=table_title,
                    column_names=merged_columns,
                    row_count=len(row_group),
                    table_group_id=table_group_id,
                    is_cross_page_table=is_cross_page_table,
                    table_part_no=part_no,
                    char_count=len(table_child_text),
                )
                chunks.append(
                    self._build_chunk_record(
                        chunk_uuid=self._generate_chunk_uuid(),
                        document_id=document["document_id"],
                        knowledge_base_id=document["knowledge_base_id"],
                        chunk_index=chunk_index,
                        chunk_type="table_child",
                        parent_chunk_uuid=table_parent_uuid,
                        level=2,
                        page_start=min(item["page_no"] for item in group),
                        page_end=max(item["page_no"] for item in group),
                        section_title=group[0]["section_title"],
                        content=table_child_text,
                        metadata=table_child_metadata,
                    )
                )

        return chunks

    def _get_chunk_strategy(self, document_type: str) -> dict:
        """返回当前文档类型对应的 V1 切片参数。"""

        strategies = {
            "policy_like": {
                "parent_target": 1200,
                "parent_max": 2000,
                "child_target": 500,
                "child_overlap": 80,
            },
            "contract_like": {
                "parent_target": 900,
                "parent_max": 1500,
                "child_target": 350,
                "child_overlap": 80,
            },
            "report_like": {
                "parent_target": 1000,
                "parent_max": 1800,
                "child_target": 450,
                "child_overlap": 80,
            },
            "general_like": {
                "parent_target": 900,
                "parent_max": 1600,
                "child_target": 500,
                "child_overlap": 100,
            },
        }
        return strategies.get(document_type, strategies["general_like"])

    def _build_text_segments(self, blocks: list[dict], document_type: str) -> list[dict]:
        """根据结构块构造文本类段级片段。

        设计说明：
        - 这里先按 heading / clause 组织“结构段”；
        - 如果结构不明显，也至少按段落形成最小父段，再由后续窗口回退兜底；
        - 这样可以避免一开始就对整篇文档粗暴定长切片。
        """

        segments: list[dict] = []
        current_segment: dict | None = None

        def flush_current_segment() -> None:
            nonlocal current_segment
            if current_segment and current_segment["text"].strip():
                segments.append(current_segment)
            current_segment = None

        for block in blocks:
            if block["block_type"] in {"table", "ocr_table", "image"}:
                flush_current_segment()
                continue

            if block["block_type"] == "heading":
                flush_current_segment()
                continue

            if block["block_type"] not in {"paragraph", "ocr_paragraph"}:
                continue

            text = block["text"].strip()
            if not text:
                continue

            should_start_new = current_segment is None
            if document_type == "contract_like" and block.get("clause_no"):
                should_start_new = True
            elif document_type == "policy_like" and block.get("clause_no"):
                should_start_new = True

            if should_start_new:
                flush_current_segment()
                current_segment = {
                    "text": text,
                    "page_start": block["page_no"],
                    "page_end": block["page_no"],
                    "section_title": block.get("section_title"),
                    "heading_path": block.get("heading_path") or [],
                    "clause_no": block.get("clause_no"),
                }
            else:
                current_segment["text"] += "\n" + text
                current_segment["page_end"] = block["page_no"]

        flush_current_segment()
        return segments

    def _split_parent_text(self, text: str, parent_max: int, parent_target: int) -> list[str]:
        """在结构段过大时，对父块内部做固定窗口回退。

        说明：
        - 这是“结构优先 + 固定窗口回退”的关键点；
        - 只有当结构段本身过大时，才在父块内部做窗口拆分；
        - 当前是可升级的 V1 方案，后续可替换为更强的 semantic chunking。
        """

        if len(text) <= parent_max:
            return [text]

        return self._split_text_with_stride(
            text=text,
            window_size=parent_target,
            overlap_size=max(parent_target // 10, 80),
        )

    def _split_child_text(self, text: str, target_size: int, overlap_size: int) -> list[str]:
        """在父块内部生成检索级子块。"""

        if len(text) <= target_size:
            return [text]
        return self._split_text_with_stride(
            text=text,
            window_size=target_size,
            overlap_size=overlap_size,
        )

    def _split_text_with_stride(self, text: str, window_size: int, overlap_size: int) -> list[str]:
        """按固定窗口 + overlap 切文本。

        当前仅作为父块内部的回退方案，不直接作用于整篇文档。
        """

        normalized_text = re.sub(r"\n{2,}", "\n", text).strip()
        if not normalized_text:
            return []

        chunks: list[str] = []
        start = 0
        step = max(window_size - overlap_size, 1)

        while start < len(normalized_text):
            end = min(start + window_size, len(normalized_text))
            chunk_text = normalized_text[start:end].strip()
            if chunk_text:
                chunks.append(chunk_text)
            if end >= len(normalized_text):
                break
            start += step

        return chunks

    def _group_table_blocks(self, blocks: list[dict]) -> list[list[dict]]:
        """把表格块按逻辑表进行分组。

        当前阶段采用规则法跨页表识别，不是最终视觉算法版本。
        主要依据：
        - 页码连续；
        - 表头相同或高度相似；
        - 列数一致或接近；
        - 没有正文明显打断；
        - 存在“续表”时增强合并信号。
        """

        table_blocks = [block for block in blocks if block["block_type"] in {"table", "ocr_table"}]
        if not table_blocks:
            return []

        groups: list[list[dict]] = []
        current_group = [table_blocks[0]]

        for block in table_blocks[1:]:
            if self._looks_like_same_cross_page_table(current_group[-1], block):
                current_group.append(block)
            else:
                groups.append(current_group)
                current_group = [block]

        groups.append(current_group)
        return groups

    def _looks_like_same_cross_page_table(self, previous_block: dict, current_block: dict) -> bool:
        """判断两个表格块是否可能属于同一跨页逻辑表。"""

        previous_columns = previous_block.get("table_data", {}).get("column_names", [])
        current_columns = current_block.get("table_data", {}).get("column_names", [])
        previous_title = (previous_block.get("raw_metadata", {}).get("table_title") or "").replace("续表", "")
        current_title = (current_block.get("raw_metadata", {}).get("table_title") or "").replace("续表", "")
        same_columns = previous_columns and current_columns and previous_columns == current_columns
        same_title = bool(previous_title and current_title and previous_title == current_title)
        continuous_page = current_block["page_no"] == previous_block["page_no"] + 1
        same_section = previous_block.get("section_title") == current_block.get("section_title")
        title_continued_signal = "续表" in (current_block.get("raw_metadata", {}).get("table_title") or "")

        return continuous_page and same_section and (same_columns or same_title or title_continued_signal)

    def _merge_table_group(self, group: list[dict]) -> tuple[list[str], list[list[str]]]:
        """把同一逻辑表的多页表格块合并为一个表。"""

        merged_columns: list[str] = []
        merged_rows: list[list[str]] = []
        for block in group:
            table_data = block.get("table_data") or {}
            columns = table_data.get("column_names") or []
            rows = table_data.get("rows") or []
            if not merged_columns and columns:
                merged_columns = columns
            merged_rows.extend(rows)
        return merged_columns, merged_rows

    def _split_table_rows(self, rows: list[list[str]], row_group_size: int = 5) -> list[list[list[str]]]:
        """把表格行按小组切成检索级块。"""

        if not rows:
            return [[]]
        return [rows[index : index + row_group_size] for index in range(0, len(rows), row_group_size)]

    def _build_table_title(self, group: list[dict]) -> str:
        """生成逻辑表标题。"""

        for block in group:
            table_title = block.get("raw_metadata", {}).get("table_title")
            if table_title:
                return table_title
        return group[0].get("section_title") or "未命名表格"

    def _build_table_parent_text(self, table_title: str, columns: list[str], rows: list[list[str]]) -> str:
        """生成表格父块正文。"""

        lines = [f"表格标题：{table_title}"]
        if columns:
            lines.append("列名：" + " | ".join(columns))
        for row in rows:
            lines.append(" | ".join(row))
        return "\n".join(lines)

    def _build_table_summary_text(self, table_title: str, columns: list[str], row_count: int) -> str:
        """生成表格摘要块正文。"""

        column_text = "、".join(columns) if columns else "无列名信息"
        return (
            f"表格摘要：{table_title}。"
            f"主要列包括：{column_text}。"
            f"当前逻辑表共包含 {row_count} 行数据。"
        )

    def _build_table_child_text(self, table_title: str, columns: list[str], rows: list[list[str]]) -> str:
        """生成表格子块正文。"""

        lines = [f"表格分块：{table_title}"]
        if columns:
            lines.append("列名：" + " | ".join(columns))
        for row in rows:
            lines.append(" | ".join(row))
        return "\n".join(lines)

    def _build_base_metadata(
        self,
        heading_path: list[str],
        clause_no: str | None,
        chunk_strategy_version: str,
        is_table: bool,
        is_cross_page_table: bool,
        table_group_id: str | None,
        table_part_no: int | None,
        char_count: int,
    ) -> dict:
        """构造文本类切片的基础 metadata。"""

        return {
            "heading_path": heading_path,
            "clause_no": clause_no,
            "chunk_strategy_version": chunk_strategy_version,
            "is_table": is_table,
            "is_cross_page_table": is_cross_page_table,
            "table_group_id": table_group_id,
            "table_part_no": table_part_no,
            "char_count": char_count,
        }

    def _build_table_metadata(
        self,
        heading_path: list[str],
        chunk_strategy_version: str,
        table_title: str,
        column_names: list[str],
        row_count: int,
        table_group_id: str,
        is_cross_page_table: bool,
        table_part_no: int,
        char_count: int,
    ) -> dict:
        """构造表格类切片 metadata。"""

        metadata = self._build_base_metadata(
            heading_path=heading_path,
            clause_no=None,
            chunk_strategy_version=chunk_strategy_version,
            is_table=True,
            is_cross_page_table=is_cross_page_table,
            table_group_id=table_group_id,
            table_part_no=table_part_no,
            char_count=char_count,
        )
        metadata.update(
            {
                "table_title": table_title,
                "column_names": column_names,
                "row_count": row_count,
            }
        )
        return metadata

    def _build_chunk_record(
        self,
        chunk_uuid: str,
        document_id: str,
        knowledge_base_id: str,
        chunk_index: int,
        chunk_type: str,
        parent_chunk_uuid: str | None,
        level: int,
        page_start: int | None,
        page_end: int | None,
        section_title: str | None,
        content: str,
        metadata: dict,
    ) -> dict:
        """构造统一切片记录。"""

        return {
            "chunk_uuid": chunk_uuid,
            "document_id": document_id,
            "knowledge_base_id": knowledge_base_id,
            "chunk_index": chunk_index,
            "chunk_type": chunk_type,
            "parent_chunk_uuid": parent_chunk_uuid,
            "level": level,
            "page_start": page_start,
            "page_end": page_end,
            "section_title": section_title,
            "content_preview": content,
            "token_count": max(len(content), 1),
            "metadata": metadata,
        }

    def _generate_chunk_uuid(self) -> str:
        """生成带业务前缀的切片 UUID。"""

        return f"chunk_{uuid4().hex[:12]}"
