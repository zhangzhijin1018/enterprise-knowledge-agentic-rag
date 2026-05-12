"""Chunk 变化检测器。

核心问题：如何判断哪些 chunk 需要更新？

判断逻辑：
1. 两个 chunk 如果 position_index 相同且内容相同 → 不变，跳过
2. 两个 chunk 如果 position_index 相同但内容不同 → 修改，更新
3. 新文档的某个 position_index 在旧文档中没有 → 新增，插入
4. 旧文档的某个 position_index 在新文档中没有 → 删除，移除

关键点：
- 必须使用相同的分块策略（新旧文档分块逻辑要一致）
- 父子块关系要同步更新
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ChunkChange:
    """Chunk 变化结果。

    Attributes:
        chunk_id: Chunk ID
        position_index: 位置索引
        change_type: 变化类型（unchanged/modified/new/deleted）
        content: 块内容
        content_hash: 内容哈希
    """

    chunk_id: str
    position_index: int
    change_type: str  # "unchanged" | "modified" | "new" | "deleted"
    content: str = ""
    content_hash: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ChangeDetectionResult:
    """变化检测结果。

    Attributes:
        unchanged: 未变化的 chunks
        modified: 修改的 chunks
        new: 新增的 chunks
        deleted: 删除的 chunks
        summary: 统计摘要
    """

    unchanged: list[ChunkChange] = field(default_factory=list)
    modified: list[ChunkChange] = field(default_factory=list)
    new: list[ChunkChange] = field(default_factory=list)
    deleted: list[ChunkChange] = field(default_factory=list)

    @property
    def summary(self) -> dict[str, int]:
        """统计摘要。"""
        return {
            "total_old": len(self.unchanged) + len(self.modified) + len(self.deleted),
            "total_new": len(self.unchanged) + len(self.modified) + len(self.new),
            "unchanged_count": len(self.unchanged),
            "modified_count": len(self.modified),
            "new_count": len(self.new),
            "deleted_count": len(self.deleted),
        }

    def to_dict(self) -> dict[str, Any]:
        """转换为字典。"""
        return {
            "unchanged": [c.__dict__ for c in self.unchanged],
            "modified": [c.__dict__ for c in self.modified],
            "new": [c.__dict__ for c in self.new],
            "deleted": [c.__dict__ for c in self.deleted],
            "summary": self.summary,
        }


class ChunkChangeDetector:
    """Chunk 变化检测器。

    核心功能：
    1. 比较新旧文档的 chunks
    2. 标记变化类型：新增/修改/删除/不变
    3. 使用 position_index + content_hash 进行比较

    使用场景：
    - 文档增量更新：只更新变化的部分
    - 版本对比：查看文档变更历史
    - 数据同步：多系统间的 chunk 同步
    """

    def __init__(
        self,
        chunk_size: int = 500,
        chunk_overlap: int = 50,
        hash_algorithm: str = "md5",
    ):
        """初始化变化检测器。

        Args:
            chunk_size: 分块大小
            chunk_overlap: 重叠大小
            hash_algorithm: 哈希算法（md5/sha256）
        """
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.hash_algorithm = hash_algorithm

    def detect_changes(
        self,
        old_chunks: list[dict[str, Any]],
        new_document_text: str,
    ) -> ChangeDetectionResult:
        """检测 chunk 变化。

        Args:
            old_chunks: 旧版 chunks（从 PostgreSQL 查询）
            new_document_text: 新版文档全文

        Returns:
            变化检测结果
        """
        if not old_chunks:
            # 没有旧 chunks，全部是新增
            new_chunks = self._chunk_document(new_document_text)
            result = ChangeDetectionResult()
            for chunk in new_chunks:
                result.new.append(ChunkChange(
                    chunk_id=chunk["chunk_id"],
                    position_index=chunk["position_index"],
                    change_type="new",
                    content=chunk["content"],
                    content_hash=chunk["content_hash"],
                ))
            return result

        # Step 1：用相同策略对新文档分块
        new_chunks = self._chunk_document(new_document_text)

        # Step 2：构建旧 chunk 的索引
        old_chunk_map = {
            chunk["position_index"]: chunk
            for chunk in old_chunks
        }

        # Step 3：逐个比较
        result = ChangeDetectionResult()
        new_chunk_positions = set()

        for new_chunk in new_chunks:
            pos = new_chunk["position_index"]
            new_chunk_positions.add(pos)

            if pos not in old_chunk_map:
                # 新文档有，旧文档没有 → 新增
                result.new.append(ChunkChange(
                    chunk_id=new_chunk["chunk_id"],
                    position_index=pos,
                    change_type="new",
                    content=new_chunk["content"],
                    content_hash=new_chunk["content_hash"],
                ))
            else:
                # 新旧文档都有，比较内容
                old_chunk = old_chunk_map[pos]
                if self._is_content_changed(old_chunk, new_chunk):
                    # 内容变了 → 修改
                    result.modified.append(ChunkChange(
                        chunk_id=old_chunk.get("chunk_id", new_chunk["chunk_id"]),
                        position_index=pos,
                        change_type="modified",
                        content=new_chunk["content"],
                        content_hash=new_chunk["content_hash"],
                        metadata={"old_content_hash": old_chunk.get("content_hash")},
                    ))
                else:
                    # 内容没变 → 不变
                    result.unchanged.append(ChunkChange(
                        chunk_id=old_chunk.get("chunk_id", ""),
                        position_index=pos,
                        change_type="unchanged",
                        content=new_chunk["content"],
                        content_hash=new_chunk["content_hash"],
                    ))

        # Step 4：找出需要删除的
        for old_chunk in old_chunks:
            pos = old_chunk["position_index"]
            if pos not in new_chunk_positions:
                result.deleted.append(ChunkChange(
                    chunk_id=old_chunk.get("chunk_id", ""),
                    position_index=pos,
                    change_type="deleted",
                    content=old_chunk.get("content", ""),
                    content_hash=old_chunk.get("content_hash", ""),
                ))

        return result

    def _chunk_document(self, text: str) -> list[dict[str, Any]]:
        """对文档进行分块（与首次入库时相同的逻辑）。

        关键：必须使用相同的 chunk_size 和 chunk_overlap。
        """
        chunks = []
        start = 0
        position = 0

        while start < len(text):
            end = start + self.chunk_size
            chunk_text = text[start:end]

            if not chunk_text.strip():
                break

            # 生成 chunk ID（用内容哈希，保证幂等性）
            chunk_hash = self._compute_hash(
                f"{text[:50]}:{position}:{chunk_text}".encode()
            )

            chunks.append({
                "chunk_id": f"chunk_{position}_{chunk_hash[:12]}",
                "position_index": position,
                "content": chunk_text,
                "content_hash": self._compute_hash(chunk_text.encode()),
                "char_count": len(chunk_text),
            })

            # 移动位置（考虑重叠）
            start = start + self.chunk_size - self.chunk_overlap
            if start >= len(text):
                break
            position += 1

        return chunks

    def _compute_hash(self, data: bytes) -> str:
        """计算内容哈希。

        Args:
            data: 字节数据

        Returns:
            哈希值
        """
        if self.hash_algorithm == "md5":
            return hashlib.md5(data).hexdigest()
        elif self.hash_algorithm == "sha256":
            return hashlib.sha256(data).hexdigest()
        else:
            return hashlib.md5(data).hexdigest()

    def _is_content_changed(
        self,
        old_chunk: dict[str, Any],
        new_chunk: dict[str, Any],
    ) -> bool:
        """判断 chunk 内容是否变化。

        Args:
            old_chunk: 旧 chunk
            new_chunk: 新 chunk

        Returns:
            是否变化
        """
        # 方法1：直接比较哈希（最快）
        old_hash = old_chunk.get("content_hash", "")
        new_hash = new_chunk.get("content_hash", "")

        if old_hash and new_hash:
            return old_hash != new_hash

        # 方法2：比较内容
        old_content = old_chunk.get("content", "")
        new_content = new_chunk.get("content", "")

        return old_content != new_content

    def detect_changes_by_comparison(
        self,
        old_chunks: list[dict[str, Any]],
        new_chunks: list[dict[str, Any]],
    ) -> ChangeDetectionResult:
        """直接比较新旧 chunks（不重新分块）。

        用于：
        - 已经分好块的文档比较
        - 不同分块策略的文档比较

        Args:
            old_chunks: 旧 chunks
            new_chunks: 新 chunks

        Returns:
            变化检测结果
        """
        old_chunk_map = {c["position_index"]: c for c in old_chunks}
        new_chunk_map = {c["position_index"]: c for c in new_chunks}

        result = ChangeDetectionResult()

        # 遍历新的，找变化
        for new_chunk in new_chunks:
            pos = new_chunk["position_index"]
            if pos not in old_chunk_map:
                result.new.append(ChunkChange(
                    chunk_id=new_chunk.get("chunk_id", ""),
                    position_index=pos,
                    change_type="new",
                    content=new_chunk.get("content", ""),
                    content_hash=new_chunk.get("content_hash", ""),
                ))
            elif self._is_content_changed(old_chunk_map[pos], new_chunk):
                result.modified.append(ChunkChange(
                    chunk_id=old_chunk_map[pos].get("chunk_id", ""),
                    position_index=pos,
                    change_type="modified",
                    content=new_chunk.get("content", ""),
                    content_hash=new_chunk.get("content_hash", ""),
                ))
            else:
                result.unchanged.append(ChunkChange(
                    chunk_id=old_chunk_map[pos].get("chunk_id", ""),
                    position_index=pos,
                    change_type="unchanged",
                    content=new_chunk.get("content", ""),
                    content_hash=new_chunk.get("content_hash", ""),
                ))

        # 找删除的
        for old_chunk in old_chunks:
            pos = old_chunk["position_index"]
            if pos not in new_chunk_map:
                result.deleted.append(ChunkChange(
                    chunk_id=old_chunk.get("chunk_id", ""),
                    position_index=pos,
                    change_type="deleted",
                    content=old_chunk.get("content", ""),
                    content_hash=old_chunk.get("content_hash", ""),
                ))

        return result


class ParentChildChangeDetector:
    """父子块变化检测器。

    父子块关系：
    - 父块 = 多个子块的拼接（用于检索）
    - 子块 = 原始分段（用于精确定位）

    更新规则：
    1. 子块变了 → 父块必须重新生成
    2. 父块变了 → 不影响子块（子块是原始数据）
    """

    def __init__(self, parent_chunk_size: int = 3):
        """初始化父子块变化检测器。

        Args:
            parent_chunk_size: 每个父块包含的子块数量
        """
        self.parent_chunk_size = parent_chunk_size

    def sync_parent_child(
        self,
        changed_child_chunks: list[ChunkChange],
    ) -> list[int]:
        """同步更新父子块。

        找出受影响的父块位置。

        Args:
            changed_child_chunks: 变化的子块列表

        Returns:
            需要重建的父块位置列表
        """
        affected_parent_positions = set()

        for chunk in changed_child_chunks:
            if chunk.change_type in ["new", "modified"]:
                pos = chunk.position_index
                # 向上取整到父块的位置
                parent_pos = pos // self.parent_chunk_size
                affected_parent_positions.add(parent_pos)

                # 也需要更新相邻的父块（因为重叠）
                if parent_pos > 0:
                    affected_parent_positions.add(parent_pos - 1)
                affected_parent_positions.add(parent_pos + 1)

        return sorted(affected_parent_positions)

    def rebuild_parent_chunk(
        self,
        child_chunks: list[dict[str, Any]],
        parent_position: int,
    ) -> dict[str, Any] | None:
        """重建一个父块。

        Args:
            child_chunks: 所有子块
            parent_position: 父块位置

        Returns:
            重建后的父块
        """
        start = parent_position * self.parent_chunk_size
        end = start + self.parent_chunk_size

        relevant_children = [
            c for c in child_chunks
            if start <= c["position_index"] < end
        ]

        if not relevant_children:
            return None

        # 拼接子块内容作为父块
        parent_content = "\n".join(c["content"] for c in relevant_children)
        parent_hash = hashlib.md5(parent_content.encode()).hexdigest()

        return {
            "parent_id": f"parent_{parent_position}",
            "position_index": parent_position,
            "content": parent_content,
            "content_hash": parent_hash,
            "child_ids": [c["chunk_id"] for c in relevant_children],
            "child_count": len(relevant_children),
        }
