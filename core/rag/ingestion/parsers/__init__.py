"""PP-Structure 表格识别器。

基于 PaddleOCR 的 PP-Structure 表格识别能力。
"""

from core.rag.ingestion.parsers.ppstructure_parser import (
    PPStructureTableRecognizer,
    TableResult,
    MarkerTableRecognizer,
    TableRecognitionStrategy,
)

__all__ = [
    "PPStructureTableRecognizer",
    "TableResult",
    "MarkerTableRecognizer",
    "TableRecognitionStrategy",
]
