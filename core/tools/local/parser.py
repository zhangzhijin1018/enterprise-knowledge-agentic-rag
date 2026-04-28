"""本地文档解析器。

本轮目标不是直接做最终版 OCR / 版面理解系统，
而是把真实企业文档常见的输入类型先统一转换为“结构块”：
- docx：优先原生段落和表格解析；
- pdf：优先文本抽取 + 表格抽取；
- 扫描 PDF / 图片：再进入 OCR 路线；
- txt / md：继续保留第五轮的轻量文本解析能力。

这样做的原因是：
- docx 原生表格如果走 OCR，会丢掉原始表结构；
- 文本型 PDF 如果全部走 OCR，会更慢、成本更高、误差更大；
- 扫描件和图片才是 OCR 的主要场景；
- 统一结构块输出后，后续 chunk、embedding、Milvus、检索都可以复用同一条下游链路。
"""

from __future__ import annotations

import re
import tempfile
from pathlib import Path
from typing import Any

from core.tools.local.ocr import LocalOCRGateway


class LocalDocumentParser:
    """本地统一文档解析器。"""

    IMAGE_FILE_TYPES = {"png", "jpg", "jpeg", "bmp", "tif", "tiff", "webp"}

    def __init__(self, ocr_gateway: LocalOCRGateway | None = None) -> None:
        """初始化本地解析器。"""

        self.ocr_gateway = ocr_gateway or LocalOCRGateway()

    def parse(self, file_path: str | Path, file_type: str) -> list[dict]:
        """把文件解析为统一结构块列表。"""

        path = Path(file_path)
        normalized_file_type = (file_type or path.suffix.lstrip(".") or "unknown").lower()

        if normalized_file_type in {"txt", "md"}:
            text = path.read_text(encoding="utf-8", errors="ignore")
            return self._parse_text_like_content(text)

        if normalized_file_type == "docx":
            return self._parse_docx(path)

        if normalized_file_type == "pdf":
            return self._parse_pdf(path)

        if normalized_file_type in self.IMAGE_FILE_TYPES:
            return self._parse_image(path)

        text = path.read_text(encoding="utf-8", errors="ignore")
        return self._parse_text_like_content(text)

    def _parse_docx(self, file_path: Path) -> list[dict]:
        """使用 python-docx 原生解析 docx。

        关键原则：
        - docx 正文段落直接读取，不走 OCR；
        - docx 原生表格直接读取 cell 内容，不走 OCR；
        - 尽量在 block 中保留标题路径和表格前置标题，帮助后续 chunk 更稳定。
        """

        try:
            from docx import Document as DocxDocument  # type: ignore
            from docx.oxml.table import CT_Tbl  # type: ignore
            from docx.oxml.text.paragraph import CT_P  # type: ignore
            from docx.table import Table  # type: ignore
            from docx.text.paragraph import Paragraph  # type: ignore
        except Exception:
            return [self._build_placeholder_block(file_path, "docx_dependency_missing")]

        document = DocxDocument(str(file_path))
        heading_stack: list[str] = []
        blocks: list[dict] = []
        last_non_empty_text = file_path.stem

        for child in document.element.body.iterchildren():
            if isinstance(child, CT_P):
                paragraph = Paragraph(child, document)
                text = paragraph.text.strip()
                if not text:
                    continue

                if self._is_docx_heading(paragraph):
                    heading_level = self._infer_docx_heading_level(paragraph)
                    self._update_heading_stack(heading_stack, heading_level, text)
                    blocks.append(
                        {
                            "block_type": "heading",
                            "text": text,
                            "page_no": 1,
                            "heading_path": list(heading_stack),
                            "section_title": text,
                            "clause_no": self._extract_clause_no(text),
                            "table_data": None,
                            "image_ref": None,
                            "raw_metadata": {
                                "parse_mode": "docx_native",
                                "heading_level": heading_level,
                                "style_name": getattr(paragraph.style, "name", ""),
                            },
                        }
                    )
                else:
                    blocks.append(
                        {
                            "block_type": "paragraph",
                            "text": text,
                            "page_no": 1,
                            "heading_path": list(heading_stack),
                            "section_title": heading_stack[-1] if heading_stack else None,
                            "clause_no": self._extract_clause_no(text),
                            "table_data": None,
                            "image_ref": None,
                            "raw_metadata": {
                                "parse_mode": "docx_native",
                                "style_name": getattr(paragraph.style, "name", ""),
                            },
                        }
                    )
                last_non_empty_text = text
                continue

            if isinstance(child, CT_Tbl):
                table = Table(child, document)
                table_data = self._parse_docx_table(table)
                blocks.append(
                    {
                        "block_type": "table",
                        "text": self._build_table_text_from_rows(
                            table_title=self._extract_table_title(last_non_empty_text),
                            column_names=table_data["column_names"],
                            rows=table_data["rows"],
                        ),
                        "page_no": 1,
                        "heading_path": list(heading_stack),
                        "section_title": heading_stack[-1] if heading_stack else None,
                        "clause_no": None,
                        "table_data": table_data,
                        "image_ref": None,
                        "raw_metadata": {
                            "parse_mode": "docx_native",
                            "table_title": self._extract_table_title(last_non_empty_text),
                            "column_names": table_data["column_names"],
                            "row_count": table_data["row_count"],
                        },
                    }
                )

        return blocks or [self._build_placeholder_block(file_path, "docx_empty")]

    def _parse_pdf(self, file_path: Path) -> list[dict]:
        """使用 PyMuPDF + pdfplumber 解析 PDF。

        路线选择原则：
        1. 文本型 PDF：优先文本抽取；
        2. 文本型表格：优先 pdfplumber 抽表；
        3. 页面文本极少或几乎为空：回退到 OCR 路线。

        这样做的原因：
        - 文本 PDF 直接提文本更快、更稳定；
        - pdfplumber 对文本型表格恢复更适合当前阶段；
        - 扫描件如果硬走文本抽取，往往拿不到有效内容，必须进入 OCR。
        """

        try:
            import fitz  # type: ignore
        except Exception:
            return [self._build_placeholder_block(file_path, "pdf_dependency_missing")]

        try:
            pdf_document = fitz.open(str(file_path))
        except Exception:
            return [self._build_placeholder_block(file_path, "pdf_open_failed")]

        if self._should_use_pdf_ocr(pdf_document):
            try:
                return self._parse_scanned_pdf_with_ocr(pdf_document, file_path)
            finally:
                pdf_document.close()

        try:
            import pdfplumber  # type: ignore

            plumber_document = pdfplumber.open(str(file_path))
        except Exception:
            plumber_document = None

        blocks: list[dict] = []
        current_heading_path: list[str] = []

        for page_index in range(len(pdf_document)):
            page_no = page_index + 1
            page = pdf_document[page_index]
            page_text = (page.get_text("text") or "").strip()

            page_blocks: list[dict] = []
            if page_text:
                page_blocks = self._parse_text_like_content(page_text, page_offset=page_index)
                current_heading_path = self._propagate_page_heading_context(page_blocks, current_heading_path)
                for block in page_blocks:
                    block["raw_metadata"] = {
                        **block.get("raw_metadata", {}),
                        "parse_mode": "pdf_text",
                    }
                blocks.extend(page_blocks)

            if plumber_document is not None:
                plumber_page = plumber_document.pages[page_index]
                table_blocks = self._extract_pdf_tables(
                    plumber_page=plumber_page,
                    page_no=page_no,
                    heading_path=current_heading_path,
                    section_title=current_heading_path[-1] if current_heading_path else None,
                    page_blocks=page_blocks,
                )
                blocks.extend(table_blocks)

            image_blocks = self._extract_pdf_images(
                page=page,
                page_no=page_no,
                heading_path=current_heading_path,
            )
            blocks.extend(image_blocks)

        if plumber_document is not None:
            plumber_document.close()
        pdf_document.close()

        return blocks or [self._build_placeholder_block(file_path, "pdf_empty")]

    def _parse_scanned_pdf_with_ocr(self, pdf_document: Any, file_path: Path) -> list[dict]:
        """对扫描型 PDF 执行 OCR 路线。

        当前阶段不做复杂视觉切页算法，
        先把每页渲染成图片，再走 OCR/PP-Structure 入口。
        """

        try:
            import fitz  # type: ignore
        except Exception:
            return [self._build_placeholder_block(file_path, "pdf_ocr_dependency_missing")]

        blocks: list[dict] = []
        with tempfile.TemporaryDirectory(prefix="pdf_ocr_") as temp_dir:
            temp_dir_path = Path(temp_dir)
            for page_index in range(len(pdf_document)):
                page_no = page_index + 1
                page = pdf_document[page_index]
                pixmap = page.get_pixmap(matrix=fitz.Matrix(2, 2))
                image_path = temp_dir_path / f"{file_path.stem}_page_{page_no}.png"
                pixmap.save(str(image_path))
                blocks.extend(
                    self.ocr_gateway.extract_structure_from_image(
                        image_path=image_path,
                        page_no=page_no,
                        raw_metadata={
                            "parse_mode": "pdf_ocr",
                            "source_file": file_path.name,
                        },
                    )
                )

        return blocks or [self._build_placeholder_block(file_path, "pdf_ocr_empty")]

    def _parse_image(self, file_path: Path) -> list[dict]:
        """解析图片文件。

        图片文件没有原生结构文本可读，因此直接进入 OCR 路线。
        """

        return self.ocr_gateway.extract_structure_from_image(
            image_path=file_path,
            page_no=1,
            raw_metadata={
                "parse_mode": "image_ocr",
                "source_file": file_path.name,
            },
        )

    def _parse_text_like_content(self, text: str, page_offset: int = 0) -> list[dict]:
        """解析 txt / md / 抽取后的纯文本内容。"""

        pages = self._split_pages(text)
        heading_stack: list[str] = []
        blocks: list[dict] = []

        for page_idx, page_text in enumerate(pages, start=1 + page_offset):
            lines = page_text.splitlines()
            paragraph_buffer: list[str] = []
            last_non_empty_line = ""
            line_index = 0

            while line_index < len(lines):
                raw_line = lines[line_index]
                line = raw_line.strip()

                if not line:
                    self._flush_paragraph_buffer(
                        paragraph_buffer=paragraph_buffer,
                        page_no=page_idx,
                        heading_stack=heading_stack,
                        blocks=blocks,
                    )
                    line_index += 1
                    continue

                if self._is_heading(line):
                    self._flush_paragraph_buffer(
                        paragraph_buffer=paragraph_buffer,
                        page_no=page_idx,
                        heading_stack=heading_stack,
                        blocks=blocks,
                    )
                    heading_level, heading_text = self._parse_heading(line)
                    self._update_heading_stack(heading_stack, heading_level, heading_text)
                    blocks.append(
                        {
                            "block_type": "heading",
                            "text": heading_text,
                            "page_no": page_idx,
                            "heading_path": list(heading_stack),
                            "section_title": heading_text,
                            "clause_no": self._extract_clause_no(heading_text),
                            "table_data": None,
                            "image_ref": None,
                            "raw_metadata": {"heading_level": heading_level},
                        }
                    )
                    last_non_empty_line = heading_text
                    line_index += 1
                    continue

                if self._is_markdown_table_line(line):
                    self._flush_paragraph_buffer(
                        paragraph_buffer=paragraph_buffer,
                        page_no=page_idx,
                        heading_stack=heading_stack,
                        blocks=blocks,
                    )
                    table_lines = []
                    while line_index < len(lines) and self._is_markdown_table_line(lines[line_index].strip()):
                        table_lines.append(lines[line_index].strip())
                        line_index += 1

                    table_data = self._parse_markdown_table(table_lines)
                    blocks.append(
                        {
                            "block_type": "table",
                            "text": "\n".join(table_lines),
                            "page_no": page_idx,
                            "heading_path": list(heading_stack),
                            "section_title": heading_stack[-1] if heading_stack else None,
                            "clause_no": None,
                            "table_data": table_data,
                            "image_ref": None,
                            "raw_metadata": {
                                "table_title": self._extract_table_title(last_non_empty_line),
                                "column_names": table_data["column_names"],
                                "row_count": table_data["row_count"],
                            },
                        }
                    )
                    continue

                paragraph_buffer.append(line)
                last_non_empty_line = line
                line_index += 1

            self._flush_paragraph_buffer(
                paragraph_buffer=paragraph_buffer,
                page_no=page_idx,
                heading_stack=heading_stack,
                blocks=blocks,
            )

        return blocks

    def _should_use_pdf_ocr(self, pdf_document: Any) -> bool:
        """判断 PDF 是否更适合进入 OCR 路线。

        当前是规则法 V1：
        - 如果整份 PDF 提取到的纯文本极少，说明大概率是扫描页或图片型 PDF；
        - 这时继续死磕文本抽取收益很低，应尽早切到 OCR。
        """

        total_non_whitespace_chars = 0
        for page in pdf_document:
            page_text = page.get_text("text") or ""
            total_non_whitespace_chars += len(re.sub(r"\s+", "", page_text))

        average_chars_per_page = total_non_whitespace_chars / max(len(pdf_document), 1)
        return average_chars_per_page < 20

    def _propagate_page_heading_context(
        self,
        page_blocks: list[dict],
        inherited_heading_path: list[str],
    ) -> list[str]:
        """让 PDF 页级解析结果继承上一页的标题上下文。"""

        if not page_blocks:
            return inherited_heading_path

        current_heading_path = list(inherited_heading_path)
        for block in page_blocks:
            if block["block_type"] == "heading":
                current_heading_path = list(block.get("heading_path") or [])
                continue

            if not block.get("heading_path") and current_heading_path:
                block["heading_path"] = list(current_heading_path)
                if block.get("section_title") is None:
                    block["section_title"] = current_heading_path[-1]

        return current_heading_path

    def _extract_pdf_tables(
        self,
        plumber_page: Any,
        page_no: int,
        heading_path: list[str],
        section_title: str | None,
        page_blocks: list[dict],
    ) -> list[dict]:
        """使用 pdfplumber 提取 PDF 文本型表格。"""

        table_blocks: list[dict] = []
        extracted_tables = plumber_page.extract_tables() or []
        for table_index, table in enumerate(extracted_tables, start=1):
            normalized_rows = self._normalize_table_rows(table)
            if not normalized_rows:
                continue

            column_names = normalized_rows[0]
            rows = normalized_rows[1:] if len(normalized_rows) > 1 else []
            table_title = self._infer_pdf_table_title(page_blocks, table_index)

            table_blocks.append(
                {
                    "block_type": "table",
                    "text": self._build_table_text_from_rows(table_title, column_names, rows),
                    "page_no": page_no,
                    "heading_path": list(heading_path),
                    "section_title": section_title,
                    "clause_no": None,
                    "table_data": {
                        "column_names": column_names,
                        "rows": rows,
                        "row_count": len(rows),
                    },
                    "image_ref": None,
                    "raw_metadata": {
                        "parse_mode": "pdf_table",
                        "table_title": table_title,
                        "column_names": column_names,
                        "row_count": len(rows),
                        "table_index": table_index,
                    },
                }
            )

        return table_blocks

    def _extract_pdf_images(
        self,
        page: Any,
        page_no: int,
        heading_path: list[str],
    ) -> list[dict]:
        """提取 PDF 页中的图片占位块。

        当前阶段图片块先只记录引用信息，
        不在这里直接强制对所有图片做 OCR，
        这样可以避免文本型 PDF 被无谓放大成本。
        """

        image_blocks: list[dict] = []
        for image_index, _ in enumerate(page.get_images(full=True) or [], start=1):
            image_blocks.append(
                {
                    "block_type": "image",
                    "text": f"PDF 图片区域 page={page_no}, image={image_index}",
                    "page_no": page_no,
                    "heading_path": list(heading_path),
                    "section_title": heading_path[-1] if heading_path else None,
                    "clause_no": None,
                    "table_data": None,
                    "image_ref": f"page={page_no}#image={image_index}",
                    "raw_metadata": {
                        "parse_mode": "pdf_image",
                        "image_index": image_index,
                    },
                }
            )
        return image_blocks

    def _parse_docx_table(self, table: Any) -> dict:
        """解析 docx 原生表格。"""

        rows: list[list[str]] = []
        for row in table.rows:
            values = [cell.text.strip() for cell in row.cells]
            if any(value for value in values):
                rows.append(values)

        if not rows:
            return {
                "column_names": [],
                "rows": [],
                "row_count": 0,
            }

        column_names = rows[0]
        data_rows = rows[1:] if len(rows) > 1 else []
        return {
            "column_names": column_names,
            "rows": data_rows,
            "row_count": len(data_rows),
        }

    def _normalize_table_rows(self, raw_rows: list[list[Any] | None]) -> list[list[str]]:
        """规范化表格行数据。"""

        normalized_rows: list[list[str]] = []
        for row in raw_rows:
            if not row:
                continue
            values = [str(cell or "").strip() for cell in row]
            if any(values):
                normalized_rows.append(values)
        return normalized_rows

    def _infer_pdf_table_title(self, page_blocks: list[dict], table_index: int) -> str:
        """从 PDF 页文本块中推断表标题。"""

        title_candidates = []
        for block in page_blocks:
            if block["block_type"] in {"heading", "paragraph"}:
                text = block["text"].strip()
                if "表" in text[:12]:
                    title_candidates.append(text)

        if title_candidates:
            return self._extract_table_title(title_candidates[-1])
        return f"PDF 表格 {table_index}"

    def _is_docx_heading(self, paragraph: Any) -> bool:
        """判断 docx 段落是否为标题。"""

        style_name = str(getattr(paragraph.style, "name", "") or "").lower()
        if "heading" in style_name or "标题" in style_name:
            return True
        return self._is_heading(paragraph.text.strip())

    def _infer_docx_heading_level(self, paragraph: Any) -> int:
        """推断 docx 标题层级。"""

        style_name = str(getattr(paragraph.style, "name", "") or "")
        matched = re.search(r"(\d+)", style_name)
        if matched:
            return max(int(matched.group(1)), 1)
        return self._parse_heading(paragraph.text.strip())[0] if self._is_heading(paragraph.text.strip()) else 1

    def _build_table_text_from_rows(
        self,
        table_title: str | None,
        column_names: list[str],
        rows: list[list[str]],
    ) -> str:
        """把表格结构还原为可检索文本。"""

        lines: list[str] = []
        if table_title:
            lines.append(table_title)
        if column_names:
            lines.append(" | ".join(column_names))
        for row in rows:
            lines.append(" | ".join(row))
        return "\n".join(lines).strip()

    def _build_placeholder_block(self, file_path: Path, reason: str) -> dict:
        """构造解析回退占位块。"""

        return {
            "block_type": "paragraph",
            "text": f"{file_path.name} 当前使用了解析占位回退，原因：{reason}",
            "page_no": 1,
            "heading_path": [],
            "section_title": file_path.stem,
            "clause_no": None,
            "table_data": None,
            "image_ref": None,
            "raw_metadata": {"parse_mode": "placeholder", "reason": reason},
        }

    def _split_pages(self, text: str) -> list[str]:
        """把原始文本切成页级文本。"""

        if "\f" in text:
            return [item for item in text.split("\f") if item.strip()]

        page_marker_pattern = re.compile(r"\[\[PAGE:(\d+)\]\]")
        if page_marker_pattern.search(text):
            pages: list[str] = []
            current_lines: list[str] = []
            for line in text.splitlines():
                if page_marker_pattern.fullmatch(line.strip()):
                    if current_lines:
                        pages.append("\n".join(current_lines))
                        current_lines = []
                    continue
                current_lines.append(line)
            if current_lines:
                pages.append("\n".join(current_lines))
            return [item for item in pages if item.strip()]

        return [text]

    def _flush_paragraph_buffer(
        self,
        paragraph_buffer: list[str],
        page_no: int,
        heading_stack: list[str],
        blocks: list[dict],
    ) -> None:
        """把缓存中的段落输出为 paragraph 结构块。"""

        if not paragraph_buffer:
            return

        paragraph_text = "\n".join(paragraph_buffer).strip()
        paragraph_buffer.clear()
        if not paragraph_text:
            return

        blocks.append(
            {
                "block_type": "paragraph",
                "text": paragraph_text,
                "page_no": page_no,
                "heading_path": list(heading_stack),
                "section_title": heading_stack[-1] if heading_stack else None,
                "clause_no": self._extract_clause_no(paragraph_text),
                "table_data": None,
                "image_ref": None,
                "raw_metadata": {"char_count": len(paragraph_text)},
            }
        )

    def _is_heading(self, line: str) -> bool:
        """判断当前行是否可视为结构标题。"""

        heading_patterns = [
            r"^#{1,6}\s+.+",
            r"^第[一二三四五六七八九十百千万0-9]+[章节条款]\s*.+",
            r"^[一二三四五六七八九十]+[、.．]\s*.+",
            r"^[0-9]+(\.[0-9]+)*\s+.+",
        ]
        return any(re.match(pattern, line) for pattern in heading_patterns)

    def _parse_heading(self, line: str) -> tuple[int, str]:
        """解析标题层级与标题文本。"""

        if line.startswith("#"):
            level = len(line) - len(line.lstrip("#"))
            return level, line.lstrip("#").strip()

        if re.match(r"^第[一二三四五六七八九十百千万0-9]+章", line):
            return 1, line
        if re.match(r"^第[一二三四五六七八九十百千万0-9]+节", line):
            return 2, line
        if re.match(r"^第[一二三四五六七八九十百千万0-9]+条", line):
            return 3, line
        if re.match(r"^[一二三四五六七八九十]+[、.．]", line):
            return 2, line
        if re.match(r"^[0-9]+(\.[0-9]+)*", line):
            level = min(line.split(" ")[0].count(".") + 1, 6)
            return level, line
        return 1, line

    def _update_heading_stack(self, heading_stack: list[str], heading_level: int, heading_text: str) -> None:
        """更新标题路径栈。"""

        normalized_level = max(1, heading_level)
        while len(heading_stack) >= normalized_level:
            heading_stack.pop()
        heading_stack.append(heading_text)

    def _extract_clause_no(self, text: str) -> str | None:
        """提取最小条款号。"""

        patterns = [
            r"(第[一二三四五六七八九十百千万0-9]+条)",
            r"(^[0-9]+(\.[0-9]+)*)",
            r"(^[一二三四五六七八九十]+[、.．])",
        ]
        for pattern in patterns:
            matched = re.search(pattern, text)
            if matched:
                return matched.group(1) if matched.groups() else matched.group(0)
        return None

    def _is_markdown_table_line(self, line: str) -> bool:
        """判断当前行是否为 markdown 表格行。"""

        return line.count("|") >= 2

    def _parse_markdown_table(self, table_lines: list[str]) -> dict:
        """解析 markdown 表格。"""

        rows = []
        for line in table_lines:
            if re.fullmatch(r"\|\s*[-:| ]+\|?", line):
                continue
            values = [item.strip() for item in line.strip("|").split("|")]
            if any(values):
                rows.append(values)

        if not rows:
            return {
                "column_names": [],
                "rows": [],
                "row_count": 0,
            }

        column_names = rows[0]
        data_rows = rows[1:] if len(rows) > 1 else []
        return {
            "column_names": column_names,
            "rows": data_rows,
            "row_count": len(data_rows),
        }

    def _extract_table_title(self, last_non_empty_line: str) -> str | None:
        """从表格前一行提取最小表标题。"""

        if not last_non_empty_line:
            return None
        if "表" in last_non_empty_line[:12]:
            return last_non_empty_line
        return None
