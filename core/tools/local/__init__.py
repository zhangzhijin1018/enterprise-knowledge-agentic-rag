"""本地工具包。"""

from .ocr import LocalOCRGateway
from .parser import LocalDocumentParser

__all__ = [
    "LocalDocumentParser",
    "LocalOCRGateway",
]
