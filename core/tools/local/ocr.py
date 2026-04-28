"""本地 OCR 适配器。

当前阶段的设计目标不是把 PaddleOCR 的调用散落在各处，
而是先收口成一个统一入口，便于后续做：
- 依赖探测；
- OCR 与 PP-Structure 路线选择；
- 结果结构化；
- 日志与错误治理；
- 未来替换为更强的文档理解服务。

本轮能力边界：
- 普通图片 OCR：优先尝试 PaddleOCR；
- 图片结构化解析：优先尝试 PP-Structure；
- 若运行环境没有安装相关依赖，则返回清晰的占位结构块，
  保证 parse 主链路和测试链路不断。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


class LocalOCRGateway:
    """本地 OCR 统一适配器。

    设计原因：
    - 普通 OCR 适合“把图片里的文字读出来”；
    - PP-Structure 更适合“把图片里的结构化区域拆出来”，例如表格、标题、正文；
    - 两者虽然都属于 Paddle 生态，但业务语义不同，应该在统一入口里显式区分。
    """

    def __init__(self) -> None:
        """延迟初始化 OCR 引擎。

        这里不在构造函数里直接强行初始化 PaddleOCR，
        是为了避免：
        - 本地没有安装 Paddle 依赖时 import 直接失败；
        - API 进程启动时平白承担较重的初始化成本；
        - 非 OCR 文档解析路径被无关依赖拖慢。
        """

        self._ocr_engine: Any | None = None
        self._pp_structure_engine: Any | None = None
        self._ocr_import_error: Exception | None = None
        self._pp_structure_import_error: Exception | None = None

    def extract_text_from_image(
        self,
        image_path: str | Path,
        page_no: int = 1,
        raw_metadata: dict | None = None,
    ) -> list[dict]:
        """从图片中提取普通 OCR 文本。

        适用场景：
        - 扫描页；
        - PDF 图片页；
        - PNG/JPG 等图片文件；
        - 当前不要求恢复复杂布局，只要先把可读文本转成结构块。
        """

        path = Path(image_path)
        metadata = dict(raw_metadata or {})
        metadata.setdefault("ocr_route", "paddle_ocr")
        metadata.setdefault("image_path", str(path))

        engine = self._get_ocr_engine()
        if engine is None:
            return [
                self._build_placeholder_paragraph_block(
                    path=path,
                    page_no=page_no,
                    message="当前环境未安装 PaddleOCR，返回 OCR 占位结构块。",
                    raw_metadata={
                        **metadata,
                        "ocr_fallback": True,
                        "ocr_dependency_available": False,
                    },
                )
            ]

        try:
            result = engine.ocr(str(path), cls=True) or []
            lines: list[str] = []
            for page_result in result:
                for item in page_result or []:
                    if len(item) < 2:
                        continue
                    recognized_text = (item[1][0] or "").strip()
                    if recognized_text:
                        lines.append(recognized_text)

            if not lines:
                return [
                    self._build_placeholder_paragraph_block(
                        path=path,
                        page_no=page_no,
                        message="OCR 已执行，但当前图片未识别到明确文本。",
                        raw_metadata={
                            **metadata,
                            "ocr_fallback": True,
                            "ocr_dependency_available": True,
                        },
                    )
                ]

            return [
                {
                    "block_type": "ocr_paragraph",
                    "text": "\n".join(lines),
                    "page_no": page_no,
                    "heading_path": [],
                    "section_title": None,
                    "clause_no": None,
                    "table_data": None,
                    "image_ref": str(path),
                    "raw_metadata": {
                        **metadata,
                        "ocr_fallback": False,
                        "ocr_dependency_available": True,
                        "line_count": len(lines),
                    },
                }
            ]
        except Exception as exc:
            return [
                self._build_placeholder_paragraph_block(
                    path=path,
                    page_no=page_no,
                    message=f"OCR 执行异常，当前回退到占位结构块：{exc}",
                    raw_metadata={
                        **metadata,
                        "ocr_fallback": True,
                        "ocr_dependency_available": True,
                        "ocr_error": str(exc),
                    },
                )
            ]

    def extract_structure_from_image(
        self,
        image_path: str | Path,
        page_no: int = 1,
        raw_metadata: dict | None = None,
    ) -> list[dict]:
        """从图片中提取结构化块。

        适用场景：
        - 扫描 PDF 页；
        - 图片文档；
        - 图片中的表格和多区域布局。

        说明：
        - 优先尝试 PP-Structure，因为它更适合结构块输出；
        - 如果环境没有 PP-Structure，再回退到普通 OCR；
        - 这是“有依赖则真实调用、无依赖则清晰占位”的最小可扩展方案。
        """

        path = Path(image_path)
        metadata = dict(raw_metadata or {})
        metadata.setdefault("ocr_route", "pp_structure")
        metadata.setdefault("image_path", str(path))

        engine = self._get_pp_structure_engine()
        if engine is None:
            return self.extract_text_from_image(
                image_path=path,
                page_no=page_no,
                raw_metadata={
                    **metadata,
                    "pp_structure_available": False,
                },
            )

        try:
            result = engine(str(path)) or []
            blocks = self._convert_pp_structure_result_to_blocks(
                result=result,
                image_path=path,
                page_no=page_no,
                raw_metadata=metadata,
            )
            if blocks:
                return blocks
        except Exception as exc:
            metadata["pp_structure_error"] = str(exc)

        return self.extract_text_from_image(
            image_path=path,
            page_no=page_no,
            raw_metadata={
                **metadata,
                "pp_structure_fallback": True,
            },
        )

    def _get_ocr_engine(self) -> Any | None:
        """惰性获取 PaddleOCR 引擎。"""

        if self._ocr_engine is not None:
            return self._ocr_engine
        if self._ocr_import_error is not None:
            return None

        try:
            from paddleocr import PaddleOCR  # type: ignore

            self._ocr_engine = PaddleOCR(use_angle_cls=True, lang="ch")
        except Exception as exc:  # pragma: no cover - 依赖缺失分支依赖运行环境
            self._ocr_import_error = exc
            self._ocr_engine = None
        return self._ocr_engine

    def _get_pp_structure_engine(self) -> Any | None:
        """惰性获取 PP-Structure 引擎。"""

        if self._pp_structure_engine is not None:
            return self._pp_structure_engine
        if self._pp_structure_import_error is not None:
            return None

        try:
            from paddleocr import PPStructure  # type: ignore

            self._pp_structure_engine = PPStructure(show_log=False)
        except Exception as exc:  # pragma: no cover - 依赖缺失分支依赖运行环境
            self._pp_structure_import_error = exc
            self._pp_structure_engine = None
        return self._pp_structure_engine

    def _convert_pp_structure_result_to_blocks(
        self,
        result: list[dict],
        image_path: Path,
        page_no: int,
        raw_metadata: dict,
    ) -> list[dict]:
        """把 PP-Structure 结果转换成统一结构块。

        当前阶段只做最小封装：
        - 文本区域转为 `ocr_paragraph`
        - 表格区域转为 `ocr_table`
        - 其他图片区域转为 `image`

        这里不追求最终高精度 HTML 表格恢复，
        但会尽量把表格标题、列名、行数等信息留在 metadata 中，
        方便后续继续增强。
        """

        blocks: list[dict] = []
        for item in result:
            block_type = (item.get("type") or "").lower()
            area_result = item.get("res") or {}

            if block_type == "table":
                table_text = (
                    area_result.get("html")
                    or area_result.get("text")
                    or "当前 PP-Structure 表格结果未提供可直接恢复的纯文本。"
                )
                blocks.append(
                    {
                        "block_type": "ocr_table",
                        "text": table_text,
                        "page_no": page_no,
                        "heading_path": [],
                        "section_title": None,
                        "clause_no": None,
                        "table_data": {
                            "column_names": area_result.get("column_names") or [],
                            "rows": area_result.get("rows") or [],
                            "row_count": len(area_result.get("rows") or []),
                        },
                        "image_ref": str(image_path),
                        "raw_metadata": {
                            **raw_metadata,
                            "pp_structure_available": True,
                            "table_title": area_result.get("title"),
                            "column_names": area_result.get("column_names") or [],
                            "row_count": len(area_result.get("rows") or []),
                        },
                    }
                )
                continue

            if block_type in {"text", "title", "list"}:
                lines: list[str] = []
                if isinstance(area_result, dict):
                    content = str(area_result.get("text") or "").strip()
                    if content:
                        lines.append(content)
                    nested_items = area_result.get("res") or []
                    for text_item in nested_items:
                        if isinstance(text_item, dict):
                            nested_content = str(text_item.get("text") or "").strip()
                        else:
                            nested_content = str(text_item).strip()
                        if nested_content:
                            lines.append(nested_content)
                else:
                    for text_item in area_result:
                        if isinstance(text_item, dict):
                            content = str(text_item.get("text") or "").strip()
                        else:
                            content = str(text_item).strip()
                        if content:
                            lines.append(content)
                if lines:
                    blocks.append(
                        {
                            "block_type": "ocr_paragraph",
                            "text": "\n".join(lines),
                            "page_no": page_no,
                            "heading_path": [],
                            "section_title": None,
                            "clause_no": None,
                            "table_data": None,
                            "image_ref": str(image_path),
                            "raw_metadata": {
                                **raw_metadata,
                                "pp_structure_available": True,
                                "pp_structure_block_type": block_type,
                            },
                        }
                    )
                continue

            blocks.append(
                {
                    "block_type": "image",
                    "text": f"图片区域：{image_path.name}",
                    "page_no": page_no,
                    "heading_path": [],
                    "section_title": None,
                    "clause_no": None,
                    "table_data": None,
                    "image_ref": str(image_path),
                    "raw_metadata": {
                        **raw_metadata,
                        "pp_structure_available": True,
                        "pp_structure_block_type": block_type or "image",
                    },
                }
            )

        return blocks

    def _build_placeholder_paragraph_block(
        self,
        path: Path,
        page_no: int,
        message: str,
        raw_metadata: dict,
    ) -> dict:
        """构造 OCR 回退占位块。"""

        return {
            "block_type": "ocr_paragraph",
            "text": f"{path.name}：{message}",
            "page_no": page_no,
            "heading_path": [],
            "section_title": None,
            "clause_no": None,
            "table_data": None,
            "image_ref": str(path),
            "raw_metadata": raw_metadata,
        }
