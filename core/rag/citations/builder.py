"""引用构建器。

生成答案中的引用标记，实现答案可溯源。
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class CitationBuilder:
    """引用构建器。

    职责：
    - 为每个检索 chunk 生成唯一引用 ID
    - 构造引用标记格式 [1], [2], ...
    - 生成引用详情列表
    - 在答案中插入引用标记

    设计原因：
    - 企业知识问答必须可溯源，用户需要知道答案的来源
    - 引用标记帮助用户快速定位原始文档
    - 引用信息也是审计和评估的重要依据
    """

    def __init__(
        self,
        citation_format: str = "bracket",  # bracket=[1], numeric=1., superscript=[ⁱ]
        max_citations: int = 10,
    ) -> None:
        """初始化引用构建器。

        Args:
            citation_format: 引用格式
                - bracket: [1], [2], ...（默认）
                - numeric: 1., 2., ...
                - superscript: [¹], [²], ...
            max_citations: 最大引用数量
        """

        self.citation_format = citation_format
        self.max_citations = max_citations

        # 引用序号映射
        self._citation_map: dict[str, str] = {}

    def build_citations(self, chunks: list[dict]) -> list[dict]:
        """为检索结果 chunks 生成引用信息。

        Args:
            chunks: 检索结果 chunks

        Returns:
            引用列表，每项包含：
            - citation_id: 引用 ID，如 "[1]", "[2]"
            - chunk_uuid: 对应的 chunk UUID
            - content: chunk 内容
            - score: 相关性分数
            - metadata: 元数据
            - section_title: 章节标题
            - page_no: 页码
            - document_id: 文档 ID
            - matched_terms: 匹配的关键词（如果有）
        """

        if not chunks:
            return []

        # 重置引用映射
        self._citation_map = {}

        citations = []
        for i, chunk in enumerate(chunks[:self.max_citations], 1):
            citation_id = self._format_citation_id(i)

            # 记录映射
            self._citation_map[chunk.get("chunk_uuid", "")] = citation_id

            citation = {
                "citation_id": citation_id,
                "chunk_uuid": chunk.get("chunk_uuid", ""),
                "content": chunk.get("content", ""),
                "content_preview": chunk.get("content_preview", "")[:200],
                "score": chunk.get("score", 0.0),
                "rerank_score": chunk.get("rerank_score", chunk.get("score", 0.0)),
                "dense_score": chunk.get("dense_score", 0.0),
                "sparse_score": chunk.get("sparse_score", 0.0),
                "metadata": chunk.get("metadata", {}),
                "chunk_type": chunk.get("chunk_type", ""),
                "section_title": chunk.get("section_title") or chunk.get("metadata", {}).get("section_title"),
                "page_start": chunk.get("page_start"),
                "page_end": chunk.get("page_end"),
                "document_id": chunk.get("document_id", ""),
                "matched_terms": chunk.get("matched_terms", []),
                "source": self._build_source(chunk),
            }

            citations.append(citation)

        logger.debug(f"[CitationBuilder] 生成了 {len(citations)} 个引用")

        return citations

    def _format_citation_id(self, index: int) -> str:
        """格式化引用 ID。

        Args:
            index: 引用序号（从 1 开始）

        Returns:
            格式化的引用 ID
        """

        if self.citation_format == "bracket":
            return f"[{index}]"
        elif self.citation_format == "numeric":
            return f"{index}."
        elif self.citation_format == "superscript":
            # 使用 Unicode 上标数字
            superscripts = ["⁰", "¹", "²", "³", "⁴", "⁵", "⁶", "⁷", "⁸", "⁹"]
            digits = []
            for d in str(index):
                if d.isdigit():
                    digits.append(superscripts[int(d)])
                else:
                    digits.append(d)
            return "[" + "".join(digits) + "]"
        else:
            return f"[{index}]"

    def _build_source(self, chunk: dict) -> str:
        """构建引用来源描述。

        Args:
            chunk: chunk 数据

        Returns:
            来源描述，如 "制度手册 - 第一章 总则 (第3页)"
        """

        parts = []

        # 文档类型
        chunk_type = chunk.get("chunk_type", "")
        if chunk_type == "table_parent" or chunk_type == "table_summary":
            parts.append("表格")
        elif chunk_type == "table_child":
            parts.append("表格片段")

        # 章节标题
        section_title = chunk.get("section_title") or chunk.get("metadata", {}).get("section_title")
        if section_title:
            parts.append(section_title)

        # 页码
        page_start = chunk.get("page_start")
        page_end = chunk.get("page_end")
        if page_start:
            if page_end and page_end != page_start:
                parts.append(f"第{page_start}-{page_end}页")
            else:
                parts.append(f"第{page_start}页")

        return " - ".join(parts) if parts else "未知来源"

    def insert_citations(self, answer: str, citations: list[dict]) -> str:
        """在答案中插入引用标记。

        当前实现为简单版本，直接在答案末尾添加引用列表。
        后续可以扩展为在答案中的适当位置插入引用标记。

        Args:
            answer: 原始答案
            citations: 引用列表

        Returns:
            带引用的答案
        """

        if not citations:
            return answer

        # 在答案末尾添加引用列表
        citation_lines = ["\n\n---\n**参考来源：**\n"]

        for cite in citations:
            source = cite.get("source", "")
            score_info = f"相关性: {cite.get('score', 0):.2%}"

            line = f"{cite['citation_id']} {source}"
            if cite.get("matched_terms"):
                terms = ", ".join(cite["matched_terms"][:5])
                line += f"（匹配词: {terms}）"
            line += f" [{score_info}]"

            citation_lines.append(line)

        return answer + "\n".join(citation_lines)

    def get_citation_id(self, chunk_uuid: str) -> str | None:
        """根据 chunk_uuid 获取引用 ID。

        Args:
            chunk_uuid: chunk 唯一标识

        Returns:
            引用 ID，如果不存在返回 None
        """

        return self._citation_map.get(chunk_uuid)

    def build_reference_list(self, citations: list[dict]) -> str:
        """构建引用参考列表（用于格式化输出）。

        Args:
            citations: 引用列表

        Returns:
            格式化后的引用列表
        """

        if not citations:
            return ""

        lines = []
        for i, cite in enumerate(citations, 1):
            # 来源
            source_parts = []

            # 文档 ID
            if cite.get("document_id"):
                source_parts.append(f"文档ID: {cite['document_id']}")

            # 章节
            if cite.get("section_title"):
                source_parts.append(f"章节: {cite['section_title']}")

            # 页码
            if cite.get("page_start"):
                if cite.get("page_end") and cite["page_end"] != cite["page_start"]:
                    source_parts.append(f"页码: {cite['page_start']}-{cite['page_end']}")
                else:
                    source_parts.append(f"页码: {cite['page_start']}")

            # chunk 类型
            if cite.get("chunk_type"):
                type_names = {
                    "parent_text": "正文",
                    "child_text": "正文片段",
                    "table_parent": "表格",
                    "table_summary": "表格摘要",
                    "table_child": "表格片段",
                }
                chunk_type_name = type_names.get(cite["chunk_type"], cite["chunk_type"])
                source_parts.append(f"类型: {chunk_type_name}")

            source_str = " | ".join(source_parts) if source_parts else "未知来源"

            # 相关性
            score = cite.get("score", 0.0)
            score_str = f"{score:.1%}"

            lines.append(
                f"{cite['citation_id']} {source_str} | 相关性: {score_str}"
            )

        return "\n".join(lines)
