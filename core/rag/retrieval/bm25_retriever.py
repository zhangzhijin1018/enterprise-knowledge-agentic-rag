"""BM25 检索器。

BM25 是一种基于关键词的经典检索算法，擅长精确匹配。
在 RAG 多路召回中作为独立的稀疏检索一路。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from core.vectorstore.base import BaseVectorStore

logger = logging.getLogger(__name__)


class BM25Retriever:
    """BM25 检索器。

    职责：
    - 对文档集合建立 BM25 索引
    - 对查询计算 BM25 得分
    - 返回按相关性排序的文档

    设计原因：
    - BM25 是经典的稀疏检索算法，不依赖向量模型
    - 擅长精确关键词匹配，如制度编号、设备型号、专业术语
    - 与 Dense 向量检索互补：Dense 擅长语义，Dense+BM25 兼顾语义和关键词
    - 企业知识场景中既有语义问法（"安全注意什么"）也有精确问法（"第十五条"）

    BM25 算法原理：
    - 基于词频和逆文档频率的统计模型
    - 对查询中每个词计算在文档中的得分
    - 使用文档长度归一化，避免对长文档的偏好
    - 公式：Score(D,Q) = Σ IDF(qi) × (tf(qi,D) × (k1+1)) / (tf(qi,D) + k1 × (1-b+b×|D|/avgdl))

    与 BGE-M3 Sparse 的区别：
    - BGE-M3 Sparse：基于 BGE-M3 模型生成的稀疏向量，MLM 驱动
    - BM25：传统统计方法，TF-IDF 变体，直接基于词频统计
    - 两者可互补使用，增强稀疏检索能力

    参考实现：参考 integrated_qa_system 项目中的 BM25Search 实现
    """

    def __init__(
        self,
        vector_store: BaseVectorStore | None = None,
        top_k: int = 20,
        k1: float = 1.5,
        b: float = 0.75,
        chunk_types: list[str] | None = None,
    ) -> None:
        """初始化 BM25 检索器。

        Args:
            vector_store: 向量存储（用于获取文档集合）
            top_k: 默认返回结果数量
            k1: BM25 词频饱和参数，控制词频增长的平滑程度
                 - k1=0 时退化为二元模型（只考虑词是否存在）
                 - k1 越大，词频得分增长越快
                 - 默认 1.5 是经验最优值
            b: BM25 文档长度归一化参数
                 - b=0 时不考虑文档长度
                 - b=1 时完全归一化
                 - 默认 0.75 是经验最优值
            chunk_types: 可检索的 chunk 类型过滤
        """
        self.vector_store = vector_store
        self.top_k = top_k
        self.k1 = k1
        self.b = b
        self.chunk_types = chunk_types

        # BM25 索引数据
        self._corpus: list[dict] = []  # 文档列表
        self._tokenized_corpus: list[list[str]] = []  # 分词后的文档列表
        self._doc_freqs: dict[str, int] = {}  # 词频统计（包含该词的文档数）
        self._avgdl: float = 0.0  # 平均文档长度
        self._num_docs: int = 0  # 文档总数
        self._idf: dict[str, float] = {}  # 逆文档频率
        self._initialized: bool = False

    def initialize(self, documents: list[dict]) -> None:
        """初始化 BM25 索引。

        从文档集合构建 BM25 索引。

        Args:
            documents: 文档列表，每项需包含 content 字段
        """
        if not documents:
            logger.warning("[BM25Retriever] 初始化文档为空，跳过")
            return

        logger.info(f"[BM25Retriever] 开始初始化索引，文档数: {len(documents)}")

        self._corpus = documents
        self._num_docs = len(documents)

        # 分词
        from core.rag.retrieval.bm25_retriever import tokenize_chinese

        self._tokenized_corpus = [tokenize_chinese(doc.get("content", "")) for doc in documents]

        # 统计词频
        self._doc_freqs = {}
        for tokens in self._tokenized_corpus:
            unique_tokens = set(tokens)
            for token in unique_tokens:
                self._doc_freqs[token] = self._doc_freqs.get(token, 0) + 1

        # 计算平均文档长度
        total_len = sum(len(tokens) for tokens in self._tokenized_corpus)
        self._avgdl = total_len / self._num_docs if self._num_docs > 0 else 0

        # 计算 IDF
        self._idf = {}
        for token, df in self._doc_freqs.items():
            # IDF 公式：log((N - n + 0.5) / (n + 0.5) + 1)
            # 使用平滑处理避免零除
            idf = max(0, (self._num_docs - df + 0.5) / (df + 0.5))
            self._idf[token] = idf + 1  # 加1确保非负

        self._initialized = True
        logger.info(f"[BM25Retriever] 索引初始化完成，词表大小: {len(self._idf)}")

    def retrieve(
        self,
        query_text: str,
        filters: dict[str, Any] | None = None,
        top_k: int | None = None,
    ) -> list[dict]:
        """执行 BM25 检索。

        Args:
            query_text: 查询文本（用户问题）
            filters: 元数据过滤条件（暂不支持）
            top_k: 返回结果数量，默认为初始化时的 top_k

        Returns:
            检索结果列表，每项包含：
            - chunk_uuid: 切片唯一标识
            - content: 切片内容
            - score: BM25 相关性分数
            - metadata: 切片元数据
            - matched_terms: 匹配的关键词列表

        示例返回：
            [
                {
                    "chunk_uuid": "chunk_xyz789",
                    "content": "第十五条 安全生产责任...",
                    "score": 12.5,
                    "metadata": {"section_title": "安全责任", ...},
                    "matched_terms": ["安全生产", "责任", "第十五条"]
                },
                ...
            ]
        """
        logger.debug(f"[BM25Retriever] 检索 query={query_text[:50]}...")

        # 检查是否已初始化
        if not self._initialized:
            logger.warning("[BM25Retriever] BM25 索引未初始化，返回空结果")
            return []

        search_top_k = top_k or self.top_k

        # 1. 分词查询
        query_tokens = tokenize_chinese(query_text)

        if not query_tokens:
            logger.warning("[BM25Retriever] 查询分词为空，返回空结果")
            return []

        # 2. 计算 IDF 权重
        query_idf = {}
        for token in set(query_tokens):
            if token in self._idf:
                query_idf[token] = self._idf[token]

        # 3. 对每个文档计算 BM25 得分
        scores: list[tuple[int, float, list[str]]] = []

        for idx, doc_tokens in enumerate(self._tokenized_corpus):
            if idx >= len(self._corpus):
                continue

            doc = self._corpus[idx]
            doc_len = len(doc_tokens)

            # 计算词频
            tf: dict[str, int] = {}
            for token in doc_tokens:
                tf[token] = tf.get(token, 0) + 1

            # 计算 BM25 得分
            score = 0.0
            matched_terms: list[str] = []

            for token in query_tokens:
                if token in tf:
                    # 计算该词的 BM25 贡献
                    term_freq = tf[token]
                    idf = query_idf.get(token, 0)

                    # BM25 公式：IDF * (tf * (k1+1)) / (tf + k1 * (1-b+b*|D|/avgdl))
                    numerator = term_freq * (self.k1 + 1)
                    denominator = term_freq + self.k1 * (1 - self.b + self.b * doc_len / max(self._avgdl, 1))
                    term_score = idf * numerator / denominator

                    score += term_score
                    matched_terms.append(token)

            if score > 0:
                scores.append((idx, score, matched_terms))

        # 4. 排序
        scores.sort(key=lambda x: x[1], reverse=True)

        # 5. 格式化结果
        results = []
        for idx, score, matched_terms in scores[:search_top_k]:
            doc = self._corpus[idx]
            results.append({
                "chunk_uuid": doc.get("chunk_uuid", ""),
                "content": doc.get("content", ""),
                "content_preview": doc.get("content", "")[:200],
                "score": round(score, 4),
                "dense_score": 0.0,
                "sparse_score": score,
                "metadata": doc.get("metadata", {}),
                "chunk_type": doc.get("chunk_type", ""),
                "chunk_index": doc.get("chunk_index", 0),
                "section_title": doc.get("section_title"),
                "page_start": doc.get("page_start"),
                "page_end": doc.get("page_end"),
                "document_id": doc.get("document_id"),
                "parent_chunk_uuid": doc.get("parent_chunk_uuid"),
                "matched_terms": list(set(matched_terms)),  # 去重
            })

        logger.info(f"[BM25Retriever] 检索完成，召回 {len(results)} 条结果")

        return results

    def add_documents(self, documents: list[dict]) -> None:
        """添加文档到索引。

        增量更新索引，避免全量重建。

        Args:
            documents: 新增的文档列表
        """
        if not documents:
            return

        from core.rag.retrieval.bm25_retriever import tokenize_chinese

        # 如果未初始化，直接初始化
        if not self._initialized:
            self.initialize(documents)
            return

        logger.info(f"[BM25Retriever] 增量添加 {len(documents)} 个文档")

        # 追加文档
        for doc in documents:
            self._corpus.append(doc)
            tokens = tokenize_chinese(doc.get("content", ""))
            self._tokenized_corpus.append(tokens)

            # 更新词频
            unique_tokens = set(tokens)
            for token in unique_tokens:
                self._doc_freqs[token] = self._doc_freqs.get(token, 0) + 1

        # 更新文档数
        old_num_docs = self._num_docs
        self._num_docs = len(self._corpus)

        # 重新计算平均文档长度
        total_len = sum(len(tokens) for tokens in self._tokenized_corpus)
        self._avgdl = total_len / self._num_docs if self._num_docs > 0 else 0

        # 重新计算 IDF（简化处理：使用新文档数）
        for token, df in self._doc_freqs.items():
            idf = max(0, (self._num_docs - df + 0.5) / (df + 0.5))
            self._idf[token] = idf + 1

        logger.info(f"[BM25Retriever] 增量更新完成，总文档数: {self._num_docs}")

    def reset(self) -> None:
        """重置索引，清空所有数据。"""
        self._corpus = []
        self._tokenized_corpus = []
        self._doc_freqs = {}
        self._avgdl = 0.0
        self._num_docs = 0
        self._idf = {}
        self._initialized = False
        logger.info("[BM25Retriever] 索引已重置")

    def is_initialized(self) -> bool:
        """检查索引是否已初始化。

        Returns:
            True 如果已初始化
        """
        return self._initialized


def tokenize_chinese(text: str) -> list[str]:
    """中文分词函数。

    使用 jieba 进行中文分词，支持英文和数字。

    Args:
        text: 输入文本

    Returns:
        分词后的词列表
    """
    import re

    # 导入 jieba
    try:
        import jieba
    except ImportError:
        logger.warning("[tokenize_chinese] jieba 未安装，使用简单分词")
        # 简单分词：按空格和标点分割
        text = re.sub(r"[^\w\u4e00-\u9fff]+", " ", text)
        return text.lower().split()

    # 使用 jieba 精确模式分词
    tokens = jieba.lcut(text.lower())

    # 过滤停用词和单字符
    # 常见停用词
    stopwords = {
        "的", "了", "在", "是", "我", "有", "和", "就", "不", "人", "都", "一", "一个",
        "上", "也", "很", "到", "说", "要", "去", "你", "会", "着", "没有", "看", "好",
        "自己", "这", "那", "它", "他", "她", "们", "什么", "怎么", "为什么", "如何",
        "吗", "呢", "吧", "啊", "哦", "嗯", "呀", "哈", "嘿",
        "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
        "of", "with", "by", "from", "is", "are", "was", "were", "be", "been",
        "this", "that", "these", "those", "it", "its",
    }

    filtered = []
    for token in tokens:
        token = token.strip()
        # 过滤空字符串、停用词、纯标点、单个字符（中文单字无意义）
        if token and token not in stopwords and len(token) > 1 and not re.match(r"^[^\w\u4e00-\u9fff]+$", token):
            filtered.append(token)

    return filtered
