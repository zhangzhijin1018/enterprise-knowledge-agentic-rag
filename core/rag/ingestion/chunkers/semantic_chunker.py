"""语义重叠切块器。

核心原理：
- 在固定窗口的基础上，增加语义完整性判断
- 优先在句子边界、段落边界切分
- 对于必须切分的情况，保留足够的语义上下文

优化效果：
- 减少语义割裂
- 提高检索命中的语义完整性
- 改善答案生成质量
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass
class SemanticChunk:
    """语义块。

    Attributes:
        content: 块内容
        start_pos: 起始位置
        end_pos: 结束位置
        sentences: 包含的句子数
        has_warning: 是否包含警告信息
        has_question: 是否包含疑问
    """

    content: str
    start_pos: int
    end_pos: int
    sentences: int = 0
    has_warning: bool = False
    has_question: bool = False

    def to_dict(self) -> dict[str, Any]:
        """转换为字典。"""
        return {
            "content": self.content,
            "start_pos": self.start_pos,
            "end_pos": self.end_pos,
            "sentences": self.sentences,
            "has_warning": self.has_warning,
            "has_question": self.has_question,
        }


class SemanticOverlapChunker:
    """语义重叠切块器。

    传统固定 overlap 的问题：
    - 在固定窗口边界处可能切断语义完整性
    - "第一章 总则\n第一条 为了加强XX管理..." 可能被切成 "...加强XX管理..."，
      丢失了"第一章 总则"这个重要上下文

    优化方案：语义重叠切块
    - 优先在句子边界、段落边界切分
    - 对于必须切分的情况，保留足够的语义上下文
    """

    # 中文句子边界符号
    CHINESE_SENTENCE_ENDINGS = "。！？；"
    # 英文句子边界符号
    ENGLISH_SENTENCE_ENDINGS = ".!?"
    # 段落分隔符
    PARAGRAPH_SEPARATORS = ["\n\n", "\r\n\r\n"]

    # 安全关键词（切分时需要保留）
    WARNING_KEYWORDS = [
        "注意", "警告", "严禁", "必须", "禁止",
        "危险", "紧急", "应急", "防护", "安全",
    ]

    def __init__(
        self,
        target_size: int = 500,
        overlap_size: int = 50,
        min_sentence_chars: int = 10,
        max_sentence_chars: int = 500,
    ):
        """初始化语义重叠切块器。

        Args:
            target_size: 目标块大小（字符数）
            overlap_size: 重叠大小（字符数）
            min_sentence_chars: 最小句子长度（过滤过短句子）
            max_sentence_chars: 最大句子长度（超过则强制切分）
        """
        self.target_size = target_size
        self.overlap_size = overlap_size
        self.min_sentence_chars = min_sentence_chars
        self.max_sentence_chars = max_sentence_chars

    def chunk(self, text: str) -> list[SemanticChunk]:
        """语义感知的重叠切块。

        Args:
            text: 待切分文本

        Returns:
            语义块列表
        """
        if not text or not text.strip():
            return []

        # 1. 句子分割
        sentences = self._split_into_sentences(text)

        if not sentences:
            # 如果没有识别到句子，用固定大小切分
            return self._chunk_by_fixed_size(text)

        # 2. 语义分组
        chunks = self._group_into_chunks(sentences, text)

        return chunks

    def _split_into_sentences(self, text: str) -> list[dict[str, Any]]:
        """智能句子分割。

        处理多种分隔符：
        - 中文句号：。！？；
        - 英文句号：. ! ?
        - 换行符：\n（作为段落分隔）
        """
        sentences = []
        current_sentence = ""
        current_start = 0

        i = 0
        while i < len(text):
            char = text[i]

            # 检查是否为句子结束符
            is_sentence_end = False
            is_paragraph_end = False

            if char in self.CHINESE_SENTENCE_ENDINGS:
                is_sentence_end = True
            elif char in self.ENGLISH_SENTENCE_ENDINGS:
                is_sentence_end = True
                # 英文句号需要检查是否为缩写
                if i > 0 and text[i - 1].isupper():
                    is_sentence_end = False

            # 检查是否为段落分隔
            if text[i:i + 2] in ["\n\n", "\r\n"]:
                is_paragraph_end = True

            # 添加当前字符
            current_sentence += char

            # 判断是否结束当前句子
            if is_sentence_end:
                end_pos = i + 1
                sentence_text = current_sentence.strip()

                # 过滤过短句子（合并到下一个）
                if len(sentence_text) >= self.min_sentence_chars:
                    # 检查是否包含警告关键词
                    has_warning = any(kw in sentence_text for kw in self.WARNING_KEYWORDS)
                    has_question = "？" in sentence_text or "?" in sentence_text

                    sentences.append({
                        "text": sentence_text,
                        "start": current_start,
                        "end": end_pos,
                        "has_warning": has_warning,
                        "has_question": has_question,
                        "length": len(sentence_text),
                    })

                current_sentence = ""
                current_start = end_pos

            elif is_paragraph_end:
                # 段落分隔作为软边界
                if current_sentence.strip():
                    end_pos = i + 2
                    sentence_text = current_sentence.strip()

                    if len(sentence_text) >= self.min_sentence_chars:
                        has_warning = any(kw in sentence_text for kw in self.WARNING_KEYWORDS)
                        has_question = "？" in sentence_text or "?" in sentence_text

                        sentences.append({
                            "text": sentence_text,
                            "start": current_start,
                            "end": end_pos,
                            "has_warning": has_warning,
                            "has_question": has_question,
                            "length": len(sentence_text),
                            "is_paragraph": True,
                        })

                    current_sentence = ""
                    current_start = end_pos

            # 检查超长句子（强制切分）
            if len(current_sentence) > self.max_sentence_chars:
                end_pos = i + 1
                sentences.append({
                    "text": current_sentence.strip(),
                    "start": current_start,
                    "end": end_pos,
                    "has_warning": any(kw in current_sentence for kw in self.WARNING_KEYWORDS),
                    "has_question": "？" in current_sentence or "?" in current_sentence,
                    "length": len(current_sentence),
                    "forced_split": True,
                })
                current_sentence = ""
                current_start = end_pos

            i += 1

        # 处理剩余文本
        if current_sentence.strip():
            sentences.append({
                "text": current_sentence.strip(),
                "start": current_start,
                "end": len(text),
                "has_warning": any(kw in current_sentence for kw in self.WARNING_KEYWORDS),
                "has_question": "？" in current_sentence or "?" in current_sentence,
                "length": len(current_sentence.strip()),
            })

        return sentences

    def _group_into_chunks(
        self,
        sentences: list[dict[str, Any]],
        original_text: str,
    ) -> list[SemanticChunk]:
        """将句子分组为语义块。

        Args:
            sentences: 句子列表
            original_text: 原始文本（用于计算重叠）

        Returns:
            语义块列表
        """
        chunks = []
        current_group = []
        current_size = 0
        group_start = 0

        for sentence in sentences:
            sentence_text = sentence["text"]
            sentence_len = sentence["length"]
            has_warning = sentence.get("has_warning", False)

            # 判断是否需要开始新块
            should_start_new = False

            # 情况1：当前组加上这个句子会超过目标大小
            if current_size + sentence_len > self.target_size and current_group:
                should_start_new = True

            # 情况2：段落边界（软切分点）
            elif sentence.get("is_paragraph") and current_size > self.target_size * 0.5:
                should_start_new = True

            # 情况3：包含警告关键词，需要延展
            elif has_warning and current_size + sentence_len > self.target_size * 0.8:
                # 尝试在警告关键词处切分上一个块
                if current_group and not current_group[-1].get("has_warning"):
                    should_start_new = True

            if should_start_new:
                # 创建当前块
                chunk = self._create_chunk(current_group, original_text, group_start)
                chunks.append(chunk)

                # 计算重叠部分
                overlap_text = self._calculate_overlap(
                    chunk.content,
                    original_text,
                )

                # 开始新组
                current_group = [sentence]
                current_size = sentence_len
                group_start = sentence["start"]

                # 如果有重叠文本，加入新组
                if overlap_text:
                    current_group.insert(0, {
                        "text": overlap_text,
                        "start": max(0, chunk.end_pos - len(overlap_text)),
                        "end": chunk.end_pos,
                    })
                    current_size += len(overlap_text)
            else:
                current_group.append(sentence)
                current_size += sentence_len

        # 处理最后一个组
        if current_group:
            chunk = self._create_chunk(current_group, original_text, group_start)
            chunks.append(chunk)

        return chunks

    def _create_chunk(
        self,
        sentences: list[dict[str, Any]],
        original_text: str,
        start_offset: int,
    ) -> SemanticChunk:
        """创建语义块。

        Args:
            sentences: 句子列表
            original_text: 原始文本
            start_offset: 起始偏移

        Returns:
            语义块
        """
        if not sentences:
            return SemanticChunk(
                content="",
                start_pos=0,
                end_pos=0,
            )

        # 拼接内容
        content = "".join(s["text"] for s in sentences)

        # 计算位置
        start_pos = sentences[0]["start"]
        end_pos = sentences[-1]["end"]

        # 统计信息
        has_warning = any(s.get("has_warning", False) for s in sentences)
        has_question = any(s.get("has_question", False) for s in sentences)
        sentence_count = len(sentences)

        return SemanticChunk(
            content=content,
            start_pos=start_pos,
            end_pos=end_pos,
            sentences=sentence_count,
            has_warning=has_warning,
            has_question=has_question,
        )

    def _calculate_overlap(
        self,
        prev_content: str,
        original_text: str,
    ) -> str:
        """计算重叠部分。

        从上一个块的末尾提取重叠上下文，确保语义连贯。

        Args:
            prev_content: 上一个块的内容
            original_text: 原始文本

        Returns:
            重叠文本
        """
        if not prev_content or not original_text:
            return ""

        # 从上一个块末尾取重叠大小的文本
        overlap_chars = prev_content[-self.overlap_size:] if len(prev_content) >= self.overlap_size else prev_content

        # 尝试找到一个好的切分点（句子边界或逗号）
        for i in range(len(overlap_chars) - 1, -1, -1):
            char = overlap_chars[i]
            if char in "。！？；,\n":
                # 在这里切分，保留后半部分作为重叠
                return overlap_chars[i + 1:]

        return overlap_chars

    def _chunk_by_fixed_size(self, text: str) -> list[SemanticChunk]:
        """固定大小切分（回退方案）。

        当无法进行语义切分时使用。

        Args:
            text: 文本

        Returns:
            语义块列表
        """
        chunks = []
        start = 0
        index = 0

        while start < len(text):
            end = start + self.target_size
            chunk_text = text[start:end]

            chunks.append(SemanticChunk(
                content=chunk_text,
                start_pos=start,
                end_pos=end,
            ))

            index += 1
            start = end - self.overlap_size
            if start >= len(text):
                break

        return chunks


class HybridChunker:
    """混合切块器。

    结合文档类型感知切块和语义重叠切块的优点：
    - 先用文档类型感知切块识别文档结构
    - 再用语义重叠切块优化边界
    """

    def __init__(
        self,
        document_chunker: DocumentTypeAwareChunker,
        semantic_chunker: SemanticOverlapChunker,
    ):
        """初始化混合切块器。

        Args:
            document_chunker: 文档类型感知切块器
            semantic_chunker: 语义重叠切块器
        """
        self.document_chunker = document_chunker
        self.semantic_chunker = semantic_chunker

    def chunk(
        self,
        text: str,
        document_type: str | None = None,
    ) -> list[dict[str, Any]]:
        """执行混合切块。

        Args:
            text: 待切分文本
            document_type: 文档类型

        Returns:
            块列表
        """
        # Step 1: 文档类型感知切块
        doc_chunks = self.document_chunker.chunk(
            text,
            document_type=document_type,
            return_parent_child=True,
        )

        # Step 2: 对每个块应用语义重叠优化
        result = []
        for chunk in doc_chunks:
            # 如果是父块，直接添加
            if chunk.chunk_type == "parent":
                result.append(chunk.to_dict())
            else:
                # 子块应用语义重叠切分
                semantic_chunks = self.semantic_chunker.chunk(chunk.content)
                for i, sem_chunk in enumerate(semantic_chunks):
                    chunk_dict = chunk.to_dict()
                    chunk_dict.update({
                        "content": sem_chunk.content,
                        "start_pos": sem_chunk.start_pos,
                        "end_pos": sem_chunk.end_pos,
                        "position_index": chunk.position_index * 100 + i,
                        "semantic_has_warning": sem_chunk.has_warning,
                        "semantic_has_question": sem_chunk.has_question,
                    })
                    result.append(chunk_dict)

        return result


# 导入 DocumentTypeAwareChunker（用于混合切块器）
from core.rag.ingestion.chunkers.document_chunker import DocumentTypeAwareChunker
