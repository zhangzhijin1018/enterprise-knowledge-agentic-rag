"""文档类型感知的智能切块器。

核心设计理念：
- 不同业务文档有不同的结构特征和语义边界
- 制度文档：按"章-节-条"层级切分，保证条款完整性
- 合同文档：按"章节-条款-子条款"切分，保证法律语义
- 报告文档：按"章节-段落-图表"切分，保持叙事连贯
- 设备手册：按"章节-步骤-注意事项"切分，保证操作完整性
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ChunkResult:
    """切块结果。

    Attributes:
        content: 块内容
        chunk_type: 块类型（parent/child）
        position_index: 位置索引
        document_type: 文档类型
        metadata: 元数据（标题、层级、关键词等）
    """

    content: str
    chunk_type: str  # "parent" | "child"
    position_index: int
    document_type: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """转换为字典格式。"""
        return {
            "content": self.content,
            "chunk_type": self.chunk_type,
            "position_index": self.position_index,
            "document_type": self.document_type,
            "metadata": self.metadata,
        }


class DocumentTypeAwareChunker:
    """文档类型感知的智能切块器。

    能源集团典型文档类型及其切块策略：

    | 文档类型 | 父块策略 | 目标大小 | 子块策略 | 目标大小 |
    |----------|----------|----------|----------|----------|
    | policy   | 语义层级 | 800      | 条款边界 | 300      |
    | safety   | 流程导向 | 600      | 步骤保持 | 250      |
    | contract | 法律条款 | 500      | 子条款   | 200      |
    | equipment| 操作步骤 | 700      | 参数保持 | 350      |
    | report   | 章节分析 | 900      | 图表绑定 | 400      |
    """

    # 能源集团典型文档类型及其切块策略
    CHUNKING_STRATEGIES = {
        # 制度政策类：强调条款完整性和层级结构
        "policy": {
            "parent_strategy": "semantic_hierarchy",  # 语义层级切块
            "parent_target": 800,
            "parent_max": 1200,
            "child_strategy": "clause_boundary",  # 条款边界切块
            "child_target": 300,
            "child_overlap": 50,
            "preserve_structure": True,  # 保留层级结构
            "min_clause_length": 50,  # 最小条款长度
            "structure_markers": [  # 结构标记（标题层级）
                r"第[一二三四五六七八九十百千\d]+章",
                r"第[一二三四五六七八九十百千\d]+节",
                r"第[一二三四五六七八九十百千\d]+条",
                r"^\d+\.\d+",  # 1.1 格式
            ],
        },

        # 安全生产类：强调操作步骤和风险提示的完整性
        "safety": {
            "parent_strategy": "procedure_oriented",  # 流程导向切块
            "parent_target": 600,
            "parent_max": 1000,
            "child_strategy": "step_preserving",  # 步骤保持切块
            "child_target": 250,
            "child_overlap": 40,
            "safety_keywords": [  # 安全关键词保留
                "必须", "严禁", "禁止", "注意", "警告",
                "危险", "紧急", "应急", "防护", "安全",
            ],
            "step_markers": [  # 步骤标记
                r"^\d+[.、]",
                r"^第[一二三四五六七八九十\d]+步",
                r"^步骤\d+",
            ],
        },

        # 合同协议类：强调法律条款的完整性和可引用性
        "contract": {
            "parent_strategy": "legal_clause",  # 法律条款切块
            "parent_target": 500,
            "parent_max": 800,
            "child_strategy": "sub_clause",  # 子条款切块
            "child_target": 200,
            "child_overlap": 30,
            "preserve_clause_numbers": True,  # 保留条款编号
            "key_terms": [  # 关键法律术语
                "甲方", "乙方", "违约", "责任", "赔偿",
                "解除", "终止", "变更", "效力", "争议",
            ],
            "clause_markers": [  # 条款标记
                r"第[一二三四五六七八九十百千\d]+条",
                r"^\d+\.",
                r"^[（\(]\d+[）\)]",  # (1) 格式
            ],
        },

        # 设备检修类：强调操作步骤和参数的完整性
        "equipment": {
            "parent_strategy": "operation_step",  # 操作步骤切块
            "parent_target": 700,
            "parent_max": 1100,
            "child_strategy": "parameter_preserving",  # 参数保持切块
            "child_target": 350,
            "child_overlap": 60,
            "parameter_patterns": [  # 参数识别模式
                r"\d+\.\d+",  # 小数
                r"\d+kV",  # 电压
                r"\d+A",  # 电流
                r"\d+℃",  # 温度
                r"\d+MW",  # 功率
            ],
            "section_markers": [  # 章节标记
                r"^\d+\.\d+\s",
                r"^[一二三四五六七八九十]+、",
            ],
        },

        # 经营分析类：强调数据表格和分析结论的关联
        "report": {
            "parent_strategy": "section_analysis",  # 章节分析切块
            "parent_target": 900,
            "parent_max": 1500,
            "child_strategy": "chart_paragraph_binding",  # 图表段落绑定
            "child_target": 400,
            "child_overlap": 80,
            "table_context_window": 200,  # 表格上下文窗口
            "analysis_markers": [  # 分析标记
                r"^\d+\.\d+\s",
                r"^[一二三四五六七八九十]+、",
                r"^表\d+",
                r"^图\d+",
            ],
        },

        # 通用文档类型（默认策略）
        "general": {
            "parent_strategy": "fixed_size",
            "parent_target": 500,
            "parent_max": 800,
            "child_strategy": "fixed_size",
            "child_target": 250,
            "child_overlap": 50,
        },
    }

    def __init__(self, default_document_type: str = "general"):
        """初始化切块器。

        Args:
            default_document_type: 默认文档类型
        """
        self.default_document_type = default_document_type

    def chunk(
        self,
        text: str,
        document_type: str | None = None,
        return_parent_child: bool = True,
    ) -> list[ChunkResult]:
        """执行文档切块。

        Args:
            text: 待切分文档内容
            document_type: 文档类型（policy/safety/contract/equipment/report/general）
            return_parent_child: 是否返回父子块结构

        Returns:
            切块结果列表
        """
        doc_type = document_type or self.default_document_type
        strategy = self.CHUNKING_STRATEGIES.get(
            doc_type,
            self.CHUNKING_STRATEGIES["general"]
        )

        # Step 1: 识别文档结构
        structure = self._analyze_document_structure(text, strategy)

        # Step 2: 生成子块
        child_chunks = self._generate_child_chunks(text, structure, strategy)

        if not return_parent_child:
            return child_chunks

        # Step 3: 生成父块（通过子块聚合）
        parent_chunks = self._generate_parent_chunks(child_chunks, strategy)

        # 合并父子块
        return parent_chunks + child_chunks

    def _analyze_document_structure(
        self,
        text: str,
        strategy: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """分析文档结构，识别标题层级。

        Args:
            text: 文档文本
            strategy: 切块策略

        Returns:
            结构化段落列表
        """
        # 按换行分割段落
        lines = text.split("\n")
        paragraphs = []
        current_section = {"level": 0, "title": ""}
        current_content = []

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # 检查是否为标题行
            is_title, level = self._is_heading(line, strategy)

            if is_title:
                # 保存之前的段落
                if current_content:
                    paragraphs.append({
                        "content": "\n".join(current_content),
                        "section": current_section.copy(),
                    })
                    current_content = []

                # 更新当前章节
                current_section = {"level": level, "title": line}
            else:
                current_content.append(line)

        # 保存最后一个段落
        if current_content:
            paragraphs.append({
                "content": "\n".join(current_content),
                "section": current_section.copy(),
            })

        return paragraphs

    def _is_heading(self, line: str, strategy: dict[str, Any]) -> tuple[bool, int]:
        """判断是否为标题行。

        Args:
            line: 文本行
            strategy: 切块策略

        Returns:
            (是否为标题, 标题级别)
        """
        # 获取该文档类型的结构标记
        markers = strategy.get("structure_markers", [])

        # 如果有通用标记
        if not markers:
            # 默认：纯数字开头的行视为标题
            if re.match(r"^\d+\.", line) and len(line) < 50:
                return True, 1

        # 检查是否匹配结构标记
        for i, marker_pattern in enumerate(markers):
            if re.search(marker_pattern, line):
                return True, i + 1

        return False, 0

    def _generate_child_chunks(
        self,
        text: str,
        structure: list[dict[str, Any]],
        strategy: dict[str, Any],
    ) -> list[ChunkResult]:
        """生成子块。

        Args:
            text: 文档文本
            structure: 文档结构
            strategy: 切块策略

        Returns:
            子块列表
        """
        child_strategy = strategy.get("child_strategy", "fixed_size")
        child_target = strategy.get("child_target", 250)
        child_overlap = strategy.get("child_overlap", 50)

        if child_strategy == "clause_boundary":
            return self._chunk_by_clause_boundary(text, strategy)
        elif child_strategy == "step_preserving":
            return self._chunk_by_step_preserving(text, strategy)
        elif child_strategy == "sub_clause":
            return self._chunk_by_sub_clause(text, strategy)
        elif child_strategy == "parameter_preserving":
            return self._chunk_by_parameter_preserving(text, strategy)
        elif child_strategy == "chart_paragraph_binding":
            return self._chunk_by_chart_paragraph_binding(text, strategy)
        else:
            return self._chunk_by_fixed_size(text, child_target, child_overlap, strategy)

    def _chunk_by_clause_boundary(
        self,
        text: str,
        strategy: dict[str, Any],
    ) -> list[ChunkResult]:
        """按条款边界切块（制度政策类）。

        识别"第X条"等条款标记，在条款边界处切分。
        """
        chunks = []
        position = 0
        doc_type = strategy.get("document_type", "policy")

        # 条款边界正则
        clause_pattern = r"第[一二三四五六七八九十百千\d]+条"

        # 分割文本
        parts = re.split(f"({clause_pattern})", text)

        current_chunk = ""
        for part in parts:
            part = part.strip()
            if not part:
                continue

            # 检查是否为条款标记
            if re.match(clause_pattern, part):
                # 保存当前块（如果不为空）
                if current_chunk:
                    chunks.append(ChunkResult(
                        content=current_chunk.strip(),
                        chunk_type="child",
                        position_index=position,
                        document_type=doc_type,
                        metadata={"clause_mark": part},
                    ))
                    position += 1
                    current_chunk = ""

                current_chunk = part + " "
            else:
                current_chunk += part + " "

                # 检查是否达到目标大小
                if len(current_chunk) >= strategy.get("child_target", 300):
                    chunks.append(ChunkResult(
                        content=current_chunk.strip(),
                        chunk_type="child",
                        position_index=position,
                        document_type=doc_type,
                    ))
                    position += 1
                    current_chunk = ""

        # 保存最后一个块
        if current_chunk.strip():
            chunks.append(ChunkResult(
                content=current_chunk.strip(),
                chunk_type="child",
                position_index=position,
                document_type=doc_type,
            ))

        return chunks

    def _chunk_by_step_preserving(
        self,
        text: str,
        strategy: dict[str, Any],
    ) -> list[ChunkResult]:
        """按步骤保持切块（安全生产类）。

        优先在步骤边界处切分，并保留安全关键词。
        """
        chunks = []
        position = 0
        doc_type = strategy.get("document_type", "safety")
        safety_keywords = strategy.get("safety_keywords", [])

        # 步骤标记
        step_pattern = r"(^\d+[.、]|^第[一二三四五六七八九十\d]+步|步骤\d+[:：])"

        # 分割文本
        lines = text.split("\n")
        current_chunk = []
        current_chunk_size = 0
        target_size = strategy.get("child_target", 250)

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # 检查是否为步骤开始
            is_step = re.search(step_pattern, line)

            # 计算当前行大小
            line_size = len(line)

            # 检查安全关键词（需要保留到下一块）
            has_safety_keyword = any(kw in line for kw in safety_keywords)

            # 判断是否需要切分
            should_split = False
            if is_step and current_chunk_size > target_size * 0.5:
                should_split = True
            elif current_chunk_size + line_size > target_size:
                should_split = True

            if should_split and current_chunk:
                # 保存当前块
                chunk_content = "\n".join(current_chunk)

                # 如果包含安全关键词，延展到下一个块
                if has_safety_keyword:
                    # 标记需要延展
                    pass

                chunks.append(ChunkResult(
                    content=chunk_content,
                    chunk_type="child",
                    position_index=position,
                    document_type=doc_type,
                    metadata={"has_safety_keyword": has_safety_keyword},
                ))
                position += 1
                current_chunk = []
                current_chunk_size = 0

            current_chunk.append(line)
            current_chunk_size += line_size

        # 保存最后一个块
        if current_chunk:
            chunks.append(ChunkResult(
                content="\n".join(current_chunk),
                chunk_type="child",
                position_index=position,
                document_type=doc_type,
            ))

        return chunks

    def _chunk_by_sub_clause(
        self,
        text: str,
        strategy: dict[str, Any],
    ) -> list[ChunkResult]:
        """按子条款切块（合同协议类）。

        识别"(1)"、"(2)"等子条款标记，保持法律条款完整性。
        """
        chunks = []
        position = 0
        doc_type = strategy.get("document_type", "contract")

        # 子条款标记：数字编号、括号编号
        sub_clause_pattern = r"^(\d+\.|\([一二三四五六七八九十\d]+\)|[（\(]\d+[）\)])"

        lines = text.split("\n")
        current_chunk = []
        current_chunk_size = 0
        target_size = strategy.get("child_target", 200)

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # 检查是否为子条款开始
            is_sub_clause = re.match(sub_clause_pattern, line)

            # 判断是否需要切分
            if is_sub_clause and current_chunk_size > target_size * 0.5:
                # 保存当前块
                chunks.append(ChunkResult(
                    content="\n".join(current_chunk),
                    chunk_type="child",
                    position_index=position,
                    document_type=doc_type,
                ))
                position += 1
                current_chunk = []
                current_chunk_size = 0

            current_chunk.append(line)
            current_chunk_size += len(line)

        # 保存最后一个块
        if current_chunk:
            chunks.append(ChunkResult(
                content="\n".join(current_chunk),
                chunk_type="child",
                position_index=position,
                document_type=doc_type,
            ))

        return chunks

    def _chunk_by_parameter_preserving(
        self,
        text: str,
        strategy: dict[str, Any],
    ) -> list[ChunkResult]:
        """按参数保持切块（设备检修类）。

        确保技术参数（电压、电流、温度等）不被切断。
        """
        chunks = []
        position = 0
        doc_type = strategy.get("document_type", "equipment")
        param_patterns = strategy.get("parameter_patterns", [])

        lines = text.split("\n")
        current_chunk = []
        current_chunk_size = 0
        target_size = strategy.get("child_target", 350)

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # 检查是否包含技术参数
            has_param = any(re.search(p, line) for p in param_patterns)
            line_size = len(line)

            # 如果当前块快超大小，但当前行包含参数，需要延展
            if current_chunk_size + line_size > target_size and has_param:
                # 先保存当前块
                if current_chunk:
                    chunks.append(ChunkResult(
                        content="\n".join(current_chunk),
                        chunk_type="child",
                        position_index=position,
                        document_type=doc_type,
                    ))
                    position += 1
                    current_chunk = []
                    current_chunk_size = 0

            current_chunk.append(line)
            current_chunk_size += line_size

            # 如果超过最大大小，强制切分
            if current_chunk_size > target_size * 1.2:
                chunks.append(ChunkResult(
                    content="\n".join(current_chunk),
                    chunk_type="child",
                    position_index=position,
                    document_type=doc_type,
                ))
                position += 1
                current_chunk = []
                current_chunk_size = 0

        # 保存最后一个块
        if current_chunk:
            chunks.append(ChunkResult(
                content="\n".join(current_chunk),
                chunk_type="child",
                position_index=position,
                document_type=doc_type,
            ))

        return chunks

    def _chunk_by_chart_paragraph_binding(
        self,
        text: str,
        strategy: dict[str, Any],
    ) -> list[ChunkResult]:
        """按图表段落绑定切块（经营分析类）。

        将表格与相邻分析段落绑定，保持数据与结论的关联。
        """
        chunks = []
        position = 0
        doc_type = strategy.get("document_type", "report")

        lines = text.split("\n")
        current_chunk = []
        current_chunk_size = 0
        target_size = strategy.get("child_target", 400)
        context_window = strategy.get("table_context_window", 200)

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # 检查是否为表格行（包含多个分隔符）
            is_table_row = len(re.findall(r"[|\t]", line)) >= 2

            # 检查是否为图表标题
            is_chart_title = re.match(r"^(表|图)\d+", line)

            # 计算行大小
            line_size = len(line)

            # 判断是否需要切分
            if is_chart_title:
                # 图表标题单独成块
                if current_chunk:
                    chunks.append(ChunkResult(
                        content="\n".join(current_chunk),
                        chunk_type="child",
                        position_index=position,
                        document_type=doc_type,
                    ))
                    position += 1
                    current_chunk = []
                    current_chunk_size = 0

                current_chunk.append(line)
                chunks.append(ChunkResult(
                    content=line,
                    chunk_type="child",
                    position_index=position,
                    document_type=doc_type,
                    metadata={"chart_title": line},
                ))
                position += 1
                current_chunk = []
                current_chunk_size = 0
            elif current_chunk_size + line_size > target_size:
                # 保存当前块
                chunks.append(ChunkResult(
                    content="\n".join(current_chunk),
                    chunk_type="child",
                    position_index=position,
                    document_type=doc_type,
                ))
                position += 1
                current_chunk = []
                current_chunk_size = 0
                current_chunk.append(line)
                current_chunk_size = line_size
            else:
                current_chunk.append(line)
                current_chunk_size += line_size

        # 保存最后一个块
        if current_chunk:
            chunks.append(ChunkResult(
                content="\n".join(current_chunk),
                chunk_type="child",
                position_index=position,
                document_type=doc_type,
            ))

        return chunks

    def _chunk_by_fixed_size(
        self,
        text: str,
        target_size: int,
        overlap_size: int,
        strategy: dict[str, Any],
    ) -> list[ChunkResult]:
        """固定大小切块（默认策略）。

        Args:
            text: 文档文本
            target_size: 目标块大小
            overlap_size: 重叠大小
            strategy: 切块策略

        Returns:
            块列表
        """
        chunks = []
        position = 0
        doc_type = strategy.get("document_type", "general")

        start = 0
        while start < len(text):
            end = start + target_size
            chunk_text = text[start:end]

            chunks.append(ChunkResult(
                content=chunk_text,
                chunk_type="child",
                position_index=position,
                document_type=doc_type,
            ))

            position += 1
            start = end - overlap_size  # 下一个块从重叠处开始
            if start >= len(text):
                break

        return chunks

    def _generate_parent_chunks(
        self,
        child_chunks: list[ChunkResult],
        strategy: dict[str, Any],
    ) -> list[ChunkResult]:
        """生成父块（通过子块聚合）。

        将多个子块聚合为一个父块，用于检索。

        Args:
            child_chunks: 子块列表
            strategy: 切块策略

        Returns:
            父块列表
        """
        parent_chunks = []
        parent_target = strategy.get("parent_target", 500)
        parent_max = strategy.get("parent_max", 800)
        doc_type = strategy.get("document_type", "general")

        current_group = []
        current_size = 0
        position = 0

        for child in child_chunks:
            child_size = len(child.content)

            # 如果加入当前子块会超过最大大小，先保存当前组
            if current_size + child_size > parent_max and current_group:
                parent_content = "\n".join([c.content for c in current_group])
                parent_chunks.append(ChunkResult(
                    content=parent_content,
                    chunk_type="parent",
                    position_index=position,
                    document_type=doc_type,
                    metadata={
                        "child_count": len(current_group),
                        "child_ids": [f"child_{c.position_index}" for c in current_group],
                    },
                ))
                position += 1
                current_group = []
                current_size = 0

            current_group.append(child)
            current_size += child_size

        # 保存最后一个组
        if current_group:
            parent_content = "\n".join([c.content for c in current_group])
            parent_chunks.append(ChunkResult(
                content=parent_content,
                chunk_type="parent",
                position_index=position,
                document_type=doc_type,
                metadata={
                    "child_count": len(current_group),
                    "child_ids": [f"child_{c.position_index}" for c in current_group],
                },
            ))

        return parent_chunks
