"""PP-Structure 表格识别器。

PP-Structure 是 PaddleOCR 团队开源的表格识别工具，用深度学习端到端识别表格，
直接输出 HTML 或 Excel 格式。

为什么用 PP-Structure：
- 自己写规则就像手写正则表达式去匹配网页内容，费时费力还容易出错
- 用 PP-Structure 就像用 BeautifulSoup，底层帮你做好了，你只管用
- 中文表格识别准确率高，适合能源集团场景
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class TableResult:
    """表格识别结果。

    Attributes:
        html: HTML 格式的表格（带结构）
        excel_path: Excel 文件路径（可选）
        cells: 单元格列表
        rows: 行数
        cols: 列数
        bbox: 表格边界框
        confidence: 置信度
    """

    html: str
    excel_path: str | None = None
    cells: list[list[str]] = field(default_factory=list)
    rows: int = 0
    cols: int = 0
    bbox: tuple[int, int, int, int] | None = None  # x1, y1, x2, y2
    confidence: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """转换为字典。"""
        return {
            "html": self.html,
            "excel_path": self.excel_path,
            "cells": self.cells,
            "rows": self.rows,
            "cols": self.cols,
            "bbox": self.bbox,
            "confidence": self.confidence,
        }


class PPStructureTableRecognizer:
    """PP-Structure 表格识别器（生产级实现）。

    PP-Structure 工作原理（面试版）：
    1. 版面分析：定位表格在文档中的区域
    2. 表格检测：用深度学习网络识别表格边界
    3. 结构识别：识别单元格坐标和内容
    4. HTML/Excel 输出：输出结构化格式

    性能对比：
    | 自己写规则 | PP-Structure |
    | 准确率 70% | 准确率 95%+ |
    | 中文支持差 | 中文支持好 |
    | 维护成本高 | 维护成本低 |
    """

    def __init__(
        self,
        use_gpu: bool = True,
        model_dir: str | None = None,
        use_angle_cls: bool = True,
        layout_analysis_model: str = "ppocr",
        table_model: str = "ch_ppstructure_mobile_v2.0_table_infer",
    ):
        """初始化 PP-Structure 表格识别器。

        Args:
            use_gpu: 是否使用 GPU
            model_dir: 模型目录路径
            use_angle_cls: 是否使用角度分类（处理旋转表格）
            layout_analysis_model: 版面分析模型
            table_model: 表格识别模型
        """
        self.use_gpu = use_gpu
        self.model_dir = model_dir
        self.use_angle_cls = use_angle_cls
        self.layout_analysis_model = layout_analysis_model
        self.table_model = table_model
        self._pp_structure_engine = None
        self._initialized = False

    def initialize(self) -> None:
        """初始化 PP-Structure 引擎。

        注意：初始化可能需要几秒钟，应在实际使用时调用。
        """
        if self._initialized:
            return

        try:
            from paddleocr import PaddleOCR

            # 初始化 PaddleOCR（包含 PP-Structure）
            self._pp_structure_engine = PaddleOCR(
                use_angle_cls=self.use_angle_cls,
                lang="ch",  # 中文
                use_gpu=self.use_gpu,
                det_model_dir=self.model_dir,
                show_log=False,  # 关闭日志输出
            )

            self._initialized = True
            logger.info("PP-Structure 初始化完成")

        except ImportError:
            logger.warning(
                "PaddleOCR 未安装，将使用备用表格识别方案。"
                "安装命令：pip install paddleocr"
            )
            self._initialized = True  # 标记为已初始化，避免重复警告

    def recognize_from_image(
        self,
        image_path: str,
        output_dir: str | None = None,
    ) -> TableResult | None:
        """从图片识别表格。

        Args:
            image_path: 图片路径
            output_dir: 输出目录（用于保存 Excel）

        Returns:
            表格识别结果
        """
        self.initialize()

        if self._pp_structure_engine is None:
            return self._fallback_table_recognition(image_path)

        try:
            # 调用 PP-Structure 表格识别
            result = self._pp_structure_engine.ocr(
                image_path,
                cls=self.use_angle_cls,
                table=True,  # 启用表格识别
            )

            if not result or not result[0]:
                logger.warning(f"未在图片中检测到表格: {image_path}")
                return None

            # 解析结果
            table_info = result[0][0]  # 取第一个表格
            return self._parse_ppstructure_result(table_info, output_dir)

        except Exception as e:
            logger.error(f"PP-Structure 表格识别失败: {e}")
            return self._fallback_table_recognition(image_path)

    def recognize_from_array(
        self,
        image_array,
        output_dir: str | None = None,
    ) -> TableResult | None:
        """从 numpy 数组识别表格。

        Args:
            image_array: numpy 数组格式的图片
            output_dir: 输出目录

        Returns:
            表格识别结果
        """
        self.initialize()

        if self._pp_structure_engine is None:
            return None

        try:
            result = self._pp_structure_engine.ocr(
                image_array,
                cls=self.use_angle_cls,
                table=True,
            )

            if not result or not result[0]:
                return None

            table_info = result[0][0]
            return self._parse_ppstructure_result(table_info, output_dir)

        except Exception as e:
            logger.error(f"PP-Structure 数组表格识别失败: {e}")
            return None

    def _parse_ppstructure_result(
        self,
        table_info: dict[str, Any],
        output_dir: str | None = None,
    ) -> TableResult:
        """解析 PP-Structure 返回结果。

        PP-Structure 返回格式：
        {
            "bbox": [...],  # 边界框
            "html": "<table>...</table>",  # HTML 格式
            "cell_bsh": [[...], [...]],  # 单元格坐标
        }

        Args:
            table_info: PP-Structure 返回的表格信息
            output_dir: 输出目录

        Returns:
            解析后的表格结果
        """
        # 提取 HTML 内容
        html = table_info.get("html", "")

        # 提取边界框
        bbox = table_info.get("bbox")

        # 解析行列数（从 HTML 统计）
        rows = html.count("<tr>")
        cols = 0
        if "<td>" in html:
            # 统计第一行的列数
            first_row_match = html.split("<tr>")[1].split("</tr>")[0] if "<tr>" in html else ""
            cols = first_row_match.count("<td>") + first_row_match.count("<th>")

        # 提取单元格内容
        cells = self._html_to_cells(html)

        # 生成 Excel 文件（可选）
        excel_path = None
        if output_dir:
            excel_path = self._save_as_excel(html, output_dir)

        # 计算置信度（基于行列数是否合理）
        confidence = 0.95 if rows > 0 and cols > 0 else 0.5

        return TableResult(
            html=html,
            excel_path=excel_path,
            cells=cells,
            rows=rows,
            cols=cols,
            bbox=bbox,
            confidence=confidence,
        )

    def _html_to_cells(self, html: str) -> list[list[str]]:
        """将 HTML 表格转换为单元格列表。

        Args:
            html: HTML 表格字符串

        Returns:
            二维单元格列表
        """
        import re

        cells = []

        # 移除 HTML 标签，获取纯文本
        # 简单解析：提取 <tr>...</tr> 内的 <td>...</td> 内容
        rows = re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.DOTALL)

        for row in rows:
            row_cells = []
            # 匹配 td 和 th
            cells_in_row = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.DOTALL)

            for cell in cells_in_row:
                # 清理 HTML 标签
                clean_text = re.sub(r"<[^>]+>", "", cell).strip()
                row_cells.append(clean_text)

            if row_cells:
                cells.append(row_cells)

        return cells

    def _save_as_excel(self, html: str, output_dir: str) -> str | None:
        """将 HTML 表格保存为 Excel 文件。

        Args:
            html: HTML 表格
            output_dir: 输出目录

        Returns:
            Excel 文件路径
        """
        try:
            import pandas as pd

            # 转换 HTML 为 DataFrame
            dfs = pd.read_html(html)
            if not dfs:
                return None

            df = dfs[0]

            # 生成文件名
            output_path = Path(output_dir) / "table.xlsx"
            output_path.parent.mkdir(parents=True, exist_ok=True)

            # 保存为 Excel
            df.to_excel(output_path, index=False, engine="openpyxl")

            return str(output_path)

        except Exception as e:
            logger.error(f"保存 Excel 失败: {e}")
            return None

    def _fallback_table_recognition(
        self,
        image_path: str,
    ) -> TableResult | None:
        """备用表格识别方案。

        当 PP-Structure 不可用时使用简单规则识别。
        """
        try:
            from PIL import Image
            import pytesseract

            # 读取图片
            img = Image.open(image_path)

            # 使用 Tesseract OCR 识别表格
            # 尝试识别为表格格式
            data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DATAFRAME)

            # 简单处理：过滤空行
            data = data.dropna(subset=["text"])
            data["text"] = data["text"].astype(str)

            if data.empty:
                return None

            # 构建简单表格
            cells = []
            for text in data["text"].values:
                text = text.strip()
                if text:
                    cells.append([text])

            return TableResult(
                html="<table><tr><td>备用表格识别</td></tr></table>",
                cells=cells,
                rows=len(cells),
                cols=1,
                confidence=0.3,  # 低置信度
            )

        except Exception as e:
            logger.error(f"备用表格识别失败: {e}")
            return None


class MarkerTableRecognizer:
    """Marker 表格识别器（PP-Structure 替代方案）。

    Marker 是另一个优秀的文档处理库，适合：
    - Markdown/PDF 转换
    - 表格结构保持
    - 公式识别

    Marker vs PP-Structure：
    | 特性 | Marker | PP-Structure |
    |------|--------|--------------|
    | 表格识别 | 中等 | 强 |
    | 版面分析 | 一般 | 强 |
    | 部署难度 | 中等 | 中等 |
    | 中文支持 | 良好 | 良好 |
    """

    def __init__(self):
        """初始化 Marker 识别器。"""
        self._initialized = False

    def initialize(self) -> None:
        """初始化 Marker 引擎。"""
        if self._initialized:
            return

        try:
            # Marker 需要 GPU 和额外依赖
            # 这里只是预留接口
            logger.info("Marker 表格识别器初始化完成")
            self._initialized = True

        except Exception as e:
            logger.error(f"Marker 初始化失败: {e}")

    def recognize_from_pdf(
        self,
        pdf_path: str,
        output_dir: str | None = None,
    ) -> list[TableResult]:
        """从 PDF 识别所有表格。

        Args:
            pdf_path: PDF 文件路径
            output_dir: 输出目录

        Returns:
            表格识别结果列表
        """
        self.initialize()

        # TODO: 实现 Marker 调用
        # Marker 的调用方式：
        # from marker.converters.pdf import PdfConverter
        # converter = PdfConverter()
        # result = converter(pdf_path)
        # tables = result.tables

        logger.warning("Marker 表格识别器待实现")
        return []


# =============================================================================
# 表格识别策略选择
# =============================================================================

class TableRecognitionStrategy:
    """表格识别策略。

    根据文档类型和场景选择合适的表格识别方案。
    """

    @staticmethod
    def get_recommender(document_type: str, table_complexity: str) -> str:
        """获取推荐的表格识别方案。

        Args:
            document_type: 文档类型
            table_complexity: 表格复杂度（simple/medium/complex）

        Returns:
            推荐的识别方案
        """
        # 简单表格：规则识别即可
        if table_complexity == "simple":
            return "rule_based"

        # 复杂表格（多级表头、合并单元格）：用 PP-Structure
        if table_complexity == "complex":
            return "ppstructure"

        # 中等复杂度：根据文档类型选择
        if document_type in ["contract", "policy"]:
            # 合同、制度类文档表格通常较规范
            return "rule_based"

        # 设备手册、报告类：表格可能较复杂
        return "ppstructure"


# =============================================================================
# 演示代码
# =============================================================================

def demo_ppstructure():
    """演示 PP-Structure 表格识别。"""

    # 初始化识别器
    recognizer = PPStructureTableRecognizer(
        use_gpu=True,
        use_angle_cls=True,
    )

    # 识别表格
    # result = recognizer.recognize_from_image("path/to/table_image.png")

    # if result:
    #     print(f"识别到 {result.rows} 行 x {result.cols} 列")
    #     print(f"HTML: {result.html}")
    #     print(f"单元格: {result.cells}")

    print("PP-Structure 表格识别已配置完成")
    print("使用前请确保已安装：pip install paddlepaddle paddleocr")


if __name__ == "__main__":
    demo_ppstructure()
