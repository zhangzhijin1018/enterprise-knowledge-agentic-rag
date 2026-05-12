"""文档切分器包。

文档切分策略：
- DocumentTypeAwareChunker: 文档类型感知切块器
- SemanticOverlapChunker: 语义重叠切块器
- ChunkChangeDetector: Chunk 变化检测器
- HybridChunker: 混合切块器
"""

from core.rag.ingestion.chunkers.document_chunker import (
    DocumentTypeAwareChunker,
    ChunkResult,
)

from core.rag.ingestion.chunkers.semantic_chunker import (
    SemanticOverlapChunker,
    SemanticChunk,
    HybridChunker,
)

from core.rag.ingestion.chunkers.change_detector import (
    ChunkChangeDetector,
    ChunkChange,
    ChangeDetectionResult,
    ParentChildChangeDetector,
)

__all__ = [
    # 文档类型感知切块器
    "DocumentTypeAwareChunker",
    "ChunkResult",
    # 语义重叠切块器
    "SemanticOverlapChunker",
    "SemanticChunk",
    "HybridChunker",
    # 变化检测器
    "ChunkChangeDetector",
    "ChunkChange",
    "ChangeDetectionResult",
    "ParentChildChangeDetector",
]
