"""增量更新器包。

包含：
- IdempotentIncrementalUpdater: 幂等性增量更新器
- MilvusVersionManager: Milvus 版本管理器
- IncrementalDocumentUpdateService: 增量文档更新服务
"""

from core.rag.ingestion.updaters.idempotent_updater import (
    IdempotentIncrementalUpdater,
    IdempotentOperation,
)

from core.rag.ingestion.updaters.version_manager import (
    MilvusVersionManager,
    DocumentVersion,
    DocumentVersionStatus,
    InMemoryVersionStore,
)

from core.rag.ingestion.updaters.incremental_update_service import (
    IncrementalDocumentUpdateService,
    UpdateResult,
    create_incremental_update_service,
)

__all__ = [
    # 幂等性更新器
    "IdempotentIncrementalUpdater",
    "IdempotentOperation",
    # 版本管理器
    "MilvusVersionManager",
    "DocumentVersion",
    "DocumentVersionStatus",
    "InMemoryVersionStore",
    # 增量更新服务
    "IncrementalDocumentUpdateService",
    "UpdateResult",
    "create_incremental_update_service",
]
