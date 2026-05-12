"""RAG 文档入库包。

文档入库流程：
1. 文档解析 (parsers/)
2. 文档切分 (chunkers/)
3. 增量更新 (updaters/)

包含功能：
- DocumentTypeAwareChunker: 文档类型感知切块
- SemanticOverlapChunker: 语义重叠切块
- ChunkChangeDetector: Chunk 变化检测
- PPStructureTableRecognizer: PP-Structure 表格识别
- IdempotentIncrementalUpdater: 幂等性增量更新
- MilvusVersionManager: Milvus 版本管理
- IncrementalDocumentUpdateService: 增量更新服务
"""

from core.rag.ingestion.chunkers import (
    DocumentTypeAwareChunker,
    ChunkResult,
    SemanticOverlapChunker,
    SemanticChunk,
    HybridChunker,
    ChunkChangeDetector,
    ChunkChange,
    ChangeDetectionResult,
    ParentChildChangeDetector,
)

from core.rag.ingestion.parsers import (
    PPStructureTableRecognizer,
    TableResult,
    MarkerTableRecognizer,
    TableRecognitionStrategy,
)

from core.rag.ingestion.updaters import (
    IdempotentIncrementalUpdater,
    IdempotentOperation,
    MilvusVersionManager,
    DocumentVersion,
    DocumentVersionStatus,
    InMemoryVersionStore,
    IncrementalDocumentUpdateService,
    UpdateResult,
    create_incremental_update_service,
)

__all__ = [
    # 切分器
    "DocumentTypeAwareChunker",
    "ChunkResult",
    "SemanticOverlapChunker",
    "SemanticChunk",
    "HybridChunker",
    # 变化检测
    "ChunkChangeDetector",
    "ChunkChange",
    "ChangeDetectionResult",
    "ParentChildChangeDetector",
    # 表格识别
    "PPStructureTableRecognizer",
    "TableResult",
    "MarkerTableRecognizer",
    "TableRecognitionStrategy",
    # 增量更新
    "IdempotentIncrementalUpdater",
    "IdempotentOperation",
    "MilvusVersionManager",
    "DocumentVersion",
    "DocumentVersionStatus",
    "InMemoryVersionStore",
    "IncrementalDocumentUpdateService",
    "UpdateResult",
    "create_incremental_update_service",
]
