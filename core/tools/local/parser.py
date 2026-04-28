"""本地最小文档解析器。

当前阶段不追求完整 OCR 或复杂版式理解，
但必须先把不同文件格式统一转换成“结构块”列表，
为后续切片、表格处理、embedding 和检索提供稳定输入。

当前最小支持：
- `.txt`
- `.md`
- `.pdf`（优先尝试文本抽取；无法抽取时回退到占位解析）
"""

from __future__ import annotations

import re
from pathlib import Path


class LocalDocumentParser:
    """本地最小文档解析器。"""

    def parse(self, file_path: str | Path, file_type: str) -> list[dict]:
        """把文件解析为统一结构块列表。"""

        path = Path(file_path)
        normalized_file_type = (file_type or path.suffix.lstrip(".") or "unknown").lower()

        if normalized_file_type in {"txt", "md"}:
            text = path.read_text(encoding="utf-8", errors="ignore")
            return self._parse_text_like_content(text)

        if normalized_file_type == "pdf":
            return self._parse_pdf(path)

        text = path.read_text(encoding="utf-8", errors="ignore")
        return self._parse_text_like_content(text)

    def _parse_pdf(self, file_path: Path) -> list[dict]:
        """最小 PDF 解析。

        当前阶段优先尝试文本抽取：
        - 如果环境中已有 `pypdf`，则按页抽取文本；
        - 如果没有可用解析器，则回退到占位实现，保证 parse 流程不断。

        说明：
        - 这不是最终 PDF/OCR 方案；
        - 真实扫描件、复杂表格和版面分析仍需要后续独立接入更强解析器。
        """

        try:
            from pypdf import PdfReader  # type: ignore

            reader = PdfReader(str(file_path))
            all_blocks: list[dict] = []
            for page_index, page in enumerate(reader.pages, start=1):
                page_text = page.extract_text() or ""
                if page_text.strip():
                    all_blocks.extend(self._parse_text_like_content(page_text, page_offset=page_index - 1))
            if all_blocks:
                return all_blocks
        except Exception:
            pass

        # 如果没有可用 PDF 文本抽取器，仍然返回一个最小结构块，
        # 这样上传后的 parse 状态流转、切片落库和后续任务入口都能继续验证。
        placeholder_text = (
            f"当前 PDF 文件 `{file_path.name}` 使用了第五轮最小占位解析。"
            "后续需要接入更强的 PDF 解析与 OCR 才能获得更高质量结构块。"
        )
        return [
            {
                "block_type": "paragraph",
                "text": placeholder_text,
                "page_no": 1,
                "heading_path": [],
                "section_title": file_path.stem,
                "clause_no": None,
                "table_data": None,
                "raw_metadata": {"parse_mode": "pdf_placeholder"},
            }
        ]

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

    def _split_pages(self, text: str) -> list[str]:
        """把原始文本切成页级文本。

        支持两种最小分页信号：
        - `\f` 分页符；
        - `[[PAGE:n]]` 这类测试与开发场景下的显式页码标记。
        """

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
            return min(line.count(".") + line.count("．") + 1, 4), line
        return 1, line

    def _update_heading_stack(self, heading_stack: list[str], heading_level: int, heading_text: str) -> None:
        """根据标题层级维护当前标题路径。"""

        while len(heading_stack) >= heading_level:
            heading_stack.pop()
        heading_stack.append(heading_text)

    def _extract_clause_no(self, text: str) -> str | None:
        """从标题或段落中提取最小条款号。"""

        patterns = [
            r"(第[一二三四五六七八九十百千万0-9]+条)",
            r"^([0-9]+(\.[0-9]+)*)",
            r"^([一二三四五六七八九十]+[、.．])",
        ]
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return match.group(1)
        return None

    def _is_markdown_table_line(self, line: str) -> bool:
        """判断当前行是否可能属于 Markdown 风格表格。"""

        return line.count("|") >= 2

    def _parse_markdown_table(self, table_lines: list[str]) -> dict:
        """把最小 Markdown 表格解析成结构化数据。"""

        cleaned_lines = [line.strip().strip("|") for line in table_lines if line.strip()]
        if not cleaned_lines:
            return {"column_names": [], "rows": [], "row_count": 0}

        parsed_rows = []
        for line in cleaned_lines:
            cells = [cell.strip() for cell in line.split("|")]
            parsed_rows.append(cells)

        # 第二行通常是 Markdown 表头分隔符，需要剔除。
        column_names = parsed_rows[0]
        data_rows = parsed_rows[1:]
        if data_rows and all(set(cell) <= {"-", ":"} for cell in data_rows[0]):
            data_rows = data_rows[1:]

        return {
            "column_names": column_names,
            "rows": data_rows,
            "row_count": len(data_rows),
        }

    def _extract_table_title(self, previous_line: str) -> str | None:
        """从表格前一行提取最小表标题。"""

        if not previous_line:
            return None
        if "表" in previous_line or "续表" in previous_line:
            return previous_line
        return None
